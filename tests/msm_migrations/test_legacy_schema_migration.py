"""Exercise real Alembic upgrade paths and preserve populated application rows."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import uuid

from sqlalchemy.engine import make_url

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa

from msm_migrations import migration
from tests.support.migrations import _config, _seed_every_table

BRIDGE = importlib.import_module("msm_migrations.versions.mainsequence_markets.0020_merge_legacy_schema")


CALENDAR_REVISION_DROPS = (
    "ms_markets__calendardate",
    "ms_markets__calendarsession",
    "ms_markets__calendarevent",
)


TARGETS_REVISION_DELETES = ("ms_markets__positionset", "ms_markets__targetpositionsts")
CATALOG_REVISION_DROPS = ("ms_markets__portfoliodatasetavailability",)
"""Revision 0033 drops the portfolio dataset catalog (ADR 0060)."""


def _seed_asset(connection):
    table = sa.Table("ms_markets__asset", sa.MetaData(), autoload_with=connection)
    connection.execute(table.insert(), {
        "uid": (uuid.UUID("01aaca14-65ec-4542-96aa-77ab37506a0d") if connection.dialect.name == "postgresql" else "01aaca1465ec454296aa77ab37506a0d"),
        "unique_identifier": "migration-preservation-asset",
        "asset_type": "currency",
    })
    connection.commit()


@pytest.mark.parametrize("start", [None, "0018", "0019"])
def test_fresh_and_development_paths_keep_data_and_one_head(tmp_path, sqlite_revisions, start):
    # Without a start, the whole chain runs from an empty database: the one test that
    # does. With one, the database starts from the session's copy at that revision.
    path = tmp_path / "migration.sqlite"
    if start:
        engine = sqlite_revisions.engine(path, start)
    else:
        engine = sa.create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        config = _config(connection)
        if start:
            _seed_asset(connection)
        command.upgrade(config, "head")
        assert ScriptDirectory.from_config(config).get_heads() == ["0036"]
        assert connection.exec_driver_sql("SELECT version_num FROM ms_markets__alembic_version").scalar_one() == "0036"
        # Revision 0027 drops three calendar tables and adds two; 0028 adds AssetCalendar.
        # Revision 0029 adds a column to the portfolio values table; 0030 two to the
        # portfolio weights table; 0031 indexes to six portfolio dataset tables; 0032 a
        # manager column to Portfolio and SignalMetadata; 0033 drops the portfolio dataset
        # catalog table.
        assert len(sa.inspect(connection).get_table_names()) == 64
        if start:
            assert connection.exec_driver_sql("SELECT unique_identifier FROM ms_markets__asset").scalar_one() == "migration-preservation-asset"
        connection.rollback()
        command.upgrade(config, "head")
        assert connection.exec_driver_sql("SELECT version_num FROM ms_markets__alembic_version").scalar_one() == "0036"
    engine.dispose()


def test_bridge_rejects_missing_columns_without_modifying_schema(tmp_path, sqlite_revisions):
    engine = sqlite_revisions.engine(tmp_path / "broken.sqlite", "0019")
    with engine.connect() as connection:
        connection.exec_driver_sql("ALTER TABLE ms_markets__asset RENAME COLUMN asset_type TO incorrect_type")
        connection.commit()
        with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="column contract differs"):
            BRIDGE.upgrade()
        assert connection.exec_driver_sql("SELECT version_num FROM ms_markets__alembic_version").scalar_one() == "0019"
        assert "incorrect_type" in {column["name"] for column in sa.inspect(connection).get_columns("ms_markets__asset")}
    engine.dispose()


def test_original_0017_postgresql_upgrade_preserves_every_row():
    url = os.environ.get("MS_MARKETS_LEGACY_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set MS_MARKETS_LEGACY_TEST_POSTGRES_URL to a disposable PostgreSQL database")
    parsed = make_url(url)
    if parsed.host not in {"localhost", "127.0.0.1"} or not (parsed.database or "").startswith("markets_"):
        pytest.fail("Legacy regression accepts only a disposable markets_* database on localhost")
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        connection.exec_driver_sql("SET search_path TO public")
        connection.commit()
        if sa.inspect(connection).get_table_names():
            pytest.fail("Legacy regression requires an empty disposable database")
        fixture = Path(__file__).with_name("fixtures") / "legacy_0017.sql"
        connection.exec_driver_sql(fixture.read_text())
        connection.exec_driver_sql("SET search_path TO public")
        connection.exec_driver_sql("INSERT INTO ms_markets__alembic_version VALUES ('0017')")
        connection.commit()
        _seed_every_table(connection)
        # PostgreSQL transactional DDL must roll back 0019 as well when the
        # merge refuses an overlong legacy identifier. No value is truncated.
        # Simulate a legacy database that lacks this FK and contains an
        # overlong value; an intact FK to Asset already prevents that value.
        fk = next(fk for fk in sa.inspect(connection).get_foreign_keys("ms_markets__ordersts")
                  if fk["constrained_columns"] == ["asset_identifier"])
        connection.exec_driver_sql(f'ALTER TABLE ms_markets__ordersts DROP CONSTRAINT "{fk["name"]}"')
        original = connection.exec_driver_sql("SELECT asset_identifier FROM ms_markets__ordersts").scalar_one()
        connection.exec_driver_sql("UPDATE ms_markets__ordersts SET asset_identifier = %s", ("x" * 256,))
        connection.commit()
        with pytest.raises(RuntimeError, match="exceeds 255 characters"):
            command.upgrade(_config(connection), "head")
        connection.rollback()
        assert connection.exec_driver_sql("SELECT version_num FROM ms_markets__alembic_version").scalar_one() == "0017"
        assert connection.exec_driver_sql("SELECT asset_identifier FROM ms_markets__ordersts").scalar_one() == "x" * 256
        assert next(c for c in sa.inspect(connection).get_columns("ms_markets__ordersts") if c["name"] == "asset_identifier")["type"].length is None
        connection.exec_driver_sql("UPDATE ms_markets__ordersts SET asset_identifier = %s", (original,))
        connection.exec_driver_sql(
            f'ALTER TABLE ms_markets__ordersts ADD CONSTRAINT "{fk["name"]}" '
            'FOREIGN KEY (asset_identifier) REFERENCES ms_markets__asset (unique_identifier)'
        )
        connection.commit()
        tables = sorted(name for name in sa.inspect(connection).get_table_names() if name != migration.version_table)
        before = {name: BRIDGE._fingerprint(connection, name) for name in tables}
        counts = {name: connection.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar_one() for name in tables}
        connection.rollback()
        # The 0020 bridge must leave every row byte-identical; 0021 then adds a nullable
        # column to SignalMetadata, which changes row JSON, so fingerprints are taken at 0020.
        command.upgrade(_config(connection), "0020")
        assert connection.exec_driver_sql("SELECT version_num FROM ms_markets__alembic_version").scalar_one() == "0020"
        assert {name: BRIDGE._fingerprint(connection, name) for name in tables} == before
        for table_name, names in BRIDGE.LEGACY_IDENTIFIERS.items():
            actual = {column["name"]: column for column in sa.inspect(connection).get_columns(table_name)}
            assert all(actual[name]["type"].length == 255 for name in names)
        connection.rollback()
        command.upgrade(_config(connection), "0020")
        assert {name: BRIDGE._fingerprint(connection, name) for name in tables} == before
        connection.rollback()
        command.upgrade(_config(connection), "head")
        assert connection.exec_driver_sql("SELECT version_num FROM ms_markets__alembic_version").scalar_one() == "0036"
        # Revision 0024 deletes the account targets, as its docstring says. Revision 0027
        # converts the stored calendar rows and drops their three tables.
        kept = [
            name
            for name in tables
            if name not in CALENDAR_REVISION_DROPS
            and name not in CATALOG_REVISION_DROPS
            and name not in TARGETS_REVISION_DELETES
        ]
        assert all(
            connection.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar_one() == 0
            for name in TARGETS_REVISION_DELETES
        )
        assert {name: connection.exec_driver_sql(f'SELECT count(*) FROM "{name}"').scalar_one() for name in kept} == {name: counts[name] for name in kept}
        assert not set(CALENDAR_REVISION_DROPS) & set(sa.inspect(connection).get_table_names())
        assert connection.exec_driver_sql("SELECT count(*) FROM ms_markets__calendarsessionrule").scalar_one() == 1
        assert "ms_markets__portfoliodatasetavailability" not in sa.inspect(connection).get_table_names()
    engine.dispose()
