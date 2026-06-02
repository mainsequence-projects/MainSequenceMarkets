from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mainsequence.meta_tables import PlatformManagedMetaTable, PlatformTimeIndexMetaData
from mainsequence.meta_tables.migrations import (
    AlembicMetaTableMigration,
    load_alembic_metatable_migration_provider,
)

from msm.base import MARKETS_SCHEMA, MarketsBase
from msm.maintenance.catalog import SDK_MIGRATION_UPGRADE_COMMAND
from msm.maintenance.models import MarketsMetaTableCatalogTable
from msm.migrations import MarketsAlembicVersion, migration
from msm.migrations.registry import migration_model_registry


def test_migration_provider_is_single_sdk_alembic_provider() -> None:
    assert isinstance(migration, AlembicMetaTableMigration)
    assert migration.package == "msm"
    assert migration.script_location == "msm:migrations"
    assert migration.target_metadata is MarketsBase.metadata
    assert migration.alembic_registry is MarketsAlembicVersion
    assert migration.version_table == "msm_alembic_version"
    assert migration.version_table_schema == MARKETS_SCHEMA
    assert migration.alembic_version_table == f"{MARKETS_SCHEMA}.msm_alembic_version"
    assert migration.after_register_metatables is not None
    assert (
        migration.after_register_metatables.__name__
        == "refresh_markets_catalog_from_registered_metatables"
    )
    assert list(migration.metatable_models) == migration_model_registry()


def test_migration_upgrade_command_uses_current_sdk_flags() -> None:
    assert SDK_MIGRATION_UPGRADE_COMMAND == (
        "mainsequence migrations upgrade --provider msm.migrations:migration --to head"
    )
    assert "--register-metatables" not in SDK_MIGRATION_UPGRADE_COMMAND
    assert "--apply" not in SDK_MIGRATION_UPGRADE_COMMAND


def test_sdk_loader_resolves_msm_migration_provider() -> None:
    loaded = load_alembic_metatable_migration_provider("msm.migrations:migration")

    assert loaded is migration


def test_migration_provider_filters_unrelated_tables() -> None:
    catalog_table_name = MarketsMetaTableCatalogTable.__table__.name

    assert migration.include_name(catalog_table_name, "table", {"schema_name": MARKETS_SCHEMA})
    assert not migration.include_name("unrelated_table", "table", {"schema_name": MARKETS_SCHEMA})
    assert migration.include_name("unrelated_index", "index", {"schema_name": MARKETS_SCHEMA})


def test_package_migration_registry_covers_all_markets_subpackages() -> None:
    model_names = {model.__name__ for model in migration_model_registry()}

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
    models = migration_model_registry()
    identifiers = [model.__metatable_identifier__ for model in models]

    assert len(identifiers) == len(set(identifiers))
    assert all(issubclass(model, MarketsBase) for model in models)
    assert all(
        issubclass(model, (PlatformManagedMetaTable, PlatformTimeIndexMetaData))
        for model in models
    )


def test_refresh_catalog_hook_upserts_registered_metatables(monkeypatch) -> None:
    refresh_hook = migration.after_register_metatables
    assert refresh_hook is not None
    models = migration_model_registry()
    metatables = [
        SimpleNamespace(
            uid=f"meta-table-{index}",
            identifier=model.__metatable_identifier__,
            namespace=getattr(model, "__metatable_namespace__", None),
            physical_table_name=f"physical_table_{index}",
        )
        for index, model in enumerate(models)
    ]
    upserts: list[dict[str, object]] = []

    monkeypatch.setitem(
        refresh_hook.__globals__,
        "catalog_repository_context",
        lambda *, catalog_meta_table, timeout=None: SimpleNamespace(
            catalog_meta_table=catalog_meta_table,
            timeout=timeout,
        ),
    )

    def fake_upsert_catalog_row(context, *, model, meta_table, contract_hash=None):
        upsert = {
            "context": context,
            "model": model,
            "meta_table": meta_table,
            "contract_hash": contract_hash,
        }
        upserts.append(upsert)
        return {
            "identifier": model.__metatable_identifier__,
            "meta_table_uid": meta_table.uid,
        }

    monkeypatch.setitem(refresh_hook.__globals__, "upsert_catalog_row", fake_upsert_catalog_row)

    rows = refresh_hook(metatables)

    assert len(rows) == len(models)
    assert upserts[0]["model"] is MarketsMetaTableCatalogTable
    assert upserts[0]["meta_table"] is metatables[0]
    assert rows[0]["identifier"] == MarketsMetaTableCatalogTable.__metatable_identifier__
