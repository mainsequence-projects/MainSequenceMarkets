from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from mainsequence.client.exceptions import ConflictError, NotFoundError
from mainsequence.client.models_metatables import MetaTable
from mainsequence.logconf import logger as _mainsequence_logger
from mainsequence.meta_tables import register_external_sqlalchemy_model

from msm.base import MARKETS_SCHEMA, MarketsBase, markets_table_storage_name
from msm.models.registration import (
    MarketsManagementMode,
    MarketsModelSelector,
    MarketsMetaTableRegistrationResult,
    _target_meta_tables_from_bound_models,
    is_time_index_meta_table_model,
    markets_meta_table_identifier,
    resolve_markets_meta_table_model,
)
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import delete_model, search_model, upsert_model

from .models import (
    MarketsMetaTableCatalogRow,
    MarketsMetaTableCatalogTable,
    markets_meta_table_contract_hash,
)


logger = _mainsequence_logger.bind(sub_application="markets", component="maintenance")


class CatalogBootstrapError(RuntimeError):
    """Raised when catalog bootstrap cannot safely resolve MetaTable state."""


class CatalogStaleMetaTableUidError(CatalogBootstrapError):
    """Raised when a catalog row points at a backend MetaTable UID that is gone."""


@dataclass(frozen=True)
class CatalogBootstrapResult:
    """Catalog bootstrap output for application MetaTable registration."""

    registration: MarketsMetaTableRegistrationResult
    catalog_meta_table: MetaTable
    attached_count: int = 0
    imported_count: int = 0
    registered_count: int = 0


@dataclass(frozen=True)
class CatalogRotationResult:
    """Result from intentionally replacing one catalog row."""

    namespace: str
    identifier: str
    model_name: str
    meta_table_uid: str
    old_contract_hash: str | None
    new_contract_hash: str
    changed: bool
    row: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "identifier": self.identifier,
            "model_name": self.model_name,
            "meta_table_uid": self.meta_table_uid,
            "old_contract_hash": self.old_contract_hash,
            "new_contract_hash": self.new_contract_hash,
            "changed": self.changed,
            "row": dict(self.row),
        }


@dataclass(frozen=True)
class _CatalogBootstrapModelPlan:
    model: type[MarketsBase]
    storage_hash: str
    namespace: str
    identifier: str


def attach_markets_meta_tables_from_catalog(
    *,
    management_mode: MarketsManagementMode = "platform_managed",
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> CatalogBootstrapResult:
    """Attach markets MetaTables from the finalized catalog without mutation."""

    resolved_models = list(models or [])
    catalog_meta_table = resolve_catalog_table(timeout=timeout)
    catalog_context = catalog_repository_context(
        catalog_meta_table=catalog_meta_table,
        timeout=timeout,
    )
    model_plans = [
        _CatalogBootstrapModelPlan(
            model=model,
            storage_hash=_catalog_model_storage_hash(model),
            namespace=_catalog_model_namespace(model),
            identifier=markets_meta_table_identifier(model),
        )
        for model in resolved_models
    ]
    catalog_rows_by_identifier = find_catalog_rows_by_identifier(
        catalog_context,
        identifiers=[plan.identifier for plan in model_plans],
    )
    missing_identifiers = [
        plan.identifier for plan in model_plans if plan.identifier not in catalog_rows_by_identifier
    ]
    if missing_identifiers:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog is missing finalized rows for "
            f"{missing_identifiers!r}. Run `msm migrations upgrade` before runtime startup."
        )

    meta_tables: list[MetaTable] = []
    meta_table_by_identifier: dict[str, MetaTable] = {}
    for position, plan in enumerate(model_plans, start=1):
        catalog_row = catalog_rows_by_identifier[plan.identifier]
        validate_catalog_contract(catalog_row, model=plan.model)
        meta_table = resolve_catalog_meta_table(
            catalog_row,
            model=plan.model,
            timeout=timeout,
        )
        validate_platform_meta_table_physical_contract(
            meta_table,
            model=plan.model,
            timeout=timeout,
        )
        _bind_model_meta_table(plan.model, meta_table)
        meta_tables.append(meta_table)
        meta_table_by_identifier[plan.identifier] = meta_table
        logger.debug(
            "Attached markets MetaTable from finalized catalog",
            model=plan.model.__name__,
            namespace=catalog_row.get("namespace"),
            identifier=catalog_row.get("identifier"),
            meta_table_uid=_meta_table_uid(meta_table),
            model_index=position,
            model_count=len(resolved_models),
        )

    return CatalogBootstrapResult(
        registration=MarketsMetaTableRegistrationResult(
            meta_tables=meta_tables,
            models=resolved_models,
            meta_table_by_identifier=meta_table_by_identifier,
        ),
        catalog_meta_table=catalog_meta_table,
        attached_count=len(meta_tables),
    )


