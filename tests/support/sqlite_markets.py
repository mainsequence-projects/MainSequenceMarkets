"""A migrated SQLite DataSource served by MetaTables' own server code, and its row helpers.

The `sqlite_markets` fixture (`tests/conftest.py`) gives each test its own copy of a
SQLite file migrated to head with the Markets migrations once per session.
`MetaTable.execute_operation` and `MetaTable.execute_transaction` go, after wire
serialization, to the SQLite backend's `execute` and `execute_transaction`, which bind
values and own the transaction as the local API does. Nothing leaves the process.

The row helpers read and write that file directly, outside MetaTables.
"""

from __future__ import annotations

import datetime as dt
import shutil
import uuid
from types import SimpleNamespace

import sqlalchemy as sa

import metatables.runtime_context
from metatables import (
    MetaTable,
    MetaTableCompiledSQLOperation,
    MetaTableCompiledSQLTransaction,
    MetaTableTransactionGuardError,
)
from metatables.runtime_contract import RuntimeContext

from msm.repositories.accounts import (
    replace_account_holdings_snapshot,
    replace_account_target_positions_snapshot,
)
from msm.repositories.base import MarketsRepositoryContext

WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)

GUARDED_TABLES = (
    "ms_markets__asset",
    "ms_markets__assetcategorymembership",
    "ms_markets__openfigiassetdetails",
    "ms_markets__currencyspotassetdetails",
)


def make_sqlite_markets(tmp_path, monkeypatch, *, template, prepare=None):
    """A migrated SQLite DataSource whose operations run through MetaTables' server code.

    The DataSource's file is a copy of ``template``, a file migrated to head.
    ``prepare(engine)`` runs on the copy before the execution identity is built, so
    tables it creates are readable and writable by the identity. Every SQL text sent to
    the backend is recorded in ``statements``.

    ``keep_statistics(*models)`` stores the update statistics of those time-index tables
    in ``index_stats``, by table name, as a table that keeps statistics has them in the
    catalog. After each write the harness does what MetaTables' route does after a
    compiled-SQL write (MetaTables#117): it rebuilds, with MetaTables' own
    ``rebuild_index_statistics``, the statistics of each written table that keeps them.
    """

    from dataclasses import replace

    from mainsequence.code_repository_context import GitCodeRepositorySourceContext
    from metatables.api.backend.backends.access import ExecutionIdentity
    from metatables.api.backend.backends.contracts import SQLExecutionError
    from metatables.api.backend.backends.operations import rebuild_index_statistics
    from metatables.api.backend.backends.registry import backend_for
    from metatables.api.backend.integrations.local_workspace import select_local_workspace

    workspace = select_local_workspace(
        source=GitCodeRepositorySourceContext(
            tmp_path, "https://example.test/repo", "test", "refs/heads/test", "a" * 40
        ),
        values={"METATABLES_LOCAL_STORAGE_DIR": str(tmp_path)},
    )
    workspace.tables_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, workspace.tables_path)
    engine = sa.create_engine(f"sqlite:///{workspace.tables_path}")
    if prepare is not None:
        prepare(engine)

    source = workspace.data_source
    backend = backend_for(source)
    tables = frozenset(("main", name) for name in sa.inspect(engine).get_table_names())
    identity = ExecutionIdentity(uuid.uuid4(), "fixture", None, tables, tables)
    runtime = RuntimeContext(
        git_source=None,
        dialect="sqlite",
        paramstyle="qmark",
        data_source={"uid": str(source.uid)},
        default_schema="main",
    )
    monkeypatch.setattr(metatables.runtime_context, "get_runtime_context", lambda: runtime)

    statements: list[str] = []
    index_stats: dict[str, dict] = {}
    kept: dict[str, type] = {}

    def rebuild(model) -> None:
        stats = rebuild_index_statistics(
            source=replace(source, execution_identity=identity),
            physical_schema=None,
            physical_table_name=model.__table__.name,
            time_index_name=model.__time_index_name__,
            identity_dimensions=tuple(model.__index_names__[1:]),
        )
        # An emptied table keeps no statistics, as the route stores them.
        index_stats[model.__table__.name] = stats if stats["_GLOBAL_"]["max"] is not None else {}

    def keep_statistics(*models) -> None:
        for model in models:
            kept[model.__table__.name] = model
            rebuild(model)

    def refreshed(result: dict) -> dict:
        # The route takes the written relations off the result and rebuilds each written
        # time-index table that keeps statistics; nothing stored cannot be stale.
        for _schema, name in result.pop("written_relations", None) or ():
            if name in kept and index_stats.get(name):
                rebuild(kept[name])
        return result

    def execute_operation(cls, operation, *, timeout=None):
        wire = MetaTableCompiledSQLOperation.model_validate_json(operation.model_dump_json())
        statements.append(wire.statement.sql)
        return refreshed(
            backend.sql.execute(
                identity=identity,
                sql_text=wire.statement.sql,
                operation=wire.operation,
                parameters=wire.statement.parameters,
                parameter_types=wire.statement.parameter_types,
                **wire.limits.model_dump(include={"max_rows", "offset", "statement_timeout_ms"}),
            )
        )

    def execute_transaction(cls, transaction, *, timeout=None):
        wire = MetaTableCompiledSQLTransaction.model_validate_json(transaction.model_dump_json())
        statements.extend(statement.sql for statement in wire.statements)
        try:
            return refreshed(
                backend.sql.execute_transaction(
                    identity=identity,
                    operation=wire.operation,
                    statements=[
                        statement.model_dump(
                            include={"sql", "parameters", "parameter_types", "expect_rows", "label"}
                        )
                        for statement in wire.statements
                    ],
                    **wire.limits.model_dump(include={"max_rows", "offset", "statement_timeout_ms"}),
                )
            )
        except SQLExecutionError as error:
            # The route answers 409 and the client raises this (MetaTables ADR 0026).
            if error.code != MetaTableTransactionGuardError.code:
                raise
            raise MetaTableTransactionGuardError(
                str(error),
                statement_index=error.extra.get("statement_index"),
                label=error.extra.get("label"),
                expect_rows=error.extra.get("expect_rows"),
                row_count=error.extra.get("row_count"),
            ) from error

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(execute_operation))
    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(execute_transaction))
    return SimpleNamespace(
        engine=engine,
        context=MarketsRepositoryContext(),
        statements=statements,
        index_stats=index_stats,
        keep_statistics=keep_statistics,
    )


