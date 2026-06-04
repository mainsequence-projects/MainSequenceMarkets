from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from mainsequence.client.metatables import MetaTable, TimeIndexMetaTable
from mainsequence.logconf import logger as _mainsequence_logger
from mainsequence.meta_tables.migrations import AlembicMetaTableCatalogRefreshContext

from msm.base import MarketsBase, markets_table_storage_name
from msm.models.registration import (
    MarketsManagementMode,
    MarketsMetaTableRegistrationResult,
    is_time_index_meta_table_model,
)
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import bulk_upsert_model, search_model, upsert_model

from .models import (
    MarketsMetaTableCatalogRow,
    MarketsMetaTableCatalogTable,
)


logger = _mainsequence_logger.bind(sub_application="markets", component="maintenance")
SDK_MIGRATION_UPGRADE_COMMAND = (
    "mainsequence migrations upgrade --provider msm.migrations:migration head"
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
    namespace: str
    table_name: str


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
            namespace=_catalog_model_namespace(model),
            table_name=_catalog_model_table_name(model),
        )
        for model in resolved_models
    ]
    catalog_rows_by_table_name = find_catalog_rows_by_table_name(
        catalog_context,
        table_names=[plan.table_name for plan in model_plans],
    )
    missing_table_names = [
        plan.table_name for plan in model_plans if plan.table_name not in catalog_rows_by_table_name
    ]
    if missing_table_names:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog is missing finalized rows for "
            f"{missing_table_names!r}. Run `{SDK_MIGRATION_UPGRADE_COMMAND}` before runtime startup."
        )

    resolved_meta_tables = resolve_catalog_meta_tables(
        catalog_rows_by_table_name,
        model_plans=model_plans,
        management_mode=management_mode,
        timeout=timeout,
    )

    meta_tables: list[MetaTable] = []
    meta_table_by_identifier: dict[str, MetaTable] = {}
    for position, plan in enumerate(model_plans, start=1):
        catalog_row = catalog_rows_by_table_name[plan.table_name]
        meta_table = resolved_meta_tables[plan.table_name]
        _bind_model_meta_table(plan.model, meta_table)
        meta_tables.append(meta_table)
        meta_table_by_identifier[plan.table_name] = meta_table
        logger.debug(
            "Attached markets MetaTable from finalized catalog",
            model=plan.model.__name__,
            namespace=catalog_row.get("namespace"),
            table_name=catalog_row.get("table_name"),
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
    reserved_policy: str | None = None,
) -> MarketsRepositoryContext:
    _bind_model_meta_table(MarketsMetaTableCatalogTable, catalog_meta_table)
    return MarketsRepositoryContext(
        timeout=timeout,
        namespace=catalog_meta_table.namespace,
        reserved_policy=reserved_policy,
    )


def refresh_markets_catalog_from_registered_metatables(
    context: AlembicMetaTableCatalogRefreshContext,
) -> list[dict[str, Any]]:
    """Refresh the internal markets catalog after SDK provider registration."""

    from msm.migrations.registry import metatable_provider_models

    models = metatable_provider_models()
    registered_meta_tables = list(context.registered_metatables)
    if len(registered_meta_tables) != len(models):
        raise CatalogBootstrapError(
            "SDK provider registered a different number of MetaTables than the "
            f"markets migration model registry. Registered={len(registered_meta_tables)}, "
            f"expected={len(models)}."
        )

    registered_by_model = dict(zip(models, registered_meta_tables, strict=True))
    registered_catalog_meta_table = registered_by_model.get(MarketsMetaTableCatalogTable)
    if registered_catalog_meta_table is None:
        raise CatalogBootstrapError(
            "The markets migration provider must include MarketsMetaTableCatalogTable "
            "so catalog rows can be refreshed after registration."
        )

    catalog_context = catalog_repository_context(
        catalog_meta_table=registered_catalog_meta_table,
        reserved_policy=context.reserved_policy,
    )
    catalog_rows = [
        MarketsMetaTableCatalogRow.from_meta_table(
            model=model,
            meta_table=registered_meta_table,
            sdk_version=_sdk_version(),
        )
        for model, registered_meta_table in registered_by_model.items()
    ]
    return upsert_catalog_rows(catalog_context, rows=catalog_rows)


def find_catalog_row(
    context: MarketsRepositoryContext,
    *,
    model: type[MarketsBase],
) -> dict[str, Any] | None:
    table_name = _catalog_model_table_name(model)
    rows_by_table_name = find_catalog_rows_by_table_name(
        context,
        table_names=[table_name],
    )
    return rows_by_table_name.get(table_name)


