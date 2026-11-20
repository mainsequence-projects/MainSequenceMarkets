"""Revision 0024 stored account targets in units (ADR 0052, superseded by ADR 0054)."""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic import command

from tests.support.migrations import _config, _seed_every_table

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0024_account_targets_in_units"
)
ALLOCATION_TABLE = "ms_markets__accounttargetallocation"
FORMER_COLUMNS = {
    "weight_notional_exposure",
    "constant_notional_exposure",
    "single_asset_quantity",
}


def _columns(connection) -> dict[str, dict]:
    return {
        column["name"]: column for column in sa.inspect(connection).get_columns(REVISION.TABLE)
    }


def _count(connection, table: str) -> int:
    return connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()


def _unique_index_columns(connection) -> list[list[str]]:
    return [
        index["column_names"]
        for index in sa.inspect(connection).get_indexes(REVISION.TABLE)
        if index["unique"]
    ]


def test_0024_deletes_the_target_history_and_stores_units(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "targets-in-units.sqlite", "0023")
    with engine.connect() as connection:
        config = _config(connection)
        _seed_every_table(connection, expected_tables=63)
        connection.commit()
        assert _count(connection, REVISION.TABLE) == 1
        assert _count(connection, REVISION.POSITION_SET_TABLE) == 1
        allocations = _count(connection, ALLOCATION_TABLE)

        command.upgrade(config, "0024")

        assert _count(connection, REVISION.TABLE) == 0
        assert _count(connection, REVISION.POSITION_SET_TABLE) == 0
        assert _count(connection, ALLOCATION_TABLE) == allocations
        columns = _columns(connection)
        assert not FORMER_COLUMNS & set(columns)
        assert columns["quantity"]["nullable"] is False
        assert columns["direction"]["nullable"] is False
        assert columns["asset_uid"]["nullable"] is False
        assert columns["portfolio_uid"]["nullable"] is True
        assert _unique_index_columns(connection) == [REVISION.GRAIN]


def test_0024_refuses_a_zero_quantity_and_an_unknown_direction(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "targets-checks.sqlite", "0024")
    with engine.connect() as connection:
        checks = {
            constraint["sqltext"]
            for constraint in sa.inspect(connection).get_check_constraints(REVISION.TABLE)
        }

    assert "quantity > 0" in checks
    assert "direction IN (1, -1)" in checks


def test_0024_downgrade_restores_the_former_columns(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "targets-downgrade.sqlite", "0024")
    with engine.connect() as connection:
        config = _config(connection)

        command.downgrade(config, "0023")

        columns = _columns(connection)
        assert FORMER_COLUMNS <= set(columns)
        assert "quantity" not in columns
        assert "direction" not in columns
        assert columns["asset_uid"]["nullable"] is True
        assert _unique_index_columns(connection) == [REVISION.FORMER_GRAIN]

        command.upgrade(config, "head")
