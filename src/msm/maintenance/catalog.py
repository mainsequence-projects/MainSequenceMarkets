from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from mainsequence.client.metatables import MetaTable
from mainsequence.logconf import logger as _mainsequence_logger

from msm.base import MarketsBase, markets_table_storage_name
from msm.models.registration import (
    MarketsManagementMode,
    MarketsMetaTableRegistrationResult,
    markets_meta_table_identifier,
)
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import search_model, upsert_model

from .models import (
    MarketsMetaTableCatalogRow,
    MarketsMetaTableCatalogTable,
    markets_meta_table_contract_hash,
)


logger = _mainsequence_logger.bind(sub_application="markets", component="maintenance")
SDK_MIGRATION_UPGRADE_COMMAND = (
    "mainsequence migrations upgrade --provider msm.migrations:migration --to head"
)


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
            f"{missing_identifiers!r}. Run `{SDK_MIGRATION_UPGRADE_COMMAND}` before runtime startup."
        )

    for plan in model_plans:
        validate_catalog_contract(catalog_rows_by_identifier[plan.identifier], model=plan.model)

    resolved_meta_tables = resolve_catalog_meta_tables(
        catalog_rows_by_identifier,
        model_plans=model_plans,
        management_mode=management_mode,
        timeout=timeout,
    )

    meta_tables: list[MetaTable] = []
    meta_table_by_identifier: dict[str, MetaTable] = {}
    for position, plan in enumerate(model_plans, start=1):
        catalog_row = catalog_rows_by_identifier[plan.identifier]
        meta_table = resolved_meta_tables[plan.identifier]
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
            "Markets MetaTable catalog is not initialized. "
            f"Run `{SDK_MIGRATION_UPGRADE_COMMAND}` "
            "before runtime startup."
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


def refresh_markets_catalog_from_registered_metatables(
    registered_metatables: Sequence[Any],
) -> list[dict[str, Any]]:
    """Refresh the internal markets catalog after SDK provider registration."""

    from msm.migrations.registry import migration_model_registry

    models = migration_model_registry()
    meta_tables = list(registered_metatables)
    if len(meta_tables) != len(models):
        raise CatalogBootstrapError(
            "SDK provider registered a different number of MetaTables than the "
            f"markets migration model registry. Registered={len(meta_tables)}, "
            f"expected={len(models)}."
        )

    registered_by_model = dict(zip(models, meta_tables, strict=True))
    catalog_meta_table = registered_by_model.get(MarketsMetaTableCatalogTable)
    if catalog_meta_table is None:
        raise CatalogBootstrapError(
            "The markets migration provider must include MarketsMetaTableCatalogTable "
            "so catalog rows can be refreshed after registration."
        )

    _bind_model_meta_table(MarketsMetaTableCatalogTable, catalog_meta_table)
    catalog_context = catalog_repository_context(catalog_meta_table=catalog_meta_table)
    rows: list[dict[str, Any]] = []
    for model, meta_table in registered_by_model.items():
        _meta_table_uid(meta_table)
        _bind_model_meta_table(model, meta_table)
        rows.append(
            upsert_catalog_row(
                catalog_context,
                model=model,
                meta_table=meta_table,
            )
        )
    return rows


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


def resolve_catalog_meta_tables(
    catalog_rows_by_identifier: Mapping[str, Mapping[str, Any]],
    *,
    model_plans: Sequence[_CatalogBootstrapModelPlan],
    management_mode: MarketsManagementMode,
    timeout: int | float | tuple[float, float] | None = None,
) -> dict[str, MetaTable]:
    uid_by_identifier = {
        plan.identifier: str(
            catalog_rows_by_identifier[plan.identifier].get("meta_table_uid") or ""
        )
        for plan in model_plans
    }
    missing_catalog_uid_identifiers = [
        identifier for identifier, uid in uid_by_identifier.items() if not uid
    ]
    if missing_catalog_uid_identifiers:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog has rows without meta_table_uid for "
            f"{missing_catalog_uid_identifiers!r}."
        )
    duplicate_uids = sorted(
        {
            uid
            for uid in uid_by_identifier.values()
            if list(uid_by_identifier.values()).count(uid) > 1
        }
    )
    if duplicate_uids:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog maps multiple identifiers to the same "
            f"MetaTable UID(s) {duplicate_uids!r}."
        )
    requested_uids = list(dict.fromkeys(uid_by_identifier.values()))

    if not requested_uids:
        return {}

    logger.info(
        "Resolving cataloged markets MetaTables",
        meta_table_uid_count=len(requested_uids),
        model_count=len(model_plans),
        management_mode=management_mode,
    )
    matches = MetaTable.filter(
        timeout=timeout,
        uid__in=requested_uids,
        management_mode=management_mode,
    )
    matches_by_uid: dict[str, MetaTable] = {}
    for meta_table in matches:
        uid = _meta_table_uid(meta_table)
        if uid in matches_by_uid:
            raise CatalogBootstrapError(
                f"Multiple platform MetaTables matched catalog UID {uid!r}."
            )
        matches_by_uid[uid] = meta_table

    missing_uids = sorted(set(requested_uids) - set(matches_by_uid))
    if missing_uids:
        raise CatalogStaleMetaTableUidError(
            "Markets MetaTable catalog rows point to missing backend MetaTables "
            f"{missing_uids!r}."
        )

    resolved: dict[str, MetaTable] = {}
    for plan in model_plans:
        catalog_row = catalog_rows_by_identifier[plan.identifier]
        uid = str(catalog_row["meta_table_uid"])
        meta_table = matches_by_uid[uid]
        _validate_catalog_meta_table_identity(
            catalog_row,
            meta_table=meta_table,
            model=plan.model,
        )
        resolved[plan.identifier] = meta_table

    logger.info(
        "Resolved cataloged markets MetaTables",
        meta_table_count=len(resolved),
        model_count=len(model_plans),
        management_mode=management_mode,
    )
    return resolved


def _validate_catalog_meta_table_identity(
    catalog_row: Mapping[str, Any],
    *,
    meta_table: MetaTable,
    model: type[MarketsBase],
) -> None:
    expected_uid = str(catalog_row.get("meta_table_uid") or "")
    actual_uid = _meta_table_uid(meta_table)
    if actual_uid != expected_uid:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog UID mismatch for "
            f"{model.__name__}: catalog={expected_uid!r}, backend={actual_uid!r}."
        )

    expected_identifier = str(catalog_row.get("identifier") or "")
    actual_identifier = str(getattr(meta_table, "identifier", "") or "")
    if actual_identifier and actual_identifier != expected_identifier:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog identifier mismatch for "
            f"{model.__name__}: catalog={expected_identifier!r}, "
            f"backend={actual_identifier!r}."
        )

    expected_namespace = str(catalog_row.get("namespace") or "")
    actual_namespace = str(getattr(meta_table, "namespace", "") or "")
    if actual_namespace and actual_namespace != expected_namespace:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog namespace mismatch for "
            f"{model.__name__}: catalog={expected_namespace!r}, "
            f"backend={actual_namespace!r}."
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
    "CatalogStaleMetaTableUidError",
    "attach_markets_meta_tables_from_catalog",
    "catalog_repository_context",
    "find_catalog_row",
    "find_catalog_rows_by_identifier",
    "meta_table_from_catalog_row",
    "refresh_markets_catalog_from_registered_metatables",
    "resolve_catalog_table",
    "resolve_catalog_meta_tables",
    "upsert_catalog_row",
    "validate_catalog_contract",
]
