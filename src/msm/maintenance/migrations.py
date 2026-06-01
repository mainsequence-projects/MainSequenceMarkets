from __future__ import annotations

import importlib
import json
import pkgutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

from mainsequence.client.models_metatables import MetaTable
from mainsequence.logconf import logger as _mainsequence_logger

from msm.base import MarketsBase, markets_meta_table_identifier
from msm.migrations.registry import migration_model_registry
from msm.models.registration import (
    MarketsModelSelector,
    is_time_index_meta_table_model,
    resolve_markets_meta_table_model,
)
from msm.settings import markets_namespace

from .catalog import (
    CatalogBootstrapError,
    bootstrap_catalog_table,
    catalog_repository_context,
    find_catalog_rows_by_identifier,
    resolve_catalog_table,
    upsert_catalog_row,
    validate_catalog_contract,
)
from .models import MarketsMigrationTable


MIGRATION_PACKAGE = "msm"
MIGRATION_VERSIONS_PACKAGE = "msm.migrations.versions"
logger = _mainsequence_logger.bind(sub_application="markets", component="migrations")


class MigrationSupportError(RuntimeError):
    """Raised when the installed SDK cannot run MetaTable migrations."""


class MigrationStateError(RuntimeError):
    """Raised when runtime startup sees missing or stale migration state."""


@dataclass(frozen=True)
class MigrationSpec:
    module_name: str
    revision: str
    expected_current_revision: str | None
    migration_namespace: str | None
    operations: list[dict[str, Any]]
    affected_models: list[type[MarketsBase]]
    old_contract_hashes: dict[str, str]

    @property
    def identifiers(self) -> list[str]:
        return [markets_meta_table_identifier(model) for model in self.affected_models]

    def to_payload(self) -> dict[str, Any]:
        return {
            "module": self.module_name,
            "revision": self.revision,
            "expected_current_revision": self.expected_current_revision,
            "migration_namespace": self.migration_namespace,
            "operations": list(self.operations),
            "affected_identifiers": self.identifiers,
            "old_contract_hashes": dict(self.old_contract_hashes),
        }


@dataclass(frozen=True)
class MaterializedMigration:
    spec: MigrationSpec
    packaged: Any

    def to_payload(self) -> dict[str, Any]:
        manifest = _model_dump(getattr(self.packaged, "manifest", {}))
        return {
            **self.spec.to_payload(),
            "manifest_sha256": getattr(self.packaged, "manifest_sha256", None),
            "sql_sha256": getattr(self.packaged, "sql_sha256", None),
            "manifest": manifest,
        }


@dataclass(frozen=True)
class MigrationCommandResult:
    command: str
    migration_namespace: str
    expected_revisions: list[str]
    migration_registry_uid: str | None
    status: Any | None
    synced: list[Any]
    applied: list[Any]
    skipped: list[str]
    catalog_rows: list[dict[str, Any]]
    catalog_status: list[dict[str, Any]]
    ok: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "migration_namespace": self.migration_namespace,
            "expected_revisions": list(self.expected_revisions),
            "migration_registry_uid": self.migration_registry_uid,
            "status": _model_dump(self.status) if self.status is not None else None,
            "synced": [_sync_payload(item) for item in self.synced],
            "applied": [_model_dump(item) for item in self.applied],
            "skipped": list(self.skipped),
            "catalog_rows": [dict(row) for row in self.catalog_rows],
            "catalog_status": [dict(row) for row in self.catalog_status],
            "ok": self.ok,
        }


def load_migration_specs() -> list[MigrationSpec]:
    """Load packaged Python migration modules in revision order."""

    versions_package = importlib.import_module(MIGRATION_VERSIONS_PACKAGE)
    package_path = getattr(versions_package, "__path__", None)
    if package_path is None:
        raise MigrationSupportError(f"{MIGRATION_VERSIONS_PACKAGE} is not a package.")

    specs = [
        _migration_spec_from_module(importlib.import_module(module_info.name))
        for module_info in pkgutil.iter_modules(
            package_path,
            prefix=f"{MIGRATION_VERSIONS_PACKAGE}.",
        )
        if not module_info.ispkg
    ]
    return sorted(specs, key=lambda spec: spec.revision)