def bootstrap_markets_meta_tables_from_catalog(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_identifier: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> CatalogBootstrapResult:
    """Attach/register markets MetaTables through the maintenance catalog."""

    resolved_models = list(models or [])
    catalog_meta_table = bootstrap_catalog_table(timeout=timeout)
    catalog_context = catalog_repository_context(
        catalog_meta_table=catalog_meta_table,
        timeout=timeout,
    )
    storage_hash_mapping = dict(storage_hash_by_identifier or {})
    model_plans: list[_CatalogBootstrapModelPlan] = []
    for model in resolved_models:
        identifier = markets_meta_table_identifier(model)
        namespace = _catalog_model_namespace(model)
        model_plans.append(
            _CatalogBootstrapModelPlan(
                model=model,
                storage_hash=_catalog_model_storage_hash(
                    model,
                    storage_hash=storage_hash_mapping.get(identifier),
                ),
                namespace=namespace,
                identifier=identifier,
            )
        )
    catalog_rows_by_identifier = find_catalog_rows_by_identifier(
        catalog_context,
        identifiers=[plan.identifier for plan in model_plans],
    )

    meta_tables: list[MetaTable] = []
    meta_table_by_identifier: dict[str, MetaTable] = {}
    attached_count = 0
    imported_count = 0
    registered_count = 0

    for position, plan in enumerate(model_plans, start=1):
        model = plan.model
        catalog_row = catalog_rows_by_identifier.get(plan.identifier)
        target_meta_tables = _target_meta_tables_from_bound_models(resolved_models)
        resolved_catalog_meta_table: MetaTable | None = None
        if catalog_row is not None and not is_time_index_meta_table_model(model):
            try:
                resolved_catalog_meta_table = resolve_catalog_meta_table(
                    catalog_row,
                    model=model,
                    timeout=timeout,
                )
            except CatalogStaleMetaTableUidError as exc:
                invalidate_stale_catalog_row(
                    catalog_context,
                    catalog_row=catalog_row,
                    model=model,
                    reason=str(exc),
                )
                catalog_row = None

        if catalog_row is not None:
            validate_catalog_contract(catalog_row, model=model)
            if is_time_index_meta_table_model(model):
                meta_table = register_catalog_missing_meta_table(
                    model,
                    data_source_uid=_external_data_source_uid(
                        management_mode=management_mode,
                        data_source_uid=data_source_uid,
                    ),
                    management_mode=management_mode,
                    target_meta_tables=target_meta_tables,
                    open_for_everyone=open_for_everyone,
                    protect_from_deletion=protect_from_deletion,
                    introspect=introspect,
                    storage_hash=plan.storage_hash,
                    timeout=timeout,
                )
                catalog_uid = str(catalog_row["meta_table_uid"])
                if _meta_table_uid(meta_table) != catalog_uid:
                    raise CatalogBootstrapError(
                        "Markets MetaTable catalog drift detected for "
                        f"{model.__name__}. Catalog UID {catalog_uid!r} does not match "
                        f"the registered storage UID {_meta_table_uid(meta_table)!r}."
                    )
            else:
                meta_table = resolved_catalog_meta_table
                if meta_table is None:
                    meta_table = resolve_catalog_meta_table(
                        catalog_row,
                        model=model,
                        timeout=timeout,
                    )
                validate_platform_meta_table_physical_contract(
                    meta_table,
                    model=model,
                    timeout=timeout,
                )
            attached_count += 1
            logger.debug(
                "Attached markets MetaTable from catalog",
                model=model.__name__,
                namespace=catalog_row.get("namespace"),
                identifier=catalog_row.get("identifier"),
                meta_table_uid=_meta_table_uid(meta_table),
                model_index=position,
                model_count=len(resolved_models),
            )
        else:
            meta_table = None
            if not is_time_index_meta_table_model(model):
                meta_table = _resolve_platform_meta_table(
                    model,
                    data_source_uid=_external_data_source_uid(
                        management_mode=management_mode,
                        data_source_uid=data_source_uid,
                    ),
                    management_mode=management_mode,
                    timeout=timeout,
                )
            if meta_table is not None:
                validate_platform_meta_table_physical_contract(
                    meta_table,
                    model=model,
                    timeout=timeout,
                )
                imported_count += 1
                logger.info(
                    "Importing existing markets MetaTable into catalog",
                    model=model.__name__,
                    namespace=getattr(model, "__metatable_namespace__", None),
                    identifier=getattr(model, "__metatable_identifier__", None),
                    meta_table_uid=_meta_table_uid(meta_table),
                    model_index=position,
                    model_count=len(resolved_models),
                )
            else:
                meta_table = register_catalog_missing_meta_table(
                    model,
                    data_source_uid=_external_data_source_uid(
                        management_mode=management_mode,
                        data_source_uid=data_source_uid,
                    ),
                    management_mode=management_mode,
                    target_meta_tables=target_meta_tables,
                    open_for_everyone=open_for_everyone,
                    protect_from_deletion=protect_from_deletion,
                    introspect=introspect,
                    storage_hash=plan.storage_hash,
                    timeout=timeout,
                )
                registered_count += 1
                logger.info(
                    "Registered missing markets MetaTable from catalog bootstrap",
                    model=model.__name__,
                    namespace=getattr(model, "__metatable_namespace__", None),
                    identifier=getattr(model, "__metatable_identifier__", None),
                    meta_table_uid=_meta_table_uid(meta_table),
                    model_index=position,
                    model_count=len(resolved_models),
                )

            upsert_catalog_row(
                catalog_context,
                model=model,
                meta_table=meta_table,
            )

        _bind_model_meta_table(model, meta_table)
        meta_tables.append(meta_table)
        meta_table_by_identifier[plan.identifier] = meta_table

    return CatalogBootstrapResult(
        registration=MarketsMetaTableRegistrationResult(
            meta_tables=meta_tables,
            models=resolved_models,
            meta_table_by_identifier=meta_table_by_identifier,
        ),
        catalog_meta_table=catalog_meta_table,
        attached_count=attached_count,
        imported_count=imported_count,
        registered_count=registered_count,
    )


def rotate_catalogue(model_or_row_type: MarketsModelSelector | type[Any]) -> CatalogRotationResult:
    """Replace one catalog row from the model's current registered MetaTable.

    This is the explicit override for metadata-only catalog drift. The caller
    passes the authored model/API row type, for example ``rotate_catalogue(Account)``.
    The registered backend ``MetaTable`` is resolved through ``model.register()``;
    this function does not accept UID, identifier, or data-source lookup knobs.
    """

    model = resolve_catalogue_model(model_or_row_type)
    catalog_meta_table = bootstrap_catalog_table()
    catalog_context = catalog_repository_context(catalog_meta_table=catalog_meta_table)
    existing_row = find_catalog_row(catalog_context, model=model)
    meta_table = _register_catalogue_rotation_meta_table(model)
    validate_platform_meta_table_physical_contract(
        meta_table,
        model=model,
        timeout=None,
    )

    row = MarketsMetaTableCatalogRow.from_meta_table(
        model=model,
        meta_table=meta_table,
        sdk_version=_sdk_version(),
    )
    payload = row.to_payload()
    changed = _catalog_row_changed(existing_row, payload)
    upserted = _upsert_catalog_payload(catalog_context, payload)
    old_contract_hash = str(existing_row.get("contract_hash")) if existing_row else None
    logger.info(
        "Rotated markets MetaTable catalog row",
        model=model.__name__,
        namespace=payload["namespace"],
        identifier=payload["identifier"],
        meta_table_uid=payload["meta_table_uid"],
        old_contract_hash=old_contract_hash,
        new_contract_hash=payload["contract_hash"],
        changed=changed,
    )
    return CatalogRotationResult(
        namespace=payload["namespace"],
        identifier=payload["identifier"],
        model_name=model.__name__,
        meta_table_uid=payload["meta_table_uid"],
        old_contract_hash=old_contract_hash,
        new_contract_hash=payload["contract_hash"],
        changed=changed,
        row=_first_operation_row(upserted) or payload,
    )


def resolve_catalogue_model(
    model_or_row_type: MarketsModelSelector | type[Any],
) -> type[MarketsBase]:
    """Resolve a catalog rotation input to its SQLAlchemy MetaTable model."""

    if isinstance(model_or_row_type, type):
        if issubclass(model_or_row_type, MarketsBase):
            return model_or_row_type
        table_model = getattr(model_or_row_type, "__table__", None)
        if isinstance(table_model, type) and issubclass(table_model, MarketsBase):
            return table_model
    return resolve_markets_meta_table_model(model_or_row_type)


def bootstrap_catalog_table(
    *,
    timeout: int | float | tuple[float, float] | None = None,
) -> MetaTable:
    """Attach or create the maintenance catalog MetaTable."""

    existing = _resolve_platform_meta_table(
        MarketsMetaTableCatalogTable,
        management_mode="platform_managed",
        timeout=timeout,
    )
    if existing is not None:
        validate_platform_meta_table_physical_contract(
            existing,
            model=MarketsMetaTableCatalogTable,
            timeout=timeout,
        )
        logger.info(
            "Attached markets MetaTable catalog",
            namespace=getattr(existing, "namespace", None),
            identifier=getattr(existing, "identifier", None),
            meta_table_uid=_meta_table_uid(existing),
        )
        return existing

    logger.info(
        "Creating markets MetaTable catalog",
        namespace=getattr(MarketsMetaTableCatalogTable, "__metatable_namespace__", None),
        identifier=getattr(MarketsMetaTableCatalogTable, "__metatable_identifier__", None),
    )
    try:
        return MarketsMetaTableCatalogTable.register(timeout=timeout)
    except ConflictError as exc:
        recovered = _meta_table_from_conflict(
            exc,
            model=MarketsMetaTableCatalogTable,
            management_mode="platform_managed",
            timeout=timeout,
        )
        if recovered is not None:
            logger.info(
                "Attached markets MetaTable catalog after duplicate registration",
                meta_table_uid=_meta_table_uid(recovered),
            )
            return recovered
        raise CatalogBootstrapError(
            "Could not create or attach the markets MetaTable catalog. "
            "Resolve the catalog MetaTable conflict before registering application tables."
        ) from exc


def resolve_catalog_table(
    *,
    timeout: int | float | tuple[float, float] | None = None,
) -> MetaTable:
    """Resolve the finalized maintenance catalog without creating it."""

    existing = _resolve_platform_meta_table(
        MarketsMetaTableCatalogTable,
        management_mode="platform_managed",
        timeout=timeout,
    )
    if existing is None:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog is not initialized. Run `msm migrations upgrade` "
            "before runtime startup."
        )
    validate_platform_meta_table_physical_contract(
        existing,
        model=MarketsMetaTableCatalogTable,
        timeout=timeout,
    )
    return existing