def serve_row_operations(monkeypatch, markets) -> None:
    """Run every row operation on ``markets``, resolving its tables as a deployment does.

    ``msm.bootstrap.resolve_runtime`` answers with the SQLite context, after resolving
    the models the operation names with the same resolver the real runtime uses, so a
    table it cannot find fails here as it fails in a deployed API (#103).
    """

    from msm.models.registration import resolve_markets_meta_table_models

    def resolve_runtime(*, models, **_kwargs):
        resolve_markets_meta_table_models(models)
        return SimpleNamespace(context=markets.context)

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", resolve_runtime)


def _refuse_identical_rewrites(engine) -> None:
    with engine.begin() as connection:
        for table in GUARDED_TABLES:
            columns = [column["name"] for column in sa.inspect(connection).get_columns(table)]
            same = " AND ".join(f'NEW."{name}" IS OLD."{name}"' for name in columns)
            connection.exec_driver_sql(
                f"CREATE TRIGGER refuse_identical_rewrite_{table} BEFORE UPDATE ON {table} "
                f"WHEN {same} BEGIN SELECT RAISE(ABORT, 'identical rewrite of {table}'); END"
            )


def table_reads(engine, operation, table_names) -> dict[str, list[str]]:
    """The steps of SQLite's plan for a compiled read that read each of ``table_names``.

    One detail per step, such as ``SEARCH t USING COVERING INDEX ix (a=?)`` for an index
    search or ``SCAN t`` for a full scan. The read is bound as MetaTables binds it.
    """

    import re

    from metatables.api.backend.backends.restricted_sql import parameters_for

    statement = operation.statement
    values = parameters_for(statement.parameters, statement.parameter_types, "sqlite")
    if isinstance(values, list):
        # Positional SQL (MetaTables 0.1.71 and later): one parameter set, not a list of them.
        values = tuple(values)
    with engine.connect() as connection:
        plan = connection.exec_driver_sql(f"EXPLAIN QUERY PLAN {statement.sql}", values).all()
    return {
        name: [row[3] for row in plan if re.search(rf"\b{name}\b", row[3])] for name in table_names
    }


