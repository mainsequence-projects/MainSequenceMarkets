"""Revision 0025 restores account exposure and adds the allocation lines table (ADR 0054)."""

from __future__ import annotations

import datetime as dt
import importlib
import uuid

import sqlalchemy as sa
from alembic import command

from msm.time_index.accounts.storage import TargetPositionsStorage
from msm.time_index.accounts.virtual_funds.storage import AccountAllocationLinesStorage
from tests.msm.maintenance.test_legacy_schema_migration import _config, _seed_every_table

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0025_account_exposure_and_fund_targets"
)
WHEN = dt.datetime(2026, 11, 15, tzinfo=dt.UTC)


def _columns(connection, table: str) -> dict[str, dict]:
    return {column["name"]: column for column in sa.inspect(connection).get_columns(table)}


def _unit_target(connection, *, portfolio: bool) -> str:
    """Write one PositionSet in units, as 3.6 did: an asset row, or a portfolio row."""

    metadata = sa.MetaData()
    metadata.reflect(connection)
    position_sets = metadata.tables[REVISION.POSITION_SET_TABLE]
    targets = metadata.tables[REVISION.TABLE]

    def uid_of(table: str) -> str:
        return connection.execute(sa.select(metadata.tables[table].c.uid)).scalar_one()

    asset_uid = uid_of("ms_markets__asset")
    portfolio_uid = uid_of("ms_markets__portfolio")
    # SQLite reflects uid columns as text.
    position_set_uid = uuid.uuid4().hex
    connection.execute(
        position_sets.insert(),
        {
            "uid": position_set_uid,
            "account_target_allocation_uid": uid_of("ms_markets__accounttargetallocation"),
            "position_set_time": WHEN + dt.timedelta(hours=2 if portfolio else 1),
            "source": "test",
        },
    )
    connection.execute(
        targets.insert(),
        {
            "time_index": WHEN,
            "position_set_uid": position_set_uid,
            "target_type": "portfolio" if portfolio else "asset",
            "target_uid": portfolio_uid if portfolio else asset_uid,
            "asset_uid": asset_uid,
            "portfolio_uid": portfolio_uid if portfolio else None,
            "quantity": 40.0,
            "direction": -1,
        },
    )
    connection.commit()
    return position_set_uid


def test_0025_matches_the_storage_models(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'exposure-model.sqlite'}")
    with engine.connect() as connection:
        command.upgrade(_config(connection), "head")
        inspector = sa.inspect(connection)

        for model in (TargetPositionsStorage.__table__, AccountAllocationLinesStorage.__table__):
            assert set(_columns(connection, model.name)) == {column.name for column in model.columns}
            assert {
                constraint["name"] for constraint in inspector.get_check_constraints(model.name)
            } == {
                constraint.name
                for constraint in model.constraints
                if isinstance(constraint, sa.CheckConstraint)
            }
            assert {index["name"] for index in inspector.get_indexes(model.name)} == {
                index.name for index in model.indexes
            }
            assert {
                key["name"]: (key["constrained_columns"], key["options"].get("ondelete"))
                for key in inspector.get_foreign_keys(model.name)
            } == {
                key.name: ([column.name for column in key.columns], key.ondelete)
                for key in model.foreign_key_constraints
            }
        assert REVISION.EXPOSURE_GRAIN == list(TargetPositionsStorage.__index_names__)
        assert REVISION.LINES_GRAIN == list(AccountAllocationLinesStorage.__index_names__)


def test_0025_keeps_asset_targets_and_deletes_portfolio_targets_in_units(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'exposure-data.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        command.upgrade(config, "0023")
        _seed_every_table(connection, expected_tables=63)
        command.upgrade(config, "0024")
        asset_set = _unit_target(connection, portfolio=False)
        _unit_target(connection, portfolio=True)

        command.upgrade(config, "0025")

        metadata = sa.MetaData()
        metadata.reflect(connection)
        targets = metadata.tables[REVISION.TABLE]
        rows = connection.execute(
            sa.select(
                targets.c.position_set_uid, targets.c.target_type, targets.c.single_asset_quantity
            )
        ).all()
        position_sets = connection.execute(
            sa.select(metadata.tables[REVISION.POSITION_SET_TABLE].c.uid)
        ).all()
        columns = _columns(connection, REVISION.TABLE)

    assert [tuple(row) for row in rows] == [(asset_set, "asset", -40.0)]
    assert [row[0] for row in position_sets] == [asset_set]
    assert "quantity" not in columns
    assert "direction" not in columns
    assert columns["asset_uid"]["nullable"] is True
    assert columns["weight_notional_exposure"]["nullable"] is True
    assert columns["constant_notional_exposure"]["nullable"] is True


def test_0025_leaves_the_fund_holdings_as_they_are(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'fund-holdings.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        command.upgrade(config, "0023")
        _seed_every_table(connection, expected_tables=63)
        before = set(_columns(connection, "ms_markets__virtualfundholdingsts"))
        command.upgrade(config, "0025")

        assert set(_columns(connection, "ms_markets__virtualfundholdingsts")) == before
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM ms_markets__virtualfundholdingsts"
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            f"SELECT count(*) FROM {REVISION.LINES_TABLE}"
        ).scalar_one() == 0


def test_0025_downgrade_restores_the_unit_columns(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'exposure-downgrade.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        command.upgrade(config, "0025")

        command.downgrade(config, "0024")

        columns = _columns(connection, REVISION.TABLE)
        assert {"quantity", "direction"} <= set(columns)
        assert "weight_notional_exposure" not in columns
        assert columns["asset_uid"]["nullable"] is False
        assert REVISION.LINES_TABLE not in sa.inspect(connection).get_table_names()

        command.upgrade(config, "head")
