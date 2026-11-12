"""Account registration on a SQLite DataSource, end to end (ADR 0051, #63).

Each test migrates a fresh SQLite file and runs `msm.services.register_account` through
MetaTables' own server code for the local runtime, as `test_sqlite_snapshot_writes` does.
The operation counts are the MetaTables requests the Markets API would make.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest

from metatables import MetaTable
from msm.repositories.account_registration import (
    AccountRegistrationWrites,
    AccountWrite,
    HoldingPosition,
    HoldingsWrite,
    register_account as run_registration_writes,
)
from msm.services import (
    AccountHoldingsSnapshotExistsError,
    AssetTypeConflictError,
    get_or_create_currency_asset,
    register_account,
)
from tests.msm.repositories.test_sqlite_snapshot_writes import (
    _account,
    _asset,
    _count,
    _insert,
    _rows,
    make_sqlite_markets,
)

DAY_1 = dt.datetime(2026, 11, 10, 21, 0, tzinfo=dt.UTC)
DAY_2 = dt.datetime(2026, 11, 11, 21, 0, tzinfo=dt.UTC)
STORED_DAY_1 = "2026-11-10 21:00:00.000000"
STORED_DAY_2 = "2026-11-11 21:00:00.000000"


@pytest.fixture
def sqlite_markets(tmp_path, monkeypatch):
    return make_sqlite_markets(tmp_path, monkeypatch)


def _record_operations(monkeypatch) -> list[str]:
    """Each MetaTables request from here on: ``read`` or ``transaction``."""

    operations: list[str] = []
    execute_operation, execute_transaction = MetaTable.execute_operation, MetaTable.execute_transaction

    def recorded_operation(cls, operation, *, timeout=None):
        operations.append("read" if operation.operation == "select" else operation.operation)
        return execute_operation(operation, timeout=timeout)

    def recorded_transaction(cls, transaction, *, timeout=None):
        operations.append("transaction")
        return execute_transaction(transaction, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(recorded_operation))
    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(recorded_transaction))
    return operations


def _request(
    *,
    holdings_date=DAY_1,
    positions=None,
    overwrite=False,
    account_name="Venue account",
    assets=None,
    cash_currency="USD",
    **account,
):
    return {
        "account": {
            "unique_identifier": "venue::account-1",
            "account_name": account_name,
            "is_paper": True,
            "account_is_active": True,
            **account,
        },
        "assets": assets
        if assets is not None
        else [
            {
                "unique_identifier": "venue::AAPL",
                "asset_type": {"asset_type": "Venue Equity", "display_name": "Venue equity"},
                "snapshot": {"name": "Apple Inc.", "ticker": "AAPL", "exchange_code": "XNAS"},
            },
            {
                "unique_identifier": "venue::MSFT",
                "asset_type": {"asset_type": "venue_equity", "display_name": "Other name"},
                "snapshot": {"name": "Microsoft", "ticker": "MSFT", "exchange_code": "XNAS"},
            },
        ],
        "cash_currency": cash_currency,
        "holdings_date": holdings_date.isoformat(),
        "overwrite": overwrite,
        "positions": positions
        if positions is not None
        else [
            {"asset_identifier": "venue::AAPL", "quantity": "3", "extra_details": {"lot": 1}},
            {"asset_identifier": "venue::MSFT", "quantity": "1.5", "direction": -1},
            {"asset_identifier": "USD", "quantity": "1000"},
        ],
    }


def _holdings(engine):
    return _rows(
        engine,
        "SELECT h.asset_identifier, h.quantity, h.direction, h.time_index, h.target_trade_time, "
        "h.extra_details, h.account_uid, s.uid AS holdings_set_uid FROM ms_markets__accountholdingsts h "
        "JOIN ms_markets__accountholdingsset s ON s.uid = h.holdings_set_uid "
        "ORDER BY h.time_index, h.asset_identifier",
    )


def test_a_first_registration_creates_everything_in_one_transaction(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    operations = _record_operations(monkeypatch)

    result = register_account(sqlite_markets.context, _request())

    assert operations == ["read", "read", "transaction"]
    response = result.response
    (account,) = _rows(engine, "SELECT * FROM ms_markets__account")
    assert account["unique_identifier"] == "venue::account-1"
    assert account["account_name"] == "Venue account"
    assert uuid.UUID(str(response["account"]["uid"])).hex == account["uid"]

    assert _rows(
        engine,
        "SELECT asset_type, display_name, description FROM ms_markets__assettype ORDER BY asset_type",
    ) == [
        {
            "asset_type": "currency",
            "display_name": "Currency",
            "description": "Single currency assets used as denomination, base, or quote units.",
        },
        {"asset_type": "venue_equity", "display_name": "Venue equity", "description": None},
    ]
    assets = _rows(engine, "SELECT uid, unique_identifier, asset_type FROM ms_markets__asset ORDER BY unique_identifier")
    assert [(row["unique_identifier"], row["asset_type"]) for row in assets] == [
        ("USD", "currency"),
        ("venue::AAPL", "venue_equity"),
        ("venue::MSFT", "venue_equity"),
    ]
    assert {key: uuid.UUID(value).hex for key, value in response["asset_uids"].items()} == {
        row["unique_identifier"]: row["uid"] for row in assets
    }

    assert _rows(
        engine,
        "SELECT asset_identifier, time_index, name, ticker, exchange_code "
        "FROM ms_markets__assetsnapshotsts ORDER BY asset_identifier",
    ) == [
        {"asset_identifier": "venue::AAPL", "time_index": STORED_DAY_1, "name": "Apple Inc.", "ticker": "AAPL", "exchange_code": "XNAS"},
        {"asset_identifier": "venue::MSFT", "time_index": STORED_DAY_1, "name": "Microsoft", "ticker": "MSFT", "exchange_code": "XNAS"},
    ]

    holdings = _holdings(engine)
    assert [(row["asset_identifier"], row["quantity"], row["direction"]) for row in holdings] == [
        ("USD", 1000.0, 1),
        ("venue::AAPL", 3.0, 1),
        ("venue::MSFT", 1.5, -1),
    ]
    assert {row["account_uid"] for row in holdings} == {account["uid"]}
    assert {row["time_index"] for row in holdings} == {STORED_DAY_1}
    assert {row["target_trade_time"] for row in holdings} == {STORED_DAY_1}
    assert json.loads(holdings[1]["extra_details"]) == {"lot": 1}
    assert {row["holdings_set_uid"] for row in holdings} == {uuid.UUID(response["holdings_set_uid"]).hex}

    assert response["written"] == {
        "asset_types": {"created": 2, "changed": 0},
        "assets": {"created": 3, "changed": 0},
        "asset_snapshots": {"created": 2, "changed": 0},
        "accounts": {"created": 1, "changed": 0},
        "holdings_sets": {"created": 1, "changed": 0},
        "holdings": {"created": 3, "changed": 0},
    }
    assert [(write.resource, write.action) for write in result.writes] == [
        ("asset-type", "create"),
        ("asset-type", "create"),
        ("asset", "create"),
        ("asset", "create"),
        ("asset", "create"),
        ("asset-snapshot", "create"),
        ("account", "create"),
        ("account-holdings", "add"),
    ]
    assert {write.details["account_identifier"] for write in result.writes} == {"venue::account-1"}
    assert result.writes[-1].details["row_count"] == 3


def test_a_sync_of_known_assets_costs_two_reads_and_one_transaction(sqlite_markets, monkeypatch) -> None:
    register_account(sqlite_markets.context, _request())
    operations = _record_operations(monkeypatch)
    sent: list[int] = []
    execute_transaction = MetaTable.execute_transaction

    def counted(cls, transaction, *, timeout=None):
        sent.append(len(transaction.statements))
        return execute_transaction(transaction, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(counted))

    result = register_account(
        sqlite_markets.context,
        _request(
            holdings_date=DAY_2,
            positions=[
                {"asset_identifier": "venue::AAPL", "quantity": "4"},
                {"asset_identifier": "USD", "quantity": "900"},
            ],
        ),
    )

    assert operations == ["read", "read", "transaction"]
    # The holdings set, its rows and the answer: no asset, snapshot or account statement.
    assert sent == [3]
    assert result.response["written"] == {
        "asset_types": {"created": 0, "changed": 0},
        "assets": {"created": 0, "changed": 0},
        "asset_snapshots": {"created": 0, "changed": 0},
        "accounts": {"created": 0, "changed": 0},
        "holdings_sets": {"created": 1, "changed": 0},
        "holdings": {"created": 2, "changed": 0},
    }
    assert [(write.resource, write.action) for write in result.writes] == [("account-holdings", "add")]
    engine = sqlite_markets.engine
    assert _count(engine, "ms_markets__assetsnapshotsts") == 2
    assert [
        (row["time_index"], row["asset_identifier"], row["quantity"]) for row in _holdings(engine)
    ] == [
        (STORED_DAY_1, "USD", 1000.0),
        (STORED_DAY_1, "venue::AAPL", 3.0),
        (STORED_DAY_1, "venue::MSFT", 1.5),
        (STORED_DAY_2, "USD", 900.0),
        (STORED_DAY_2, "venue::AAPL", 4.0),
    ]


@pytest.mark.parametrize("overwrite", [False, True])
def test_an_identical_repeat_succeeds_without_a_transaction(sqlite_markets, monkeypatch, overwrite) -> None:
    first = register_account(sqlite_markets.context, _request())
    operations = _record_operations(monkeypatch)

    repeat = register_account(sqlite_markets.context, _request(overwrite=overwrite))

    assert operations == ["read", "read"]
    assert repeat.writes == ()
    assert repeat.response["holdings_set_uid"] == first.response["holdings_set_uid"]
    assert repeat.response["asset_uids"] == first.response["asset_uids"]
    assert repeat.response["account"]["account_name"] == "Venue account"
    assert all(count == {"created": 0, "changed": 0} for count in repeat.response["written"].values())


def test_different_holdings_without_overwrite_are_refused_and_nothing_is_written(
    sqlite_markets, monkeypatch
) -> None:
    register_account(sqlite_markets.context, _request())
    engine = sqlite_markets.engine
    before = _holdings(engine)
    operations = _record_operations(monkeypatch)
    request = _request(
        account_name="Renamed",
        assets=[
            {
                "unique_identifier": "venue::NVDA",
                "asset_type": {"asset_type": "venue_equity"},
                "snapshot": {"name": "NVIDIA", "ticker": "NVDA"},
            }
        ],
        positions=[{"asset_identifier": "venue::NVDA", "quantity": "2"}],
    )

    with pytest.raises(AccountHoldingsSnapshotExistsError, match="overwrite=true"):
        register_account(sqlite_markets.context, request)

    assert operations == ["read", "read"]
    assert _holdings(engine) == before
    assert _rows(engine, "SELECT unique_identifier FROM ms_markets__asset WHERE unique_identifier = 'venue::NVDA'") == []
    assert _rows(engine, "SELECT account_name FROM ms_markets__account") == [{"account_name": "Venue account"}]


def test_different_holdings_with_overwrite_replace_the_rows_of_the_same_set(sqlite_markets) -> None:
    first = register_account(sqlite_markets.context, _request())

    replaced = register_account(
        sqlite_markets.context,
        _request(overwrite=True, positions=[{"asset_identifier": "venue::MSFT", "quantity": "7"}]),
    )

    engine = sqlite_markets.engine
    assert [(row["asset_identifier"], row["quantity"]) for row in _holdings(engine)] == [("venue::MSFT", 7.0)]
    assert replaced.response["holdings_set_uid"] == first.response["holdings_set_uid"]
    assert replaced.response["written"]["holdings_sets"] == {"created": 0, "changed": 1}
    assert replaced.response["written"]["holdings"] == {"created": 1, "changed": 0}
    assert [(write.resource, write.action) for write in replaced.writes] == [("account-holdings", "replace")]


def test_a_changed_account_field_updates_only_the_account(sqlite_markets) -> None:
    first = register_account(sqlite_markets.context, _request())

    result = register_account(
        sqlite_markets.context,
        _request(account_name="Renamed", account_is_active=False, is_paper=None),
    )

    (account,) = _rows(engine := sqlite_markets.engine, "SELECT * FROM ms_markets__account")
    assert (account["account_name"], account["account_is_active"], account["is_paper"]) == ("Renamed", 0, 1)
    assert result.response["account"]["uid"] == first.response["account"]["uid"]
    assert result.response["written"]["accounts"] == {"created": 0, "changed": 1}
    assert [(write.resource, write.action) for write in result.writes] == [("account", "update")]
    assert _count(engine, "ms_markets__accountholdingsts") == 3


def test_an_existing_asset_of_another_type_refuses_the_registration(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    _insert(engine, "ms_markets__asset", uid=uuid.uuid4().hex, unique_identifier="venue::AAPL", asset_type="equity")
    _insert(engine, "ms_markets__asset", uid=uuid.uuid4().hex, unique_identifier="USD", asset_type=None)
    operations = _record_operations(monkeypatch)

    with pytest.raises(AssetTypeConflictError) as refused:
        register_account(sqlite_markets.context, _request())

    assert "'venue::AAPL' is 'equity', not 'venue_equity'" in str(refused.value)
    assert "'USD' is None, not 'currency'" in str(refused.value)
    assert operations == ["read", "read"]
    assert _count(engine, "ms_markets__account") == 0
    assert _count(engine, "ms_markets__assettype") == 0
    assert _count(engine, "ms_markets__asset") == 2


def test_unknown_and_repeated_position_assets_are_refused_before_any_write(sqlite_markets, monkeypatch) -> None:
    operations = _record_operations(monkeypatch)

    with pytest.raises(ValueError, match=r"Assets 'GHOST-1', 'GHOST-2' were not found"):
        register_account(
            sqlite_markets.context,
            _request(
                positions=[
                    {"asset_identifier": "GHOST-1", "quantity": "1"},
                    {"asset_identifier": "venue::AAPL", "quantity": "1"},
                    {"asset_identifier": "GHOST-2", "quantity": "1"},
                ]
            ),
        )
    with pytest.raises(ValueError, match="repeated: 'venue::AAPL'"):
        register_account(
            sqlite_markets.context,
            _request(
                positions=[
                    {"asset_identifier": "venue::AAPL", "quantity": "1"},
                    {"asset_identifier": "venue::AAPL", "quantity": "2"},
                ]
            ),
        )

    assert operations == ["read", "read"]
    assert _count(sqlite_markets.engine, "ms_markets__asset") == 0


def test_a_position_may_name_an_existing_asset_not_listed_in_assets(sqlite_markets) -> None:
    _asset(sqlite_markets.engine, "venue::IBM")

    result = register_account(
        sqlite_markets.context,
        _request(assets=[], cash_currency=None, positions=[{"asset_identifier": "venue::IBM", "quantity": "1"}]),
    )

    assert list(result.response["asset_uids"]) == ["venue::IBM"]
    assert result.response["written"]["assets"] == {"created": 0, "changed": 0}


def test_snapshots_are_written_only_when_they_change_after_the_latest(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    register_account(sqlite_markets.context, _request(holdings_date=DAY_2))
    renamed = _request(holdings_date=DAY_1, overwrite=True)
    renamed["assets"][0]["snapshot"]["name"] = "Apple"

    # The latest snapshot is later than holdings_date: nothing is written over or before it.
    earlier = register_account(sqlite_markets.context, renamed)

    assert earlier.response["written"]["asset_snapshots"]["created"] == 0
    assert _count(engine, "ms_markets__assetsnapshotsts") == 2

    later = dict(renamed, holdings_date=(DAY_2 + dt.timedelta(days=1)).isoformat())
    result = register_account(sqlite_markets.context, later)

    assert result.response["written"]["asset_snapshots"]["created"] == 1
    assert _rows(
        engine,
        "SELECT asset_identifier, name FROM ms_markets__assetsnapshotsts ORDER BY time_index, asset_identifier",
    ) == [
        {"asset_identifier": "venue::AAPL", "name": "Apple Inc."},
        {"asset_identifier": "venue::MSFT", "name": "Microsoft"},
        {"asset_identifier": "venue::AAPL", "name": "Apple"},
    ]


def test_holdings_take_the_account_uid_that_exists_when_another_call_created_it_first(sqlite_markets) -> None:
    """Two first registrations: the second's candidate uid loses to the stored account."""

    engine = sqlite_markets.engine
    existing = _account(engine)
    _asset(engine, "AAA")
    (row,) = _rows(engine, "SELECT unique_identifier FROM ms_markets__account")
    writes = AccountRegistrationWrites(
        account_identifier=row["unique_identifier"],
        holdings_date=DAY_1,
        asset_identifiers=("AAA",),
        account=AccountWrite(uid=uuid.uuid4(), account_name="Second caller"),
        holdings=HoldingsWrite(
            holdings_set_uid=uuid.uuid4(),
            positions=(HoldingPosition("AAA", 1.0, 1, {}),),
        ),
    )

    answer = run_registration_writes(sqlite_markets.context, writes)

    assert uuid.UUID(answer["rows"][0]["uid"]) == existing
    assert {row["account_uid"] for row in _holdings(engine)} == {existing.hex}
    assert _rows(engine, "SELECT account_name FROM ms_markets__account") == [{"account_name": "Second caller"}]


