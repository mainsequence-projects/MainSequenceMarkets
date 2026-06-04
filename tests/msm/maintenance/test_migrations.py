from __future__ import annotations

from importlib import resources
from pathlib import Path
from types import SimpleNamespace

from mainsequence.client.metatables import MetaTable
from mainsequence.meta_tables import (
    POSTGRES_IDENTIFIER_MAX_LENGTH,
    PlatformManagedMetaTable,
    PlatformTimeIndexMetaData,
)
from mainsequence.meta_tables.migrations import (
    AlembicMetaTableCatalogRefreshContext,
    AlembicMetaTableMigration,
    load_alembic_metatable_migration_provider,
)

from msm.base import MARKETS_SCHEMA, MARKETS_TABLE_APP, MarketsBase, markets_table_name
from msm.maintenance.catalog import SDK_MIGRATION_UPGRADE_COMMAND
from msm.maintenance.models import MarketsMetaTableCatalogTable
from msm.migrations import MarketsAlembicVersion, migration
from msm.migrations.registry import metatable_provider_models
from msm.settings import markets_identifier, markets_namespace


def test_migration_provider_is_single_sdk_alembic_provider() -> None:
    assert isinstance(migration, AlembicMetaTableMigration)
    assert migration.package == "msm"
    assert migration.script_location == "msm:migrations"
    assert migration.target_metadata is MarketsBase.metadata
    assert migration.alembic_registry is MarketsAlembicVersion
    assert MarketsAlembicVersion.__metatable_namespace__ == markets_namespace()
    assert MarketsAlembicVersion.__metatable_identifier__ == markets_identifier(
        "msm.alembic_version"
    )
    assert migration.version_table == markets_table_name(MARKETS_TABLE_APP, "alembic_version")
    assert migration.version_table_schema == MARKETS_SCHEMA
    assert migration.alembic_version_table == (
        f"{MARKETS_SCHEMA}.{markets_table_name(MARKETS_TABLE_APP, 'alembic_version')}"
    )
    assert migration.after_register_metatables is not None
    assert (
        migration.after_register_metatables.__name__
        == "refresh_markets_catalog_from_registered_metatables"
    )
    assert list(migration.metatable_models) == metatable_provider_models()


def test_migration_upgrade_command_uses_current_sdk_flags() -> None:
    assert SDK_MIGRATION_UPGRADE_COMMAND == (
        "mainsequence migrations upgrade --provider msm.migrations:migration head"
    )
    assert "--register-metatables" not in SDK_MIGRATION_UPGRADE_COMMAND
    assert "--apply" not in SDK_MIGRATION_UPGRADE_COMMAND


def test_sdk_loader_resolves_msm_migration_provider() -> None:
    loaded = load_alembic_metatable_migration_provider("msm.migrations:migration")

    assert loaded is migration


def test_migration_script_template_is_packaged() -> None:
    template = resources.files("msm.migrations").joinpath("script.py.mako")

    assert template.is_file()
    template_text = template.read_text(encoding="utf-8")
    assert "revision: str = ${repr(up_revision)}" in template_text
    assert "def upgrade() -> None:" in template_text
    assert "def downgrade() -> None:" in template_text


def test_migration_provider_filters_unrelated_tables() -> None:
    catalog_table_name = MarketsMetaTableCatalogTable.__table__.name

    assert migration.include_name(catalog_table_name, "table", {"schema_name": MARKETS_SCHEMA})
    assert not migration.include_name("unrelated_table", "table", {"schema_name": MARKETS_SCHEMA})
    assert migration.include_name("unrelated_index", "index", {"schema_name": MARKETS_SCHEMA})


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


def test_alembic_env_uses_schema_aware_reflection() -> None:
    env_text = Path("src/msm/migrations/env.py").read_text(encoding="utf-8")

    assert '"include_schemas": True' in env_text
    assert "def _included_schema" in env_text
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
        issubclass(model, (PlatformManagedMetaTable, PlatformTimeIndexMetaData)) for model in models
    )


def test_refresh_catalog_hook_upserts_registered_metatables(monkeypatch) -> None:
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
    upserts: list[dict[str, object]] = []

    monkeypatch.setitem(
        refresh_hook.__globals__,
        "catalog_repository_context",
        lambda *, catalog_meta_table, reserved_policy=None: SimpleNamespace(
            catalog_meta_table=catalog_meta_table,
            reserved_policy=reserved_policy,
        ),
    )

    def fake_upsert_catalog_row(
        context,
        *,
        model,
        meta_table,
        contract_hash=None,
    ):
        upsert = {
            "context": context,
            "model": model,
            "meta_table": meta_table,
            "contract_hash": contract_hash,
        }
        upserts.append(upsert)
        return {
            "table_name": model.__table__.name,
            "meta_table_uid": meta_table.uid,
        }

    monkeypatch.setitem(
        refresh_hook.__globals__,
        "upsert_catalog_row",
        fake_upsert_catalog_row,
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
    assert upserts[0]["model"] is MarketsMetaTableCatalogTable
    assert upserts[0]["meta_table"] is metatables[0]
    assert upserts[0]["context"].reserved_policy == "reconcile"
    assert rows[0]["table_name"] == MarketsMetaTableCatalogTable.__table__.name
