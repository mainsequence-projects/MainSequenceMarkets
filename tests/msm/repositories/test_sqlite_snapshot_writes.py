"""The account snapshot writes on a SQLite DataSource, end to end (MainSequenceMarkets#53).

SQLite accepts only `SELECT` inside `WITH`, so these writes run there as statement
lists in one MetaTables transaction (MetaTables ADR 0026). Each test gets its own copy
of a SQLite file migrated to head with the Markets migrations, then runs the
repositories through MetaTables' own server code for the local runtime
(`tests/support/sqlite_markets.py`): `MetaTable.execute_operation` and
`MetaTable.execute_transaction` go, after wire serialization, to the SQLite backend's
`execute` and `execute_transaction`, which bind values and own the transaction as the
local API does. Nothing leaves the process.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest

from metatables import MetaTable

from msm.repositories.accounts import replace_account_target_positions_snapshot
from msm.repositories.base import MarketsRepositoryContext
from tests.support.sqlite_markets import (
    WHEN,
    _account,
    _asset,
    _count,
    _insert,
    _portfolio,
    _portfolio_position,
    _rows,
    _write_holdings,
    _write_target,
)

STORED_WHEN = "2026-11-10 15:30:00.000000"  # How the local runtime stores a UTC timestamp.


# Holdings ----------------------------------------------------------------------------


def test_holdings_snapshot_writes_the_set_and_its_rows(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAA")
    _asset(engine, "BBB")

    result = _write_holdings(
        sqlite_markets,
        account,
        [
            {"asset_identifier": "AAA", "quantity": 10.0, "extra_details": {"lot": 1}},
            {"asset_identifier": "BBB", "quantity": 5.5, "direction": -1},
        ],
    )

    assert sorted(row["asset_identifier"] for row in result["rows"]) == ["AAA", "BBB"]
    (holdings_set,) = _rows(engine, "SELECT uid, account_uid, time_index FROM ms_markets__accountholdingsset")
    assert holdings_set["account_uid"] == account.hex
    assert holdings_set["time_index"] == STORED_WHEN
    stored = _rows(
        engine,
        "SELECT asset_identifier, quantity, direction, holdings_set_uid, time_index, "
        "target_trade_time, extra_details FROM ms_markets__accountholdingsts ORDER BY asset_identifier",
    )
    assert [(row["asset_identifier"], row["quantity"], row["direction"]) for row in stored] == [
        ("AAA", 10.0, 1),
        ("BBB", 5.5, -1),
    ]
    assert {row["holdings_set_uid"] for row in stored} == {holdings_set["uid"]}
    assert {row["time_index"] for row in stored} == {STORED_WHEN}
    assert {row["target_trade_time"] for row in stored} == {STORED_WHEN}
    assert json.loads(stored[0]["extra_details"]) == {"lot": 1}


def test_existing_holdings_snapshot_is_refused_without_overwrite_and_replaced_with_it(
    sqlite_markets,
) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAA")
    _asset(engine, "BBB")
    _write_holdings(sqlite_markets, account, [{"asset_identifier": "AAA", "quantity": 1.0}])

    refused = _write_holdings(sqlite_markets, account, [{"asset_identifier": "BBB", "quantity": 2.0}])

    assert refused["rows"] == []
    assert _rows(engine, "SELECT asset_identifier, quantity FROM ms_markets__accountholdingsts") == [
        {"asset_identifier": "AAA", "quantity": 1.0}
    ]

    replaced = _write_holdings(
        sqlite_markets, account, [{"asset_identifier": "BBB", "quantity": 2.0}], overwrite=True
    )

    assert [row["asset_identifier"] for row in replaced["rows"]] == ["BBB"]
    assert _rows(engine, "SELECT asset_identifier, quantity FROM ms_markets__accountholdingsts") == [
        {"asset_identifier": "BBB", "quantity": 2.0}
    ]
    assert _count(engine, "ms_markets__accountholdingsset") == 1


def test_a_failing_holdings_row_rolls_back_the_whole_snapshot(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAA")

    with pytest.raises(Exception, match="FOREIGN KEY"):
        _write_holdings(
            sqlite_markets,
            account,
            [
                {"asset_identifier": "AAA", "quantity": 1.0},
                {"asset_identifier": "NOT-AN-ASSET", "quantity": 1.0},
            ],
        )

    assert _count(engine, "ms_markets__accountholdingsset") == 0
    assert _count(engine, "ms_markets__accountholdingsts") == 0


# Target positions ----------------------------------------------------------------------


def test_target_snapshot_writes_the_allocation_its_position_set_and_rows(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio = _portfolio(engine)
    asset = _asset(engine, "AAA")

    result = _write_target(
        sqlite_markets,
        account,
        [
            _portfolio_position(portfolio),
            {"target_type": "asset", "target_uid": asset, "asset_uid": asset, "single_asset_quantity": 3.0},
        ],
    )

    assert sorted(row["target_type"] for row in result["rows"]) == ["asset", "portfolio"]
    (model,) = _rows(engine, "SELECT uid, allocation_model_name, metadata_json FROM ms_markets__accountallocationmodel")
    assert model["allocation_model_name"] == str(account)
    (allocation,) = _rows(
        engine,
        "SELECT uid, unique_identifier, account_uid, account_allocation_model_uid, display_name, "
        "is_active, source FROM ms_markets__accounttargetallocation",
    )
    assert allocation["unique_identifier"] == str(account)  # Dashed, as on PostgreSQL.
    assert allocation["account_uid"] == account.hex
    assert allocation["account_allocation_model_uid"] == model["uid"]
    assert (allocation["display_name"], allocation["is_active"], allocation["source"]) == (
        "SQLite account",
        1,
        "apps.v1",
    )
    (position_set,) = _rows(
        engine,
        "SELECT uid, account_target_allocation_uid, position_set_time FROM ms_markets__positionset",
    )
    assert position_set["account_target_allocation_uid"] == allocation["uid"]
    assert position_set["position_set_time"] == STORED_WHEN
    stored = _rows(
        engine,
        "SELECT target_type, portfolio_uid, asset_uid, weight_notional_exposure, "
        "single_asset_quantity, position_set_uid, time_index, metadata_json "
        "FROM ms_markets__targetpositionsts ORDER BY target_type",
    )
    assert [
        (row["target_type"], row["asset_uid"], row["portfolio_uid"]) for row in stored
    ] == [("asset", asset.hex, None), ("portfolio", None, portfolio.hex)]
    assert stored[1]["weight_notional_exposure"] == 0.4
    assert stored[0]["single_asset_quantity"] == 3.0
    assert {row["position_set_uid"] for row in stored} == {position_set["uid"]}
    assert {row["time_index"] for row in stored} == {STORED_WHEN}
    assert json.loads(stored[1]["metadata_json"]) == {"note": "sqlite"}


def test_existing_target_snapshot_is_refused_without_overwrite_and_replaced_with_it(
    sqlite_markets,
) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    first, second = _portfolio(engine), _portfolio(engine)
    _write_target(sqlite_markets, account, [_portfolio_position(first)])

    refused = _write_target(sqlite_markets, account, [_portfolio_position(second)])

    assert refused["rows"] == []
    assert _rows(engine, "SELECT portfolio_uid FROM ms_markets__targetpositionsts") == [
        {"portfolio_uid": first.hex}
    ]

    replaced = _write_target(sqlite_markets, account, [_portfolio_position(second, 0.5)], overwrite=True)

    assert [row["weight_notional_exposure"] for row in replaced["rows"]] == [0.5]
    assert _rows(engine, "SELECT portfolio_uid FROM ms_markets__targetpositionsts") == [
        {"portfolio_uid": second.hex}
    ]
    assert _count(engine, "ms_markets__positionset") == 1
    assert _count(engine, "ms_markets__accounttargetallocation") == 1


def test_a_retired_portfolio_refuses_the_target_snapshot_and_nothing_is_written(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    live, retired = _portfolio(engine), _portfolio(engine, retired=True)

    result = _write_target(
        sqlite_markets, account, [_portfolio_position(live), _portfolio_position(retired)]
    )

    assert result["rows"] == []
    for table in (
        "ms_markets__accountallocationmodel",
        "ms_markets__accounttargetallocation",
        "ms_markets__positionset",
        "ms_markets__targetpositionsts",
    ):
        assert _count(engine, table) == 0, table


def test_clearing_the_target_writes_an_empty_position_set_and_deactivates_the_allocation(
    sqlite_markets,
) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio = _portfolio(engine)
    _write_target(sqlite_markets, account, [_portfolio_position(portfolio)])

    later = WHEN + dt.timedelta(days=1)
    cleared = replace_account_target_positions_snapshot(
        sqlite_markets.context,
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        account_uid=account,
        account_name="SQLite account",
        target_positions_date=later,
        positions=[],
    )

    position_sets = _rows(
        engine, "SELECT uid, position_set_time FROM ms_markets__positionset ORDER BY position_set_time"
    )
    assert [row["position_set_time"] for row in position_sets] == [
        STORED_WHEN,
        "2026-11-11 15:30:00.000000",
    ]
    # The answer renders the uid dashed, as the MetaTables route does; the table stores it as hex.
    assert [uuid.UUID(row["uid"]).hex for row in cleared["rows"]] == [position_sets[1]["uid"]]
    assert _rows(engine, "SELECT is_active FROM ms_markets__accounttargetallocation") == [{"is_active": 0}]
    # History keeps the earlier snapshot; the clear adds an empty one.
    assert _rows(engine, "SELECT position_set_uid FROM ms_markets__targetpositionsts") == [
        {"position_set_uid": position_sets[0]["uid"]}
    ]


def test_clearing_over_an_existing_snapshot_is_refused_without_overwrite(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio = _portfolio(engine)
    _write_target(sqlite_markets, account, [_portfolio_position(portfolio)])

    refused = _write_target(sqlite_markets, account, [])

    assert refused["rows"] == []
    assert _rows(engine, "SELECT is_active FROM ms_markets__accounttargetallocation") == [{"is_active": 1}]
    assert _count(engine, "ms_markets__targetpositionsts") == 1

    cleared = _write_target(sqlite_markets, account, [], overwrite=True)

    assert len(cleared["rows"]) == 1
    assert _rows(engine, "SELECT is_active FROM ms_markets__accounttargetallocation") == [{"is_active": 0}]
    assert _count(engine, "ms_markets__targetpositionsts") == 0
    assert _count(engine, "ms_markets__positionset") == 1


# The services behind the routes -------------------------------------------------------
#
# Routes pass UUIDs as text, and each service reads back what it wrote. These run the
# whole service on SQLite (MetaTables 0.1.61 binds text UUIDs there, MetaTables#100/#101),
# through the `msm.services` entry points the Markets API calls.


def test_the_holdings_service_writes_reads_back_and_refuses_a_repeat(sqlite_markets) -> None:
    from msm.services import add_account_holdings_snapshot_response
    from msm.services.accounts import AccountHoldingsSnapshotExistsError

    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAA")

    snapshot = add_account_holdings_snapshot_response(
        sqlite_markets.context,
        account_uid=str(account),
        holdings_date=WHEN,
        positions=[{"asset_identifier": "AAA", "quantity": 2.0}],
    )

    assert snapshot["holdings_date"] == WHEN
    assert [row["asset_identifier"] for row in snapshot["holdings"]] == ["AAA"]
    with pytest.raises(AccountHoldingsSnapshotExistsError):
        add_account_holdings_snapshot_response(
            sqlite_markets.context,
            account_uid=str(account),
            holdings_date=WHEN,
            positions=[{"asset_identifier": "AAA", "quantity": 3.0}],
        )
    assert _rows(engine, "SELECT quantity FROM ms_markets__accountholdingsts") == [{"quantity": 2.0}]


def _record_operations(monkeypatch) -> list[str]:
    """The kind of each MetaTables operation run from here on, in order."""

    operations: list[str] = []
    execute_operation, execute_transaction = MetaTable.execute_operation, MetaTable.execute_transaction

    def recorded_operation(cls, operation, *, timeout=None):
        operations.append(operation.operation)
        return execute_operation(operation, timeout=timeout)

    def recorded_transaction(cls, transaction, *, timeout=None):
        operations.append(transaction.operation)
        return execute_transaction(transaction, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(recorded_operation))
    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(recorded_transaction))
    return operations


def _holdings_positions(identifiers):
    return [
        {"asset_identifier": identifier, "quantity": index + 1.5, "direction": -1 if index % 2 else 1}
        for index, identifier in enumerate(identifiers)
    ]


@pytest.mark.parametrize("include_asset_detail", [True, False])
def test_a_holdings_publish_costs_three_operations_whatever_its_size(
    sqlite_markets, monkeypatch, include_asset_detail
) -> None:
    """MainSequenceMarkets#61: read the account, read every asset at once, write. No read-back."""

    from msm.services import add_account_holdings_snapshot_response
    from msm.services.accounts import get_account_holdings_snapshot_response

    engine = sqlite_markets.engine
    account = _account(engine)
    identifiers = [f"ASSET-{index:02d}" for index in range(12)]
    for identifier in identifiers:
        _asset(engine, identifier)
    _insert(
        engine,
        "ms_markets__assetsnapshotsts",
        time_index=WHEN,
        asset_identifier="ASSET-03",
        name="Asset three",
        ticker="A3",
    )
    operations = _record_operations(monkeypatch)

    snapshot = add_account_holdings_snapshot_response(
        sqlite_markets.context,
        account_uid=str(account),
        holdings_date=WHEN,
        # Sent in reverse; the snapshot lists holdings by asset identifier.
        positions=_holdings_positions(reversed(identifiers)),
        include_asset_detail=include_asset_detail,
    )

    assert operations == ["select", "select", "upsert"]
    # The answer is the snapshot a read returns.
    assert snapshot == get_account_holdings_snapshot_response(
        sqlite_markets.context,
        account_uid=str(account),
        holdings_date=WHEN,
        include_asset_detail=include_asset_detail,
    )
    assert [row["asset_identifier"] for row in snapshot["holdings"]] == identifiers
    asset = snapshot["holdings"][3]["asset"]
    if include_asset_detail:
        assert asset["asset_identifier"] == "ASSET-03"
        assert asset["current_snapshot"] == {"name": "Asset three", "ticker": "A3"}
    else:
        assert asset is None


