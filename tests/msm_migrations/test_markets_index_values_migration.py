"""Revision 0039: Markets' own Index-value tables at 1m, 1h and 1d (ADR 0066, decision 6).

Markets declares the three as class statements, its migration provider lists them, and
the revision creates their tables. A table that already exists is taken when it matches
the ``IndexValuesTS`` contract and refused when it differs (issue 147).

Each upgrade test runs on SQLite and on PostgreSQL, whose reflected types differ from the
declared ones. Set ``MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL`` to an empty, disposable
``markets_*`` database on localhost to run the PostgreSQL cases; they are skipped otherwise.
"""

from __future__ import annotations

import datetime as dt
import importlib
import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from msm.base import MarketsBase
from msm.time_index.indices.storage import (
    IndexValues1d,
    IndexValues1h,
    IndexValues1m,
    IndexValuesStorage,
)
from msm_migrations.registry import metatable_provider_models
from tests.support.migrations import _config
from tests.support.postgresql_databases import worker_database

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0039_markets_index_values_per_cadence"
)
DECLARED = (IndexValues1m, IndexValues1h, IndexValues1d)
TABLES = {model.__table__.name for model in DECLARED}
URL_VARIABLE = "MS_MARKETS_TIMESCALE_TEST_POSTGRES_URL"
ONE_DAY = IndexValues1d.__table__
NAMES = REVISION.TABLES[ONE_DAY.name]


def _table_of(difference) -> str | None:
    item = difference[0] if isinstance(difference, list) else difference
    for value in item[1:]:
        table = getattr(value, "table", None)
        name = getattr(table, "name", None) or getattr(value, "name", None)
        if isinstance(name, str) and name in TABLES:
            return name
        if isinstance(value, str) and value in TABLES:
            return value
    return None


def _differences_from_the_models(connection) -> list:
    differences = compare_metadata(
        MigrationContext.configure(connection, opts={"compare_type": True}),
        MarketsBase.metadata,
    )
    return [difference for difference in differences if _table_of(difference)]


def _version(connection) -> str:
    return connection.exec_driver_sql(
        "SELECT version_num FROM ms_markets__alembic_version"
    ).scalar_one()


@pytest.fixture(params=["sqlite", "postgresql"])
def at_0038(request, tmp_path, sqlite_revisions):
    """An engine on a database at revision 0038, on SQLite or on PostgreSQL."""

    if request.param == "sqlite":
        engine = sqlite_revisions.engine(tmp_path / "at-0038.sqlite", "0038")
    else:
        url = os.environ.get(URL_VARIABLE)
        if not url:
            pytest.skip(f"Set {URL_VARIABLE} to a disposable PostgreSQL database")
        parsed = make_url(url)
        if parsed.host not in {"localhost", "127.0.0.1"} or not (parsed.database or "").startswith(
            "markets_"
        ):
            pytest.fail("These tests accept only a disposable markets_* database on localhost")
        parsed = worker_database(parsed)
        engine = sa.create_engine(parsed.set(drivername="postgresql+psycopg"), poolclass=NullPool)
        with engine.connect() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
            connection.commit()
            command.upgrade(_config(connection), "0038")
            connection.commit()
    yield engine
    engine.dispose()


def test_markets_declares_index_values_at_1m_1h_and_1d_and_its_provider_lists_them() -> None:
    models = metatable_provider_models()
    cadenced = [
        model
        for model in models
        if str(getattr(model, "__metatable_identifier__", "")).startswith("IndexValuesTS.")
    ]

    assert cadenced == list(DECLARED)
    assert [model.__cadence__ for model in cadenced] == ["1m", "1h", "1d"]
    assert set(REVISION.TABLES) == TABLES
    # Each after the tables its keys point at.
    assert models.index(IndexValuesStorage) < models.index(IndexValues1m)


def test_0039_creates_the_tables_as_the_models_declare_them(at_0038) -> None:
    with at_0038.connect() as connection:
        assert not TABLES & set(sa.inspect(connection).get_table_names())
        command.upgrade(_config(connection), "0039")
        connection.commit()

        created = TABLES & set(sa.inspect(connection).get_table_names())
        assert created == TABLES
        assert _differences_from_the_models(connection) == []


