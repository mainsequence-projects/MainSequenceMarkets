"""Account registration on PostgreSQL, the hosted dialect (ADR 0051, #63).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost to run these tests; they are skipped otherwise. Each test migrates
the database to head, runs ``msm.services.register_account`` and sends every compiled
statement the way MetaTables' PostgreSQL backend does: values bound by its
``parameters_for``, each statement executed with ``prepare=True``, a statement list in one
transaction with its row guards, and the rows answered in their wire form.
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
from msm.services import AccountHoldingsSnapshotExistsError, get_or_create_currency_asset, register_account
from tests.msm.maintenance.test_legacy_schema_migration import _config

URL_VARIABLE = "MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL"
DAY_1 = dt.datetime(2026, 11, 10, 21, 0, tzinfo=dt.UTC)
DAY_2 = dt.datetime(2026, 11, 11, 21, 0, tzinfo=dt.UTC)


@pytest.fixture
def postgresql_markets(monkeypatch):
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


def _request(*, holdings_date=DAY_1, positions=None, overwrite=False, account_name="Venue account"):
    return {
        "account": {"unique_identifier": "venue::account-1", "account_name": account_name},
        "assets": [
            {
                "unique_identifier": "venue::AAPL",
                "asset_type": {"asset_type": "venue_equity"},
                "snapshot": {"name": "Apple Inc.", "ticker": "AAPL"},
            }
        ],
        "cash_currency": "USD",
        "holdings_date": holdings_date.isoformat(),
        "overwrite": overwrite,
        "positions": positions
        or [
            {"asset_identifier": "venue::AAPL", "quantity": "3", "extra_details": {"lot": 1, "src": "x"}},
            {"asset_identifier": "USD", "quantity": "100", "direction": -1},
        ],
    }


def _scalar_rows(engine, sql):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.exec_driver_sql(sql)]


def test_registration_runs_on_postgresql_and_repeats_idempotently(postgresql_markets) -> None:
    engine, context, operations = postgresql_markets

    first = register_account(context, _request())

    assert operations == ["read", "read", "transaction"]
    assert first.response["written"]["assets"] == {"created": 2, "changed": 0}
    assert first.response["written"]["asset_types"] == {"created": 2, "changed": 0}
    assert first.response["written"]["holdings"] == {"created": 2, "changed": 0}
    assert _scalar_rows(
        engine,
        "SELECT asset_identifier, quantity, direction, extra_details, time_index = target_trade_time "
        "FROM ms_markets__accountholdingsts ORDER BY asset_identifier",
    ) == [("USD", 100.0, -1, {}, True), ("venue::AAPL", 3.0, 1, {"lot": 1, "src": "x"}, True)]
    assert _scalar_rows(
        engine, "SELECT asset_identifier, name, ticker, exchange_code FROM ms_markets__assetsnapshotsts"
    ) == [("venue::AAPL", "Apple Inc.", "AAPL", "")]

    operations.clear()
    repeat = register_account(context, _request())
    assert operations == ["read", "read"]
    assert repeat.response["holdings_set_uid"] == first.response["holdings_set_uid"]

    operations.clear()
    sync = register_account(
        context,
        _request(holdings_date=DAY_2, positions=[{"asset_identifier": "venue::AAPL", "quantity": "4"}]),
    )
    assert operations == ["read", "read", "transaction"]
    assert sync.response["written"]["holdings_sets"] == {"created": 1, "changed": 0}
    assert sync.response["written"]["assets"] == {"created": 0, "changed": 0}

    with pytest.raises(AccountHoldingsSnapshotExistsError):
        register_account(context, _request(account_name="Renamed", positions=[{"asset_identifier": "USD", "quantity": "1"}]))
    assert _scalar_rows(engine, "SELECT account_name FROM ms_markets__account") == [("Venue account",)]

    replaced = register_account(
        context,
        _request(account_name="Renamed", overwrite=True, positions=[{"asset_identifier": "USD", "quantity": "1"}]),
    )
    assert replaced.response["written"]["holdings_sets"] == {"created": 0, "changed": 1}
    assert replaced.response["written"]["accounts"] == {"created": 0, "changed": 1}
    assert _scalar_rows(
        engine,
        "SELECT h.asset_identifier, h.quantity FROM ms_markets__accountholdingsts h "
        "JOIN ms_markets__accountholdingsset s ON s.uid = h.holdings_set_uid "
        f"WHERE s.uid = '{first.response['holdings_set_uid']}'",
    ) == [("USD", 1.0)]


def test_currency_get_or_create_runs_on_postgresql(postgresql_markets) -> None:
    engine, context, operations = postgresql_markets

    created = get_or_create_currency_asset(context, code="EUR")
    again = get_or_create_currency_asset(context, code="EUR")

    assert operations == ["transaction", "transaction"]
    assert uuid.UUID(str(created["uid"])) == uuid.UUID(str(again["uid"]))
    assert _scalar_rows(engine, "SELECT asset_type FROM ms_markets__assettype") == [("currency",)]