def test_a_holdings_publish_names_every_unknown_asset_and_writes_nothing(
    sqlite_markets, monkeypatch
) -> None:
    from msm.services import add_account_holdings_snapshot_response

    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAA")
    operations = _record_operations(monkeypatch)

    with pytest.raises(ValueError) as raised:
        add_account_holdings_snapshot_response(
            sqlite_markets.context,
            account_uid=str(account),
            holdings_date=WHEN,
            positions=_holdings_positions(["MISSING-1", "AAA", "MISSING-2"]),
        )

    assert str(raised.value) == "Assets 'MISSING-1', 'MISSING-2' were not found."
    assert operations == ["select", "select"]
    assert _count(engine, "ms_markets__accountholdingsset") == 0
    assert _count(engine, "ms_markets__accountholdingsts") == 0


def test_a_holdings_publish_over_the_row_cap_reads_the_rows_its_write_did_not_return(
    sqlite_markets, monkeypatch
) -> None:
    """A write returns at most an operation's `max_rows` rows; one read then returns them all."""

    from msm.services import add_account_holdings_snapshot_response
    from msm.services.accounts import get_account_holdings_snapshot_response

    engine = sqlite_markets.engine
    account = _account(engine)
    identifiers = ["A", "B", "C", "D", "E"]
    for identifier in identifiers:
        _asset(engine, identifier)
    capped = MarketsRepositoryContext(limits={"max_rows": 2})
    operations = _record_operations(monkeypatch)

    snapshot = add_account_holdings_snapshot_response(
        capped,
        account_uid=str(account),
        holdings_date=WHEN,
        positions=_holdings_positions(identifiers),
    )

    # Account; assets in pages of two; the write; its five rows in one read.
    assert operations == ["select"] + ["select"] * 3 + ["upsert", "select"]
    assert [row["asset_identifier"] for row in snapshot["holdings"]] == identifiers
    assert snapshot == get_account_holdings_snapshot_response(
        sqlite_markets.context,
        account_uid=str(account),
        holdings_date=WHEN,
    )