def catalog_repository_context(
    *,
    catalog_meta_table: MetaTable,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRepositoryContext:
    _bind_model_meta_table(MarketsMetaTableCatalogTable, catalog_meta_table)
    return MarketsRepositoryContext(
        timeout=timeout,
        namespace=getattr(catalog_meta_table, "namespace", None),
    )


def find_catalog_row(
    context: MarketsRepositoryContext,
    *,
    model: type[MarketsBase],
) -> dict[str, Any] | None:
    identifier = markets_meta_table_identifier(model)
    rows_by_identifier = find_catalog_rows_by_identifier(
        context,
        identifiers=[identifier],
    )
    return rows_by_identifier.get(identifier)


def find_catalog_rows_by_identifier(
    context: MarketsRepositoryContext,
    *,
    identifiers: Sequence[str],
) -> dict[str, dict[str, Any]]:
    requested_identifiers = list(
        dict.fromkeys(str(identifier) for identifier in identifiers if identifier)
    )
    if not requested_identifiers:
        return {}

    result = search_model(
        context,
        model=MarketsMetaTableCatalogTable,
        in_filters={
            "identifier": sorted(requested_identifiers),
        },
        limit=len(requested_identifiers) * 2,
    )
    requested_identifier_set = set(requested_identifiers)
    rows_by_identifier: dict[str, dict[str, Any]] = {}
    for row in _operation_result_rows(result):
        row_identifier = str(row.get("identifier") or "")
        if not row_identifier:
            raise CatalogBootstrapError(
                "Markets MetaTable catalog returned a row without identifier."
            )
        if row_identifier not in requested_identifier_set:
            continue
        if row_identifier in rows_by_identifier:
            raise CatalogBootstrapError(
                "Markets MetaTable catalog returned multiple rows for "
                f"identifier {row_identifier!r}. The catalog uniqueness invariant is broken."
            )
        rows_by_identifier[row_identifier] = row
    return rows_by_identifier


def meta_table_from_catalog_row(
    catalog_row: Mapping[str, Any],
    *,
    model: type[MarketsBase],
    management_mode: MarketsManagementMode,
) -> MetaTable:
    storage_hash = markets_table_storage_name(model)
    return MetaTable(
        uid=str(catalog_row["meta_table_uid"]),
        namespace=str(catalog_row.get("namespace") or ""),
        identifier=str(
            catalog_row.get("identifier")
            or getattr(model, "__metatable_identifier__", model.__name__)
        ),
        description=catalog_row.get("description"),
        storage_hash=storage_hash,
        physical_table_name=storage_hash,
        management_mode=management_mode,
    )


def resolve_catalog_meta_table(
    catalog_row: Mapping[str, Any],
    *,
    model: type[MarketsBase],
    timeout: int | float | tuple[float, float] | None = None,
) -> MetaTable:
    try:
        return MetaTable.get_by_uid(
            uid=str(catalog_row["meta_table_uid"]),
            timeout=timeout,
        )
    except NotFoundError as exc:
        raise CatalogStaleMetaTableUidError(
            "Markets MetaTable catalog row points to missing backend MetaTable "
            f"{catalog_row.get('meta_table_uid')!r} for {model.__name__}."
        ) from exc
    except Exception as exc:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog row is stale for "
            f"{model.__name__}: platform MetaTable {catalog_row.get('meta_table_uid')!r} "
            "could not be resolved. Repair or rebuild the catalog before startup."
        ) from exc


