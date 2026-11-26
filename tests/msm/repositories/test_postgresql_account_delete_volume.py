"""How long one account delete takes on PostgreSQL with months of history in the tables.

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost to run this test; it is skipped otherwise, so it never runs in CI.
Run it with ``-s`` to see the measurement:

    uv run --frozen --all-extras pytest -s tests/msm/repositories/test_postgresql_account_delete_volume.py

The database holds `ACCOUNTS` accounts. Each has `HOLDINGS_SETS` holdings sets of
`POSITIONS` positions (one set per sync, five minutes apart), its last `ALLOCATED_SETS`
sets allocated to two virtual funds (fund holdings and allocation lines), `TARGET_SETS`
target snapshots, and `ORDERS` orders, each with a trade and three events.

The test runs `msm.services.delete_account` for one account as the Markets API does: one
read, then one transaction. The MetaTables requests run as MetaTables' PostgreSQL backend
runs them (values bound by its ``parameters_for``, a statement list in one transaction
with its row guards), and after the transaction commits, MetaTables' own statistics
rebuild runs for each time-index table the transaction locked for writing, as the
MetaTables API does after a compiled write (MetaTables#117). It prints the time of the
read, of each statement, of the transaction and of each rebuild.

The read and the transaction, which ms-markets sends, must take less than
`BUDGET_SECONDS`. The rebuilds are printed, not bounded: each reads its whole table, all
accounts included, and that is MetaTables' to change. Before revision 0034 the
holdings-set statement alone took about 53 s here: each deleted set had its foreign keys
checked by reading the whole referencing tables.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Mapping

import psycopg
import psycopg2
import pytest
import sqlalchemy as sa
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from metatables import (
    MetaTable,
    MetaTableCompiledSQLOperation,
    MetaTableCompiledSQLTransaction,
    MetaTableTransactionGuardError,
)
from metatables.api.backend.backends.adapters.postgresql_time_index_stats import (
    rebuild_index_statistics,
)
from metatables.api.backend.backends.restricted_sql import json_value, parameters_for
from msm.models import AccountTable
from msm.services import delete_account
from msm.services.accounts import deletion
from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
from msm.time_index.accounts.virtual_funds.storage import (
    AccountAllocationLinesStorage,
    VirtualFundHoldingsStorage,
)
from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage

ACCOUNTS = 10
HOLDINGS_SETS = 1_000
POSITIONS = 20
ALLOCATED_SETS = 100
FUND_POSITIONS = 10
TARGET_SETS = 100
ORDERS = 1_000
BUDGET_SECONDS = 10.0

TIME_INDEX_TABLES = {
    model.__table__.name: (model.__time_index_name__, tuple(model.__index_names__[1:]))
    for model in (
        AccountHoldingsStorage,
        AccountAllocationLinesStorage,
        VirtualFundHoldingsStorage,
        TargetPositionsStorage,
        OrdersStorage,
        TradesStorage,
        OrderEventsStorage,
    )
}
# The relations a transaction locked for writing: what MetaTables takes as written.
WRITTEN_RELATIONS = (
    "SELECT c.relname FROM pg_catalog.pg_locks AS l "
    "JOIN pg_catalog.pg_class AS c ON c.oid = l.relation "
    "WHERE l.pid = pg_catalog.pg_backend_pid() AND l.mode = 'RowExclusiveLock'"
)

SEED = [
    "INSERT INTO ms_markets__asset (uid, unique_identifier) "
    "SELECT gen_random_uuid(), 'ASSET-' || g FROM generate_series(1, :positions) AS g",
    "INSERT INTO ms_markets__calendar (uid, unique_identifier, display_name, calendar_type, timezone) "
    "VALUES (gen_random_uuid(), 'volume-calendar', 'Volume calendar', 'exchange', 'UTC')",
    "INSERT INTO ms_markets__portfolio (uid, unique_identifier, calendar_uid, backtest_table_price_column_name) "
    "SELECT gen_random_uuid(), 'volume-portfolio-' || g, c.uid, 'close' "
    "FROM ms_markets__calendar AS c, generate_series(1, 2) AS g",
    "INSERT INTO ms_markets__accountallocationmodel (uid, allocation_model_name) "
    "VALUES (gen_random_uuid(), 'volume-model')",
    "INSERT INTO ms_markets__account (uid, unique_identifier, account_name, is_paper, account_is_active) "
    "SELECT gen_random_uuid(), 'volume-account-' || a, 'Volume account ' || a, true, true "
    "FROM generate_series(1, :accounts) AS a",
    # One holdings set per sync, five minutes apart.
    "INSERT INTO ms_markets__accountholdingsset (uid, account_uid, time_index) "
    "SELECT gen_random_uuid(), a.uid, timestamptz '2026-10-01' + s * interval '5 minutes' "
    "FROM ms_markets__account AS a, generate_series(1, :holdings_sets) AS s",
    "INSERT INTO ms_markets__accountholdingsts "
    "(time_index, account_uid, asset_identifier, holdings_set_uid, direction, quantity) "
    "SELECT h.time_index, h.account_uid, 'ASSET-' || g, h.uid, 1, 100 "
    "FROM ms_markets__accountholdingsset AS h, generate_series(1, :positions) AS g",
    "INSERT INTO ms_markets__accounttargetallocation "
    "(uid, unique_identifier, account_uid, account_allocation_model_uid, is_active) "
    "SELECT gen_random_uuid(), a.uid::text, a.uid, m.uid, true "
    "FROM ms_markets__account AS a, ms_markets__accountallocationmodel AS m",
    # Each account's funds belong to its target allocation.
    "INSERT INTO ms_markets__virtualfund "
    "(uid, unique_identifier, account_uid, account_target_allocation_uid, target_portfolio_uid) "
    "SELECT gen_random_uuid(), a.unique_identifier || '-' || p.unique_identifier, a.uid, t.uid, p.uid "
    "FROM ms_markets__account AS a "
    "JOIN ms_markets__accounttargetallocation AS t ON t.account_uid = a.uid, ms_markets__portfolio AS p",
    "CREATE TEMPORARY TABLE allocated_set ON COMMIT DROP AS "
    "SELECT uid, account_uid, time_index FROM ("
    "  SELECT h.*, row_number() OVER (PARTITION BY account_uid ORDER BY time_index DESC) AS n "
    "  FROM ms_markets__accountholdingsset AS h"
    ") AS ranked WHERE n <= :allocated_sets",
    "INSERT INTO ms_markets__virtualfundholdingsset "
    "(uid, virtual_fund_uid, source_account_holdings_set_uid, time_index) "
    "SELECT gen_random_uuid(), f.uid, s.uid, s.time_index "
    "FROM allocated_set AS s JOIN ms_markets__virtualfund AS f ON f.account_uid = s.account_uid",
    "INSERT INTO ms_markets__virtualfundholdingsts (time_index, virtual_fund_uid, asset_identifier, "
    "virtual_fund_holdings_set_uid, source_account_holdings_set_uid, allocated_quantity, "
    "allocation_strategy, direction) "
    "SELECT s.time_index, s.virtual_fund_uid, 'ASSET-' || g, s.uid, s.source_account_holdings_set_uid, "
    "10, 'proportional_attribution', 1 "
    "FROM ms_markets__virtualfundholdingsset AS s, generate_series(1, :fund_positions) AS g",
    "INSERT INTO ms_markets__accountallocationlinests (time_index, holdings_set_uid, owner_type, "
    "owner_uid, asset_identifier, account_uid, virtual_fund_uid, target_quantity, target_direction, "
    "assigned_quantity, assigned_direction, allocation_strategy) "
    "SELECT s.time_index, s.uid, 'fund', f.uid, 'ASSET-' || g, s.account_uid, f.uid, 10, 1, 10, 1, "
    "'proportional_attribution' "
    "FROM allocated_set AS s JOIN ms_markets__virtualfund AS f ON f.account_uid = s.account_uid, "
    "generate_series(1, :positions) AS g "
    "UNION ALL "
    "SELECT s.time_index, s.uid, 'direct', s.account_uid, 'ASSET-' || g, s.account_uid, NULL, 80, 1, "
    "80, 1, 'proportional_attribution' "
    "FROM allocated_set AS s, generate_series(1, :positions) AS g",
    "INSERT INTO ms_markets__positionset (uid, account_target_allocation_uid, position_set_time) "
    "SELECT gen_random_uuid(), t.uid, timestamptz '2026-10-01' + s * interval '1 hour' "
    "FROM ms_markets__accounttargetallocation AS t, generate_series(1, :target_sets) AS s",
    "INSERT INTO ms_markets__targetpositionsts "
    "(time_index, position_set_uid, target_type, target_uid, portfolio_uid, weight_notional_exposure) "
    "SELECT s.position_set_time, s.uid, 'portfolio', p.uid, p.uid, 0.5 "
    "FROM ms_markets__positionset AS s, ms_markets__portfolio AS p",
    "INSERT INTO ms_markets__ordermanager (uid, unique_identifier, target_account_uid, target_time) "
    "SELECT gen_random_uuid(), 'manager-' || a.unique_identifier, a.uid, timestamptz '2026-10-01' "
    "FROM ms_markets__account AS a",
    "INSERT INTO ms_markets__order (uid, account_identifier, asset_identifier, order_manager_identifier) "
    "SELECT gen_random_uuid(), a.unique_identifier, 'ASSET-' || (1 + o % :positions), "
    "'manager-' || a.unique_identifier "
    "FROM ms_markets__account AS a, generate_series(1, :orders) AS o",
    "INSERT INTO ms_markets__ordersts (order_time, order_uid) "
    "SELECT timestamptz '2026-10-01' + row_number() OVER (PARTITION BY account_identifier "
    "ORDER BY uid) * interval '1 minute', uid FROM ms_markets__order",
    "INSERT INTO ms_markets__tradests "
    "(trade_time, trade_identifier, account_identifier, asset_identifier, order_uid) "
    "SELECT s.order_time + interval '1 second', o.uid::text || '-trade', o.account_identifier, "
    "o.asset_identifier, o.uid "
    "FROM ms_markets__ordersts AS s JOIN ms_markets__order AS o ON o.uid = s.order_uid",
    "INSERT INTO ms_markets__ordereventsts (event_time, order_uid) "
    "SELECT s.order_time + e * interval '1 second', s.order_uid "
    "FROM ms_markets__ordersts AS s, generate_series(1, 3) AS e",
]


class _RebuildRefused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@pytest.fixture
def history(postgresql_markets, monkeypatch):
    """The seeded database and a log of each MetaTables request's time."""

    engine, context, _operations = postgresql_markets
    monkeypatch.setattr(AccountTable, "get_meta_table", classmethod(lambda cls: None))

    def no_impact():
        raise AssertionError("The account delete must not ask MetaTables for its impact.")

    monkeypatch.setattr(deletion, "account_delete_impact", no_impact)
    parameters = {
        "accounts": ACCOUNTS,
        "holdings_sets": HOLDINGS_SETS,
        "positions": POSITIONS,
        "allocated_sets": ALLOCATED_SETS,
        "fund_positions": FUND_POSITIONS,
        "target_sets": TARGET_SETS,
        "orders": ORDERS,
    }
    started = time.perf_counter()
    with engine.begin() as connection:
        for statement in SEED:
            connection.execute(sa.text(statement), parameters)
    with engine.connect() as connection:
        # Settle the seed: statistics and visibility for the planner, and no autovacuum or
        # checkpoint of the seed's writes inside the measurement.
        autocommit = connection.execution_options(isolation_level="AUTOCOMMIT")
        autocommit.exec_driver_sql("VACUUM (ANALYZE)")
        autocommit.exec_driver_sql("CHECKPOINT")
    seeded = time.perf_counter() - started

    dsn = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    log: list[dict] = []

    def execute_operation(cls, operation, *, timeout=None):
        wire = MetaTableCompiledSQLOperation.model_validate_json(operation.model_dump_json())
        return _run(dsn, [wire.statement], guarded=False, log=log, request="read")

    def execute_transaction(cls, transaction, *, timeout=None):
        wire = MetaTableCompiledSQLTransaction.model_validate_json(transaction.model_dump_json())
        request = f"transaction of {len(wire.statements)} statements"
        return _run(dsn, wire.statements, guarded=True, log=log, request=request)

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(execute_operation))
    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(execute_transaction))
    return engine, context, log, seeded


