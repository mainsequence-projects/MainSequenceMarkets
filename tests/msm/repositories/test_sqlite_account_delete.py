"""The account delete on a SQLite DataSource, end to end (ADR 0050).

Each test migrates a fresh SQLite file and runs `msm.services` through MetaTables' own
server code for the local runtime, as `test_sqlite_snapshot_writes` does. Tables of
another application are created with `provider_ns__` names; the tests check that no
statement Markets sends names them, so they change only through their own keys.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.sql.util import find_tables

from msm.repositories.account_deletion import (
    ACCOUNT_DELETE_TABLES,
    account_delete_statements,
    count_account_delete_rows,
)
from msm.services import (
    AccountDeleteConflictError,
    bulk_delete_accounts,
    delete_account,
    preflight_account_delete,
    preflight_bulk_delete_accounts,
)
from tests.msm.repositories.test_sqlite_snapshot_writes import (
    WHEN,
    _account,
    _asset,
    _count,
    _fund,
    _insert,
    _portfolio,
    _portfolio_position,
    _rows,
    _write_funds,
    _write_holdings,
    _write_target,
    make_sqlite_markets,
)

MARKETS_TABLES = {table.model.__table__.name for table in ACCOUNT_DELETE_TABLES}


@pytest.fixture
def sqlite_markets(tmp_path, monkeypatch):
    return make_sqlite_markets(tmp_path, monkeypatch)


def _identifier(engine, account: uuid.UUID) -> str:
    (row,) = _rows(engine, "SELECT unique_identifier FROM ms_markets__account WHERE uid = :uid", uid=account.hex)
    return row["unique_identifier"]


def _order_manager(engine, account: uuid.UUID) -> str:
    identifier = f"manager-{uuid.uuid4().hex[:8]}"
    _insert(engine, "ms_markets__ordermanager", unique_identifier=identifier, target_account_uid=account.hex)
    return identifier


def _order(engine, account_identifier: str, *, order_identifier: str, manager: str | None = None) -> None:
    _insert(
        engine,
        "ms_markets__ordersts",
        order_time=WHEN,
        order_identifier=order_identifier,
        account_identifier=account_identifier,
        order_manager_identifier=manager,
        asset_identifier="AAA",
    )


def _trade(engine, account_identifier: str, *, order_identifier: str) -> None:
    _insert(
        engine,
        "ms_markets__tradests",
        trade_time=WHEN,
        trade_identifier=f"trade-{uuid.uuid4().hex[:8]}",
        account_identifier=account_identifier,
        order_identifier=order_identifier,
        asset_identifier="AAA",
        commission_asset_identifier=None,
        settlement_asset_identifier=None,
    )


def _order_event(engine, order_identifier: str, *, event_time: dt.datetime = WHEN) -> None:
    _insert(engine, "ms_markets__ordereventsts", event_time=event_time, order_identifier=order_identifier)


def _history(sqlite_markets, account: uuid.UUID) -> dict[str, str]:
    """Give the account one row in every table its delete reaches."""

    engine = sqlite_markets.engine
    identifier = _identifier(engine, account)
    portfolio = _portfolio(engine)
    written = _write_holdings(sqlite_markets, account, [{"asset_identifier": "AAA", "quantity": 1.0}])
    _write_target(sqlite_markets, account, [_portfolio_position(portfolio)])
    source = uuid.UUID(str(written["rows"][0]["holdings_set_uid"]))
    _write_funds(sqlite_markets, account, source, [_fund(f"fund-{identifier}", portfolio, ("AAA", 1.0))])
    manager = _order_manager(engine, account)
    order = f"order-{uuid.uuid4().hex[:8]}"
    _order(engine, identifier, order_identifier=order, manager=manager)
    _trade(engine, identifier, order_identifier=order)
    _order_event(engine, order)
    return {"identifier": identifier, "order": order, "manager": manager}


def _account_rows(engine, account: uuid.UUID, identifier: str) -> dict[str, int]:
    uid = account.hex
    queries = {
        "accounts": ("SELECT count(*) FROM ms_markets__account WHERE uid = :uid", {"uid": uid}),
        "holdings_sets": ("SELECT count(*) FROM ms_markets__accountholdingsset WHERE account_uid = :uid", {"uid": uid}),
        "holdings": ("SELECT count(*) FROM ms_markets__accountholdingsts WHERE account_uid = :uid", {"uid": uid}),
        "target_allocations": (
            "SELECT count(*) FROM ms_markets__accounttargetallocation WHERE account_uid = :uid",
            {"uid": uid},
        ),
        "virtual_funds": ("SELECT count(*) FROM ms_markets__virtualfund WHERE account_uid = :uid", {"uid": uid}),
        "order_managers": (
            "SELECT count(*) FROM ms_markets__ordermanager WHERE target_account_uid = :uid",
            {"uid": uid},
        ),
        "orders": (
            "SELECT count(*) FROM ms_markets__ordersts WHERE account_identifier = :identifier",
            {"identifier": identifier},
        ),
        "trades": (
            "SELECT count(*) FROM ms_markets__tradests WHERE account_identifier = :identifier",
            {"identifier": identifier},
        ),
    }
    with engine.connect() as connection:
        return {
            key: connection.execute(sa.text(sql), parameters).scalar_one()
            for key, (sql, parameters) in queries.items()
        }


def _no_impact(monkeypatch) -> None:
    """The fixture binds no MetaTables catalog; report the impact as unavailable."""

    from msm.services.accounts import deletion

    monkeypatch.setattr(deletion, "account_delete_impact", lambda: deletion.AccountDeleteImpact(impact=None))


# Statements ------------------------------------------------------------------------------


def test_every_statement_targets_a_markets_table() -> None:
    statements = account_delete_statements(uid=uuid.uuid4(), unique_identifier="account-1")

    assert len(statements) == len(ACCOUNT_DELETE_TABLES)
    for item in statements:
        statement = getattr(item, "statement", item)
        assert statement.table.name in MARKETS_TABLES
        assert {table.name for table in find_tables(statement, include_crud=True)} <= MARKETS_TABLES
    assert [getattr(item, "statement", item).table.name for item in statements] == [
        table.model.__table__.name for table in ACCOUNT_DELETE_TABLES
    ]
    assert statements[-1].label == "account" and statements[-1].expect_rows == 1


def test_a_blank_identifier_is_refused() -> None:
    with pytest.raises(ValueError, match="unique_identifier"):
        account_delete_statements(uid=uuid.uuid4(), unique_identifier=" ")


# The delete ------------------------------------------------------------------------------


def test_the_account_is_deleted_with_its_whole_history(sqlite_markets, monkeypatch) -> None:
    _no_impact(monkeypatch)
    engine = sqlite_markets.engine
    _asset(engine, "AAA")
    account, other = _account(engine), _account(engine)
    history = _history(sqlite_markets, account)
    other_history = _history(sqlite_markets, other)
    # Another account's order that reuses the identifier keeps its events.
    _order(engine, other_history["identifier"], order_identifier=history["order"])
    assets, portfolios = _count(engine, "ms_markets__asset"), _count(engine, "ms_markets__portfolio")

    before = count_account_delete_rows(
        sqlite_markets.context, uid=account, unique_identifier=history["identifier"]
    )
    deleted = delete_account(sqlite_markets.context, uid=str(account))

    assert deleted["uid"] == str(account)
    assert deleted["unique_identifier"] == history["identifier"]
    assert deleted["deleted_count"] == 1
    assert deleted["deleted_rows"] == {key: before[key] for key in deleted["deleted_rows"]}
    assert deleted["deleted_rows"]["order_events"] == 0  # its only order's identifier is shared
    assert all(
        deleted["deleted_rows"][key] >= 1 for key in deleted["deleted_rows"] if key != "order_events"
    )
    assert deleted["other_namespace_cascades"] == []
    assert set(_account_rows(engine, account, history["identifier"]).values()) == {0}
    assert _count(engine, "ms_markets__positionset") == 1
    assert _count(engine, "ms_markets__targetpositionsts") == 1
    assert _count(engine, "ms_markets__virtualfundholdingsset") == 1
    assert _count(engine, "ms_markets__virtualfundholdingsts") == 1
    assert _count(engine, "ms_markets__ordereventsts") == 2
    other_rows = _account_rows(engine, other, other_history["identifier"])
    assert other_rows["orders"] == 2 and 0 not in other_rows.values()
    assert _count(engine, "ms_markets__asset") == assets
    assert _count(engine, "ms_markets__portfolio") == portfolios


def test_the_events_of_the_accounts_own_orders_are_deleted(sqlite_markets, monkeypatch) -> None:
    _no_impact(monkeypatch)
    engine = sqlite_markets.engine
    _asset(engine, "AAA")
    account = _account(engine)
    history = _history(sqlite_markets, account)
    _order_event(engine, history["order"], event_time=WHEN + dt.timedelta(minutes=1))

    deleted = delete_account(sqlite_markets.context, uid=account)

    assert deleted["deleted_rows"]["order_events"] == 2
    assert _count(engine, "ms_markets__ordereventsts") == 0


def test_a_missing_account_deletes_nothing(sqlite_markets, monkeypatch) -> None:
    _no_impact(monkeypatch)
    missing = uuid.uuid4()

    assert delete_account(sqlite_markets.context, uid=missing) is None
    assert preflight_account_delete(sqlite_markets.context, uid=missing) is None


def test_an_invalid_uid_is_a_value_error(sqlite_markets, monkeypatch) -> None:
    _no_impact(monkeypatch)

    with pytest.raises(ValueError):
        delete_account(sqlite_markets.context, uid="not-a-uid")


# Other accounts' Markets rows ------------------------------------------------------------


def test_another_accounts_order_on_its_order_manager_blocks_the_delete(sqlite_markets, monkeypatch) -> None:
    _no_impact(monkeypatch)
    engine = sqlite_markets.engine
    _asset(engine, "AAA")
    account, other = _account(engine), _account(engine)
    history = _history(sqlite_markets, account)
    _order(engine, _identifier(engine, other), order_identifier="foreign", manager=history["manager"])

    preflight = preflight_account_delete(sqlite_markets.context, uid=account)
    assert preflight["blockers"] == [
        "1 orders of other accounts name its order managers (ON DELETE RESTRICT)."
    ]
    with pytest.raises(AccountDeleteConflictError, match="orders of other accounts"):
        delete_account(sqlite_markets.context, uid=account)
    assert _account_rows(engine, account, history["identifier"])["accounts"] == 1


# Other applications' tables --------------------------------------------------------------

PROVIDER_TABLES = (
    # A sidecar on the account with cascade delete (ADR 0047's worked example).
    "CREATE TABLE provider_ns__account_sidecar (account_uid CHAR(32) PRIMARY KEY "
    "REFERENCES ms_markets__account (uid) ON DELETE CASCADE, credentials TEXT)",
    # A storage instance of the holdings rows, which copies the core CASCADE key.
    "CREATE TABLE provider_ns__accountholdingsts__copy (holdings_set_uid CHAR(32) NOT NULL "
    "REFERENCES ms_markets__accountholdingsset (uid) ON DELETE CASCADE, quantity FLOAT)",
    # A storage instance of the order events, which has no key.
    "CREATE TABLE provider_ns__ordereventsts__copy (order_identifier VARCHAR(255) NOT NULL, status TEXT)",
    # A storage instance of the orders, which copies the core RESTRICT key.
    "CREATE TABLE provider_ns__ordersts__copy (order_identifier VARCHAR(255) PRIMARY KEY, "
    "account_identifier VARCHAR(255) NOT NULL REFERENCES ms_markets__account (unique_identifier) "
    "ON DELETE RESTRICT)",
)


def _create_provider_tables(engine) -> None:
    with engine.begin() as connection:
        for ddl in PROVIDER_TABLES:
            connection.exec_driver_sql(ddl)


def _provider_statements(markets) -> list[str]:
    return [sql for sql in markets.statements if "provider_ns__" in sql]


# The provider tables are created after the execution identity, so they lie outside
# it, as another application's tables do. SQLite still reads them to enforce their
# keys (mainsequence-projects/MetaTables#105).


def test_other_namespace_tables_change_only_through_their_own_keys(
    sqlite_markets, monkeypatch
) -> None:
    markets = sqlite_markets
    _no_impact(monkeypatch)
    engine = markets.engine
    _asset(engine, "AAA")
    account = _account(engine)
    history = _history(markets, account)
    _create_provider_tables(engine)
    (holdings_set,) = _rows(
        engine,
        "SELECT uid FROM ms_markets__accountholdingsset WHERE account_uid = :uid LIMIT 1",
        uid=account.hex,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__account_sidecar VALUES (?, 'secret')", (account.hex,)
        )
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__accountholdingsts__copy VALUES (?, 2.0)", (holdings_set["uid"],)
        )
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__ordereventsts__copy VALUES (?, 'filled')", (history["order"],)
        )

    deleted = delete_account(markets.context, uid=account)

    assert deleted is not None
    assert _provider_statements(markets) == []
    assert _count(engine, "provider_ns__account_sidecar") == 0  # its own CASCADE key
    assert _count(engine, "provider_ns__accountholdingsts__copy") == 0  # its own CASCADE key
    assert _count(engine, "provider_ns__ordereventsts__copy") == 1  # no key: it stays


def test_a_restrict_key_in_another_namespace_refuses_the_whole_delete(
    sqlite_markets, monkeypatch
) -> None:
    markets = sqlite_markets
    _no_impact(monkeypatch)
    engine = markets.engine
    _asset(engine, "AAA")
    account = _account(engine)
    history = _history(markets, account)
    _create_provider_tables(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__ordersts__copy VALUES ('provider-order', ?)", (history["identifier"],)
        )
    before = _account_rows(engine, account, history["identifier"])

    with pytest.raises(AccountDeleteConflictError, match="nothing was deleted"):
        delete_account(markets.context, uid=account)

    assert _provider_statements(markets) == []
    assert _account_rows(engine, account, history["identifier"]) == before
    assert _count(engine, "ms_markets__ordereventsts") == 1
    assert _count(engine, "provider_ns__ordersts__copy") == 1


def test_keys_from_tables_outside_the_identity_do_not_stop_the_delete(sqlite_markets, monkeypatch) -> None:
    _no_impact(monkeypatch)
    engine = sqlite_markets.engine
    _asset(engine, "AAA")
    account = _account(engine)
    _history(sqlite_markets, account)
    _create_provider_tables(engine)

    assert delete_account(sqlite_markets.context, uid=account) is not None


# Bulk ------------------------------------------------------------------------------------


def test_bulk_delete_deletes_each_account_and_reports_the_rest(sqlite_markets, monkeypatch) -> None:
    _no_impact(monkeypatch)
    engine = sqlite_markets.engine
    _asset(engine, "AAA")
    first, blocked, other = _account(engine), _account(engine), _account(engine)
    _history(sqlite_markets, first)
    blocked_history = _history(sqlite_markets, blocked)
    _order(engine, _identifier(engine, other), order_identifier="foreign", manager=blocked_history["manager"])
    missing = uuid.uuid4()

    preflight = preflight_bulk_delete_accounts(sqlite_markets.context, uids=[first, blocked, missing])
    assert preflight["allowed"] is False
    assert preflight["matched_count"] == 2
    assert [item["uid"] for item in preflight["accounts"]] == [str(first), str(blocked)]
    assert f"Account {missing} was not found." in preflight["blockers"]

    result = bulk_delete_accounts(sqlite_markets.context, uids=[first, blocked, missing, first])

    assert result["deleted_count"] == 1
    assert [item["uid"] for item in result["deleted"]] == [str(first)]
    assert [item["uid"] for item in result["failed"]] == [str(blocked), str(missing)]
    assert _count(engine, "ms_markets__account") == 2


def test_bulk_preflight_allows_a_clean_selection(sqlite_markets, monkeypatch) -> None:
    _no_impact(monkeypatch)
    engine = sqlite_markets.engine
    _asset(engine, "AAA")
    first, second = _account(engine), _account(engine)
    _history(sqlite_markets, first)

    preflight = preflight_bulk_delete_accounts(sqlite_markets.context, uids=[first, second])

    assert preflight["allowed"] is True
    assert preflight["blockers"] == []
    counts = {item["uid"]: item["row_counts"] for item in preflight["accounts"]}
    assert counts[str(first)]["holdings"] >= 1
    assert set(counts[str(second)].values()) == {0}
    assert _count(engine, "ms_markets__account") == 2


def test_the_preflight_counts_match_what_the_delete_removes(sqlite_markets, monkeypatch) -> None:
    _no_impact(monkeypatch)
    engine = sqlite_markets.engine
    _asset(engine, "AAA")
    account = _account(engine)
    _history(sqlite_markets, account)
    totals_before = {name: _count(engine, name) for name in MARKETS_TABLES}

    counts = preflight_account_delete(sqlite_markets.context, uid=account)["row_counts"]
    delete_account(sqlite_markets.context, uid=account)

    removed = {
        table.key: totals_before[table.model.__table__.name] - _count(engine, table.model.__table__.name)
        for table in ACCOUNT_DELETE_TABLES
        if table.key != "accounts"
    }
    assert removed == counts
