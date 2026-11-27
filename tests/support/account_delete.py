"""The account delete's harness and data on SQLite (ADR 0050, issue 91).

`tests/msm/repositories/test_sqlite_account_delete.py` and
`tests/msm_portfolios/services/test_sqlite_account_portfolio_delete.py` share them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import sqlalchemy as sa

from msm.repositories.account_deletion import ACCOUNT_DELETE_TABLES, ACCOUNT_HISTORY_KEYS
from msm.services.accounts import deletion
from tests.support.sqlite_markets import (
    WHEN,
    _asset,
    _insert,
    _portfolio,
    _portfolio_position,
    _rows,
    _write_holdings,
    _write_target,
)

MARKETS_TABLES = {table.model.__table__.name for table in ACCOUNT_DELETE_TABLES}
EVERY_TABLE_COUNTS = {key: 1 for key in ACCOUNT_HISTORY_KEYS}
"""The delete read's counts for an account with rows in every table."""


def account_markets(markets, monkeypatch) -> SimpleNamespace:
    """``markets``, the `sqlite_markets` harness, recording each MetaTables request and
    refusing the impact."""

    from metatables import MetaTable

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


def _identifier(engine, account: uuid.UUID) -> str:
    (row,) = _rows(engine, "SELECT unique_identifier FROM ms_markets__account WHERE uid = :uid", uid=account.hex)
    return row["unique_identifier"]


def _order_manager(engine, account: uuid.UUID) -> str:
    identifier = f"manager-{uuid.uuid4().hex[:8]}"
    _insert(engine, "ms_markets__ordermanager", unique_identifier=identifier, target_account_uid=account.hex)
    return identifier


def _order(engine, account_identifier: str, *, manager: str | None = None) -> uuid.UUID:
    """One order of the account, with one state row; answers its uid (ADR 0064)."""

    order = uuid.uuid4()
    _insert(
        engine,
        "ms_markets__order",
        uid=order.hex,
        account_identifier=account_identifier,
        order_manager_identifier=manager,
        asset_identifier="AAA",
    )
    _insert(engine, "ms_markets__ordersts", order_time=WHEN, order_uid=order.hex)
    return order


def _trade(engine, account_identifier: str, *, order: uuid.UUID) -> None:
    _insert(
        engine,
        "ms_markets__tradests",
        trade_time=WHEN,
        trade_identifier=f"trade-{uuid.uuid4().hex[:8]}",
        account_identifier=account_identifier,
        order_uid=order.hex,
        asset_identifier="AAA",
        commission_asset_identifier=None,
        settlement_asset_identifier=None,
    )


def _order_event(engine, order: uuid.UUID, *, event_time: dt.datetime = WHEN) -> None:
    _insert(engine, "ms_markets__ordereventsts", event_time=event_time, order_uid=order.hex)


def _virtual_fund(engine, account, source, portfolio, unique_identifier: str) -> None:
    """One virtual fund allocated from ``source``: its row, its holdings set and one holding."""

    fund = uuid.uuid4()
    holdings_set = uuid.uuid4()
    (allocation,) = _rows(
        engine,
        "SELECT uid FROM ms_markets__accounttargetallocation WHERE account_uid = :account",
        account=account.hex,
    )
    _insert(
        engine,
        "ms_markets__virtualfund",
        uid=fund.hex,
        unique_identifier=unique_identifier,
        account_uid=account.hex,
        account_target_allocation_uid=allocation["uid"],
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
    order = _order(engine, identifier, manager=manager)
    _trade(engine, identifier, order=order)
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
            "SELECT count(*) FROM ms_markets__order WHERE account_identifier = :identifier",
            {"identifier": identifier},
        ),
        "order_states": (
            "SELECT count(*) FROM ms_markets__ordersts WHERE order_uid IN "
            "(SELECT uid FROM ms_markets__order WHERE account_identifier = :identifier)",
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


def _exists(engine, portfolio: uuid.UUID) -> bool:
    return bool(_rows(engine, "SELECT uid FROM ms_markets__portfolio WHERE uid = :uid", uid=portfolio.hex))


PROVIDER_TABLES = (
    # A sidecar on the account with cascade delete (ADR 0047's worked example).
    "CREATE TABLE provider_ns__account_sidecar (account_uid CHAR(32) PRIMARY KEY "
    "REFERENCES ms_markets__account (uid) ON DELETE CASCADE, credentials TEXT)",
    # A storage instance of the holdings rows, which copies the core CASCADE key.
    "CREATE TABLE provider_ns__accountholdingsts__copy (holdings_set_uid CHAR(32) NOT NULL "
    "REFERENCES ms_markets__accountholdingsset (uid) ON DELETE CASCADE, quantity FLOAT)",
    # A storage instance of the order states, which copies the core RESTRICT key into the
    # order (ADR 0064).
    "CREATE TABLE provider_ns__ordersts__copy (order_time DATETIME NOT NULL, "
    "order_uid CHAR(32) NOT NULL REFERENCES ms_markets__order (uid) ON DELETE RESTRICT)",
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