def _run(dsn: str, statements, *, guarded: bool, log: list[dict], request: str) -> dict:
    """Run ``statements`` in one transaction as MetaTables does; after a write commits,
    rebuild the statistics of each time-index table it locked, as the MetaTables API does."""

    with psycopg.connect(dsn) as connection:
        started = time.perf_counter()
        with connection.cursor() as cursor:
            rows, names = [], []
            for index, statement in enumerate(statements):
                values = parameters_for(
                    statement.parameters, statement.parameter_types, "postgresql"
                )
                began = time.perf_counter()
                cursor.execute(statement.sql, values or None, prepare=True)
                if guarded:
                    log.append(
                        {
                            "request": f"  {_target(statement.sql)}",
                            "seconds": time.perf_counter() - began,
                        }
                    )
                rows = cursor.fetchall() if cursor.description else []
                names = [column.name for column in cursor.description or ()]
                expected = getattr(statement, "expect_rows", None) if guarded else None
                count = len(rows) if cursor.description else max(cursor.rowcount, 0)
                if expected is not None and count != expected:
                    connection.rollback()
                    raise MetaTableTransactionGuardError(
                        "guard",
                        statement_index=index,
                        label=statement.label,
                        expect_rows=expected,
                        row_count=count,
                    )
            written = sorted(
                name
                for (name,) in cursor.execute(WRITTEN_RELATIONS).fetchall()
                if name in TIME_INDEX_TABLES
            )
        connection.commit()
        log.append(
            {"request": request, "seconds": time.perf_counter() - started, "kind": "request"}
        )
    if written:
        # MetaTables' rebuild reads through psycopg2, with rows as mappings.
        rebuild = psycopg2.connect(dsn)
        try:
            with rebuild.cursor(cursor_factory=RealDictCursor) as cursor:
                for table in written:
                    time_name, dimensions = TIME_INDEX_TABLES[table]
                    started = time.perf_counter()
                    try:
                        rebuild_index_statistics(
                            cursor,
                            sql.Identifier(table),
                            time_name,
                            dimensions,
                            error=_RebuildRefused,
                        )
                        outcome = "rebuilt"
                    except _RebuildRefused as refused:
                        outcome = refused.code
                    log.append(
                        {
                            "request": f"statistics of {table}",
                            "seconds": time.perf_counter() - started,
                            "outcome": outcome,
                            "kind": "statistics",
                        }
                    )
            rebuild.commit()
        finally:
            rebuild.close()
    return {"ok": True, "rows": [json_value(dict(zip(names, row))) for row in rows]}


