"""Revision 0039: Markets' own Index-value tables at 1m, 1h and 1d (ADR 0066, decision 6).

Markets declares the three as class statements, its migration provider lists them, and
the revision creates their tables.
"""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from msm.base import MarketsBase
from msm.time_index.indices.storage import (
    IndexValues1d,
    IndexValues1h,
    IndexValues1m,
    IndexValuesStorage,
)
from msm_migrations.registry import metatable_provider_models
from tests.support.migrations import _config

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0039_markets_index_values_per_cadence"
)
DECLARED = (IndexValues1m, IndexValues1h, IndexValues1d)
TABLES = {model.__table__.name for model in DECLARED}


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


def test_0039_creates_the_tables_as_the_models_declare_them(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "at-0038.sqlite", "0038")
    with engine.connect() as connection:
        assert not TABLES & set(sa.inspect(connection).get_table_names())
        command.upgrade(_config(connection), "0039")
        connection.commit()

        differences = compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}),
            MarketsBase.metadata,
        )
        created = TABLES & set(sa.inspect(connection).get_table_names())

    assert created == TABLES
    assert [difference for difference in differences if _table_of(difference)] == []


def test_0039_downgrade_restores_the_schema_of_0038(tmp_path, sqlite_revisions) -> None:
    with sqlite_revisions.engine(tmp_path / "at-0038.sqlite", "0038").connect() as connection:
        at_0038 = set(sa.inspect(connection).get_table_names())
    engine = sqlite_revisions.engine(tmp_path / "down.sqlite", "0039")
    with engine.connect() as connection:
        command.downgrade(_config(connection), "0038")
        connection.commit()

        assert set(sa.inspect(connection).get_table_names()) == at_0038