def materialize_migrations(
    *,
    namespace: str | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> list[MaterializedMigration]:
    """Build SDK packaged migration payloads from Python migration modules."""

    sdk = _sdk_migrations()
    migration_namespace = markets_namespace(namespace)
    scope_identifiers = _scope_identifiers(models)
    return [
        MaterializedMigration(
            spec=spec,
            packaged=_build_packaged_migration(
                sdk,
                spec,
                migration_namespace=migration_namespace,
            ),
        )
        for spec in load_migration_specs()
        if scope_identifiers is None or scope_identifiers.intersection(spec.identifiers)
    ]


def current_migrations(
    *,
    data_source_uid: str | None = None,
    namespace: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> MigrationCommandResult:
    """Read expected package migrations, SDK status, and catalog finalization state."""

    _validate_migration_model_registry()
    migration_namespace = markets_namespace(namespace)
    materialized = materialize_migrations(namespace=namespace, models=models)
    scoped_models = _migration_scope(models)
    migration_meta_table = resolve_migration_registry_meta_table(
        create=False,
        timeout=timeout,
    )
    status = None
    if migration_meta_table is not None:
        status = _sdk_migrations().get_migration_status(
            migration_meta_table,
            package=MIGRATION_PACKAGE,
            migration_namespace=migration_namespace,
            data_source_uid=resolved_data_source_uid,
            timeout=timeout,
        )
    catalog_status = _catalog_status(timeout=timeout, models=scoped_models)
    expected_revisions = [item.spec.revision for item in materialized]
    ok = _current_state_ok(
        status=status,
        expected_revisions=expected_revisions,
        migration_meta_table=migration_meta_table,
        catalog_status=catalog_status,
        scoped_models=scoped_models,
    )
    return MigrationCommandResult(
        command="current",
        migration_namespace=migration_namespace,
        expected_revisions=expected_revisions,
        migration_registry_uid=getattr(migration_meta_table, "uid", None),
        status=status,
        synced=[],
        applied=[],
        skipped=[],
        catalog_rows=[],
        catalog_status=catalog_status,
        ok=ok,
    )


def sync_migrations(
    *,
    data_source_uid: str | None = None,
    namespace: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MigrationCommandResult:
    """Register/sync packaged migration rows into the SDK MigrationMetaTable."""

    sdk = _sdk_migrations()
    _validate_migration_model_registry(sdk=sdk)
    migration_namespace = markets_namespace(namespace)
    materialized_migrations = materialize_migrations(namespace=namespace)
    _ensure_packaged_migrations_exist(materialized_migrations)
    synced: list[Any] = []
    for materialized in materialized_migrations:
        synced.append(
            sdk.sync_packaged_migration(
                MarketsMigrationTable,
                materialized.packaged,
                **_sync_data_source_kwargs(data_source_uid),
                timeout=timeout,
            )
        )
    migration_meta_table = _first_synced_meta_table(
        synced
    ) or resolve_migration_registry_meta_table(
        create=False,
        timeout=timeout,
    )
    status = None
    if migration_meta_table is not None:
        status = sdk.get_migration_status(
            migration_meta_table,
            package=MIGRATION_PACKAGE,
            migration_namespace=migration_namespace,
            data_source_uid=data_source_uid,
            timeout=timeout,
        )
    return MigrationCommandResult(
        command="sync",
        migration_namespace=migration_namespace,
        expected_revisions=[item.spec.revision for item in materialized_migrations],
        migration_registry_uid=getattr(migration_meta_table, "uid", None),
        status=status,
        synced=synced,
        applied=[],
        skipped=[],
        catalog_rows=[],
        catalog_status=_catalog_status(timeout=timeout),
        ok=True,
    )


def upgrade_migrations(
    *,
    data_source_uid: str | None = None,
    namespace: str | None = None,
    dry_run: bool = False,
    timeout: int | float | tuple[float, float] | None = None,
) -> MigrationCommandResult:
    """Sync and apply packaged migrations, then finalize the markets catalog."""

    sdk = _sdk_migrations()
    _validate_migration_model_registry(sdk=sdk)
    materialized = materialize_migrations(namespace=namespace)
    _ensure_packaged_migrations_exist(materialized)
    migration_namespace = markets_namespace(namespace)
    sync_result = sync_migrations(
        data_source_uid=data_source_uid,
        namespace=namespace,
        timeout=timeout,
    )
    migration_meta_table = _first_synced_meta_table(sync_result.synced)
    if migration_meta_table is None:
        migration_meta_table = resolve_migration_registry_meta_table(
            create=False,
            timeout=timeout,
        )
    if migration_meta_table is None:
        raise MigrationStateError("Could not resolve synced markets migration registry table.")

    status = sdk.get_migration_status(
        migration_meta_table,
        package=MIGRATION_PACKAGE,
        migration_namespace=migration_namespace,
        data_source_uid=data_source_uid,
        timeout=timeout,
    )
    applied_revisions = _applied_revisions(status)
    applied: list[Any] = []
    skipped: list[str] = []
    catalog_rows: list[dict[str, Any]] = []
    materialized_by_revision = {item.spec.revision: item for item in materialized}

    for synced_item in sync_result.synced:
        row = synced_item.get("row") if isinstance(synced_item, Mapping) else None
        revision = _row_revision(row)
        if revision is None:
            raise MigrationStateError("Synced migration result did not include a revision row.")
        if revision in applied_revisions and not dry_run:
            skipped.append(revision)
            catalog_rows.extend(
                finalize_catalog_from_materialized_migration(
                    materialized_by_revision[revision],
                    timeout=timeout,
                )
            )
            continue

        response = sdk.apply_migration(
            migration_meta_table,
            row,
            dry_run=dry_run,
            timeout=timeout,
        )
        applied.append(response)
        if not dry_run:
            catalog_rows.extend(
                finalize_catalog_from_apply_response(
                    response,
                    materialized=materialized_by_revision[revision],
                    timeout=timeout,
                )
            )

    status = sdk.get_migration_status(
        migration_meta_table,
        package=MIGRATION_PACKAGE,
        migration_namespace=migration_namespace,
        data_source_uid=data_source_uid,
        timeout=timeout,
    )
    expected_revisions = [item.spec.revision for item in materialized]
    catalog_status = _catalog_status(timeout=timeout)
    ok = dry_run or _current_state_ok(
        status=status,
        expected_revisions=expected_revisions,
        migration_meta_table=migration_meta_table,
        catalog_status=catalog_status,
        scoped_models=_migration_scope(None),
    )
    return MigrationCommandResult(
        command="upgrade",
        migration_namespace=migration_namespace,
        expected_revisions=expected_revisions,
        migration_registry_uid=getattr(migration_meta_table, "uid", None),
        status=status,
        synced=sync_result.synced,
        applied=applied,
        skipped=skipped,
        catalog_rows=catalog_rows,
        catalog_status=catalog_status,
        ok=ok,
    )


def validate_migrations(
    *,
    data_source_uid: str | None = None,
    namespace: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> MigrationCommandResult:
    """Validate that SDK status and the finalized catalog match package code."""

    result = current_migrations(
        data_source_uid=data_source_uid,
        namespace=namespace,
        timeout=timeout,
        models=models,
    )
    if not result.ok:
        raise MigrationStateError(_current_error_message(result))
    return MigrationCommandResult(
        command="validate",
        migration_namespace=result.migration_namespace,
        expected_revisions=result.expected_revisions,
        migration_registry_uid=result.migration_registry_uid,
        status=result.status,
        synced=[],
        applied=[],
        skipped=[],
        catalog_rows=[],
        catalog_status=result.catalog_status,
        ok=True,
    )


def verify_runtime_migrations_current(
    *,
    data_source_uid: str | None = None,
    namespace: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> None:
    """Fail runtime startup unless admin migrations finalized the requested schema."""

    result = current_migrations(
        data_source_uid=data_source_uid,
        namespace=namespace,
        timeout=timeout,
        models=models,
    )
    if result.ok:
        return
    raise MigrationStateError(_current_error_message(result))


def resolve_migration_registry_meta_table(
    *,
    create: bool,
    timeout: int | float | tuple[float, float] | None = None,
) -> MetaTable | None:
    """Resolve the SDK migration registry MetaTable."""

    sdk = _sdk_migrations()
    if create:
        if not issubclass(MarketsMigrationTable, sdk.MigrationMetaTable):
            raise MigrationSupportError(
                "Installed Main Sequence SDK does not expose MigrationMetaTable."
            )
        return MarketsMigrationTable.register(timeout=timeout)

    matches = MetaTable.filter(
        identifier=getattr(MarketsMigrationTable, "__metatable_identifier__", None),
        namespace=getattr(MarketsMigrationTable, "__metatable_namespace__", None),
        management_mode="platform_managed",
        timeout=timeout,
    )
    if not matches:
        return None
    if len(matches) > 1:
        raise MigrationStateError(
            "Multiple markets migration registry MetaTables matched "
            f"{getattr(MarketsMigrationTable, '__metatable_identifier__', None)!r}."
        )
    return matches[0]


def finalize_catalog_from_apply_response(
    response: Any,
    *,
    materialized: MaterializedMigration,
    timeout: int | float | tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """Finalize the markets catalog for tables refreshed by a migration apply."""

    _validate_apply_response(response, materialized=materialized)
    catalog_meta_table = bootstrap_catalog_table(timeout=timeout)
    catalog_context = catalog_repository_context(
        catalog_meta_table=catalog_meta_table,
        timeout=timeout,
    )
    models_by_identifier = {
        markets_meta_table_identifier(model): model for model in materialized.spec.affected_models
    }
    expected_hashes = _manifest_new_contract_hashes(materialized)
    rows: list[dict[str, Any]] = []
    for affected in _affected_table_results(response):
        identifier = str(_field(affected, "identifier") or "")
        model = models_by_identifier.get(identifier)
        if model is None:
            raise MigrationStateError(
                "Migration apply response included unknown affected table "
                f"{identifier!r} for revision {materialized.spec.revision!r}."
            )
        meta_table_uid = _field(affected, "meta_table_uid")
        if meta_table_uid in (None, ""):
            raise MigrationStateError(
                "Migration apply response did not include a MetaTable UID for "
                f"affected identifier {identifier!r}."
            )
        expected_hash = expected_hashes.get(identifier)
        response_hash = _field(affected, "new_contract_hash")
        if expected_hash and response_hash and str(response_hash) != expected_hash:
            raise MigrationStateError(
                "Migration apply response contract hash mismatch for "
                f"{identifier!r}. Expected {expected_hash!r}, got {response_hash!r}."
            )
        meta_table = MetaTable(
            uid=str(meta_table_uid),
            namespace=getattr(model, "__metatable_namespace__", None),
            identifier=markets_meta_table_identifier(model),
            description=getattr(model, "__metatable_description__", None),
            management_mode="platform_managed",
            storage_hash=_field(affected, "storage_hash"),
            physical_table_name=_field(affected, "physical_table_name"),
        )
        rows.append(
            upsert_catalog_row(
                catalog_context,
                model=model,
                meta_table=meta_table,
                contract_hash=expected_hash or (str(response_hash) if response_hash else None),
            )
        )
    return rows


def finalize_catalog_from_materialized_migration(
    materialized: MaterializedMigration,
    *,
    timeout: int | float | tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """Finalize catalog rows for an already-applied SDK migration revision."""

    catalog_meta_table = bootstrap_catalog_table(timeout=timeout)
    catalog_context = catalog_repository_context(
        catalog_meta_table=catalog_meta_table,
        timeout=timeout,
    )
    expected_hashes = _manifest_new_contract_hashes(materialized)
    rows: list[dict[str, Any]] = []
    for model in materialized.spec.affected_models:
        identifier = markets_meta_table_identifier(model)
        meta_table = _resolve_platform_meta_table_for_migration(
            model,
            timeout=timeout,
        )
        rows.append(
            upsert_catalog_row(
                catalog_context,
                model=model,
                meta_table=meta_table,
                contract_hash=expected_hashes.get(identifier),
            )
        )
    return rows


def _migration_spec_from_module(module: ModuleType) -> MigrationSpec:
    revision = _required_module_text(module, "REVISION")
    old_contract_hashes = getattr(module, "OLD_CONTRACT_HASHES", {}) or {}
    if not isinstance(old_contract_hashes, Mapping):
        raise TypeError(f"{module.__name__}.OLD_CONTRACT_HASHES must be a mapping.")
    return MigrationSpec(
        module_name=module.__name__,
        revision=revision,
        expected_current_revision=_optional_module_text(module, "EXPECTED_CURRENT_REVISION"),
        migration_namespace=_optional_module_text(module, "MIGRATION_NAMESPACE"),
        operations=_operations_from_module(module),
        affected_models=_affected_models_from_module(module),
        old_contract_hashes={str(key): str(value) for key, value in old_contract_hashes.items()},
    )


def _affected_models_from_module(module: ModuleType) -> list[type[MarketsBase]]:
    provider = getattr(module, "affected_models", None)
    if callable(provider):
        raw_models = provider()
    else:
        raw_models = getattr(module, "AFFECTED_MODELS", None)
    if raw_models is None:
        raw_models = migration_model_registry()
    if not isinstance(raw_models, Sequence) or isinstance(raw_models, (str, bytes, bytearray)):
        raise TypeError(f"{module.__name__} affected models must be a sequence.")
    return [_resolve_migration_model(model) for model in raw_models]


def _operations_from_module(module: ModuleType) -> list[dict[str, Any]]:
    provider = getattr(module, "operations", None)
    if callable(provider):
        raw_operations = provider()
    else:
        raw_operations = getattr(module, "OPERATIONS", None)
    if raw_operations is None:
        raw_operations = []
    if not isinstance(raw_operations, Sequence) or isinstance(
        raw_operations, (str, bytes, bytearray)
    ):
        raise TypeError(f"{module.__name__} operations must be a sequence.")
    operations = [_model_dump(operation) for operation in raw_operations]
    if not all(isinstance(operation, Mapping) for operation in operations):
        raise TypeError(f"{module.__name__} operations must contain mapping payloads.")
    if not operations:
        raise ValueError(f"{module.__name__} must define at least one migration operation.")
    return [dict(operation) for operation in operations]


def _resolve_migration_model(model: MarketsModelSelector) -> type[MarketsBase]:
    if isinstance(model, type) and issubclass(model, MarketsBase):
        return model
    table_model = getattr(model, "__table__", None)
    if isinstance(table_model, type) and issubclass(table_model, MarketsBase):
        return table_model
    return resolve_markets_meta_table_model(model)


def _build_packaged_migration(
    sdk: SimpleNamespace,
    spec: MigrationSpec,
    *,
    migration_namespace: str,
) -> Any:
    model_by_identifier = {
        markets_meta_table_identifier(model): model for model in spec.affected_models
    }
    sdk.validate_migration_managed_models(model_by_identifier)
    target_meta_tables = _contract_target_meta_tables(model_by_identifier.values())
    new_contracts = sdk.contracts_from_models(
        model_by_identifier,
        target_meta_tables=target_meta_tables,
    )
    new_contract_hashes = {
        identifier: sdk.contract_hash(contract) for identifier, contract in new_contracts.items()
    }
    affected_tables = [
        sdk.MetaTableMigrationAffectedTable(
            identifier=identifier,
            namespace=getattr(model, "__metatable_namespace__", None),
        )
        for identifier, model in model_by_identifier.items()
    ]
    manifest = sdk.MetaTableMigrationManifest(
        package=MIGRATION_PACKAGE,
        migration_namespace=spec.migration_namespace or migration_namespace,
        revision=spec.revision,
        expected_current_revision=spec.expected_current_revision,
        operations=[
            sdk.MetaTableMigrationSchemaOperation(**operation) for operation in spec.operations
        ],
        affected_tables=affected_tables,
        old_contract_hashes=dict(spec.old_contract_hashes),
        new_contract_hashes=new_contract_hashes,
        new_contracts=new_contracts,
    )
    manifest_payload = manifest.model_dump(mode="json", exclude_none=True)
    manifest_text = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":"))
    return sdk.PackagedMetaTableMigration(
        package=MIGRATION_PACKAGE,
        manifest_path=f"python:{spec.module_name}",
        manifest=manifest,
        manifest_text=manifest_text,
        manifest_sha256=sdk.sha256_text(manifest_text),
        sql="",
        sql_sha256=sdk.sha256_text(""),
        operations_sha256=sdk.sha256_payload(
            [_model_dump(operation) for operation in getattr(manifest, "operations", [])]
        ),
    )


def _sdk_migrations() -> SimpleNamespace:
    try:
        import mainsequence.meta_tables.migrations as sdk
        from mainsequence.client.models_metatables import MetaTableMigrationAffectedTable
    except ImportError as exc:
        raise MigrationSupportError(
            "The installed Main Sequence SDK does not expose MetaTable migrations. "
            "Update `mainsequence` to a release that provides "
            "`mainsequence.meta_tables.migrations`."
        ) from exc

    required_names = [
        "MigrationMetaTable",
        "MetaTableMigrationManifest",
        "MetaTableMigrationSchemaOperation",
        "PackagedMetaTableMigration",
        "apply_migration",
        "contract_hash",
        "contract_hashes_from_models",
        "contracts_from_models",
        "get_migration_status",
        "sha256_payload",
        "sha256_text",
        "sync_packaged_migration",
        "validate_migration_managed_models",
    ]
    missing = [name for name in required_names if not hasattr(sdk, name)]
    if missing or not hasattr(MetaTable, "apply_migration"):
        raise MigrationSupportError(
            "The installed Main Sequence SDK is missing MetaTable migration support: "
            f"{missing!r}. Update `mainsequence` before running `msm migrations`."
        )
    return SimpleNamespace(
        MigrationMetaTable=sdk.MigrationMetaTable,
        MetaTableMigrationAffectedTable=MetaTableMigrationAffectedTable,
        MetaTableMigrationManifest=sdk.MetaTableMigrationManifest,
        MetaTableMigrationSchemaOperation=sdk.MetaTableMigrationSchemaOperation,
        PackagedMetaTableMigration=sdk.PackagedMetaTableMigration,
        apply_migration=sdk.apply_migration,
        contract_hash=sdk.contract_hash,
        contract_hashes_from_models=sdk.contract_hashes_from_models,
        contracts_from_models=sdk.contracts_from_models,
        get_migration_status=sdk.get_migration_status,
        sha256_payload=sdk.sha256_payload,
        sha256_text=sdk.sha256_text,
        sync_packaged_migration=sdk.sync_packaged_migration,
        validate_migration_managed_models=sdk.validate_migration_managed_models,
    )


def _migration_scope(
    models: Sequence[type[MarketsBase]] | None,
) -> list[type[MarketsBase]]:
    registry = migration_model_registry()
    if models is None:
        return registry
    registry_set = set(registry)
    return [model for model in models if model in registry_set]


def _scope_identifiers(
    models: Sequence[type[MarketsBase]] | None,
) -> set[str] | None:
    if models is None:
        return None
    return {markets_meta_table_identifier(model) for model in _migration_scope(models)}


def _sync_data_source_kwargs(data_source_uid: str | None = None) -> dict[str, str]:
    if data_source_uid in (None, ""):
        return {}
    return {"data_source_uid": str(data_source_uid)}


def _contract_target_meta_tables(
    models: Sequence[type[MarketsBase]],
) -> dict[type[MarketsBase], Any]:
    return {
        model: SimpleNamespace(uid=f"migration-target:{markets_meta_table_identifier(model)}")
        for model in models
    }


def _validate_migration_model_registry(sdk: SimpleNamespace | None = None) -> None:
    migration_sdk = sdk or _sdk_migrations()
    models = migration_model_registry()
    model_by_identifier = {markets_meta_table_identifier(model): model for model in models}
    migration_sdk.validate_migration_managed_models(model_by_identifier)


def _ensure_packaged_migrations_exist(materialized: Sequence[MaterializedMigration]) -> None:
    if migration_model_registry() and not materialized:
        raise MigrationStateError(
            "No packaged `msm` MetaTable migrations were found for a non-empty "
            "migration model registry."
        )


def _current_state_ok(
    *,
    status: Any | None,
    expected_revisions: Sequence[str],
    migration_meta_table: MetaTable | None,
    catalog_status: Sequence[Mapping[str, Any]],
    scoped_models: Sequence[type[MarketsBase]],
) -> bool:
    if not expected_revisions and scoped_models:
        return False
    return (
        migration_meta_table is not None
        and _status_reaches_expected_revision(status, expected_revisions)
        and len(catalog_status) == len(scoped_models)
        and all(item.get("status") == "current" for item in catalog_status)
    )


def _status_reaches_expected_revision(
    status: Any | None,
    expected_revisions: Sequence[str],
) -> bool:
    expected_revision = _last_or_none(expected_revisions)
    current_revision = _status_current_revision(status)
    if expected_revision is None:
        return current_revision is None
    if current_revision == expected_revision:
        return True
    if current_revision is None:
        return False

    revision_order = [spec.revision for spec in load_migration_specs()]
    try:
        return revision_order.index(current_revision) >= revision_order.index(expected_revision)
    except ValueError:
        return False


def _catalog_status(
    *,
    timeout: int | float | tuple[float, float] | None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> list[dict[str, Any]]:
    resolved_models = _migration_scope(models)
    identifiers = [markets_meta_table_identifier(model) for model in resolved_models]
    try:
        catalog_meta_table = resolve_catalog_table(timeout=timeout)
    except CatalogBootstrapError as exc:
        return [
            {
                "identifier": identifier,
                "kind": _migration_model_kind(model),
                "model_name": model.__name__,
                "status": "missing_catalog",
                "error": str(exc),
            }
            for identifier, model in zip(identifiers, resolved_models, strict=True)
        ]

    context = catalog_repository_context(
        catalog_meta_table=catalog_meta_table,
        timeout=timeout,
    )
    rows = find_catalog_rows_by_identifier(context, identifiers=identifiers)
    status: list[dict[str, Any]] = []
    for model, identifier in zip(resolved_models, identifiers, strict=True):
        row = rows.get(identifier)
        if row is None:
            status.append(
                {
                    "identifier": identifier,
                    "kind": _migration_model_kind(model),
                    "model_name": model.__name__,
                    "status": "missing_row",
                }
            )
            continue
        try:
            validate_catalog_contract(row, model=model)
        except CatalogBootstrapError as exc:
            status.append(
                {
                    "identifier": identifier,
                    "kind": _migration_model_kind(model),
                    "model_name": model.__name__,
                    "status": "stale_contract",
                    "error": str(exc),
                }
            )
            continue
        status.append(
            {
                "identifier": identifier,
                "kind": _migration_model_kind(model),
                "model_name": model.__name__,
                "status": "current",
                "meta_table_uid": row.get("meta_table_uid"),
                "contract_hash": row.get("contract_hash"),
            }
        )
    return status


def _migration_model_kind(model: type[MarketsBase]) -> str:
    if is_time_index_meta_table_model(model):
        return "time_index_storage"
    return "domain_table"


def _validate_apply_response(
    response: Any,
    *,
    materialized: MaterializedMigration,
) -> None:
    if _field(response, "ok") is not True:
        error = _field(response, "error")
        raise MigrationStateError(
            "SDK migration apply failed for revision "
            f"{materialized.spec.revision!r}: {_model_dump(error)!r}."
        )
    status = _field(response, "status")
    if status not in (None, "applied"):
        raise MigrationStateError(
            "SDK migration apply did not finish as applied for revision "
            f"{materialized.spec.revision!r}: status={status!r}."
        )
    revision = _field(response, "revision") or _field(response, "applied_revision")
    if revision not in (None, materialized.spec.revision):
        raise MigrationStateError(
            "SDK migration apply response revision mismatch. "
            f"Expected {materialized.spec.revision!r}, got {revision!r}."
        )
    response_identifiers = {
        str(_field(affected, "identifier") or "")
        for affected in _affected_table_results(response)
        if _field(affected, "identifier") not in (None, "")
    }
    expected_identifiers = set(materialized.spec.identifiers)
    missing_identifiers = sorted(expected_identifiers - response_identifiers)
    extra_identifiers = sorted(response_identifiers - expected_identifiers)
    if missing_identifiers or extra_identifiers:
        raise MigrationStateError(
            "SDK migration apply affected-table mismatch for revision "
            f"{materialized.spec.revision!r}. Missing={missing_identifiers!r}, "
            f"extra={extra_identifiers!r}."
        )


def _manifest_new_contract_hashes(materialized: MaterializedMigration) -> dict[str, str]:
    manifest = getattr(materialized.packaged, "manifest", None)
    hashes = _field(manifest, "new_contract_hashes") or {}
    if not isinstance(hashes, Mapping):
        return {}
    return {str(identifier): str(value) for identifier, value in hashes.items()}


def _resolve_platform_meta_table_for_migration(
    model: type[MarketsBase],
    *,
    timeout: int | float | tuple[float, float] | None,
) -> Any:
    from mainsequence.client.models_metatables import TimeIndexMetaData
    from mainsequence.meta_tables import PlatformTimeIndexMetaData

    identifier = markets_meta_table_identifier(model)
    namespace = getattr(model, "__metatable_namespace__", None)
    filters = {
        "identifier": identifier,
        "namespace": namespace,
    }
    client_model = TimeIndexMetaData if issubclass(model, PlatformTimeIndexMetaData) else MetaTable
    matches = client_model.filter(
        timeout=timeout,
        **{key: value for key, value in filters.items() if value not in (None, "")},
    )
    if not matches:
        raise MigrationStateError(
            "Could not resolve platform MetaTable after applied migration for "
            f"{model.__name__} ({identifier!r})."
        )
    if len(matches) > 1:
        raise MigrationStateError(
            "Multiple platform MetaTables matched applied migration target "
            f"{model.__name__} ({identifier!r})."
        )
    return matches[0]


def _current_error_message(result: MigrationCommandResult) -> str:
    current_revision = _status_current_revision(result.status)
    return (
        "Markets MetaTable migrations are not current. "
        f"Expected revision {_last_or_none(result.expected_revisions)!r}, "
        f"current revision {current_revision!r}, "
        f"migration registry UID {result.migration_registry_uid!r}. "
        "Run `msm migrations upgrade` before runtime startup."
    )


def _status_current_revision(status: Any | None) -> str | None:
    if status is None:
        return None
    for field_name in ("current_revision", "latest_successful_revision", "applied_revision"):
        value = _field(status, field_name)
        if value not in (None, ""):
            return str(value)
    return None


def _applied_revisions(status: Any | None) -> set[str]:
    rows = _field(status, "rows") or []
    applied: set[str] = set()
    for row in rows:
        if _field(row, "status") == "applied":
            revision = _field(row, "revision")
            if revision not in (None, ""):
                applied.add(str(revision))
    return applied


def _affected_table_results(response: Any) -> list[Any]:
    affected = _field(response, "affected_tables")
    if isinstance(affected, list):
        return affected
    return []


def _first_synced_meta_table(synced: Sequence[Any]) -> MetaTable | None:
    for item in synced:
        if isinstance(item, Mapping):
            meta_table = item.get("meta_table")
            if isinstance(meta_table, MetaTable):
                return meta_table
    return None


def _sync_payload(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        return _model_dump(item)
    row = item.get("row")
    return {
        "meta_table_uid": getattr(item.get("meta_table"), "uid", None),
        "row": _model_dump(row),
        "result": _model_dump(item.get("result")),
    }


def _row_revision(row: Any) -> str | None:
    revision = _field(row, "revision")
    if revision in (None, ""):
        return None
    return str(revision)


def _field(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name)
    return getattr(value, field_name, None)


def _model_dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): _model_dump(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_model_dump(item) for item in value]
    if isinstance(value, tuple):
        return [_model_dump(item) for item in value]
    return value


def _required_module_text(module: ModuleType, name: str) -> str:
    value = _optional_module_text(module, name)
    if value is None:
        raise ValueError(f"{module.__name__}.{name} is required.")
    return value


def _optional_module_text(module: ModuleType, name: str) -> str | None:
    value = getattr(module, name, None)
    if value in (None, ""):
        return None
    return str(value)


def _last_or_none(values: Sequence[str]) -> str | None:
    if not values:
        return None
    return values[-1]


__all__ = [
    "MIGRATION_PACKAGE",
    "MIGRATION_VERSIONS_PACKAGE",
    "MaterializedMigration",
    "MigrationCommandResult",
    "MigrationSpec",
    "MigrationStateError",
    "MigrationSupportError",
    "current_migrations",
    "finalize_catalog_from_apply_response",
    "finalize_catalog_from_materialized_migration",
    "load_migration_specs",
    "materialize_migrations",
    "resolve_migration_registry_meta_table",
    "sync_migrations",
    "upgrade_migrations",
    "validate_migrations",
    "verify_runtime_migrations_current",
]