def find_catalog_rows_by_table_name(
    context: MarketsRepositoryContext,
    *,
    table_names: Sequence[str],
) -> dict[str, dict[str, Any]]:
    requested_table_names = list(
        dict.fromkeys(str(table_name) for table_name in table_names if table_name)
    )
    if not requested_table_names:
        return {}

    result = search_model(
        context,
        model=MarketsMetaTableCatalogTable,
        in_filters={
            "table_name": sorted(requested_table_names),
        },
        limit=len(requested_table_names) * 2,
    )
    requested_table_name_set = set(requested_table_names)
    rows_by_table_name: dict[str, dict[str, Any]] = {}
    for row in _operation_result_rows(result):
        row_table_name = str(row.get("table_name") or "")
        if not row_table_name:
            raise CatalogBootstrapError(
                "Markets MetaTable catalog returned a row without table_name."
            )
        if row_table_name not in requested_table_name_set:
            continue
        if row_table_name in rows_by_table_name:
            raise CatalogBootstrapError(
                "Markets MetaTable catalog returned multiple rows for "
                f"table_name {row_table_name!r}. The catalog uniqueness invariant is broken."
            )
        rows_by_table_name[row_table_name] = row
    return rows_by_table_name


def meta_table_from_catalog_row(
    catalog_row: Mapping[str, Any],
    *,
    model: type[MarketsBase],
    management_mode: MarketsManagementMode,
) -> MetaTable:
    physical_table_name = markets_table_storage_name(model)
    return MetaTable(
        uid=str(catalog_row["meta_table_uid"]),
        namespace=str(catalog_row.get("namespace") or ""),
        identifier=str(catalog_row["table_name"]),
        description=catalog_row.get("description"),
        storage_hash=physical_table_name,
        physical_table_name=physical_table_name,
        management_mode=management_mode,
    )


def resolve_catalog_meta_tables(
    catalog_rows_by_table_name: Mapping[str, Mapping[str, Any]],
    *,
    model_plans: Sequence[_CatalogBootstrapModelPlan],
    management_mode: MarketsManagementMode,
    timeout: int | float | tuple[float, float] | None = None,
) -> dict[str, MetaTable]:
    uid_by_table_name = {
        plan.table_name: str(
            catalog_rows_by_table_name[plan.table_name].get("meta_table_uid") or ""
        )
        for plan in model_plans
    }
    missing_catalog_uid_table_names = [
        table_name for table_name, uid in uid_by_table_name.items() if not uid
    ]
    if missing_catalog_uid_table_names:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog has rows without meta_table_uid for "
            f"{missing_catalog_uid_table_names!r}."
        )
    duplicate_uids = sorted(
        {
            uid
            for uid in uid_by_table_name.values()
            if list(uid_by_table_name.values()).count(uid) > 1
        }
    )
    if duplicate_uids:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog maps multiple table names to the same "
            f"MetaTable UID(s) {duplicate_uids!r}."
        )
    requested_uids = list(dict.fromkeys(uid_by_table_name.values()))

    if not requested_uids:
        return {}

    logger.info(
        "Resolving cataloged markets MetaTables",
        meta_table_uid_count=len(requested_uids),
        model_count=len(model_plans),
        management_mode=management_mode,
    )
    meta_table_uids, time_index_meta_table_uids = _partition_catalog_uids_by_model_type(
        uid_by_table_name,
        model_plans=model_plans,
    )
    matches_by_uid: dict[str, MetaTable] = {}
    if meta_table_uids:
        _add_catalog_matches_by_uid(
            matches_by_uid,
            MetaTable.filter(
                timeout=timeout,
                uid__in=meta_table_uids,
                management_mode=management_mode,
            ),
        )
    if time_index_meta_table_uids:
        _add_catalog_matches_by_uid(
            matches_by_uid,
            TimeIndexMetaTable.filter(
                timeout=timeout,
                uid__in=time_index_meta_table_uids,
            ),
        )

    missing_uids = sorted(set(requested_uids) - set(matches_by_uid))
    if missing_uids:
        raise CatalogStaleMetaTableUidError(
            f"Markets MetaTable catalog rows point to missing backend MetaTables {missing_uids!r}."
        )

    resolved: dict[str, MetaTable] = {}
    for plan in model_plans:
        catalog_row = catalog_rows_by_table_name[plan.table_name]
        uid = str(catalog_row["meta_table_uid"])
        meta_table = matches_by_uid[uid]
        _validate_catalog_meta_table_identity(
            catalog_row,
            meta_table=meta_table,
            model=plan.model,
            management_mode=management_mode,
        )
        resolved[plan.table_name] = meta_table

    logger.info(
        "Resolved cataloged markets MetaTables",
        meta_table_count=len(resolved),
        model_count=len(model_plans),
        management_mode=management_mode,
    )
    return resolved


