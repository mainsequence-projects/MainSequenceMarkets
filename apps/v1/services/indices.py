from __future__ import annotations

import datetime as dt
from mainsequence.client.command_center.contracts.tabular import (
    TabularFrameResponse,
    build_tabular_field,
    build_tabular_frame,
)

from apps.v1.schemas.common import FrontEndDetailSummary
from apps.v1.schemas.delete_impact import DeleteImpactResponse
from apps.v1.schemas.indices import (
    Index,
    IndexBulkDeleteExecuteRequest,
    IndexBulkDeletePreview,
    IndexBulkDeletePreviewRequest,
    IndexBulkDeleteResult,
    IndexCreate,
    IndexDatasetDescriptor,
    IndexDatasetSummary,
    IndexMethodologyDetail,
    IndexMethodologySummary,
    IndexRelatedMetaTable,
    IndexType,
    IndexUpdate,
)
from msm.api.base import operation_result_rows
from msm.models import IndexTable, IndexTypeTable
from msm.repositories.crud import count_model, get_model_by_uid, search_model
from msm.services.indices import (
    IndexActor,
    IndexListRequest,
    IndexValueRow,
    dataset_summary,
    discover_canonical_datasets,
    execute_bulk_delete,
    get_canonical_dataset,
    get_index_summary as get_core_index_summary,
    get_methodology as get_core_methodology,
    list_indexes as list_core_indexes,
    list_methodologies as list_core_methodologies,
    list_related_meta_tables as list_core_related_meta_tables,
    preview_bulk_delete,
    read_index_values,
)


def list_indices(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    index_type: str | None = None,
    provider: str | None = None,
    has_definition: bool | None = None,
    has_canonical_values: bool | None = None,
    cadence: str | None = None,
) -> tuple[int, list[Index]]:
    runtime = _get_runtime()
    page = list_core_indexes(
        runtime.context,
        IndexListRequest(
            search=search,
            index_type=index_type,
            provider=provider,
            has_definition=has_definition,
            has_canonical_values=has_canonical_values,
            cadence=cadence,
            limit=limit,
            offset=offset,
        ),
    )
    return page.count, list(page.results)


def list_index_types(*, limit: int = 50, offset: int = 0) -> tuple[int, list[IndexType]]:
    runtime = _get_runtime()
    count_rows = operation_result_rows(count_model(runtime.context, model=IndexTypeTable))
    rows = operation_result_rows(
        search_model(
            runtime.context,
            model=IndexTypeTable,
            limit=limit,
            offset=offset,
        )
    )
    rows.sort(key=lambda item: (str(item["index_type"]), str(item["uid"])))
    return (
        int(count_rows[0].get("count") or 0) if count_rows else 0,
        [IndexType.model_validate(row) for row in rows],
    )


def get_index_type(*, index_type: str) -> IndexType | None:
    runtime = _get_runtime()
    rows = operation_result_rows(
        search_model(
            runtime.context,
            model=IndexTypeTable,
            filters={"index_type": index_type},
            limit=1,
        )
    )
    return IndexType.model_validate(rows[0]) if rows else None


def create_index(*, payload: IndexCreate) -> Index:
    return Index.create(payload)


def update_index(*, uid: str, payload: IndexUpdate) -> Index | None:
    if get_index(uid=uid) is None:
        return None
    return Index.update(uid, payload)


def get_index(*, uid: str) -> Index | None:
    runtime = _get_runtime()
    rows = operation_result_rows(get_model_by_uid(runtime.context, model=IndexTable, uid=uid))
    return Index.model_validate(rows[0]) if rows else None


