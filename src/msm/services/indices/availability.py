from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from msm.api.base import operation_result_rows
from msm.api.indices import Index
from msm.models import IndexDatasetAvailabilityTable, IndexTable
from msm.repositories.base import (
    MarketsOperationContext,
    compile_markets_statement,
    execute_markets_operation,
)
from msm.repositories.crud import search_model, upsert_model

from .contracts import (
    IndexActor,
    IndexDatasetDescriptor,
    IndexDatasetReconciliationResult,
    IndexDatasetState,
)


def list_dataset_states(
    context: MarketsOperationContext,
    *,
    index: Index,
    actor: IndexActor | None = None,
    include_empty: bool = False,
) -> tuple[IndexDatasetState, ...]:
    """Return reconciled population states for one Index."""

    from .catalog import discover_canonical_datasets

    descriptors = {
        item.meta_table_uid: item for item in discover_canonical_datasets(actor=actor)
    }
    rows = operation_result_rows(
        search_model(
            context,
            model=IndexDatasetAvailabilityTable,
            filters={"index_uid": index.uid},
            limit=500,
        )
    )
    states: list[IndexDatasetState] = []
    for row in rows:
        descriptor = descriptors.get(str(row["meta_table_uid"]))
        if descriptor is None:
            continue
        state = _state_from_row(index=index, dataset=descriptor, row=row)
        if state.population_state == "compatible_empty" and not include_empty:
            continue
        states.append(state)
    return tuple(
        sorted(states, key=lambda item: (item.dataset.cadence, item.dataset.meta_table_uid))
    )


def reconcile_index_dataset_availability(
    context: MarketsOperationContext,
    *,
    index_uids: Sequence[uuid.UUID | str] = (),
    index_identifiers: Sequence[str] = (),
    actor: IndexActor | None = None,
) -> IndexDatasetReconciliationResult:
    """Reconcile a bounded set of Indexes against every visible canonical contract."""

    from .catalog import _dataset_model_and_handle, discover_canonical_datasets

    normalized_uids = tuple(dict.fromkeys(uuid.UUID(str(item)) for item in index_uids))
    normalized_identifiers = tuple(
        dict.fromkeys(str(item).strip() for item in index_identifiers if str(item).strip())
    )
    if not normalized_uids and not normalized_identifiers:
        raise ValueError("availability reconciliation requires explicit Index UIDs or identifiers")
    if len(normalized_uids) + len(normalized_identifiers) > 500:
        raise ValueError("availability reconciliation accepts at most 500 Index selectors")

    statement = select(IndexTable)
    if normalized_uids and normalized_identifiers:
        from sqlalchemy import or_

        statement = statement.where(
            or_(
                IndexTable.uid.in_(normalized_uids),
                IndexTable.unique_identifier.in_(normalized_identifiers),
            )
        )
    elif normalized_uids:
        statement = statement.where(IndexTable.uid.in_(normalized_uids))
    else:
        statement = statement.where(IndexTable.unique_identifier.in_(normalized_identifiers))
    rows = operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                statement,
                context=context,
                operation="select",
                models=[IndexTable],
                access="read",
            ),
            context=context,
        )
    )
    indexes = tuple(Index.model_validate(row) for row in rows)
    resolved_uids = {index.uid for index in indexes}
    resolved_identifiers = {index.unique_identifier for index in indexes}
    missing_uids = set(normalized_uids) - resolved_uids
    missing_identifiers = set(normalized_identifiers) - resolved_identifiers
    if missing_uids or missing_identifiers:
        raise LookupError(
            "availability reconciliation selectors were not found: "
            f"uids={sorted(map(str, missing_uids))}, "
            f"identifiers={sorted(missing_identifiers)}"
        )

    datasets = discover_canonical_datasets(actor=actor)
    reconciled: list[IndexDatasetState] = []
    for dataset in datasets:
        try:
            model, handle = _dataset_model_and_handle(context, dataset)
        except Exception as exc:
            for index in indexes:
                reconciled.append(
                    _write_unavailable(
                        context,
                        index=index,
                        dataset=dataset,
                        error=exc,
                    )
                )
            continue
        statement = (
            select(
                model.index_identifier,
                func.count().label("row_count"),
                func.min(model.time_index).label("earliest_time_index"),
                func.max(model.time_index).label("latest_time_index"),
            )
            .where(
                model.index_identifier.in_(
                    [index.unique_identifier for index in indexes]
                )
            )
            .group_by(model.index_identifier)
        )
        try:
            aggregate_rows = operation_result_rows(
                execute_markets_operation(
                    compile_markets_statement(
                        statement,
                        context=handle,
                        operation="select",
                        models=[model],
                        access="read",
                    ),
                    context=handle,
                )
            )
        except Exception as exc:
            for index in indexes:
                reconciled.append(
                    _write_unavailable(
                        context,
                        index=index,
                        dataset=dataset,
                        error=exc,
                    )
                )
            continue
        aggregates = {str(row["index_identifier"]): row for row in aggregate_rows}
        for index in indexes:
            reconciled.append(
                _write_population(
                    context,
                    index=index,
                    dataset=dataset,
                    aggregate=aggregates.get(index.unique_identifier, {}),
                )
            )
    return IndexDatasetReconciliationResult(
        index_uids=tuple(index.uid for index in indexes),
        dataset_count=len(datasets),
        states=tuple(reconciled),
    )