def invalidate_stale_catalog_row(
    context: MarketsRepositoryContext,
    *,
    catalog_row: Mapping[str, Any],
    model: type[MarketsBase],
    reason: str,
) -> None:
    row_uid = catalog_row.get("uid")
    logger.warning(
        "Invalidating stale markets MetaTable catalog row",
        model=model.__name__,
        namespace=catalog_row.get("namespace"),
        identifier=catalog_row.get("identifier"),
        meta_table_uid=catalog_row.get("meta_table_uid"),
        catalog_row_uid=row_uid,
        reason=reason,
    )
    if row_uid in (None, ""):
        logger.warning(
            "Could not delete stale markets MetaTable catalog row without row uid",
            model=model.__name__,
            identifier=catalog_row.get("identifier"),
            meta_table_uid=catalog_row.get("meta_table_uid"),
        )
        return
    delete_model(
        context,
        model=MarketsMetaTableCatalogTable,
        uid=str(row_uid),
    )


def validate_catalog_contract(
    catalog_row: Mapping[str, Any],
    *,
    model: type[MarketsBase],
) -> None:
    expected_contract_hash = markets_meta_table_contract_hash(model)
    actual_contract_hash = str(catalog_row.get("contract_hash") or "")
    if actual_contract_hash != expected_contract_hash:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog contract drift detected for "
            f"{model.__name__}. Catalog hash {actual_contract_hash!r} does not match "
            f"local hash {expected_contract_hash!r}. Add an explicit migration or repair "
            "the catalog before startup."
        )


