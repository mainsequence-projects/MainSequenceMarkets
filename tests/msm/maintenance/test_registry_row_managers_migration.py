"""Revision 0032 records who manages each portfolio and signal (ADR 0060, decision 4)."""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic import command

from tests.msm.maintenance.test_legacy_schema_migration import _config
from tests.msm.repositories.test_sqlite_snapshot_writes import _insert

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0032_registry_row_managers"
)


def _rows(connection, table: str) -> list[dict]:
    reflected = sa.Table(table, sa.MetaData(), autoload_with=connection)
    return [dict(row) for row in connection.execute(sa.select(reflected)).mappings()]


def test_0032_adds_a_null_manager_to_existing_rows_and_downgrades_cleanly(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'managers.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        command.upgrade(config, "0031")
        connection.commit()
        calendar = _insert(engine, "ms_markets__calendar")
        _insert(engine, "ms_markets__signalmetadata", signal_uid="signal")
        _insert(
            engine,
            "ms_markets__portfolio",
            unique_identifier="portfolio",
            calendar_uid=calendar["uid"],
            signal_uid="signal",
        )
        before = {table: _rows(connection, table) for table in REVISION.TABLES}

        command.upgrade(config, "0032")
        for table in REVISION.TABLES:
            columns = {
                column["name"]: column for column in sa.inspect(connection).get_columns(table)
            }
            assert columns[REVISION.COLUMN]["nullable"] is True
            after = _rows(connection, table)
            assert [row.pop(REVISION.COLUMN) for row in after] == [None] * len(after)
            assert after == before[table]

        command.downgrade(config, "0031")
        for table in REVISION.TABLES:
            assert REVISION.COLUMN not in {
                column["name"] for column in sa.inspect(connection).get_columns(table)
            }
            assert _rows(connection, table) == before[table]
    engine.dispose()