def get_index_summary(*, uid: str, actor: IndexActor | None) -> FrontEndDetailSummary | None:
    runtime = _get_runtime()
    index = get_index(uid=uid)
    if index is None:
        return None
    summary = get_core_index_summary(runtime.context, index=index, actor=actor)
    active = summary.active_definition
    latest_values = [
        item for item in summary.dataset_summaries if item.latest_time_index is not None
    ]
    latest_values.sort(
        key=lambda item: item.latest_time_index or dt.datetime.min.replace(tzinfo=dt.UTC)
    )
    latest = latest_values[-1] if latest_values else None
    return FrontEndDetailSummary.model_validate(
        {
            "entity": {
                "id": str(index.uid),
                "type": "index",
                "title": index.display_name,
            },
            "badges": [
                {"key": "index_type", "label": index.index_type, "tone": "info"},
                {
                    "key": "methodology",
                    "label": "core-derived" if summary.definition_count else "plain",
                    "tone": "success" if summary.definition_count else "neutral",
                },
                *(
                    [{"key": "provider", "label": index.provider, "tone": "neutral"}]
                    if index.provider
                    else []
                ),
            ],
            "inline_fields": [
                {"key": "uid", "label": "UID", "value": str(index.uid), "kind": "text"},
                {
                    "key": "unique_identifier",
                    "label": "Unique identifier",
                    "value": index.unique_identifier,
                    "kind": "text",
                },
            ],
            "highlight_fields": [
                {
                    "key": "active_definition",
                    "label": "Active definition",
                    "value": active.definition_version if active else None,
                    "kind": "number",
                    "link_url": f"/api/v1/index/{uid}/methodologies/",
                },
                {
                    "key": "latest_value",
                    "label": "Latest value",
                    "value": latest.latest_value if latest else None,
                    "kind": "number",
                    "link_url": f"/api/v1/index/{uid}/datasets/",
                },
            ],
            "stats": [
                {
                    "key": "definitions",
                    "label": "Definitions",
                    "display": str(summary.definition_count),
                    "value": summary.definition_count,
                    "kind": "number",
                    "link_url": f"/api/v1/index/{uid}/methodologies/",
                },
                {
                    "key": "legs",
                    "label": "Legs",
                    "display": str(summary.leg_count),
                    "value": summary.leg_count,
                    "kind": "number",
                },
                {
                    "key": "datasets",
                    "label": "Canonical datasets",
                    "display": str(summary.dataset_count),
                    "value": summary.dataset_count,
                    "kind": "number",
                    "link_url": f"/api/v1/index/{uid}/datasets/",
                },
            ],
            "summary_warning": "; ".join(summary.warnings) or None,
            "extensions": {
                "cadences": list(summary.cadences),
                "dataset_summaries": [
                    item.model_dump(mode="json") for item in summary.dataset_summaries
                ],
                "authoritative_relationship_count": summary.authoritative_relationship_count,
                "inferred_relationship_count": summary.inferred_relationship_count,
                "related_meta_tables_url": f"/api/v1/index/{uid}/related-meta-tables/",
                "delete_preview_url": "/api/v1/index/bulk-delete/preview/",
                "update_url": f"/api/v1/index/{uid}/",
            },
        }
    )


def list_index_methodologies(*, uid: str) -> tuple[IndexMethodologySummary, ...] | None:
    if get_index(uid=uid) is None:
        return None
    return list_core_methodologies(_get_runtime().context, index_uid=uid)


def get_index_methodology(*, uid: str, definition_uid: str) -> IndexMethodologyDetail | None:
    if get_index(uid=uid) is None:
        return None
    return get_core_methodology(
        _get_runtime().context,
        index_uid=uid,
        definition_uid=definition_uid,
    )


def list_index_datasets(
    *, uid: str, actor: IndexActor | None
) -> tuple[IndexDatasetDescriptor, ...] | None:
    if get_index(uid=uid) is None:
        return None
    return discover_canonical_datasets(actor=actor)


def get_index_dataset_summary(
    *,
    uid: str,
    meta_table_uid: str,
    actor: IndexActor | None,
) -> IndexDatasetSummary | None:
    index = get_index(uid=uid)
    if index is None:
        return None
    dataset = get_canonical_dataset(meta_table_uid, actor=actor)
    if dataset is None:
        raise LookupError(f"Canonical Index dataset {meta_table_uid!r} was not found")
    return dataset_summary(_get_runtime().context, index=index, dataset=dataset)


