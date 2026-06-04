from __future__ import annotations

import datetime as dt
from importlib import resources
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mainsequence.client.metatables import MetaTable
from mainsequence.meta_tables import (
    POSTGRES_IDENTIFIER_MAX_LENGTH,
    PlatformManagedMetaTable,
    PlatformTimeIndexMetaTable,
)
from mainsequence.meta_tables.migrations import (
    AlembicMetaTableCatalogRefreshContext,
    AlembicMetaTableMigration,
    load_alembic_metatable_migration_provider,
)

from msm.base import (
    MARKETS_DEFAULT_SCHEMA,
    MARKETS_SCHEMA,
    MARKETS_TABLE_APP,
    MarketsBase,
    MarketsTimeIndexMetaTableMixin,
    markets_table_args,
    markets_table_name,
    normalize_metatable_schema,
)
from msm.maintenance.catalog import SDK_MIGRATION_UPGRADE_COMMAND
from msm.maintenance.models import MarketsMetaTableCatalogTable
from migrations import (
    MarketsAlembicVersion,
    active_namespace_version_location,
    migration,
    namespace_version_slug,
)
from migrations.registry import metatable_provider_models
from msm.settings import markets_identifier, markets_namespace


def test_migration_provider_is_single_sdk_alembic_provider() -> None:
    assert isinstance(migration, AlembicMetaTableMigration)
    assert migration.package == "msm"
    assert migration.script_location == "migrations:"
    assert migration.target_metadata is MarketsBase.metadata
    assert migration.alembic_registry is MarketsAlembicVersion
    assert MarketsAlembicVersion.__metatable_namespace__ == markets_namespace()
    assert MarketsAlembicVersion.__metatable_identifier__ == markets_identifier(
        "msm.alembic_version"
    )
    assert migration.version_table == markets_table_name(MARKETS_TABLE_APP, "alembic_version")
    assert MARKETS_SCHEMA is None
    assert migration.version_table_schema is None
    assert migration.alembic_version_table == markets_table_name(
        MARKETS_TABLE_APP, "alembic_version"
    )
    assert migration.after_register_metatables is not None
    assert (
        migration.after_register_metatables.__name__
        == "refresh_markets_catalog_from_registered_metatables"
    )
    assert list(migration.metatable_models) == metatable_provider_models()


def test_migration_upgrade_command_uses_current_sdk_flags() -> None:
    assert SDK_MIGRATION_UPGRADE_COMMAND == (
        "mainsequence migrations upgrade --provider migrations:migration head"
    )
    assert "--register-metatables" not in SDK_MIGRATION_UPGRADE_COMMAND
    assert "--apply" not in SDK_MIGRATION_UPGRADE_COMMAND


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


def test_active_namespace_version_location_uses_migrations_package() -> None:
    assert active_namespace_version_location().startswith("migrations:versions/")


def test_existing_revisions_live_under_mainsequence_examples_namespace() -> None:
    versions_root = resources.files("migrations").joinpath("versions")
    namespace_versions = versions_root.joinpath("mainsequence_examples")

    assert not versions_root.joinpath("0001_migration.py").is_file()
    assert versions_root.joinpath("default").is_dir()
    assert namespace_versions.is_dir()
    assert namespace_versions.joinpath("0001_migration.py").is_file()
    assert namespace_versions.joinpath("0002_migration.py").is_file()
    assert namespace_versions.joinpath("0003_migration.py").is_file()
    assert namespace_versions.joinpath("0004_migration.py").is_file()


def test_migration_provider_filters_unrelated_tables() -> None:
    catalog_table_name = MarketsMetaTableCatalogTable.__table__.name

    assert migration.include_name(catalog_table_name, "table", {"schema_name": None})
    assert migration.include_name(
        catalog_table_name,
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

    assert '"include_schemas": _uses_named_schemas()' in env_text
    assert "def _included_schema" in env_text
    assert "def _uses_named_schemas" in env_text
    assert 'type_ == "schema"' in env_text


def test_package_migration_registry_covers_all_markets_subpackages() -> None:
    model_names = {model.__name__ for model in metatable_provider_models()}

    assert "MarketsMetaTableCatalogTable" in model_names
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
        issubclass(model, (PlatformManagedMetaTable, PlatformTimeIndexMetaTable)) for model in models
    )


def test_refresh_catalog_hook_bulk_upserts_registered_metatables(monkeypatch) -> None:
    refresh_hook = migration.after_register_metatables
    assert refresh_hook is not None
    models = metatable_provider_models()
    metatables = [
        MetaTable.model_construct(
            uid=f"meta-table-{index}",
            identifier=model.__table__.name,
            storage_hash=f"storage_hash_{index}",
            physical_table_name=model.__table__.name,
            namespace=markets_namespace(),
            description=model.__metatable_description__,
            management_mode="platform_managed",
            provisioning_status="active",
        )
        for index, model in enumerate(models)
    ]
    bulk_upserts: list[dict[str, object]] = []

    monkeypatch.setitem(
        refresh_hook.__globals__,
        "catalog_repository_context",
        lambda *, catalog_meta_table, reserved_policy=None: SimpleNamespace(
            catalog_meta_table=catalog_meta_table,
            reserved_policy=reserved_policy,
        ),
    )

    def fake_upsert_catalog_row(*_args, **_kwargs):
        raise AssertionError("Catalog refresh must bulk upsert rows, not upsert row by row.")

    def fake_bulk_upsert_model(
        context,
        *,
        model,
        values,
        conflict_columns,
    ):
        bulk_upsert = {
            "context": context,
            "model": model,
            "values": values,
            "conflict_columns": conflict_columns,
        }
        bulk_upserts.append(bulk_upsert)
        return {
            "rows": [
                {
                    "table_name": row["table_name"],
                    "meta_table_uid": row["meta_table_uid"],
                }
                for row in values
            ]
        }

    monkeypatch.setitem(
        refresh_hook.__globals__,
        "upsert_catalog_row",
        fake_upsert_catalog_row,
    )
    monkeypatch.setitem(
        refresh_hook.__globals__,
        "bulk_upsert_model",
        fake_bulk_upsert_model,
    )

    rows = refresh_hook(
        AlembicMetaTableCatalogRefreshContext(
            package="msm",
            migration_namespace=markets_namespace(),
            registered_metatables=metatables,
            reserved_policy="reconcile",
        )
    )

    assert len(rows) == len(models)
    assert len(bulk_upserts) == 1
    bulk_upsert = bulk_upserts[0]
    assert bulk_upsert["model"] is MarketsMetaTableCatalogTable
    assert bulk_upsert["conflict_columns"] == ["table_name"]
    assert bulk_upsert["context"].reserved_policy == "reconcile"
    values = bulk_upsert["values"]
    assert len(values) == len(models)
    assert values[0]["table_name"] == MarketsMetaTableCatalogTable.__table__.name
    assert values[0]["meta_table_uid"] == metatables[0].uid
    assert rows[0]["table_name"] == MarketsMetaTableCatalogTable.__table__.name