@pytest.mark.parametrize("rows", [0, 1], ids=["empty", "with-a-row"])
def test_0039_takes_an_existing_table_that_matches_the_contract_with_its_rows(
    at_0038, rows
) -> None:
    index = MarketsBase.metadata.tables[REVISION.INDEX_TABLE]
    with at_0038.connect() as connection:
        # The table as the 1d class builds it, which is how a database came to hold one.
        ONE_DAY.create(connection)
        if rows:
            connection.execute(
                index.insert(),
                {
                    "unique_identifier": "INDEX-147",
                    "index_type": "custom",
                    "display_name": "Index 147",
                    "calculation_method": "custom",
                    "value_format": "decimal",
                },
            )
            connection.execute(
                ONE_DAY.insert(),
                {
                    "time_index": dt.datetime(2026, 11, 25, tzinfo=dt.UTC),
                    "index_identifier": "INDEX-147",
                    "value": 101.5,
                    "observation_status": "observed",
                    "metadata_json": {"source": "before 0039"},
                },
            )
        connection.commit()

        command.upgrade(_config(connection), "0039")
        connection.commit()

        assert _version(connection) == "0039"
        assert TABLES <= set(sa.inspect(connection).get_table_names())
        assert _differences_from_the_models(connection) == []
        kept = connection.execute(
            sa.select(
                ONE_DAY.c.index_identifier,
                ONE_DAY.c.value,
                ONE_DAY.c.observation_status,
                ONE_DAY.c.metadata_json,
            )
        ).all()
        assert kept == ([("INDEX-147", 101.5, "observed", {"source": "before 0039"})] if rows else [])


def test_0039_refuses_an_existing_table_that_differs_and_names_each_difference(at_0038) -> None:
    with at_0038.connect() as connection:
        metadata = sa.MetaData()
        metadata.reflect(connection, only=[REVISION.INDEX_TABLE, REVISION.DEFINITION_TABLE])
        table = ONE_DAY.to_metadata(metadata)
        table.c.value.type = sa.String(32)
        table.c.definition_uid.nullable = False
        table.append_column(sa.Column("note", sa.Text()))
        table.indexes.discard(next(i for i in table.indexes if i.name == NAMES["status_index"]))
        next(
            key for key in table.foreign_key_constraints if key.name == NAMES["definition_key"]
        ).ondelete = "CASCADE"
        table.create(connection)
        connection.commit()

        with pytest.raises(RuntimeError) as refused:
            command.upgrade(_config(connection), "0039")
        connection.rollback()

        message = str(refused.value)
        assert f"{ONE_DAY.name}: " in message
        for difference in (
            "column value is VARCHAR(32), the contract's is FLOAT",
            "column definition_uid is NOT NULL, the contract's is nullable",
            "column note is not in the contract",
            f"index {NAMES['status_index']} is missing",
            f"foreign key {NAMES['definition_key']} is (definition_uid) -> "
            f"{REVISION.DEFINITION_TABLE} (uid) ON DELETE CASCADE, the contract's is "
            f"(definition_uid) -> {REVISION.DEFINITION_TABLE} (uid) ON DELETE RESTRICT",
        ):
            assert difference in message
        # Only the table that differs is named, and only what differs in it.
        assert "__t_1m" not in message and "__t_1h" not in message
        assert NAMES["index_key"] not in message
        assert NAMES["grain_index"] not in message

        assert _version(connection) == "0038"
        found = set(sa.inspect(connection).get_table_names())
        assert TABLES & found == {ONE_DAY.name}
        assert "note" in {column["name"] for column in sa.inspect(connection).get_columns(ONE_DAY.name)}


def test_0039_downgrade_restores_the_schema_of_0038(tmp_path, sqlite_revisions) -> None:
    with sqlite_revisions.engine(tmp_path / "at-0038.sqlite", "0038").connect() as connection:
        at_0038 = set(sa.inspect(connection).get_table_names())
    engine = sqlite_revisions.engine(tmp_path / "down.sqlite", "0039")
    with engine.connect() as connection:
        command.downgrade(_config(connection), "0038")
        connection.commit()

        assert set(sa.inspect(connection).get_table_names()) == at_0038
