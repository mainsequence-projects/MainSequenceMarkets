"""Markets on a disposable PostgreSQL database, the hosted dialect.

The `postgresql_markets` fixture (`tests/conftest.py`) needs
``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL``, an empty, disposable ``markets_*``
database on localhost; tests that use it are skipped otherwise. For each test it migrates
the database to head and sends every compiled statement the way MetaTables' PostgreSQL
backend does: values bound by its ``parameters_for``, each statement executed with
``prepare=True``, a statement list in one transaction with its row guards, and the rows
answered in their wire form. Portfolio dataset rows and plans are in
`tests/support/postgresql_portfolios.py`.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import make_url

from metatables import (
    MetaTable,
    MetaTableCompiledSQLOperation,
    MetaTableCompiledSQLTransaction,
    MetaTableTransactionGuardError,
    RuntimeContext,
)
from msm.repositories.base import MarketsRepositoryContext
from tests.support.markets_runtime import use_runtime_context
from tests.support.migrations import _config
from tests.support.postgresql_databases import worker_database

URL_VARIABLE = "MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL"
WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)
"""The time `_insert` gives a required time column the test leaves out."""


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
    parsed = worker_database(parsed)

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
    use_runtime_context(runtime)
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
                if expected is not None and (
                    count < 1 if expected == "at_least_one" else count != expected
                ):
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