def validate_platform_meta_table_physical_contract(
    meta_table: MetaTable,
    *,
    model: type[MarketsBase],
    timeout: int | float | tuple[float, float] | None,
) -> None:
    if getattr(meta_table, "management_mode", None) != "platform_managed":
        return

    try:
        response = meta_table.introspect(timeout=timeout)
    except Exception as exc:
        raise CatalogBootstrapError(
            "Could not introspect platform-managed MetaTable physical table for "
            f"{model.__name__}. Repair or recreate the MetaTable before startup."
        ) from exc

    snapshot = response.get("introspection_snapshot") if isinstance(response, Mapping) else None
    if not isinstance(snapshot, Mapping):
        snapshot = getattr(meta_table, "introspection_snapshot", None)
    if not isinstance(snapshot, Mapping):
        raise CatalogBootstrapError(
            "MetaTable introspection returned no physical snapshot for "
            f"{model.__name__}. Repair or recreate the MetaTable before startup."
        )

    expected_columns = {str(column.name) for column in model.__table__.columns}
    actual_columns = {
        str(_physical_item_field(column, "name"))
        for column in _physical_collection(response, snapshot, meta_table, "columns")
        if _physical_item_field(column, "name")
    }
    expected_indexes = {
        str(index.name): _expected_index_signature(index)
        for index in getattr(model.__table__, "indexes", set()) or []
        if getattr(index, "name", None)
    }
    actual_indexes = {
        str(_physical_item_field(index, "name")): _physical_index_signature(index)
        for index in _physical_collection(
            response,
            snapshot,
            meta_table,
            "indexes",
            "indexes_meta",
        )
        if _physical_item_field(index, "name")
    }

    missing_columns = sorted(expected_columns - actual_columns)
    extra_columns = sorted(actual_columns - expected_columns)
    missing_indexes = sorted(set(expected_indexes) - set(actual_indexes))
    mismatched_indexes = {
        name: {
            "expected": expected_indexes[name],
            "actual": actual_indexes[name],
        }
        for name in sorted(set(expected_indexes).intersection(actual_indexes))
        if _physical_index_signature_mismatch(expected_indexes[name], actual_indexes[name])
    }
    if missing_columns or extra_columns or missing_indexes or mismatched_indexes:
        raise CatalogBootstrapError(
            "Registered platform-managed MetaTable has stale physical storage for "
            f"{model.__name__}. Missing columns={missing_columns!r}, "
            f"extra columns={extra_columns!r}, "
            f"missing indexes={missing_indexes!r}, "
            f"mismatched indexes={mismatched_indexes!r}. Repair or recreate the "
            "MetaTable before normal schema bootstrap."
        )


