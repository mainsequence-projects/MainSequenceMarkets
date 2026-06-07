from __future__ import annotations

import datetime as dt
from importlib import resources
from pathlib import Path

import pytest
from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mainsequence.meta_tables import (
    POSTGRES_IDENTIFIER_MAX_LENGTH,
    PlatformManagedMetaTable,
    PlatformTimeIndexMetaTable,
)
from mainsequence.meta_tables.migrations import (
    AlembicMetaTableMigration,
    load_alembic_metatable_migration_provider,
    namespace_version_location,
    namespace_version_slug,
)

from msm.base import (
    MARKETS_DEFAULT_SCHEMA,
    MARKETS_SCHEMA,
    MarketsBase,
    MarketsTimeIndexMetaTableMixin,
    markets_table_args,
    normalize_metatable_schema,
)
from migrations import (
    MarketsAlembicVersion,
    migration,
)
from migrations.registry import metatable_provider_models
from msm.models import AssetTable
from msm.settings import markets_identifier


def test_migration_provider_is_single_sdk_alembic_provider() -> None:
    assert isinstance(migration, AlembicMetaTableMigration)
    assert migration.package == "msm"
    assert migration.script_location == "migrations:"
    assert migration.target_metadata is MarketsBase.metadata
    assert migration.alembic_registry is MarketsAlembicVersion
    assert MarketsAlembicVersion.__metatable_namespace__ == migration.migration_namespace
    assert MarketsAlembicVersion.__metatable_identifier__ == markets_identifier(
        "msm.alembic_version",
        namespace=migration.migration_namespace,
    )
    expected_version_table = MarketsAlembicVersion.__alembic_version_table_name__
    assert migration.version_table == expected_version_table
    assert MARKETS_SCHEMA is None
    assert migration.version_table_schema is None
    assert migration.alembic_version_table == expected_version_table
    assert migration.after_register_metatables is None
    assert list(migration.metatable_models) == metatable_provider_models()


def test_migration_upgrade_command_uses_current_sdk_flags() -> None:
    upgrade_command = "mainsequence migrations upgrade --provider migrations:migration head"

    assert "--register-metatables" not in upgrade_command
    assert "--apply" not in upgrade_command


def test_sdk_loader_resolves_msm_migration_provider() -> None:
    loaded = load_alembic_metatable_migration_provider("migrations:migration")

    assert loaded is migration


def test_legacy_migrations_provider_import_is_compatibility_alias() -> None:
    from msm.migrations import migration as legacy_migration

    assert legacy_migration is migration


def test_migration_script_template_is_packaged() -> None:
    template = resources.files("migrations").joinpath("script.py.mako")

    assert template.is_file()
    template_text = template.read_text(encoding="utf-8")
    assert "revision: str = ${repr(up_revision)}" in template_text
    assert "def upgrade() -> None:" in template_text
    assert "def downgrade() -> None:" in template_text


def test_namespace_version_slug_is_deterministic() -> None:
    assert namespace_version_slug(None) == "default"
    assert namespace_version_slug("") == "default"
    assert namespace_version_slug("mainsequence.examples") == "mainsequence_examples"
    assert namespace_version_slug("client-a.production") == "client_a_production"
    assert len(namespace_version_slug("x" * 100)) <= 48


def test_migration_provider_uses_sdk_namespace_version_location() -> None:
    expected_location = namespace_version_location(migration.migration_namespace)

    assert migration.version_locations == [expected_location]
    assert migration.version_path == expected_location


def test_migration_version_packages_do_not_assume_generated_history() -> None:
    versions_root = resources.files("migrations").joinpath("versions")

    assert not versions_root.joinpath("0001_migration.py").is_file()
    assert versions_root.joinpath("default").is_dir()
    assert versions_root.joinpath("mainsequence_markets").is_dir()
    assert versions_root.joinpath("mainsequence_examples").is_dir()


def test_migration_provider_filters_unrelated_tables() -> None:
    asset_table_name = AssetTable.__table__.name

    assert migration.include_name(asset_table_name, "table", {"schema_name": None})
    assert migration.include_name(
        asset_table_name,
        "table",
        {"schema_name": MARKETS_DEFAULT_SCHEMA},
    )
    assert not migration.include_name("unrelated_table", "table", {"schema_name": None})
    assert migration.include_name("unrelated_index", "index", {"schema_name": None})


