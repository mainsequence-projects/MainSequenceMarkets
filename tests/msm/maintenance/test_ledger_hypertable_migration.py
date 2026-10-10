"""Portable DDL recovery and TimescaleDB partition-key contract regressions."""

from __future__ import annotations

import datetime as dt
import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from metatables import PlatformTimeIndexMetaTable
from msm_migrations.registry import metatable_provider_models
from msm_portfolios.data_nodes.portfolios.storage import PortfolioEventLedgerStorage


def test_every_time_index_unique_key_contains_its_partition_column() -> None:
    for model in metatable_provider_models():
        if not issubclass(model, PlatformTimeIndexMetaTable):
            continue
        table = model.__table__
        keys = [index for index in table.indexes if index.unique]
        keys += [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, (sa.UniqueConstraint, sa.PrimaryKeyConstraint))
            and len(constraint.columns)
        ]
        assert keys, model.__name__
        for key in keys:
            assert model.__time_index_name__ in key.columns.keys(), (model.__name__, key.name)


def test_0019_preserves_rows_and_full_grain_uniqueness(tmp_path) -> None:
    revision = importlib.import_module(
        "msm_migrations.versions.mainsequence_markets.0019_ledger_hypertable_uniqueness"
    )
    # A disposable SQLite file, not the developer's runtime or a hosted database.
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'ledger.sqlite'}")
    metadata = sa.MetaData()
    dimensions = PortfolioEventLedgerStorage.__index_names__[1:]
    table = sa.Table(
        revision.TABLE_NAME,
        metadata,
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        *(sa.Column(name, sa.String(255), nullable=False) for name in dimensions),
        sa.Column("quantity_delta", sa.Float(), nullable=False),
        sa.UniqueConstraint(*dimensions, name=revision.CONSTRAINT_NAME),
    )
    grain_index = next(
        index for index in PortfolioEventLedgerStorage.__table__.indexes if index.unique
    )
    sa.Index(
        grain_index.name,
        *(table.c[name] for name in PortfolioEventLedgerStorage.__index_names__),
        unique=True,
    )
    row = {
        "time_index": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        "portfolio_identifier": "migration-fixture",
        "event_identifier": "dividend",
        "event_revision": "v1",
        "record_identifier": "cash",
        "quantity_delta": 100.0,
    }
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(table.insert(), row)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            revision.upgrade()
        inspector = sa.inspect(connection)
        assert inspector.get_unique_constraints(table.name) == []
        assert (
            next(index for index in inspector.get_indexes(table.name) if index["unique"])[
                "column_names"
            ]
            == PortfolioEventLedgerStorage.__index_names__
        )
        assert connection.execute(sa.select(table.c.quantity_delta)).scalar_one() == 100.0
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(table.insert(), row)
        # Ordinary SQLite can restore the old constraint without rewriting rows.
        with Operations.context(context):
            revision.downgrade()
        assert (
            sa.inspect(connection).get_unique_constraints(table.name)[0]["column_names"]
            == dimensions
        )
        assert connection.execute(sa.select(table.c.quantity_delta)).scalar_one() == 100.0
    engine.dispose()
