"""The account delete on a SQLite DataSource, end to end (ADR 0050, issue 91).

Each test migrates a fresh SQLite file and runs `msm.services` through MetaTables' own
server code for the local runtime, as `test_sqlite_snapshot_writes` does. Tables of
another application are created with `provider_ns__` names; the tests check that no
statement Markets sends names them, so they change only through their own keys.

The delete that also takes the account's portfolios belongs to `msm_portfolios`; its
tests are in `tests/msm_portfolios/services/test_sqlite_account_portfolio_delete.py`
and reuse this module's fixture and data.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.sql.util import find_tables

from msm.models import AccountTable
from msm.repositories.account_deletion import (
    ACCOUNT_DELETE_TABLES,
    account_delete_statements,
    read_account_delete,
)
from msm.services import (
    AccountDeleteConflictError,
    bulk_delete_accounts,
    delete_account,
    preflight_account_delete,
    preflight_bulk_delete_accounts,
)
from msm.services.accounts import deletion
from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.msm.repositories.test_sqlite_snapshot_writes import (
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
    make_sqlite_markets,
)

MARKETS_TABLES = {table.model.__table__.name for table in ACCOUNT_DELETE_TABLES}
DATASETS = {table.key: table.table_name for table in PORTFOLIO_DATASET_TABLES}
ACCOUNT_TABLE_UID = "5a5a5a5a-0000-4000-8000-000000000005"
ACCOUNT_DELETE_IMPACT = deletion.account_delete_impact


@pytest.fixture
def sqlite_markets(tmp_path, monkeypatch):
    return make_account_markets(tmp_path, monkeypatch)


def make_account_markets(tmp_path, monkeypatch) -> SimpleNamespace:
    """The harness, recording each MetaTables request and refusing the impact."""

    from metatables import MetaTable

    markets = make_sqlite_markets(tmp_path, monkeypatch)
    requests: list[str] = []
    execute_operation = MetaTable.execute_operation
    execute_transaction = MetaTable.execute_transaction

    def operation(cls, operation, *, timeout=None):
        requests.append("read" if operation.operation == "select" else operation.operation)
        return execute_operation(operation, timeout=timeout)

    def transaction(cls, transaction, *, timeout=None):
        requests.append(f"transaction:{len(transaction.statements)}")
        return execute_transaction(transaction, timeout=timeout)

    def no_impact():
        raise AssertionError("The account delete must not ask MetaTables for its impact.")

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(operation))
    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(transaction))
    monkeypatch.setattr(deletion, "account_delete_impact", no_impact)
    _asset(markets.engine, "AAA")
    return SimpleNamespace(**vars(markets), requests=requests)


def _progress(markets, model) -> dict:
    """The progress MetaTables stores for ``model``'s table, as the harness keeps it."""

    return markets.index_stats[model.__table__.name].get("index_progress", {})


def _impact_unavailable(monkeypatch) -> list[str]:
    """Let the preflight ask for the impact, which the fixture has no catalog to compute."""

    calls: list[str] = []

    def impact():
        calls.append("impact")
        return deletion.AccountDeleteImpact(impact=None)

    monkeypatch.setattr(deletion, "account_delete_impact", impact)
    return calls


# Data ------------------------------------------------------------------------------------


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


def _virtual_fund(engine, account, source, portfolio, unique_identifier: str) -> None:
    """One virtual fund allocated from ``source``: its row, its holdings set and one holding."""

    fund = uuid.uuid4()
    holdings_set = uuid.uuid4()
    _insert(
        engine,
        "ms_markets__virtualfund",
        uid=fund.hex,
        unique_identifier=unique_identifier,
        account_uid=account.hex,
        target_portfolio_uid=portfolio.hex,
    )
    _insert(
        engine,
        "ms_markets__virtualfundholdingsset",
        uid=holdings_set.hex,
        virtual_fund_uid=fund.hex,
        source_account_holdings_set_uid=source.hex,
        time_index=WHEN,
    )
    _insert(
        engine,
        "ms_markets__virtualfundholdingsts",
        time_index=WHEN,
        virtual_fund_uid=fund.hex,
        asset_identifier="AAA",
        virtual_fund_holdings_set_uid=holdings_set.hex,
        source_account_holdings_set_uid=source.hex,
        allocated_quantity=1.0,
        allocation_strategy="explicit",
        direction=1,
    )
    # The allocation's lines: what the fund was assigned against its sized target.
    _insert(
        engine,
        "ms_markets__accountallocationlinests",
        time_index=WHEN,
        holdings_set_uid=source.hex,
        owner_type="fund",
        owner_uid=fund.hex,
        asset_identifier="AAA",
        account_uid=account.hex,
        virtual_fund_uid=fund.hex,
        target_quantity=2.0,
        target_direction=1,
        assigned_quantity=1.0,
        assigned_direction=1,
        allocation_strategy="proportional_attribution",
    )


