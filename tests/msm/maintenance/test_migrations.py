from __future__ import annotations

from types import SimpleNamespace

import msm.maintenance.migrations as migrations
from msm.migrations.registry import migration_model_registry


class FakeAffectedTable:
    def __init__(self, **kwargs) -> None:
        self.payload = dict(kwargs)

    def model_dump(self, **_kwargs):
        return dict(self.payload)


class FakeSchemaOperation:
    def __init__(self, **kwargs) -> None:
        self.payload = dict(kwargs)

    def model_dump(self, **_kwargs):
        return dict(self.payload)


class FakeManifest:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)

    def model_dump(self, **_kwargs):
        payload = dict(self.__dict__)
        payload["affected_tables"] = [
            affected.model_dump() for affected in payload.get("affected_tables", [])
        ]
        payload["operations"] = [
            operation.model_dump() if hasattr(operation, "model_dump") else operation
            for operation in payload.get("operations", [])
        ]
        return payload


class FakePackagedMigration:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


def fake_sdk():
    return SimpleNamespace(
        MetaTableMigrationAffectedTable=FakeAffectedTable,
        MetaTableMigrationManifest=FakeManifest,
        MetaTableMigrationSchemaOperation=FakeSchemaOperation,
        PackagedMetaTableMigration=FakePackagedMigration,
        contract_hash=lambda contract: f"hash-{contract['identifier']}",
        contract_hashes_from_models=lambda models: {
            identifier: f"hash-{identifier}" for identifier in models
        },
        contracts_from_models=lambda models, target_meta_tables=None: {
            identifier: {"identifier": identifier} for identifier in models
        },
        sha256_payload=lambda value: f"payload-sha-{len(value)}",
        sha256_text=lambda value: f"sha-{len(value)}",
    )


def test_load_migration_specs_uses_package_registry() -> None:
    specs = migrations.load_migration_specs()

    assert [spec.revision for spec in specs] == ["0001_initial"]
    assert specs[0].affected_models == migration_model_registry()
    assert specs[0].operations


def test_materialize_migrations_loads_python_modules(monkeypatch) -> None:
    monkeypatch.setattr(migrations, "_sdk_migrations", fake_sdk)

    materialized = migrations.materialize_migrations(namespace="mainsequence.examples")

    assert [item.spec.revision for item in materialized] == ["0001_initial"]
    assert materialized[0].packaged.sql == ""
    assert materialized[0].packaged.operations_sha256.startswith("payload-sha-")


def test_status_reaches_expected_revision_accepts_later_package_revision(monkeypatch) -> None:
    specs = [
        SimpleNamespace(revision="0001_initial"),
        SimpleNamespace(revision="0002_add_asset_status"),
    ]
    monkeypatch.setattr(migrations, "load_migration_specs", lambda: specs)
    status = SimpleNamespace(current_revision="0002_add_asset_status")

    assert migrations._status_reaches_expected_revision(status, ["0001_initial"]) is True


def test_sync_data_source_kwargs_do_not_resolve_session_data_source() -> None:
    assert migrations._sync_data_source_kwargs(None) == {}
    assert migrations._sync_data_source_kwargs("data-source-uid") == {
        "data_source_uid": "data-source-uid"
    }


def test_build_packaged_migration_uses_python_operations_only(monkeypatch) -> None:
    monkeypatch.setattr(migrations, "_sdk_migrations", fake_sdk)
    model = migration_model_registry()[0]
    spec = migrations.MigrationSpec(
        module_name="test",
        revision="0002_add_column",
        expected_current_revision=None,
        migration_namespace=None,
        operations=[
            {
                "op": "add_column",
                "table_identifier": getattr(model, "__metatable_identifier__"),
                "column": {"name": "status", "data_type": "str", "nullable": True},
            }
        ],
        affected_models=[model],
        old_contract_hashes={},
    )

    packaged = migrations._build_packaged_migration(
        fake_sdk(),
        spec,
        migration_namespace="mainsequence.examples",
    )

    assert packaged.manifest.migration_namespace == "mainsequence.examples"
    assert packaged.manifest.revision == "0002_add_column"
    assert [operation.model_dump() for operation in packaged.manifest.operations] == spec.operations
    assert packaged.manifest.affected_tables
    assert packaged.sql_sha256.startswith("sha-")
    assert packaged.sql == ""
    assert packaged.operations_sha256.startswith("payload-sha-")


def test_finalize_catalog_from_apply_response_upserts_affected_model(monkeypatch) -> None:
    model = migration_model_registry()[0]
    spec = migrations.MigrationSpec(
        module_name="test",
        revision="0001_initial",
        expected_current_revision=None,
        migration_namespace=None,
        operations=[
            {
                "op": "add_column",
                "table_identifier": getattr(model, "__metatable_identifier__"),
                "column": {"name": "uid", "data_type": "uuid", "nullable": False},
            }
        ],
        affected_models=[model],
        old_contract_hashes={},
    )
    materialized = migrations.MaterializedMigration(
        spec=spec,
        packaged=SimpleNamespace(),
    )
    upserts = []

    monkeypatch.setattr(
        migrations,
        "bootstrap_catalog_table",
        lambda timeout=None: SimpleNamespace(uid="catalog-uid", namespace="msm"),
    )
    monkeypatch.setattr(
        migrations,
        "catalog_repository_context",
        lambda catalog_meta_table, timeout=None: SimpleNamespace(
            catalog_meta_table=catalog_meta_table
        ),
    )

    def fake_upsert_catalog_row(context, *, model, meta_table, contract_hash=None):
        upserts.append(
            {
                "context": context,
                "model": model,
                "meta_table_uid": meta_table.uid,
                "identifier": meta_table.identifier,
                "contract_hash": contract_hash,
            }
        )
        return {"identifier": meta_table.identifier}

    monkeypatch.setattr(migrations, "upsert_catalog_row", fake_upsert_catalog_row)
    response = SimpleNamespace(
        ok=True,
        status="applied",
        revision="0001_initial",
        affected_tables=[
            SimpleNamespace(
                identifier=getattr(model, "__metatable_identifier__"),
                meta_table_uid="meta-table-uid",
                physical_table_name="physical_table",
                storage_hash="storage_hash",
            )
        ]
    )

    rows = migrations.finalize_catalog_from_apply_response(
        response,
        materialized=materialized,
    )

    assert rows == [{"identifier": getattr(model, "__metatable_identifier__")}]
    assert upserts == [
        {
            "context": SimpleNamespace(
                catalog_meta_table=SimpleNamespace(uid="catalog-uid", namespace="msm")
            ),
            "model": model,
            "meta_table_uid": "meta-table-uid",
            "identifier": getattr(model, "__metatable_identifier__"),
            "contract_hash": None,
        }
    ]