def test_a_holdings_set_created_in_between_refuses_the_transaction(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    register_account(sqlite_markets.context, _request())
    writes = AccountRegistrationWrites(
        account_identifier="venue::account-1",
        holdings_date=DAY_1,
        asset_identifiers=("venue::AAPL",),
        account=AccountWrite(uid=uuid.uuid4(), account_name="Renamed"),
        holdings=HoldingsWrite(
            holdings_set_uid=uuid.uuid4(),
            positions=(HoldingPosition("venue::AAPL", 9.0, 1, {}),),
        ),
    )

    assert run_registration_writes(sqlite_markets.context, writes)["rows"] == []
    assert _rows(engine, "SELECT account_name FROM ms_markets__account") == [{"account_name": "Venue account"}]
    assert _count(engine, "ms_markets__accountholdingsts") == 3


def test_currency_get_or_create_creates_once_and_refuses_another_type(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    operations = _record_operations(monkeypatch)

    created = get_or_create_currency_asset(sqlite_markets.context, code="EUR")
    again = get_or_create_currency_asset(sqlite_markets.context, code="EUR")

    assert operations == ["transaction", "transaction"]
    assert created["uid"] == again["uid"]
    assert (created["unique_identifier"], created["asset_type"]) == ("EUR", "currency")
    assert _rows(engine, "SELECT asset_type FROM ms_markets__assettype") == [{"asset_type": "currency"}]

    _insert(engine, "ms_markets__asset", uid=uuid.uuid4().hex, unique_identifier="BTC", asset_type="crypto")
    with pytest.raises(AssetTypeConflictError, match="'BTC' exists with an asset_type other than 'currency'"):
        get_or_create_currency_asset(sqlite_markets.context, code="BTC")
    assert _rows(engine, "SELECT asset_type FROM ms_markets__asset WHERE unique_identifier = 'BTC'") == [
        {"asset_type": "crypto"}
    ]