def _history(
    sqlite_markets,
    account: uuid.UUID,
    portfolio: uuid.UUID | None = None,
    *,
    also_targets: tuple[uuid.UUID, ...] = (),
) -> dict:
    """Give the account one row in every table its delete reaches.

    Its target rows and its virtual fund name ``portfolio``, a new one by default; its
    target rows also name ``also_targets``.
    """

    engine = sqlite_markets.engine
    identifier = _identifier(engine, account)
    portfolio = portfolio or _portfolio(engine)
    written = _write_holdings(sqlite_markets, account, [{"asset_identifier": "AAA", "quantity": 1.0}])
    targets = _write_target(
        sqlite_markets,
        account,
        [_portfolio_position(target) for target in (portfolio, *also_targets)],
    )
    assert len(targets["rows"]) == 1 + len(also_targets)
    source = uuid.UUID(str(written["rows"][0]["holdings_set_uid"]))
    _virtual_fund(engine, account, source, portfolio, f"fund-{identifier}")
    manager = _order_manager(engine, account)
    order = f"order-{uuid.uuid4().hex[:8]}"
    _order(engine, identifier, order_identifier=order, manager=manager)
    _trade(engine, identifier, order_identifier=order)
    _order_event(engine, order)
    return {"identifier": identifier, "order": order, "manager": manager, "portfolio": portfolio}


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


def _portfolio_identifier(engine, portfolio: uuid.UUID) -> str:
    (row,) = _rows(engine, "SELECT unique_identifier FROM ms_markets__portfolio WHERE uid = :uid", uid=portfolio.hex)
    return row["unique_identifier"]


def _portfolio_with_data(engine) -> tuple[uuid.UUID, str]:
    """A portfolio with one row in each of its datasets."""

    portfolio = _portfolio(engine)
    identifier = _portfolio_identifier(engine, portfolio)
    for table_name in DATASETS.values():
        assets = {
            foreign_key["constrained_columns"][0]: "AAA"
            for foreign_key in sa.inspect(engine).get_foreign_keys(table_name)
            if foreign_key["referred_table"] == "ms_markets__asset"
        }
        _insert(engine, table_name, time_index=WHEN, portfolio_identifier=identifier, **assets)
    return portfolio, identifier


def _dataset_rows(engine, identifier: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            key: connection.execute(
                sa.text(f"SELECT count(*) FROM {table_name} WHERE portfolio_identifier = :identifier"),
                {"identifier": identifier},
            ).scalar_one()
            for key, table_name in DATASETS.items()
        }


def _exists(engine, portfolio: uuid.UUID) -> bool:
    return bool(_rows(engine, "SELECT uid FROM ms_markets__portfolio WHERE uid = :uid", uid=portfolio.hex))


def _catalog(engine, portfolio: uuid.UUID, *, values: str) -> None:
    _insert(
        engine,
        "ms_markets__portfoliodatasetavailability",
        portfolio_uid=portfolio.hex,
        values_meta_table_uid=values,
        weights_meta_table_uid=None,
        signal_meta_table_uid=None,
        population_state="unavailable",
        row_count=None,
        earliest_time_index=None,
        latest_time_index=None,
    )


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