def test_default_postgres_schema_is_authored_as_none() -> None:
    assert normalize_metatable_schema(None) is None
    assert normalize_metatable_schema("") is None
    assert normalize_metatable_schema(" public ") is None
    assert normalize_metatable_schema(MARKETS_DEFAULT_SCHEMA) is None
    assert normalize_metatable_schema("analytics") == "analytics"
    assert "schema" not in markets_table_args("Example")[-1]


def test_platform_managed_migration_metadata_uses_default_schema_not_explicit_public() -> None:
    row_tables = [
        model.__table__
        for model in metatable_provider_models()
        if not issubclass(model, PlatformTimeIndexMetaTable)
    ]

    assert row_tables
    assert all(table.schema is None for table in row_tables)


def test_markets_time_index_mixin_uses_sdk_table_contract_validation() -> None:
    class TestBase(DeclarativeBase):
        metadata = MetaData()

    with pytest.raises(
        ValueError,
        match="PlatformTimeIndexMetaTable index_names must all exist as table columns",
    ):

        class BrokenTimeIndexStorage(MarketsTimeIndexMetaTableMixin, TestBase):
            __metatable_identifier__ = "BrokenTimeIndexStorage"
            __time_index_name__ = "time_index"
            __index_names__ = ["time_index", "missing_identifier"]

            time_index: Mapped[dt.datetime] = mapped_column(
                DateTime(timezone=True),
                nullable=False,
            )


def test_migration_metadata_uses_deterministic_bounded_names() -> None:
    tables = list(migration.target_metadata.tables.values())
    foreign_keys = [
        constraint
        for table in tables
        for constraint in table.constraints
        if constraint.__class__.__name__ == "ForeignKeyConstraint"
    ]
    primary_keys = [
        constraint
        for table in tables
        for constraint in table.constraints
        if constraint.__class__.__name__ == "PrimaryKeyConstraint"
    ]
    indexes = [index for table in tables for index in table.indexes]
    schema_names = [
        *(constraint.name for constraint in foreign_keys),
        *(constraint.name for constraint in primary_keys),
        *(index.name for index in indexes),
    ]

    assert foreign_keys
    assert all(constraint.name is not None for constraint in foreign_keys)
    assert all(constraint.name is not None for constraint in primary_keys)
    assert all(index.name is not None for index in indexes)
    assert all(len(name) <= POSTGRES_IDENTIFIER_MAX_LENGTH for name in schema_names)
    assert len([index.name for index in indexes]) == len({index.name for index in indexes})


def test_account_holdings_single_and_composite_indexes_have_distinct_names() -> None:
    from msm.models.accounts.core import AccountHoldingsSetTable

    indexes_by_columns = {
        tuple(column.name for column in index.columns): index
        for index in AccountHoldingsSetTable.__table__.indexes
    }

    assert (
        indexes_by_columns[("account_uid",)].name
        != indexes_by_columns[("account_uid", "time_index")].name
    )


def test_alembic_env_normalizes_default_schema_reflection() -> None:
    env_text = Path("src/migrations/env.py").read_text(encoding="utf-8")

    assert "run_mainsequence_alembic_env" in env_text
    assert "def _included_schema" in env_text
    assert "engine_from_config" not in env_text
    assert "run_migrations_online" not in env_text


def test_package_migration_registry_covers_all_markets_subpackages() -> None:
    model_names = {model.__name__ for model in metatable_provider_models()}

    assert "AssetTable" in model_names
    assert "PortfolioTable" in model_names
    assert "CurveTable" in model_names
    assert "OrdersStorage" in model_names
    assert "OrderEventsStorage" in model_names
    assert "TradesStorage" in model_names
    assert "ExecutionErrorTable" not in model_names
    assert "OrderTargetQuantityTable" not in model_names


def test_portfolios_and_pricing_do_not_define_separate_migration_providers() -> None:
    assert not Path("src/msm_portfolios/migrations").exists()
    assert not Path("src/msm_pricing/migrations").exists()


def test_package_migration_registry_is_deduplicated_and_sdk_managed() -> None:
    models = metatable_provider_models()
    identifiers = [model.__metatable_identifier__ for model in models]

    assert len(identifiers) == len(set(identifiers))
    assert all(issubclass(model, MarketsBase) for model in models)
    assert all(
        issubclass(model, (PlatformManagedMetaTable, PlatformTimeIndexMetaTable))
        for model in models
    )