def _target(statement_sql: str) -> str:
    match = re.match(r"\s*(DELETE FROM|INSERT INTO|UPDATE)\s+([\w.\"]+)", statement_sql)
    return f"{match.group(1).split()[0]} {match.group(2)}" if match else statement_sql.split()[0]


def _counts(engine, account_uid) -> Mapping[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.execute(
                sa.text(f"SELECT count(*) FROM {table} WHERE account_uid = :uid"),
                {"uid": account_uid},
            ).scalar_one()
            for table in ("ms_markets__accountholdingsts", "ms_markets__accountallocationlinests")
        }


def test_one_account_delete_with_months_of_history(history) -> None:
    engine, context, log, seeded = history
    with engine.connect() as connection:
        deleted, kept = (
            row.uid
            for row in connection.execute(
                sa.text(
                    "SELECT uid FROM ms_markets__account WHERE unique_identifier IN "
                    "('volume-account-1', 'volume-account-2') ORDER BY unique_identifier"
                )
            )
        )
        sizes = {
            table: connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in TIME_INDEX_TABLES
        }
    kept_before = _counts(engine, kept)

    started = time.perf_counter()
    answer = delete_account(context, uid=uuid.UUID(str(deleted)))
    seconds = time.perf_counter() - started

    print(f"\nSeeded in {seeded:.1f} s:")
    for table, size in sizes.items():
        print(f"  {table:40s} {size:>9,} rows")
    print("Delete of one account:")
    for entry in log:
        outcome = f"  ({entry['outcome']})" if entry.get("outcome", "rebuilt") != "rebuilt" else ""
        print(f"  {entry['request']:56s} {entry['seconds']:8.3f} s{outcome}")
    requests = sum(entry["seconds"] for entry in log if entry.get("kind") == "request")
    rebuilds = sum(entry["seconds"] for entry in log if entry.get("kind") == "statistics")
    print(f"  {'the read and the transaction':56s} {requests:8.3f} s")
    print(f"  {'MetaTables statistics rebuilds':56s} {rebuilds:8.3f} s")
    print(f"  {'total, as the caller waits':56s} {seconds:8.3f} s")

    assert answer is not None
    assert answer["deleted_rows"]["holdings"] == HOLDINGS_SETS * POSITIONS
    assert answer["deleted_rows"]["orders"] == ORDERS
    assert _counts(engine, deleted) == {
        "ms_markets__accountholdingsts": 0,
        "ms_markets__accountallocationlinests": 0,
    }
    assert _counts(engine, kept) == kept_before
    assert requests < BUDGET_SECONDS