def test_the_account_is_deleted_with_its_whole_history(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account, other = _account(engine), _account(engine)
    history = _history(sqlite_markets, account)
    other_history = _history(sqlite_markets, other)
    # Another account's order that reuses the identifier keeps its events.
    _order(engine, other_history["identifier"], order_identifier=history["order"])
    assets, portfolios = _count(engine, "ms_markets__asset"), _count(engine, "ms_markets__portfolio")

    before = read_account_delete(sqlite_markets.context, uid=account)["counts"]
    deleted = delete_account(sqlite_markets.context, uid=str(account))

    assert deleted == {
        "detail": f"Account {history['identifier']!r} deleted with its history.",
        "uid": str(account),
        "unique_identifier": history["identifier"],
        "deleted_count": 1,
        "deleted_rows": {key: before[key] for key in deleted["deleted_rows"]},
    }
    assert deleted["deleted_rows"]["order_events"] == 0  # its only order's identifier is shared
    assert all(
        deleted["deleted_rows"][key] >= 1 for key in deleted["deleted_rows"] if key != "order_events"
    )
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


def test_the_events_of_the_accounts_own_orders_are_deleted(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    history = _history(sqlite_markets, account)
    _order_event(engine, history["order"], event_time=WHEN + dt.timedelta(minutes=1))

    deleted = delete_account(sqlite_markets.context, uid=account)

    assert deleted["deleted_rows"]["order_events"] == 2
    assert _count(engine, "ms_markets__ordereventsts") == 0


def test_a_missing_account_deletes_nothing(sqlite_markets) -> None:
    missing = uuid.uuid4()

    assert delete_account(sqlite_markets.context, uid=missing) is None
    assert preflight_account_delete(sqlite_markets.context, uid=missing) is None
    assert sqlite_markets.requests == ["read", "read"]


def test_an_invalid_uid_is_a_value_error(sqlite_markets) -> None:
    with pytest.raises(ValueError):
        delete_account(sqlite_markets.context, uid="not-a-uid")


def test_one_delete_sends_one_read_and_one_transaction(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _history(sqlite_markets, account)
    sqlite_markets.requests.clear()

    delete_account(sqlite_markets.context, uid=account)

    assert sqlite_markets.requests == ["read", f"transaction:{len(ACCOUNT_DELETE_TABLES)}"]


def test_the_portfolios_its_history_names_stay_with_their_data(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    _history(sqlite_markets, account, portfolio)

    deleted = delete_account(sqlite_markets.context, uid=account)

    assert "deleted_portfolios" not in deleted
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
    assert not _rows(engine, "SELECT uid FROM ms_markets__account WHERE uid = :uid", uid=account.hex)


def test_an_account_changed_in_between_deletes_nothing(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _history(sqlite_markets, account)
    read = deletion.account_deletion_repository.read_account_delete

    def read_then_rename(context, **kwargs):
        result = read(context, **kwargs)
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE ms_markets__account SET unique_identifier = 'renamed' WHERE uid = :uid"),
                {"uid": account.hex},
            )
        return result

    monkeypatch.setattr(deletion.account_deletion_repository, "read_account_delete", read_then_rename)
    sqlite_markets.requests.clear()

    with pytest.raises(AccountDeleteConflictError, match="changed while it was being deleted"):
        delete_account(sqlite_markets.context, uid=account)

    assert sqlite_markets.requests == ["read", f"transaction:{len(ACCOUNT_DELETE_TABLES)}", "read"]

    assert _account_rows(engine, account, "renamed")["accounts"] == 1
    assert _count(engine, "ms_markets__ordersts") == 1  # the history under the old identifier


def test_the_deleted_accounts_orders_trades_and_events_leave_the_stored_statistics(sqlite_markets) -> None:
    """MetaTables rebuilds the statistics of each time-index table a statement list
    changes (MetaTables#117), so an account re-created under the same identifier, whose
    connector publishes its orders again, does not resume from the deleted ones."""

    engine = sqlite_markets.engine
    account, other = _account(engine), _account(engine)
    history = _history(sqlite_markets, account)
    other_history = _history(sqlite_markets, other)
    sqlite_markets.keep_statistics(OrdersStorage, TradesStorage, OrderEventsStorage)
    for model in (OrdersStorage, OrderEventsStorage):
        assert {history["order"], other_history["order"]} <= set(_progress(sqlite_markets, model))
    trades_before = set(_progress(sqlite_markets, TradesStorage))

    delete_account(sqlite_markets.context, uid=account)

    for model in (OrdersStorage, OrderEventsStorage):
        progress = _progress(sqlite_markets, model)
        assert history["order"] not in progress and other_history["order"] in progress
    remaining = {row["trade_identifier"] for row in _rows(engine, "SELECT trade_identifier FROM ms_markets__tradests")}
    assert set(_progress(sqlite_markets, TradesStorage)) == remaining < trades_before


# Other accounts' Markets rows ------------------------------------------------------------


def test_another_accounts_order_on_its_order_manager_blocks_the_delete(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account, other = _account(engine), _account(engine)
    history = _history(sqlite_markets, account)
    _order(engine, _identifier(engine, other), order_identifier="foreign", manager=history["manager"])
    sqlite_markets.requests.clear()

    preflight = preflight_account_delete(sqlite_markets.context, uid=account)
    assert preflight["blockers"] == [
        "1 orders of other accounts name its order managers (ON DELETE RESTRICT)."
    ]
    with pytest.raises(AccountDeleteConflictError, match="orders of other accounts"):
        delete_account(sqlite_markets.context, uid=account)
    assert _account_rows(engine, account, history["identifier"])["accounts"] == 1
    assert sqlite_markets.requests == ["read", "read"]


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
    # An uncatalogued instance of a portfolio's event ledger, which copies the contract's
    # RESTRICT key (`_copy_contract_table`).
    "CREATE TABLE provider_ns__portfolioeventledgerts__copy (time_index DATETIME NOT NULL, "
    "portfolio_identifier VARCHAR(255) NOT NULL REFERENCES ms_markets__portfolio "
    "(unique_identifier) ON DELETE RESTRICT)",
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


def test_other_namespace_tables_change_only_through_their_own_keys(sqlite_markets) -> None:
    markets = sqlite_markets
    engine = markets.engine
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


def test_a_restrict_key_in_another_namespace_refuses_the_whole_delete(sqlite_markets) -> None:
    markets = sqlite_markets
    engine = markets.engine
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


def test_keys_from_tables_outside_the_identity_do_not_stop_the_delete(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _history(sqlite_markets, account)
    _create_provider_tables(engine)

    assert delete_account(sqlite_markets.context, uid=account) is not None


# Bulk ------------------------------------------------------------------------------------


def test_bulk_delete_deletes_each_account_and_reports_the_rest(sqlite_markets, monkeypatch) -> None:
    impact_calls = _impact_unavailable(monkeypatch)
    engine = sqlite_markets.engine
    first, blocked, other = _account(engine), _account(engine), _account(engine)
    _history(sqlite_markets, first)
    blocked_history = _history(sqlite_markets, blocked)
    _order(engine, _identifier(engine, other), order_identifier="foreign", manager=blocked_history["manager"])
    missing = uuid.uuid4()

    preflight = preflight_bulk_delete_accounts(sqlite_markets.context, uids=[first, blocked, missing])
    assert preflight["allowed"] is False
    assert preflight["matched_count"] == 2
    assert [item["uid"] for item in preflight["accounts"]] == [str(first), str(blocked)]
    assert preflight["blockers"][1] == f"Account {missing} was not found."

    result = bulk_delete_accounts(sqlite_markets.context, uids=[first, blocked, missing, first])

    assert result["deleted_count"] == 1
    assert [item["uid"] for item in result["deleted"]] == [str(first)]
    assert [item["uid"] for item in result["failed"]] == [str(blocked), str(missing)]
    assert _count(engine, "ms_markets__account") == 2
    assert impact_calls == ["impact"]  # the preflight's; the bulk delete asks for none


def test_bulk_preflight_allows_a_clean_selection(sqlite_markets, monkeypatch) -> None:
    impact_calls = _impact_unavailable(monkeypatch)
    engine = sqlite_markets.engine
    first, second = _account(engine), _account(engine)
    _history(sqlite_markets, first)
    sqlite_markets.requests.clear()

    preflight = preflight_bulk_delete_accounts(sqlite_markets.context, uids=[first, second])

    assert preflight["allowed"] is True
    assert preflight["blockers"] == []
    assert preflight["detail"] == "2 accounts are ready for deletion with their history."
    counts = {item["uid"]: item["row_counts"] for item in preflight["accounts"]}
    assert counts[str(first)]["holdings"] >= 1
    assert set(counts[str(second)].values()) == {0}
    assert _count(engine, "ms_markets__account") == 2
    assert sqlite_markets.requests == ["read", "read"]  # one read per account
    assert impact_calls == ["impact"]


def test_the_preflight_counts_match_what_the_delete_removes(sqlite_markets) -> None:
    engine = sqlite_markets.engine
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


# MetaTables' impact ----------------------------------------------------------------------


def test_the_impact_is_asked_once_per_table_and_reused(sqlite_markets, monkeypatch) -> None:
    monkeypatch.setattr(deletion, "account_delete_impact", ACCOUNT_DELETE_IMPACT)
    calls: list[str] = []
    payload = {
        "root_uid": ACCOUNT_TABLE_UID,
        "action": "delete_rows",
        "allowed": True,
        "nodes": [
            {
                "id": ACCOUNT_TABLE_UID,
                "type": "meta_table",
                "uid": ACCOUNT_TABLE_UID,
                "identifier": "Account",
                "namespaces": ["mainsequence.markets"],
                "physical_schema": "main",
                "physical_table_name": "ms_markets__account",
                "effects": ["delete"],
            }
        ],
        "edges": [],
        "blockers": [],
    }

    class _Impact:
        def model_dump(self, mode="json"):
            return payload

    class _AccountMetaTable:
        uid = ACCOUNT_TABLE_UID

        def get_impact(self, *, action):
            calls.append(action)
            return _Impact()

    monkeypatch.setattr(AccountTable, "get_meta_table", classmethod(lambda cls: _AccountMetaTable()))
    engine = sqlite_markets.engine
    first, second = _account(engine), _account(engine)

    for _ in range(3):
        preflight = preflight_bulk_delete_accounts(sqlite_markets.context, uids=[first, second])
        assert preflight["impact"].root_uid == ACCOUNT_TABLE_UID
    bulk_delete_accounts(sqlite_markets.context, uids=[first, second])

    assert calls == ["delete_rows"]
    assert _count(engine, "ms_markets__account") == 0