def test_the_target_service_writes_reads_back_and_refuses_repeats_and_retired_portfolios(
    sqlite_markets,
) -> None:
    from msm.services import add_account_target_positions_snapshot_response
    from msm.services.portfolio_lifecycle import PortfolioRetiredError
    from msm.services.target_positions import AccountTargetPositionsSnapshotExistsError

    engine = sqlite_markets.engine
    account = _account(engine)
    live, retired = _portfolio(engine), _portfolio(engine, retired=True)

    def add(portfolio, when=WHEN):
        return add_account_target_positions_snapshot_response(
            sqlite_markets.context,
            account_uid=str(account),
            target_positions_date=when,
            positions=[
                {
                    "target_type": "portfolio",
                    "portfolio_uid": str(portfolio),
                    "weight_notional_exposure": 0.4,
                }
            ],
        )

    snapshot = add(live)

    assert snapshot["target_positions_date"] == WHEN
    assert len(snapshot["positions"]) == 1
    with pytest.raises(AccountTargetPositionsSnapshotExistsError):
        add(live)
    with pytest.raises(PortfolioRetiredError):
        add(retired, WHEN + dt.timedelta(days=1))
    assert _count(engine, "ms_markets__positionset") == 1
    assert _count(engine, "ms_markets__targetpositionsts") == 1