def _expected_index_signature(index: Any) -> dict[str, Any]:
    return {
        "columns": [str(column.name) for column in index.columns],
        "unique": bool(index.unique),
    }


def _physical_collection(
    response: Any,
    snapshot: Mapping[str, Any],
    meta_table: MetaTable,
    *field_names: str,
) -> list[Any]:
    for field_name in field_names:
        snapshot_items = snapshot.get(field_name)
        if isinstance(snapshot_items, list):
            return snapshot_items

    if isinstance(response, Mapping):
        for field_name in field_names:
            response_items = response.get(field_name)
            if isinstance(response_items, list):
                return response_items

    for field_name in field_names:
        meta_table_items = getattr(meta_table, field_name, None)
        if isinstance(meta_table_items, list):
            return meta_table_items

    return []


def _physical_item_field(item: Any, field_name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(field_name)
    return getattr(item, field_name, None)


def _physical_item_has_field(item: Any, field_name: str) -> bool:
    if isinstance(item, Mapping):
        return field_name in item
    model_fields_set = getattr(item, "model_fields_set", None)
    if isinstance(model_fields_set, set):
        return field_name in model_fields_set
    fields_set = getattr(item, "__fields_set__", None)
    if isinstance(fields_set, set):
        return field_name in fields_set
    return getattr(item, field_name, None) is not None


def _physical_index_signature_mismatch(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> bool:
    actual_columns = actual.get("columns")
    actual_unique = actual.get("unique")
    if actual_columns is None:
        return False
    if list(expected.get("columns", [])) != list(actual_columns):
        return True
    return actual_unique is not None and bool(expected.get("unique")) != bool(actual_unique)


def _physical_index_signature(index: Any) -> dict[str, Any]:
    contract_fragment = _physical_item_field(index, "contract_fragment")
    if not isinstance(contract_fragment, Mapping):
        contract_fragment = {}

    raw_columns = (
        _physical_item_field(index, "columns")
        or _physical_item_field(index, "column_names")
        or contract_fragment.get("columns")
        or contract_fragment.get("column_names")
    )
    columns = _physical_index_columns(raw_columns)
    raw_unique = None
    for field_name in ("unique", "is_unique"):
        if _physical_item_has_field(index, field_name):
            raw_unique = _physical_item_field(index, field_name)
            break
    if raw_unique is None:
        raw_unique = contract_fragment.get("unique")
    if raw_unique is None:
        raw_unique = contract_fragment.get("is_unique")

    return {
        "columns": columns,
        "unique": bool(raw_unique) if raw_unique is not None and columns is not None else None,
    }


def _physical_index_columns(value: Any) -> list[str] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None

    columns: list[str] = []
    for column in value:
        column_name = _physical_item_field(column, "name")
        if column_name in (None, ""):
            column_name = column
        if column_name not in (None, ""):
            columns.append(str(column_name))
    return columns or None


def register_catalog_missing_meta_table(
    model: type[MarketsBase],
    *,
    data_source_uid: str | None,
    management_mode: MarketsManagementMode,
    target_meta_tables: Mapping[type[MarketsBase], Any],
    open_for_everyone: bool,
    protect_from_deletion: bool,
    introspect: bool | None,
    storage_hash: str | None,
    timeout: int | float | tuple[float, float] | None,
) -> MetaTable:
    platform_kwargs = {
        "data_source_uid": data_source_uid,
        "open_for_everyone": open_for_everyone,
        "protect_from_deletion": protect_from_deletion,
        "timeout": timeout,
    }
    external_kwargs = {
        **platform_kwargs,
        "target_meta_tables": target_meta_tables,
    }
    try:
        if is_time_index_meta_table_model(model):
            return model.register(timeout=timeout)
        if management_mode == "platform_managed":
            return model.register(timeout=timeout)
        if management_mode == "external_registered":
            return register_external_sqlalchemy_model(
                model,
                introspect=True if introspect is None else introspect,
                storage_hash=storage_hash,
                schema=MARKETS_SCHEMA,
                **external_kwargs,
            )
    except ConflictError as exc:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog drift detected while registering "
            f"{model.__name__}. The platform reports that the physical table already "
            "exists, but the catalog has no matching row. Run the catalog import/repair "
            "flow before normal schema bootstrap."
        ) from exc
    raise ValueError("management_mode must be 'platform_managed' or 'external_registered'.")


def upsert_catalog_row(
    context: MarketsRepositoryContext,
    *,
    model: type[MarketsBase],
    meta_table: MetaTable,
    contract_hash: str | None = None,
) -> dict[str, Any]:
    row = MarketsMetaTableCatalogRow.from_meta_table(
        model=model,
        meta_table=meta_table,
        contract_hash=contract_hash,
        sdk_version=_sdk_version(),
    )
    return _upsert_catalog_payload(context, row.to_payload())


def _upsert_catalog_payload(
    context: MarketsRepositoryContext,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return upsert_model(
        context,
        model=MarketsMetaTableCatalogTable,
        values=dict(payload),
        conflict_columns=[
            "identifier",
        ],
    )


def _register_catalogue_rotation_meta_table(model: type[MarketsBase]) -> MetaTable:
    try:
        meta_table = model.register()
    except ConflictError as exc:
        recovered = _meta_table_from_conflict(
            exc,
            model=model,
            management_mode="platform_managed",
            timeout=None,
        )
        if recovered is None:
            raise CatalogBootstrapError(
                "Could not resolve registered markets MetaTable for catalog rotation "
                f"through {model.__name__}.register()."
            ) from exc
        meta_table = recovered
    _bind_model_meta_table(model, meta_table)
    return meta_table


def _catalog_row_changed(
    existing_row: Mapping[str, Any] | None,
    new_payload: Mapping[str, Any],
) -> bool:
    if existing_row is None:
        return True
    for key in (
        "namespace",
        "identifier",
        "description",
        "model_name",
        "meta_table_uid",
        "contract_hash",
        "sdk_version",
    ):
        if _catalog_compare_value(existing_row.get(key)) != _catalog_compare_value(
            new_payload.get(key)
        ):
            return True
    return False


def _catalog_compare_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _first_operation_row(result: Mapping[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    rows = _operation_result_rows(result)
    if not rows:
        return None
    return rows[0]


def _resolve_platform_meta_table(
    model: type[MarketsBase],
    *,
    management_mode: MarketsManagementMode,
    timeout: int | float | tuple[float, float] | None,
    data_source_uid: str | None = None,
) -> MetaTable | None:
    matches: list[MetaTable] = []
    matched_filters: dict[str, Any] | None = None
    for filters in _registered_meta_table_filter_candidates(
        model,
        data_source_uid=data_source_uid,
        management_mode=management_mode,
    ):
        matches = MetaTable.filter(timeout=timeout, **filters)
        if matches:
            matched_filters = filters
            break
    if not matches:
        return None
    if len(matches) > 1:
        raise CatalogBootstrapError(
            "Multiple registered markets MetaTables matched "
            f"{model.__name__} with filters {matched_filters!r}. Repair duplicate "
            "platform registrations before startup."
        )
    return matches[0]


def _external_data_source_uid(
    *,
    management_mode: MarketsManagementMode,
    data_source_uid: str | None,
) -> str | None:
    if management_mode == "external_registered":
        return data_source_uid
    return None


def _registered_meta_table_filter_candidates(
    model: type[MarketsBase],
    *,
    data_source_uid: str | None,
    management_mode: MarketsManagementMode,
) -> list[dict[str, Any]]:
    base_filters: dict[str, Any] = {
        "identifier": getattr(model, "__metatable_identifier__", model.__name__),
        "management_mode": management_mode,
    }
    if management_mode == "external_registered" and data_source_uid:
        base_filters["data_source__uid"] = data_source_uid

    return [_clean_filters(base_filters)]


def _clean_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if value not in (None, "")}


def _catalog_model_storage_hash(
    model: type[MarketsBase],
    *,
    storage_hash: str | None = None,
) -> str:
    if storage_hash not in (None, ""):
        return str(storage_hash)
    return markets_table_storage_name(model)


def _catalog_model_namespace(model: type[MarketsBase]) -> str:
    namespace = str(getattr(model, "__metatable_namespace__", "") or "")
    if not namespace:
        raise CatalogBootstrapError(
            f"Markets MetaTable model {model.__name__} does not expose catalog namespace."
        )
    return namespace


def _meta_table_from_conflict(
    exc: ConflictError,
    *,
    model: type[MarketsBase],
    management_mode: MarketsManagementMode,
    timeout: int | float | tuple[float, float] | None,
) -> MetaTable | None:
    payload = _conflict_payload(exc)
    existing_uid = payload.get("existing_meta_table_uid")
    if not existing_uid:
        return None

    try:
        return MetaTable.get_by_uid(uid=str(existing_uid), timeout=timeout)
    except Exception:
        table_name = str(payload.get("physical_table_name") or model.__table__.name)
        storage_hash = str(payload.get("storage_hash") or table_name)
        return MetaTable(
            uid=str(existing_uid),
            data_source_uid=payload.get("data_source_uid"),
            storage_hash=storage_hash,
            identifier=getattr(model, "__metatable_identifier__", model.__name__),
            namespace=getattr(model, "__metatable_namespace__", None),
            management_mode=management_mode,
            physical_table_name=table_name,
        )


def _conflict_payload(exc: ConflictError) -> dict[str, Any]:
    payload = getattr(exc, "payload", None)
    if isinstance(payload, Mapping):
        return dict(payload)

    response = getattr(exc, "response", None)
    if response is None:
        return {}
    try:
        response_payload = response.json()
    except Exception:
        return {}
    if isinstance(response_payload, Mapping):
        return dict(response_payload)
    return {}


def _meta_table_uid(value: Any) -> str:
    uid = getattr(value, "uid", value)
    if uid in (None, ""):
        raise ValueError("Registered MetaTable objects must expose a non-empty uid.")
    return str(uid)


def _bind_model_meta_table(model: type[MarketsBase], meta_table: MetaTable) -> None:
    if not isinstance(meta_table, MetaTable):
        return
    bind = getattr(model, "_bind_meta_table", None)
    if callable(bind):
        bind(meta_table)


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [dict(row) for row in result if isinstance(row, Mapping)]
    if not isinstance(result, Mapping):
        return []

    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]

    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            nested_rows = _operation_result_rows(value)
            if nested_rows:
                return nested_rows
            if key == "row" or "uid" in value:
                return [dict(value)]
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]

    if "uid" in result:
        return [dict(result)]
    return []


def _sdk_version() -> str | None:
    try:
        return package_version("ms-markets")
    except PackageNotFoundError:
        return None


__all__ = [
    "CatalogBootstrapError",
    "CatalogBootstrapResult",
    "CatalogRotationResult",
    "CatalogStaleMetaTableUidError",
    "attach_markets_meta_tables_from_catalog",
    "bootstrap_catalog_table",
    "bootstrap_markets_meta_tables_from_catalog",
    "catalog_repository_context",
    "find_catalog_row",
    "find_catalog_rows_by_identifier",
    "invalidate_stale_catalog_row",
    "meta_table_from_catalog_row",
    "register_catalog_missing_meta_table",
    "resolve_catalog_table",
    "resolve_catalog_meta_table",
    "resolve_catalogue_model",
    "rotate_catalogue",
    "upsert_catalog_row",
    "validate_catalog_contract",
    "validate_platform_meta_table_physical_contract",
]
