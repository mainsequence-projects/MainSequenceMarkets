from __future__ import annotations

from typing import Any

from mainsequence.client.metatables import MetaTable, TimeIndexMetaTable

from msm.models import AssetTable, IndexTable
from msm.services.indices.contracts import RelatedMetaTable

_CATALOG_PAGE_SIZE = 500


def list_reference_meta_tables(
    *,
    reference_type: str,
    numeric: bool = True,
    timestamped: bool = True,
) -> tuple[RelatedMetaTable, ...]:
    """List registered tables with an authoritative FK to Asset or Index identity."""

    if reference_type == "asset":
        target_model = AssetTable
        expected_source_column = "asset_identifier"
    elif reference_type == "index":
        target_model = IndexTable
        expected_source_column = "index_identifier"
    else:
        raise ValueError("reference_type must be 'asset' or 'index'")
    target_uid = _bound_uid(target_model)
    results: list[RelatedMetaTable] = []
    for meta_table in _all_meta_tables():
        if timestamped and not _is_timestamped(meta_table):
            continue
        for foreign_key in meta_table.foreign_keys:
            if not _matches_reference_fk(
                foreign_key,
                target_model=target_model,
                target_uid=target_uid,
                expected_source_column=expected_source_column,
            ):
                continue
            if numeric and not _has_numeric_observable(meta_table, expected_source_column):
                continue
            identifier = str(meta_table.identifier or meta_table.physical_table_name)
            results.append(
                RelatedMetaTable(
                    key=f"catalog:{meta_table.uid}:{expected_source_column}",
                    label=meta_table.description or identifier,
                    owning_package="unknown",
                    storage_kind="registered_reference_table",
                    meta_table_uid=str(meta_table.uid),
                    identifier=identifier,
                    relationship_type="registered_foreign_key",
                    join_kind="unique_identifier",
                    join_column=expected_source_column,
                    on_delete=str(foreign_key.on_delete or "UNKNOWN"),
                    authoritative=True,
                    discovery_source="inferred",
                    exploration_capability="values" if _is_timestamped(meta_table) else "count",
                    delete_capability="none",
                    confidence_reason=(
                        f"Registered MetaTable foreign key targets {reference_type}.unique_identifier."
                    ),
                )
            )
            break
    return tuple(sorted(results, key=lambda item: (item.identifier, item.meta_table_uid or "")))


def _all_meta_tables() -> tuple[MetaTable, ...]:
    results: list[MetaTable] = []
    offset = 0
    while True:
        page = list(MetaTable.filter_by_body(limit=_CATALOG_PAGE_SIZE, offset=offset))
        results.extend(page)
        if len(page) < _CATALOG_PAGE_SIZE:
            return tuple(results)
        offset += len(page)


def _matches_reference_fk(
    foreign_key: Any,
    *,
    target_model: type[Any],
    target_uid: str | None,
    expected_source_column: str,
) -> bool:
    if tuple(foreign_key.source_columns) != (expected_source_column,):
        return False
    if tuple(foreign_key.target_columns) != ("unique_identifier",):
        return False
    return bool(
        (target_uid and str(foreign_key.target_table_uid or "") == target_uid)
        or str(foreign_key.target_table_physical_table_name or "") == target_model.__table__.name
    )


def _is_timestamped(meta_table: MetaTable) -> bool:
    if meta_table.time_indexed is not None:
        return bool(meta_table.time_indexed)
    return isinstance(meta_table, TimeIndexMetaTable)


def _has_numeric_observable(meta_table: MetaTable, identity_column: str) -> bool:
    excluded = {"time_index", identity_column}
    excluded.update(
        source_column
        for foreign_key in meta_table.foreign_keys
        for source_column in foreign_key.source_columns
    )
    return any(
        column.name not in excluded and not column.primary_key and _is_numeric(column.data_type)
        for column in meta_table.columns
    )


def _is_numeric(value: Any) -> bool:
    normalized = " ".join(str(value or "").strip().lower().replace("_", " ").split())
    return normalized in {
        "int16",
        "int32",
        "int64",
        "smallint",
        "integer",
        "bigint",
        "float32",
        "float64",
        "float",
        "real",
        "double",
        "double precision",
        "numeric",
        "decimal",
    } or normalized.startswith(("numeric(", "decimal("))


def _bound_uid(model: type[Any]) -> str | None:
    getter = getattr(model, "get_meta_table_uid", None)
    value = getter() if callable(getter) else None
    return str(value) if value not in (None, "") else None


__all__ = ["list_reference_meta_tables"]
