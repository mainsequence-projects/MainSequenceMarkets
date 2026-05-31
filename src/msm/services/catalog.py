from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any

from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import delete_model, get_model_by_uid, search_model

DEFAULT_CATALOG_PAGE_SIZE = 25
MAX_CATALOG_SCAN_LIMIT = 500


class CatalogTableNotFoundError(LookupError):
    """Raised when a catalogue entry cannot be found."""


class CatalogTableUnsupportedError(RuntimeError):
    """Raised when a catalogue entry cannot be resolved to a local model."""


def catalog_repository_context(
    *,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRepositoryContext:
    from msm.maintenance.catalog import bootstrap_catalog_table, catalog_repository_context

    catalog_meta_table = bootstrap_catalog_table(timeout=timeout)
    return catalog_repository_context(
        catalog_meta_table=catalog_meta_table,
        timeout=timeout,
    )


def list_catalog_tables(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    limit: int = DEFAULT_CATALOG_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    from msm.maintenance.models import MarketsMetaTableCatalogTable

    scan_limit = _scan_limit(offset=offset, limit=limit)
    catalog_rows = _operation_result_rows(
        search_model(
            context,
            model=MarketsMetaTableCatalogTable,
            limit=scan_limit,
        )
    )
    normalized_rows = [_build_catalog_list_row(row) for row in catalog_rows]
    normalized_rows.sort(
        key=lambda row: (
            str(row["namespace"]).lower(),
            str(row["identifier"]).lower(),
            str(row["model_name"]).lower(),
            str(row["uid"]),
        )
    )

    normalized_search = search.strip().lower()
    if normalized_search:
        normalized_rows = [
            row
            for row in normalized_rows
            if _matches_search(
                values=(
                    row.get("uid"),
                    row.get("namespace"),
                    row.get("identifier"),
                    row.get("description"),
                    row.get("model_name"),
                    row.get("meta_table_uid"),
                ),
                normalized_search=normalized_search,
            )
        ]

    return {
        "results": normalized_rows[offset : offset + limit],
        "limit": limit,
        "offset": offset,
    }


def list_catalog_table_rows(
    context: MarketsRepositoryContext,
    *,
    catalog_uid: str,
    search: str = "",
    limit: int = DEFAULT_CATALOG_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    catalog_row = _get_catalog_row(context, catalog_uid=catalog_uid)
    model = _resolve_supported_catalog_model(catalog_row)
    row_context = _row_context_for_catalog_row(
        catalog_context=context,
        catalog_row=catalog_row,
        model=model,
    )

    scan_limit = _scan_limit(offset=offset, limit=limit)
    raw_rows = _operation_result_rows(search_model(row_context, model=model, limit=scan_limit))
    rows = [
        _build_catalog_table_row(row)
        for row in raw_rows
        if isinstance(row, Mapping) and row.get("uid") not in (None, "")
    ]

    normalized_search = search.strip().lower()
    if normalized_search:
        rows = [
            row
            for row in rows
            if _matches_search(
                values=row["values"].values(),
                normalized_search=normalized_search,
            )
        ]

    return {
        "catalog": _build_catalog_reference(catalog_row),
        "columns": _build_catalog_columns(model),
        "results": rows[offset : offset + limit],
        "limit": limit,
        "offset": offset,
    }


def delete_catalog_table_row(
    context: MarketsRepositoryContext,
    *,
    catalog_uid: str,
    uid: str,
) -> dict[str, Any]:
    catalog_row = _get_catalog_row(context, catalog_uid=catalog_uid)
    model = _resolve_supported_catalog_model(catalog_row)
    row_context = _row_context_for_catalog_row(
        catalog_context=context,
        catalog_row=catalog_row,
        model=model,
    )

    existing_rows = _operation_result_rows(get_model_by_uid(row_context, model=model, uid=uid))
    if not existing_rows:
        return {
            "detail": "Catalog row was not found.",
            "catalog_uid": str(catalog_row["uid"]),
            "meta_table_uid": str(catalog_row["meta_table_uid"]),
            "uid": str(uid),
            "deleted_count": 0,
            "cascade": True,
        }

    delete_model(row_context, model=model, uid=uid)
    return {
        "detail": "Deleted catalogue row.",
        "catalog_uid": str(catalog_row["uid"]),
        "meta_table_uid": str(catalog_row["meta_table_uid"]),
        "uid": str(uid),
        "deleted_count": 1,
        "cascade": True,
    }


def _get_catalog_row(
    context: MarketsRepositoryContext,
    *,
    catalog_uid: str,
) -> dict[str, Any]:
    from msm.maintenance.models import MarketsMetaTableCatalogTable

    rows = _operation_result_rows(
        get_model_by_uid(
            context,
            model=MarketsMetaTableCatalogTable,
            uid=catalog_uid,
        )
    )
    if not rows:
        raise CatalogTableNotFoundError(f"Catalog table {catalog_uid!r} was not found.")
    return rows[0]


def _build_catalog_list_row(row: Mapping[str, Any]) -> dict[str, Any]:
    row_uid = _string_value(row.get("uid"))
    supported = _catalog_model_is_supported(row)
    return {
        "uid": row_uid,
        "namespace": _string_value(row.get("namespace")),
        "identifier": _string_value(row.get("identifier")),
        "description": _optional_string(row.get("description")),
        "model_name": _string_value(row.get("model_name")),
        "meta_table_uid": _string_value(row.get("meta_table_uid")),
        "contract_hash": _string_value(row.get("contract_hash")),
        "sdk_version": _optional_string(row.get("sdk_version")),
        "created_at": _datetime_string(row.get("created_at")),
        "updated_at": _datetime_string(row.get("updated_at")),
        "supports_row_listing": supported,
        "supports_row_delete": supported,
        "rows_endpoint": f"/api/v1/catalog/{row_uid}/rows/" if supported else None,
        "delete_endpoint_template": (
            f"/api/v1/catalog/{row_uid}/rows/{{uid}}/" if supported else None
        ),
    }


def _build_catalog_reference(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": _string_value(row.get("uid")),
        "identifier": _string_value(row.get("identifier")),
        "model_name": _string_value(row.get("model_name")),
        "meta_table_uid": _string_value(row.get("meta_table_uid")),
    }


def _build_catalog_columns(model: type[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": column.name,
            "type": str(column.type),
            "nullable": bool(column.nullable),
            "primary_key": bool(column.primary_key),
        }
        for column in model.__table__.columns
    ]


def _build_catalog_table_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": _string_value(row.get("uid")),
        "values": {str(key): _json_value(value) for key, value in row.items()},
    }


def _row_context_for_catalog_row(
    *,
    catalog_context: MarketsRepositoryContext,
    catalog_row: Mapping[str, Any],
    model: type[Any],
) -> MarketsRepositoryContext:
    from msm.models.registration import markets_meta_table_identifier

    return MarketsRepositoryContext(
        target_meta_table_uid_by_identifier={
            markets_meta_table_identifier(model): _string_value(catalog_row.get("meta_table_uid"))
        },
        limits=catalog_context.limits,
        timeout=catalog_context.timeout,
        namespace=catalog_context.namespace,
    )


def _catalog_model_is_supported(row: Mapping[str, Any]) -> bool:
    try:
        _resolve_supported_catalog_model(row)
    except CatalogTableUnsupportedError:
        return False
    return True


def _resolve_supported_catalog_model(row: Mapping[str, Any]) -> type[Any]:
    from msm.models.registration import resolve_markets_meta_table_model

    model_name = _string_value(row.get("model_name"))
    try:
        model = resolve_markets_meta_table_model(model_name)
    except ValueError as exc:
        raise CatalogTableUnsupportedError(
            f"Catalog table {model_name!r} cannot be resolved to a local markets model."
        ) from exc

    if "uid" not in model.__table__.c:
        raise CatalogTableUnsupportedError(
            f"Catalog table {model_name!r} cannot be listed or deleted because it has no uid column."
        )
    return model


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


def _scan_limit(*, offset: int, limit: int) -> int:
    return min(max(offset + limit, limit, DEFAULT_CATALOG_PAGE_SIZE), MAX_CATALOG_SCAN_LIMIT)


def _matches_search(*, values: Any, normalized_search: str) -> bool:
    return any(
        normalized_search in str(value).lower() for value in values if value not in (None, "")
    )


def _datetime_string(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    return _string_value(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    return value


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _string_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


__all__ = [
    "CatalogTableNotFoundError",
    "CatalogTableUnsupportedError",
    "catalog_repository_context",
    "delete_catalog_table_row",
    "list_catalog_table_rows",
    "list_catalog_tables",
]