def _partition_catalog_uids_by_model_type(
    uid_by_table_name: Mapping[str, str],
    *,
    model_plans: Sequence[_CatalogBootstrapModelPlan],
) -> tuple[list[str], list[str]]:
    meta_table_uids: list[str] = []
    time_index_meta_table_uids: list[str] = []
    for plan in model_plans:
        uid = uid_by_table_name[plan.table_name]
        if is_time_index_meta_table_model(plan.model):
            time_index_meta_table_uids.append(uid)
        else:
            meta_table_uids.append(uid)
    return meta_table_uids, time_index_meta_table_uids


def _add_catalog_matches_by_uid(
    matches_by_uid: dict[str, MetaTable],
    matches: Sequence[MetaTable],
) -> None:
    for meta_table in matches:
        uid = _meta_table_uid(meta_table)
        if uid in matches_by_uid:
            raise CatalogBootstrapError(
                f"Multiple platform MetaTables matched catalog UID {uid!r}."
            )
        matches_by_uid[uid] = meta_table


def _validate_catalog_meta_table_identity(
    catalog_row: Mapping[str, Any],
    *,
    meta_table: MetaTable,
    model: type[MarketsBase],
    management_mode: MarketsManagementMode,
) -> None:
    expected_uid = str(catalog_row.get("meta_table_uid") or "")
    actual_uid = _meta_table_uid(meta_table)
    if actual_uid != expected_uid:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog UID mismatch for "
            f"{model.__name__}: catalog={expected_uid!r}, backend={actual_uid!r}."
        )

    expected_table_name = str(catalog_row.get("table_name") or "")
    actual_identifier = str(getattr(meta_table, "identifier", "") or "")
    if actual_identifier and actual_identifier != expected_table_name:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog table_name mismatch for "
            f"{model.__name__}: catalog={expected_table_name!r}, "
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

    actual_management_mode = str(getattr(meta_table, "management_mode", "") or "")
    if actual_management_mode and actual_management_mode != management_mode:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog management_mode mismatch for "
            f"{model.__name__}: expected={management_mode!r}, "
            f"backend={actual_management_mode!r}."
        )


def upsert_catalog_row(
    context: MarketsRepositoryContext,
    *,
    model: type[MarketsBase],
    meta_table: MetaTable,
) -> dict[str, Any]:
    row = MarketsMetaTableCatalogRow.from_meta_table(
        model=model,
        meta_table=meta_table,
        sdk_version=_sdk_version(),
    )
    return _upsert_catalog_payload(context, row.to_payload())


def upsert_catalog_rows(
    context: MarketsRepositoryContext,
    *,
    rows: Sequence[MarketsMetaTableCatalogRow],
) -> list[dict[str, Any]]:
    payloads = [row.to_payload() for row in rows]
    if not payloads:
        return []
    result = bulk_upsert_model(
        context,
        model=MarketsMetaTableCatalogTable,
        values=payloads,
        conflict_columns=[
            "table_name",
        ],
    )
    return _operation_result_rows(result)


def _upsert_catalog_payload(
    context: MarketsRepositoryContext,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return upsert_model(
        context,
        model=MarketsMetaTableCatalogTable,
        values=dict(payload),
        conflict_columns=[
            "table_name",
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
        "identifier": _catalog_model_table_name(model),
        "management_mode": management_mode,
    }
    if management_mode == "external_registered" and data_source_uid:
        base_filters["data_source__uid"] = data_source_uid

    return [_clean_filters(base_filters)]


def _clean_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if value not in (None, "")}


def _catalog_model_table_name(model: type[MarketsBase]) -> str:
    table_name = str(model.__table__.name)
    if not table_name:
        raise CatalogBootstrapError(
            f"Markets MetaTable model {model.__name__} does not expose catalog table_name."
        )
    return table_name


def _catalog_model_namespace(model: type[MarketsBase]) -> str:
    namespace = str(getattr(model, "__metatable_namespace__", "") or "")
    if not namespace:
        raise CatalogBootstrapError(
            f"Markets MetaTable model {model.__name__} does not expose catalog namespace."
        )
    return namespace


def _meta_table_uid(value: Any) -> str:
    return str(value.uid)


def _bind_model_meta_table(model: type[MarketsBase], meta_table: Any) -> None:
    model._bind_meta_table(meta_table)


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
    "find_catalog_rows_by_table_name",
    "meta_table_from_catalog_row",
    "refresh_markets_catalog_from_registered_metatables",
    "resolve_catalog_table",
    "resolve_catalog_meta_tables",
    "upsert_catalog_row",
    "upsert_catalog_rows",
]
