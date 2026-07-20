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
    IndexCreate,
    IndexDatasetState,
    IndexDatasetSummary,
    IndexFormulaDetail,
    IndexFormulaSummary,
    RelatedMetaTable,
    IndexType,
    IndexUpdate,
)
from msm.api.base import operation_result_rows
from msm.models import IndexTable, IndexTypeTable
from msm.repositories.crud import get_model_by_uid, search_model
from msm.services.indices import (
    IndexActor,
    IndexListRequest,
    IndexValueRow,
    dataset_summary,
    get_canonical_dataset,
    get_index_summary as get_core_index_summary,
    get_index_delete_impact as get_core_index_delete_impact,
    get_formula as get_core_formula,
    list_indexes as list_core_indexes,
    list_index_types as list_core_index_types,
    list_dataset_states,
    list_formulas as list_core_formulas,
    list_related_meta_tables as list_core_related_meta_tables,
    read_index_values,
)


def list_indices(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    index_type: str | None = None,
    has_formula: bool | None = None,
    has_canonical_values: bool | None = None,
    cadence: str | None = None,
) -> tuple[int, list[Index]]:
    runtime = _get_runtime()
    page = list_core_indexes(
        runtime.context,
        IndexListRequest(
            search=search,
            index_type=index_type,
            has_formula=has_formula,
            has_canonical_values=has_canonical_values,
            cadence=cadence,
            limit=limit,
            offset=offset,
        ),
    )
    return page.count, list(page.results)


def list_index_types(*, limit: int = 50, offset: int = 0) -> tuple[int, list[IndexType]]:
    runtime = _get_runtime()
    count, rows = list_core_index_types(runtime.context, limit=limit, offset=offset)
    return count, list(rows)


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


def delete_index(*, uid: str) -> bool:
    from msm.services import delete_index_record

    return delete_index_record(_get_runtime().context, uid=uid)


def get_index_summary(*, uid: str, actor: IndexActor | None) -> FrontEndDetailSummary | None:
    runtime = _get_runtime()
    index = get_index(uid=uid)
    if index is None:
        return None
    summary = get_core_index_summary(runtime.context, index=index, actor=actor)
    active = summary.active_formula
    latest_observation = max(
        (
            state.latest_time_index
            for state in summary.dataset_states
            if state.population_state == "populated" and state.latest_time_index is not None
        ),
        default=None,
    )
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
                    "key": "calculation_method",
                    "label": index.calculation_method,
                    "tone": "success" if index.calculation_method == "formula" else "neutral",
                },
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
                    "key": "active_formula",
                    "label": "Active formula",
                    "value": active.version if active else None,
                    "kind": "number",
                    "link_url": f"/api/v1/index/{uid}/formulas/",
                },
                {
                    "key": "latest_observation",
                    "label": "Latest observation",
                    "value": latest_observation.isoformat() if latest_observation else None,
                    "kind": "datetime",
                    "link_url": f"/api/v1/index/{uid}/datasets/",
                },
            ],
            "stats": [
                {
                    "key": "formulas",
                    "label": "Formulas",
                    "display": str(summary.formula_count),
                    "value": summary.formula_count,
                    "kind": "number",
                    "link_url": f"/api/v1/index/{uid}/formulas/",
                },
                {
                    "key": "inputs",
                    "label": "Inputs",
                    "display": str(summary.input_count),
                    "value": summary.input_count,
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
                "dataset_states": [item.model_dump(mode="json") for item in summary.dataset_states],
                "authoritative_relationship_count": summary.authoritative_relationship_count,
                "inferred_relationship_count": summary.inferred_relationship_count,
                "related_meta_tables_url": f"/api/v1/index/{uid}/related-meta-tables/",
                "delete_preview_url": f"/api/v1/index/{uid}/delete-impact/",
                "update_url": f"/api/v1/index/{uid}/",
            },
        }
    )


def list_index_formulas(*, uid: str) -> tuple[IndexFormulaSummary, ...] | None:
    if get_index(uid=uid) is None:
        return None
    return list_core_formulas(_get_runtime().context, index_uid=uid)


def get_index_formula(*, uid: str, definition_uid: str) -> IndexFormulaDetail | None:
    if get_index(uid=uid) is None:
        return None
    return get_core_formula(
        _get_runtime().context,
        index_uid=uid,
        definition_uid=definition_uid,
    )


def list_index_datasets(
    *, uid: str, actor: IndexActor | None, include_empty: bool = False
) -> tuple[IndexDatasetState, ...] | None:
    index = get_index(uid=uid)
    if index is None:
        return None
    return list_dataset_states(
        _get_runtime().context,
        index=index,
        actor=actor,
        include_empty=include_empty,
    )


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
        "definition_uid",
        "observation_status",
        "source_as_of",
        "metadata_json",
    ]
    field_types = {
        "time_index": "datetime",
        "index_identifier": "string",
        "value": "number",
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
                nullable=column not in {"time_index", "index_identifier", "value"},
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
                "value_format": index.value_format,
                "value_suffix": index.value_suffix,
            },
        },
    )


def _index_value_tabular_row(row: IndexValueRow) -> dict[str, object]:
    payload = row.model_dump(mode="json")
    payload["time_index"] = int(row.time_index.timestamp() * 1000)
    if row.source_as_of is not None:
        payload["source_as_of"] = int(row.source_as_of.timestamp() * 1000)
    return payload


def list_index_related_meta_tables(
    *,
    uid: str,
    numeric: bool = True,
    timestamped: bool = True,
) -> tuple[RelatedMetaTable, ...] | None:
    index = get_index(uid=uid)
    if index is None:
        return None
    return list_core_related_meta_tables(
        _get_runtime().context,
        index=index,
        numeric=numeric,
        timestamped=timestamped,
    )


def get_index_delete_impact(*, uid: str) -> DeleteImpactResponse | None:
    index = get_index(uid=uid)
    if index is None:
        return None
    impact = get_core_index_delete_impact(_get_runtime().context, index=index)
    return DeleteImpactResponse.model_validate(impact.model_dump())


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=[
            "IndexType",
            "Index",
            "IndexFormulaDefinition",
            "IndexFormulaInput",
            "IndexDatasetAvailability",
            "Asset",
        ],
        row_model_name="Index apps/v1",
    )


__all__ = [name for name in globals() if not name.startswith("_")]