def _write_population(
    context: MarketsOperationContext,
    *,
    index: Index,
    dataset: IndexDatasetDescriptor,
    aggregate: dict,
) -> IndexDatasetState:
    row_count = int(aggregate.get("row_count") or 0)
    values = {
        "uid": uuid.uuid4(),
        "index_uid": index.uid,
        "meta_table_uid": dataset.meta_table_uid,
        "cadence": dataset.cadence,
        "population_state": "populated" if row_count else "compatible_empty",
        "row_count": row_count,
        "earliest_time_index": aggregate.get("earliest_time_index"),
        "latest_time_index": aggregate.get("latest_time_index"),
        "reconciled_at": dt.datetime.now(dt.UTC),
        "error_code": None,
        "error_message": None,
    }
    result = upsert_model(
        context,
        model=IndexDatasetAvailabilityTable,
        values=values,
        conflict_columns=("index_uid", "meta_table_uid"),
    )
    persisted = operation_result_rows(result)
    row = persisted[0] if persisted else values
    return _state_from_row(index=index, dataset=dataset, row=row)


def _write_unavailable(
    context: MarketsOperationContext,
    *,
    index: Index,
    dataset: IndexDatasetDescriptor,
    error: Exception,
) -> IndexDatasetState:
    values = {
        "uid": uuid.uuid4(),
        "index_uid": index.uid,
        "meta_table_uid": dataset.meta_table_uid,
        "cadence": dataset.cadence,
        "population_state": "unavailable",
        "row_count": None,
        "earliest_time_index": None,
        "latest_time_index": None,
        "reconciled_at": dt.datetime.now(dt.UTC),
        "error_code": type(error).__name__[:128],
        "error_message": str(error)[:1024],
    }
    result = upsert_model(
        context,
        model=IndexDatasetAvailabilityTable,
        values=values,
        conflict_columns=("index_uid", "meta_table_uid"),
    )
    persisted = operation_result_rows(result)
    row = persisted[0] if persisted else values
    return _state_from_row(index=index, dataset=dataset, row=row)


def _state_from_row(
    *,
    index: Index,
    dataset: IndexDatasetDescriptor,
    row: dict,
) -> IndexDatasetState:
    error = row.get("error_message")
    if error and row.get("error_code"):
        error = f"{row['error_code']}: {error}"
    return IndexDatasetState(
        dataset=dataset,
        index_uid=index.uid,
        index_identifier=index.unique_identifier,
        population_state=row["population_state"],
        row_count=row.get("row_count"),
        earliest_time_index=row.get("earliest_time_index"),
        latest_time_index=row.get("latest_time_index"),
        reconciled_at=row["reconciled_at"],
        error=error,
    )


__all__ = ["list_dataset_states", "reconcile_index_dataset_availability"]
