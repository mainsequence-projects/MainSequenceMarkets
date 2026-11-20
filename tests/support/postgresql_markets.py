"""Markets on a disposable PostgreSQL database, the hosted dialect, and its row helpers.

The `postgresql_markets` fixture (`tests/conftest.py`) needs
``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL``, an empty, disposable ``markets_*``
database on localhost; tests that use it are skipped otherwise. For each test it migrates
the database to head and sends every compiled statement the way MetaTables' PostgreSQL
backend does: values bound by its ``parameters_for``, each statement executed with
``prepare=True``, a statement list in one transaction with its row guards, and the rows
answered in their wire form.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import make_url

import metatables.runtime_context
from metatables import (
    MetaTable,
    MetaTableCompiledSQLOperation,
    MetaTableCompiledSQLTransaction,
    MetaTableTransactionGuardError,
)
from metatables.runtime_contract import RuntimeContext
from msm.repositories.base import MarketsRepositoryContext
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.support.migrations import _config

URL_VARIABLE = "MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL"


def postgresql_markets(monkeypatch):
    """Yield the engine, a repository context and the list of MetaTables requests.

    The `postgresql_markets` fixture in `tests/conftest.py` runs this.
    """

    url = os.environ.get(URL_VARIABLE)
    if not url:
        pytest.skip(f"Set {URL_VARIABLE} to a disposable PostgreSQL database")
    parsed = make_url(url)
    if parsed.host not in {"localhost", "127.0.0.1"} or not (parsed.database or "").startswith("markets_"):
        pytest.fail("These tests accept only a disposable markets_* database on localhost")

    import psycopg
    from metatables.api.backend.backends.restricted_sql import json_value, parameters_for

    engine = sa.create_engine(parsed.set(drivername="postgresql+psycopg"))
    with engine.connect() as connection:
        connection.exec_driver_sql("DROP SCHEMA public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
        connection.commit()
        command.upgrade(_config(connection), "head")
        connection.commit()

    runtime = RuntimeContext(
        git_source=None,
        dialect="postgresql",
        paramstyle="pyformat",
        data_source={"uid": "00000000-0000-0000-0000-000000000063"},
        default_schema="public",
    )
    monkeypatch.setattr(metatables.runtime_context, "get_runtime_context", lambda: runtime)
    dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    operations: list[str] = []

    def run(statements, *, guarded):
        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            rows, names = [], []
            for index, statement in enumerate(statements):
                values = parameters_for(statement.parameters, statement.parameter_types, "postgresql")
                cursor.execute(statement.sql, values or None, prepare=True)
                rows = cursor.fetchall() if cursor.description else []
                names = [column.name for column in cursor.description or ()]
                expected = getattr(statement, "expect_rows", None) if guarded else None
                count = len(rows) if cursor.description else max(cursor.rowcount, 0)
                if expected is not None and count != expected:
                    connection.rollback()
                    raise MetaTableTransactionGuardError(
                        "guard", statement_index=index, label=statement.label,
                        expect_rows=expected, row_count=count,
                    )
            return {"ok": True, "rows": [json_value(dict(zip(names, row))) for row in rows]}

    def execute_operation(cls, operation, *, timeout=None):
        operations.append("read" if operation.operation == "select" else operation.operation)
        wire = MetaTableCompiledSQLOperation.model_validate_json(operation.model_dump_json())
        return run([wire.statement], guarded=False)

    def execute_transaction(cls, transaction, *, timeout=None):
        operations.append("transaction")
        wire = MetaTableCompiledSQLTransaction.model_validate_json(transaction.model_dump_json())
        return run(wire.statements, guarded=True)

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(execute_operation))
    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(execute_transaction))
    yield engine, MarketsRepositoryContext(), operations
    engine.dispose()


def _scalar_rows(engine, sql):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.exec_driver_sql(sql)]


WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)
DATASETS = {table.key: table.table_name for table in PORTFOLIO_DATASET_TABLES}


def _insert(engine, table_name: str, **values) -> dict:
    """Insert one row, filling required columns the test does not care about."""

    table = sa.Table(table_name, sa.MetaData(), autoload_with=engine)
    row = dict(values)
    for column in table.columns:
        if column.name in row or column.nullable or column.server_default is not None:
            continue
        kind = column.type
        if isinstance(kind, sa.Uuid):
            row[column.name] = uuid.uuid4()
        elif isinstance(kind, sa.Boolean):
            row[column.name] = True
        elif isinstance(kind, sa.DateTime):
            row[column.name] = WHEN
        elif isinstance(kind, sa.Date):
            row[column.name] = WHEN.date()
        elif isinstance(kind, sa.Integer):
            row[column.name] = 1
        elif isinstance(kind, (sa.Float, sa.Numeric)):
            row[column.name] = 1.0
        elif isinstance(kind, sa.JSON):
            row[column.name] = {}
        else:
            length = getattr(kind, "length", None) or 255
            row[column.name] = f"{uuid.uuid4().hex[:8]}-{column.name}"[:length]
    with engine.begin() as connection:
        connection.execute(table.insert(), row)
    return row


def _portfolio(engine) -> tuple[uuid.UUID, str]:
    calendar = _insert(engine, "ms_markets__calendar")
    portfolio = uuid.uuid4()
    identifier = f"portfolio-{portfolio.hex[:8]}"
    _insert(
        engine,
        "ms_markets__portfolio",
        uid=portfolio,
        unique_identifier=identifier,
        calendar_uid=calendar["uid"],
        retired_at=None,
    )
    return portfolio, identifier


def _datasets(engine, identifier: str) -> None:
    for table_name in DATASETS.values():
        assets = {
            foreign_key["constrained_columns"][0]: "AAA"
            for foreign_key in sa.inspect(engine).get_foreign_keys(table_name)
            if foreign_key["referred_table"] == "ms_markets__asset"
        }
        _insert(engine, table_name, time_index=WHEN, portfolio_identifier=identifier, **assets)


def _rows_in(engine, identifier: str, **rows: int) -> None:
    """``rows[key]`` rows of the portfolio in dataset ``key``, one a day."""

    for key, count in rows.items():
        assets = {
            foreign_key["constrained_columns"][0]: "AAA"
            for foreign_key in sa.inspect(engine).get_foreign_keys(DATASETS[key])
            if foreign_key["referred_table"] == "ms_markets__asset"
        }
        for day in range(count):
            _insert(
                engine,
                DATASETS[key],
                time_index=WHEN + dt.timedelta(days=day),
                portfolio_identifier=identifier,
                **assets,
            )


def explain(engine, operation) -> list:
    """PostgreSQL's plan for a compiled read with sequential scans priced out (``FORMAT JSON``).

    The read is bound as MetaTables binds it. With ``enable_seqscan`` off the planner
    takes any usable index even on the tests' few rows, so the plan shows whether one
    exists for the read's conditions.
    """

    from metatables.api.backend.backends.restricted_sql import parameters_for

    statement = operation.statement
    values = parameters_for(statement.parameters, statement.parameter_types, "postgresql")
    with engine.connect() as connection:
        connection.exec_driver_sql("SET enable_seqscan = off")
        return connection.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {statement.sql}", values).scalar_one()


def dataset_reads(plan: list) -> dict[str, list[str]]:
    """How the plan reads each dataset table: per plan node that reads it, the index it uses.

    ``None`` stands for a node that reads the table without an index.
    """

    reads: dict[str, list[str]] = {table_name: [] for table_name in DATASETS.values()}

    def visit(node: dict) -> None:
        if node.get("Relation Name") in reads:
            index = node.get("Index Name") or next(
                (
                    child.get("Index Name")
                    for child in node.get("Plans", ())
                    if child.get("Node Type") == "Bitmap Index Scan"
                ),
                None,
            )
            reads[node["Relation Name"]].append(index)
        for child in node.get("Plans", ()):
            visit(child)

    visit(plan[0]["Plan"])
    return reads


def series_indexes() -> dict[str, list[str]]:
    """Per dataset table, its index that leads with ``portfolio_identifier``, once."""

    return {
        table.table_name: [index.name for index in table.model.__table__.indexes if not index.unique]
        for table in PORTFOLIO_DATASET_TABLES
    }


def _dataset_rows(engine, identifier: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            key: connection.execute(
                sa.text(f"SELECT count(*) FROM {table_name} WHERE portfolio_identifier = :identifier"),
                {"identifier": identifier},
            ).scalar_one()
            for key, table_name in DATASETS.items()
        }


def _count(engine, sql: str, **parameters) -> int:
    with engine.connect() as connection:
        return connection.execute(sa.text(sql), parameters).scalar_one()


def _exists(engine, portfolio: uuid.UUID) -> bool:
    return bool(_count(engine, "SELECT count(*) FROM ms_markets__portfolio WHERE uid = :uid", uid=portfolio))