def _insert(engine, table_name: str, **values) -> dict:
    """Insert one row, filling required columns the test does not care about."""

    table = sa.Table(table_name, sa.MetaData(), autoload_with=engine)
    row = dict(values)
    for column in table.columns:
        if column.name in row or column.nullable or column.server_default is not None:
            continue
        type_name = str(column.type).upper()
        if type_name == "CHAR(32)":
            row[column.name] = uuid.uuid4().hex
        elif "BOOL" in type_name:
            row[column.name] = True
        elif "DATETIME" in type_name:
            row[column.name] = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        elif type_name == "DATE":
            row[column.name] = dt.date(2026, 1, 1)
        elif "INT" in type_name:
            row[column.name] = 1
        elif "FLOAT" in type_name or "REAL" in type_name or "NUMERIC" in type_name:
            row[column.name] = 1.0
        elif "JSON" in type_name:
            row[column.name] = {}
        else:
            length = getattr(column.type, "length", None) or 255
            row[column.name] = f"{uuid.uuid4().hex[:8]}-{column.name}"[:length]
    with engine.begin() as connection:
        connection.execute(table.insert(), row)
    return row


def _rows(engine, sql: str, **parameters) -> list[dict]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(sa.text(sql), parameters).mappings()]


def _count(engine, table_name: str) -> int:
    with engine.connect() as connection:
        return connection.execute(sa.text(f"SELECT count(*) FROM {table_name}")).scalar_one()


def _account(engine) -> uuid.UUID:
    account = uuid.uuid4()
    _insert(
        engine,
        "ms_markets__account",
        uid=account.hex,
        unique_identifier=f"account-{account.hex[:8]}",
        account_name="SQLite account",
        is_paper=True,
        account_is_active=True,
    )
    return account


def _asset(engine, unique_identifier: str) -> uuid.UUID:
    asset = uuid.uuid4()
    _insert(engine, "ms_markets__asset", uid=asset.hex, unique_identifier=unique_identifier)
    return asset


def _portfolio(engine, *, retired: bool = False) -> uuid.UUID:
    calendar = _insert(engine, "ms_markets__calendar")
    portfolio = uuid.uuid4()
    _insert(
        engine,
        "ms_markets__portfolio",
        uid=portfolio.hex,
        unique_identifier=f"portfolio-{portfolio.hex[:8]}",
        calendar_uid=calendar["uid"],
        retired_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC) if retired else None,
    )
    return portfolio


def _write_holdings(sqlite_markets, account, positions, *, overwrite=False):
    return replace_account_holdings_snapshot(
        sqlite_markets.context,
        holdings_set_uid=uuid.uuid4(),
        account_uid=account,
        holdings_date=WHEN,
        positions=positions,
        overwrite=overwrite,
    )


def _write_target(sqlite_markets, account, positions, *, overwrite=False):
    return replace_account_target_positions_snapshot(
        sqlite_markets.context,
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        account_uid=account,
        account_name="SQLite account",
        target_positions_date=WHEN,
        positions=positions,
        overwrite=overwrite,
    )


def _portfolio_position(portfolio, exposure=1000.0):
    return {
        "target_type": "portfolio",
        "target_uid": portfolio,
        "portfolio_uid": portfolio,
        "constant_notional_exposure": exposure,
        "metadata_json": {"note": "sqlite"},
    }