def test_writing_an_exposure_to_a_portfolio_creates_its_virtual_fund(sqlite_markets) -> None:
    """A fund exists from the moment it is requested, and is created once (ADR 0054)."""

    from msm.services import add_account_target_positions_snapshot_response
    from msm.services.accounts.account_virtual_allocations import (
        virtual_fund_unique_identifier_for_target,
    )

    engine = sqlite_markets.engine
    account = _account(engine)
    asset = _asset(engine, "AAPL")
    first, second = _portfolio(engine), _portfolio(engine)

    def add(positions, when):
        return add_account_target_positions_snapshot_response(
            sqlite_markets.context,
            account_uid=str(account),
            target_positions_date=when,
            positions=positions,
        )

    def exposure(portfolio, **value):
        return {"target_type": "portfolio", "portfolio_uid": str(portfolio), **value}

    add([exposure(first, weight_notional_exposure=0.4)], WHEN)
    funds = _rows(
        engine, "SELECT uid, unique_identifier, account_uid, target_portfolio_uid FROM ms_markets__virtualfund"
    )
    (allocation,) = _rows(engine, "SELECT uid FROM ms_markets__accounttargetallocation")

    assert [(row["account_uid"], row["target_portfolio_uid"]) for row in funds] == [
        (account.hex, first.hex)
    ]
    # The key is the one an allocation looks the fund up by.
    assert funds[0]["unique_identifier"] == virtual_fund_unique_identifier_for_target(
        account_uid=account,
        target_portfolio_uid=first,
        account_target_allocation_uid=allocation["uid"],
    )
    assert _count(engine, "ms_markets__virtualfundholdingsset") == 0

    # A later target keeps the first fund and creates only the new one.
    add(
        [
            exposure(first, weight_notional_exposure=0.3),
            exposure(second, weight_notional_exposure=0.3),
        ],
        WHEN + dt.timedelta(days=1),
    )
    later = _rows(engine, "SELECT uid, target_portfolio_uid FROM ms_markets__virtualfund")
    assert {row["target_portfolio_uid"]: row["uid"] for row in later} == {
        first.hex: funds[0]["uid"],
        second.hex: next(row["uid"] for row in later if row["target_portfolio_uid"] == second.hex),
    }
    assert len(later) == 2

    # A target of direct assets requests no fund.
    add(
        [{"target_type": "asset", "asset_uid": str(asset), "single_asset_quantity": 10.0}],
        WHEN + dt.timedelta(days=2),
    )
    assert _count(engine, "ms_markets__virtualfund") == 2
