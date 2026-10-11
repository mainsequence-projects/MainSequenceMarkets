"""Exercise real Alembic upgrade paths and preserve populated application rows."""

from __future__ import annotations

import importlib
import os
import datetime as dt
from decimal import Decimal
from pathlib import Path
import uuid

from sqlalchemy.engine import make_url

from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa

from metatables.migrations import alembic_config_for_provider
from msm_migrations import migration

BRIDGE = importlib.import_module("msm_migrations.versions.mainsequence_markets.0020_merge_legacy_schema")


def _config(connection):
    config = alembic_config_for_provider(migration, sqlalchemy_url=str(connection.engine.url))
    config.attributes["connection"] = connection
    return config


def _seed_asset(connection):
    table = sa.Table("ms_markets__asset", sa.MetaData(), autoload_with=connection)
    connection.execute(table.insert(), {
        "uid": (uuid.UUID("01aaca14-65ec-4542-96aa-77ab37506a0d") if connection.dialect.name == "postgresql" else "01aaca1465ec454296aa77ab37506a0d"),
        "unique_identifier": "migration-preservation-asset",
        "asset_type": "currency",
    })
    connection.commit()


def _seed_every_table(connection):
    metadata = sa.MetaData()
    metadata.reflect(connection)
    rows = {}
    for table in metadata.sorted_tables:
        if table.name == migration.version_table:
            continue
        row = {}
        for column in table.columns:
            if column.nullable:
                row[column.name] = None
            elif isinstance(column.type, sa.Uuid):
                row[column.name] = uuid.uuid5(uuid.NAMESPACE_URL, f"{table.name}.{column.name}")
            elif isinstance(column.type, sa.Boolean):
                row[column.name] = True
            elif isinstance(column.type, sa.DateTime):
                row[column.name] = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
            elif isinstance(column.type, sa.Date):
                row[column.name] = dt.date(2026, 1, 1)
            elif isinstance(column.type, sa.Integer):
                row[column.name] = 1
            elif isinstance(column.type, sa.Float):
                row[column.name] = 123.5
            elif isinstance(column.type, sa.Numeric):
                row[column.name] = Decimal("123.5")
            elif isinstance(column.type, sa.JSON):
                row[column.name] = {"migration": "preserve"}
            else:
                row[column.name] = f"seed-{column.name}"[:getattr(column.type, "length", None) or 255]
        for column in table.columns:
            if row[column.name] is not None and column.foreign_keys:
                target = next(iter(column.foreign_keys)).column
                row[column.name] = rows[target.table.name][target.name]
        if table.name == "ms_markets__index":
            row.update(calculation_method="custom", value_format="decimal")
        elif table.name == "ms_markets__indexdatasetavailability":
            row["population_state"] = "unavailable"
        elif table.name == "ms_markets__indexformuladefinition":
            row.update(alignment_policy="exact", missing_data_policy="fail", status="draft")
        elif table.name == "ms_markets__indexformulainput":
            row["asset_uid"] = rows["ms_markets__asset"]["uid"]
        elif table.name == "ms_markets__targetpositionsts":
            row.update(target_type="asset", target_uid=rows["ms_markets__asset"]["uid"],
                       asset_uid=rows["ms_markets__asset"]["uid"], single_asset_quantity=123.5)
        connection.execute(table.insert(), row)
        rows[table.name] = row
    connection.commit()
    assert len(rows) == 62


@pytest.mark.parametrize("start", [None, "0018", "0019"])
def test_fresh_and_development_paths_keep_data_and_one_head(tmp_path, start):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        if start:
            command.upgrade(config, start)
            _seed_asset(connection)
        command.upgrade(config, "head")
        assert ScriptDirectory.from_config(config).get_heads() == ["0020"]
        assert connection.exec_driver_sql("SELECT version_num FROM ms_markets__alembic_version").scalar_one() == "0020"
        assert len(sa.inspect(connection).get_table_names()) == 63
        if start:
            assert connection.exec_driver_sql("SELECT unique_identifier FROM ms_markets__asset").scalar_one() == "migration-preservation-asset"
        connection.rollback()
        command.upgrade(config, "head")
        assert connection.exec_driver_sql("SELECT version_num FROM ms_markets__alembic_version").scalar_one() == "0020"
    engine.dispose()


def test_bridge_rejects_missing_columns_without_modifying_schema(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'broken.sqlite'}")
    with engine.connect() as connection:
        command.upgrade(_config(connection), "0019")
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
        connection.rollback()
        command.upgrade(_config(connection), "head")
        assert connection.exec_driver_sql("SELECT version_num FROM ms_markets__alembic_version").scalar_one() == "0020"
        assert {name: BRIDGE._fingerprint(connection, name) for name in tables} == before
        for table_name, names in BRIDGE.LEGACY_IDENTIFIERS.items():
            actual = {column["name"]: column for column in sa.inspect(connection).get_columns(table_name)}
            assert all(actual[name]["type"].length == 255 for name in names)
        connection.rollback()
        command.upgrade(_config(connection), "head")
        assert {name: BRIDGE._fingerprint(connection, name) for name in tables} == before
    engine.dispose()