def get_index_values_frame(
    *,
    uid: str,
    meta_table_uid: str,
    start: dt.datetime,
    end: dt.datetime,
    order: str,
    limit: int,
    actor: IndexActor | None,
) -> TabularFrameResponse | None:
    index = get_index(uid=uid)
    if index is None:
        return None
    dataset = get_canonical_dataset(meta_table_uid, actor=actor)
    if dataset is None:
        raise LookupError(f"Canonical Index dataset {meta_table_uid!r} was not found")
    values = read_index_values(
        _get_runtime().context,
        index=index,
        dataset=dataset,
        start=start,
        end=end,
        order=order,
        limit=limit,
    )
    columns = [
        "time_index",
        "index_identifier",
        "value",
        "unit",
        "definition_uid",
        "observation_status",
        "source_as_of",
        "metadata_json",
    ]
    field_types = {
        "time_index": "datetime",
        "index_identifier": "string",
        "value": "number",
        "unit": "string",
        "definition_uid": "string",
        "observation_status": "string",
        "source_as_of": "datetime",
        "metadata_json": "json",
    }
    return build_tabular_frame(
        columns=columns,
        rows=[_index_value_tabular_row(row) for row in values.rows],
        fields=[
            build_tabular_field(
                key=column,
                label=column.replace("_", " ").title(),
                field_type=field_types[column],
                nullable=column not in {"time_index", "index_identifier", "value", "unit"},
            )
            for column in columns
        ],
        meta={
            "timeSeries": {
                "shape": "long",
                "timeField": "time_index",
                "valueField": "value",
                "seriesField": "index_identifier",
                "sorted": True,
                "frequency": dataset.cadence,
            }
        },
        source={
            "kind": "api",
            "id": "getIndexDatasetValuesFrame",
            "label": dataset.identifier,
            "context": {
                "index_uid": str(index.uid),
                "index_identifier": index.unique_identifier,
                "meta_table_uid": dataset.meta_table_uid,
                "cadence": dataset.cadence,
            },
        },
    )


def _index_value_tabular_row(row: IndexValueRow) -> dict[str, object]:
    payload = row.model_dump(mode="json")
    payload["time_index"] = int(row.time_index.timestamp() * 1000)
    if row.source_as_of is not None:
        payload["source_as_of"] = int(row.source_as_of.timestamp() * 1000)
    return payload


def list_index_related_meta_tables(*, uid: str) -> tuple[IndexRelatedMetaTable, ...] | None:
    index = get_index(uid=uid)
    if index is None:
        return None
    return list_core_related_meta_tables(_get_runtime().context, index=index)


def preview_index_bulk_delete(
    *,
    payload: IndexBulkDeletePreviewRequest,
    actor: IndexActor,
) -> IndexBulkDeletePreview:
    return preview_bulk_delete(_get_runtime().context, actor=actor, request=payload)


def execute_index_bulk_delete(
    *,
    payload: IndexBulkDeleteExecuteRequest,
    actor: IndexActor,
    expected_single_index_uid: str | None = None,
) -> IndexBulkDeleteResult:
    return execute_bulk_delete(
        _get_runtime().context,
        actor=actor,
        request=payload,
        expected_single_index_uid=expected_single_index_uid,
    )


def get_index_delete_impact(*, uid: str) -> DeleteImpactResponse | None:
    index = get_index(uid=uid)
    if index is None:
        return None
    relationships = list_core_related_meta_tables(_get_runtime().context, index=index)
    relationship_rows = [
        {
            "key": item.key,
            "label": item.label,
            "model": item.identifier,
            "column": item.join_column or "indirect",
            "relationship_type": item.relationship_type,
            "on_delete": item.on_delete,
            "count": int(item.count or 0),
            "effect": _delete_effect(item),
            "severity": "blocking" if item.blocks_delete else "informational",
            "blocks_delete": item.blocks_delete,
            "description": (
                "Authoritative declared Index relationship. Preview the reviewed bulk plan "
                "for cadence-specific value impacts."
            ),
        }
        for item in relationships
    ]
    blocking_count = sum(item["count"] for item in relationship_rows if item["blocks_delete"])
    warnings = [
        "This compatibility view does not authorize deletion; use bulk-delete preview and execution."
    ]
    if blocking_count:
        warnings.append(
            "Delete is blocked while authoritative dependent rows reference this Index."
        )
    return DeleteImpactResponse.model_validate(
        {
            "resource_type": "index",
            "uid": index.uid,
            "identifier": index.unique_identifier,
            "display_name": index.display_name,
            "can_delete": blocking_count == 0,
            "blocking_count": blocking_count,
            "affected_count": sum(item["count"] for item in relationship_rows),
            "delete_endpoint": "/api/v1/index/bulk-delete/",
            "relationships": relationship_rows,
            "warnings": warnings,
        }
    )


def _delete_effect(item: IndexRelatedMetaTable) -> str:
    if item.blocks_delete:
        return "blocks_cascade"
    if item.delete_capability == "cascade":
        return "cascade_delete"
    if item.delete_capability == "set_null":
        return "set_null"
    if item.delete_capability == "manual":
        return "manual_cleanup_required"
    return "none"


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "IndexType",
            "Index",
            "IndexCalculationDefinition",
            "IndexCalculationLeg",
            "IndexDeletionExecution",
            "IndexResolvedLegsStorage",
        ],
        row_model_name="Index apps/v1",
    )


__all__ = [name for name in globals() if not name.startswith("_")]
