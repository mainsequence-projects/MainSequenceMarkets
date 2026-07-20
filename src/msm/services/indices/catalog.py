from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Float, Integer, Numeric, String, and_, cast, exists, func, or_, select

from mainsequence.client.metatables import MetaTable, TimeIndexMetaTable

from msm.api.base import operation_result_rows
from msm.api.indices import Index, IndexType
from msm.analytics.indices import IndexFormulaInput
from msm.data_nodes.indices.storage import (
    INDEX_VALUES_CADENCE_COMPONENT,
    INDEX_VALUES_STORAGE_NAME_COMPONENT,
    configured_index_values_storage,
)
from msm.models import (
    AssetTable,
    IndexDatasetAvailabilityTable,
    IndexFormulaDefinitionTable,
    IndexFormulaInputTable,
    IndexTable,
    IndexTypeTable,
)
from msm.repositories.base import (
    MarketsMetaTableHandle,
    MarketsOperationContext,
    compile_markets_statement,
    execute_markets_operation,
)
from msm.repositories.crud import count_model, get_model_by_uid, search_model

from .contracts import (
    IndexActor,
    IndexDatasetAccess,
    IndexDatasetDescriptor,
    IndexDatasetSummary,
    IndexDetail,
    IndexForeignKeyDescriptor,
    IndexListRequest,
    IndexFormulaDetail,
    IndexFormulaSummary,
    IndexPage,
    RelatedMetaTable,
    IndexSummary,
    IndexValueRow,
    IndexValuesResult,
)
from .relationships import list_index_relationship_providers, require_index_foreign_key


def list_indexes(context: MarketsOperationContext, request: IndexListRequest) -> IndexPage:
    """Return an authoritative, stable page from the canonical Index table."""

    statement = select(IndexTable)
    models: list[type[Any]] = [IndexTable]
    conditions: list[Any] = []
    if request.search.strip():
        needle = f"%{request.search.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(cast(IndexTable.uid, String)).like(needle),
                func.lower(IndexTable.unique_identifier).like(needle),
                func.lower(IndexTable.display_name).like(needle),
                func.lower(func.coalesce(IndexTable.description, "")).like(needle),
            )
        )
    if request.uids:
        conditions.append(IndexTable.uid.in_(request.uids))
    if request.unique_identifiers:
        conditions.append(IndexTable.unique_identifier.in_(request.unique_identifiers))
    if request.index_type:
        conditions.append(IndexTable.index_type == request.index_type)
    if request.has_formula is not None:
        models.append(IndexFormulaDefinitionTable)
        formula_exists = exists(
            select(IndexFormulaDefinitionTable.uid).where(
                IndexFormulaDefinitionTable.index_uid == IndexTable.uid
            )
        )
        conditions.append(formula_exists if request.has_formula else ~formula_exists)

    if request.has_canonical_values is not None or request.cadence:
        models.append(IndexDatasetAvailabilityTable)
        availability_conditions = [
            IndexDatasetAvailabilityTable.index_uid == IndexTable.uid,
            IndexDatasetAvailabilityTable.population_state == "populated",
        ]
        if request.cadence:
            availability_conditions.append(
                IndexDatasetAvailabilityTable.cadence == request.cadence.strip().lower()
            )
        populated_exists = exists(
            select(IndexDatasetAvailabilityTable.uid).where(*availability_conditions)
        )
        conditions.append(
            ~populated_exists if request.has_canonical_values is False else populated_exists
        )
    if conditions:
        statement = statement.where(and_(*conditions))

    order_column = {
        "display_name": IndexTable.display_name,
        "unique_identifier": IndexTable.unique_identifier,
        "index_type": IndexTable.index_type,
        "calculation_method": IndexTable.calculation_method,
    }[request.order]
    statement = statement.order_by(
        func.lower(func.coalesce(order_column, "")),
        IndexTable.unique_identifier,
        IndexTable.uid,
    )
    count_statement = select(func.count().label("count")).select_from(statement.subquery())
    count_result = execute_markets_operation(
        compile_markets_statement(
            count_statement,
            context=context,
            operation="select",
            models=models,
            access="read",
        ),
        context=context,
    )
    page_statement = statement.limit(request.limit).offset(request.offset)
    page_result = execute_markets_operation(
        compile_markets_statement(
            page_statement,
            context=context,
            operation="select",
            models=models,
            access="read",
        ),
        context=context,
    )
    count_rows = operation_result_rows(count_result)
    return IndexPage(
        count=int(count_rows[0].get("count") or 0) if count_rows else 0,
        limit=request.limit,
        offset=request.offset,
        results=tuple(Index.model_validate(row) for row in operation_result_rows(page_result)),
    )


def list_index_types(
    context: MarketsOperationContext,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, tuple[IndexType, ...]]:
    """Return Index types with deterministic ordering applied before pagination."""

    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset must be nonnegative")
    base = select(IndexTypeTable).order_by(
        func.lower(IndexTypeTable.index_type),
        IndexTypeTable.uid,
    )
    count_statement = select(func.count().label("count")).select_from(base.subquery())
    count_rows = operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                count_statement,
                context=context,
                operation="select",
                models=[IndexTypeTable],
                access="read",
            ),
            context=context,
        )
    )
    page_rows = operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                base.limit(limit).offset(offset),
                context=context,
                operation="select",
                models=[IndexTypeTable],
                access="read",
            ),
            context=context,
        )
    )
    return (
        int(count_rows[0].get("count") or 0) if count_rows else 0,
        tuple(IndexType.model_validate(row) for row in page_rows),
    )


def list_formulas(
    context: MarketsOperationContext,
    *,
    index_uid: uuid.UUID | str,
) -> tuple[IndexFormulaSummary, ...]:
    definition_rows = operation_result_rows(
        search_model(
            context,
            model=IndexFormulaDefinitionTable,
            filters={"index_uid": uuid.UUID(str(index_uid))},
            limit=500,
        )
    )
    definition_uids = [row["uid"] for row in definition_rows]
    input_counts: dict[str, int] = {}
    if definition_uids:
        count_statement = (
            select(
                IndexFormulaInputTable.definition_uid,
                func.count().label("input_count"),
            )
            .where(IndexFormulaInputTable.definition_uid.in_(definition_uids))
            .group_by(IndexFormulaInputTable.definition_uid)
        )
        count_rows = operation_result_rows(
            execute_markets_operation(
                compile_markets_statement(
                    count_statement,
                    context=context,
                    operation="select",
                    models=[IndexFormulaInputTable],
                    access="read",
                ),
                context=context,
            )
        )
        input_counts = {
            str(row["definition_uid"]): int(row.get("input_count") or 0) for row in count_rows
        }
    summaries = [
        _formula_summary(row, input_count=input_counts.get(str(row["uid"]), 0))
        for row in sorted(
            definition_rows,
            key=lambda item: (int(item["version"]), str(item["uid"])),
            reverse=True,
        )
    ]
    return tuple(summaries)


def get_formula(
    context: MarketsOperationContext,
    *,
    index_uid: uuid.UUID | str,
    definition_uid: uuid.UUID | str,
) -> IndexFormulaDetail | None:
    row_result = get_model_by_uid(
        context,
        model=IndexFormulaDefinitionTable,
        uid=definition_uid,
    )
    rows = operation_result_rows(row_result)
    if not rows or str(rows[0]["index_uid"]) != str(index_uid):
        return None
    definition = rows[0]
    input_rows = operation_result_rows(
        search_model(
            context,
            model=IndexFormulaInputTable,
            filters={"definition_uid": uuid.UUID(str(definition_uid))},
            limit=500,
        )
    )
    asset_uids = [row["asset_uid"] for row in input_rows if row.get("asset_uid") is not None]
    index_uids = [
        row["component_index_uid"]
        for row in input_rows
        if row.get("component_index_uid") is not None
    ]
    asset_identifiers = _identifiers_by_uid(context, model=AssetTable, uids=asset_uids)
    index_identifiers = _identifiers_by_uid(context, model=IndexTable, uids=index_uids)
    inputs = tuple(
        _formula_input(
            row,
            asset_identifiers=asset_identifiers,
            index_identifiers=index_identifiers,
        )
        for row in sorted(input_rows, key=lambda item: str(item["uid"]))
    )
    summary = _formula_summary(definition, input_count=len(inputs))
    return IndexFormulaDetail(
        **summary.model_dump(),
        alignment_parameters_json=definition.get("alignment_parameters_json"),
        metadata_json=definition.get("metadata_json"),
        inputs=inputs,
    )


def discover_canonical_datasets(
    *,
    actor: IndexActor | None = None,
) -> tuple[IndexDatasetDescriptor, ...]:
    """Discover registered cadence tables and prove canonical status from SQLAlchemy FKs."""

    candidates = TimeIndexMetaTable.filter_by_body(
        identifier__contains="IndexValuesTS.",
        limit=500,
        offset=0,
    )
    descriptors: list[IndexDatasetDescriptor] = []
    for meta_table in candidates:
        descriptor = _canonical_descriptor(meta_table, actor=actor)
        if descriptor is not None:
            descriptors.append(descriptor)
    descriptors.sort(key=lambda item: (_cadence_sort_key(item.cadence), item.meta_table_uid))
    return tuple(descriptors)


def get_canonical_dataset(
    meta_table_uid: str,
    *,
    actor: IndexActor | None = None,
) -> IndexDatasetDescriptor | None:
    return next(
        (
            descriptor
            for descriptor in discover_canonical_datasets(actor=actor)
            if descriptor.meta_table_uid == str(meta_table_uid)
        ),
        None,
    )


def dataset_summary(
    context: MarketsOperationContext,
    *,
    index: Index,
    dataset: IndexDatasetDescriptor,
) -> IndexDatasetSummary:
    model, handle = _dataset_model_and_handle(context, dataset)
    aggregate = select(
        func.count().label("row_count"),
        func.min(model.time_index).label("earliest_time_index"),
        func.max(model.time_index).label("latest_time_index"),
    ).where(model.index_identifier == index.unique_identifier)
    try:
        aggregate_rows = operation_result_rows(
            execute_markets_operation(
                compile_markets_statement(
                    aggregate,
                    context=handle,
                    operation="select",
                    models=[model],
                    access="read",
                ),
                context=handle,
            )
        )
        aggregate_row = aggregate_rows[0] if aggregate_rows else {}
        latest_statement = (
            select(
                model.value,
                model.observation_status,
                model.source_as_of,
            )
            .where(model.index_identifier == index.unique_identifier)
            .order_by(model.time_index.desc())
            .limit(1)
        )
        latest_rows = operation_result_rows(
            execute_markets_operation(
                compile_markets_statement(
                    latest_statement,
                    context=handle,
                    operation="select",
                    models=[model],
                    access="read",
                ),
                context=handle,
            )
        )
        latest = latest_rows[0] if latest_rows else {}
        return IndexDatasetSummary(
            dataset=dataset,
            index_uid=index.uid,
            index_identifier=index.unique_identifier,
            row_count=int(aggregate_row.get("row_count") or 0),
            count_accuracy="exact",
            earliest_time_index=aggregate_row.get("earliest_time_index"),
            latest_time_index=aggregate_row.get("latest_time_index"),
            latest_value=latest.get("value"),
            latest_status=latest.get("observation_status"),
            latest_source_as_of=latest.get("source_as_of"),
        )
    except Exception as exc:
        return IndexDatasetSummary(
            dataset=dataset,
            index_uid=index.uid,
            index_identifier=index.unique_identifier,
            count_accuracy="unavailable",
            error=f"{type(exc).__name__}: {exc}",
        )


def read_index_values(
    context: MarketsOperationContext,
    *,
    index: Index,
    dataset: IndexDatasetDescriptor,
    start: dt.datetime,
    end: dt.datetime,
    order: str = "desc",
    limit: int = 500,
) -> IndexValuesResult:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if start > end:
        raise ValueError("start must be less than or equal to end")
    if order not in {"asc", "desc"}:
        raise ValueError("order must be asc or desc")
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    model, handle = _dataset_model_and_handle(context, dataset)
    statement = (
        select(
            model.time_index,
            model.index_identifier,
            model.value,
            model.definition_uid,
            model.observation_status,
            model.source_as_of,
            model.metadata_json,
        )
        .where(
            model.index_identifier == index.unique_identifier,
            model.time_index >= start,
            model.time_index <= end,
        )
        .order_by(model.time_index.asc() if order == "asc" else model.time_index.desc())
        .limit(limit)
    )
    result = execute_markets_operation(
        compile_markets_statement(
            statement,
            context=handle,
            operation="select",
            models=[model],
            access="read",
        ),
        context=handle,
    )
    return IndexValuesResult(
        dataset=dataset,
        index_uid=index.uid,
        index_identifier=index.unique_identifier,
        start=start,
        end=end,
        order=order,
        limit=limit,
        rows=tuple(IndexValueRow.model_validate(row) for row in operation_result_rows(result)),
    )


def list_related_meta_tables(
    context: MarketsOperationContext,
    *,
    index: Index,
    numeric: bool = True,
    timestamped: bool = True,
) -> tuple[RelatedMetaTable, ...]:
    """Return Index relationships filtered by registered table schema."""

    definitions = _count(
        count_model(
            context,
            model=IndexFormulaDefinitionTable,
            filters={"index_uid": index.uid},
        )
    )
    component_dependencies = _count(
        count_model(
            context,
            model=IndexFormulaInputTable,
            filters={"component_index_uid": index.uid},
        )
    )
    results = [
        RelatedMetaTable(
            key="formula_definitions",
            label="Formula definitions",
            owning_package="msm",
            storage_kind="related_reference_table",
            meta_table_uid=_bound_uid(IndexFormulaDefinitionTable),
            identifier=str(IndexFormulaDefinitionTable.__metatable_identifier__),
            relationship_type="direct",
            join_kind="uid",
            join_column="index_uid",
            on_delete="CASCADE",
            authoritative=True,
            discovery_source="core_model",
            exploration_capability="summary",
            delete_capability="cascade",
            count=definitions,
        ),
        RelatedMetaTable(
            key="component_index_dependencies",
            label="Formulas using this component Index",
            owning_package="msm",
            storage_kind="related_reference_table",
            meta_table_uid=_bound_uid(IndexFormulaInputTable),
            identifier=str(IndexFormulaInputTable.__metatable_identifier__),
            relationship_type="direct",
            join_kind="uid",
            join_column="component_index_uid",
            on_delete="RESTRICT",
            authoritative=True,
            discovery_source="core_model",
            exploration_capability="count",
            delete_capability="none",
            count=component_dependencies,
            blocks_delete=component_dependencies > 0,
        ),
    ]
    schema_sources: dict[str, tuple[type[Any] | None, Any | None]] = {
        "formula_definitions": (IndexFormulaDefinitionTable, None),
        "component_index_dependencies": (IndexFormulaInputTable, None),
    }
    for provider in list_index_relationship_providers():
        count: int | None = None
        count_error: str | None = None
        try:
            meta_table = provider.resolve_meta_table()
        except Exception as exc:
            meta_table = None
            count_error = f"{type(exc).__name__}: {exc}"
        if meta_table is not None and provider.exploration_capability != "none":
            try:
                handle = MarketsMetaTableHandle(
                    model=provider.storage_model,
                    meta_table=meta_table,
                    limits=context.limits,
                    data_source_uid=context.data_source_uid,
                    timeout=context.timeout,
                    namespace=context.namespace,
                    reserved_policy=context.reserved_policy,
                )
                value = index.uid if provider.join_kind == "uid" else index.unique_identifier
                count = _count(
                    count_model(
                        handle,
                        model=provider.storage_model,
                        filters={provider.join_column: value},
                    )
                )
            except Exception as exc:
                count_error = f"{type(exc).__name__}: {exc}"
        results.append(
            RelatedMetaTable(
                key=provider.key,
                label=provider.label,
                owning_package=provider.owning_package,
                storage_kind=provider.storage_kind,
                meta_table_uid=str(getattr(meta_table, "uid", "")) or None,
                identifier=str(
                    getattr(
                        meta_table, "identifier", provider.storage_model.__metatable_identifier__
                    )
                ),
                relationship_type=provider.relationship_type,
                join_kind=provider.join_kind,
                join_column=provider.join_column,
                on_delete=provider.on_delete,
                authoritative=True,
                discovery_source="declared_provider",
                exploration_capability=provider.exploration_capability,
                delete_capability=_delete_capability(provider.on_delete),
                count=count,
                blocks_delete=(
                    str(provider.on_delete).upper().replace("_", " ") in {"RESTRICT", "NO ACTION"}
                )
                and bool(count),
                confidence_reason=(
                    f"Authoritative provider count is unavailable: {count_error}"
                    if count_error
                    else None
                ),
            )
        )
        schema_sources[provider.key] = (provider.storage_model, meta_table)
    inferred = _inferred_index_relationships(
        results,
        numeric=numeric,
        timestamped=timestamped,
    )
    filtered = [
        item
        for item in results
        if _matches_related_meta_table_filters(
            storage_model=schema_sources[item.key][0],
            meta_table=schema_sources[item.key][1],
            join_column=item.join_column,
            numeric=numeric,
            timestamped=timestamped,
        )
    ]
    filtered.extend(inferred)
    return tuple(sorted(filtered, key=lambda item: item.key))


def get_index_detail(
    context: MarketsOperationContext,
    *,
    index: Index,
    actor: IndexActor | None = None,
) -> IndexDetail:
    warnings: list[str] = []
    try:
        from .availability import list_dataset_states

        datasets = list_dataset_states(context, index=index, actor=actor)
    except Exception as exc:
        datasets = ()
        warnings.append(f"Canonical dataset discovery unavailable: {type(exc).__name__}: {exc}")
    return IndexDetail(
        index=index,
        formulas=list_formulas(context, index_uid=index.uid),
        datasets=datasets,
        related_meta_tables=list_related_meta_tables(
            context,
            index=index,
            numeric=False,
            timestamped=False,
        ),
        warnings=tuple(warnings),
    )


def get_index_summary(
    context: MarketsOperationContext,
    *,
    index: Index,
    actor: IndexActor | None = None,
) -> IndexSummary:
    detail = get_index_detail(context, index=index, actor=actor)
    warnings = [*detail.warnings]
    warnings.extend(item.error for item in detail.datasets if item.error)
    formulas = detail.formulas
    active = next((item for item in formulas if item.status == "active"), None)
    relationships = detail.related_meta_tables
    return IndexSummary(
        index=index,
        formula_count=len(formulas),
        input_count=sum(item.input_count for item in formulas),
        active_formula=active,
        dataset_count=sum(item.population_state == "populated" for item in detail.datasets),
        cadences=tuple(
            sorted(
                {
                    item.dataset.cadence
                    for item in detail.datasets
                    if item.population_state == "populated"
                },
                key=_cadence_sort_key,
            )
        ),
        dataset_states=detail.datasets,
        authoritative_relationship_count=sum(item.authoritative for item in relationships),
        inferred_relationship_count=sum(not item.authoritative for item in relationships),
        warnings=tuple(str(item) for item in warnings if item),
    )


def _canonical_descriptor(
    meta_table: Any, *, actor: IndexActor | None
) -> IndexDatasetDescriptor | None:
    identifier = str(getattr(meta_table, "identifier", ""))
    marker = "IndexValuesTS."
    if marker not in identifier:
        return None
    cadence_from_identifier = identifier.rsplit(marker, 1)[-1]
    cadence = str(getattr(meta_table, "cadence", "") or "").strip().lower()
    if not cadence:
        profile = getattr(meta_table, "time_indexed_profile", None)
        cadence = str(getattr(profile, "cadence", "") or "").strip().lower()
    if not cadence or cadence != cadence_from_identifier:
        return None
    try:
        model = configured_index_values_storage(cadence=cadence)
    except ValueError:
        return None
    if identifier != str(model.__metatable_identifier__):
        return None
    components = getattr(model, "__metatable_extra_hash_components__", {})
    if (
        components.get(INDEX_VALUES_STORAGE_NAME_COMPONENT) != "index_values"
        or components.get(INDEX_VALUES_CADENCE_COMPONENT) != cadence
    ):
        return None
    physical_table_name = str(getattr(meta_table, "physical_table_name", ""))
    if physical_table_name != model.__table__.name:
        return None
    columns = tuple(_column_names(meta_table))
    if not {"time_index", "index_identifier", "value"}.issubset(columns):
        return None
    index_names = tuple(
        str(item) for item in (getattr(meta_table, "table_index_names", None) or ())
    )
    if not {"time_index", "index_identifier"}.issubset(index_names):
        return None
    foreign_key = require_index_foreign_key(
        model,
        source_column="index_identifier",
        join_kind="unique_identifier",
    )
    catalog_foreign_keys = tuple(getattr(meta_table, "foreign_keys", None) or ())
    if catalog_foreign_keys and not any(
        _catalog_fk_matches_index(item, source_column="index_identifier")
        for item in catalog_foreign_keys
    ):
        return None
    owner_uid = str(getattr(meta_table, "created_by_user_uid", "") or "")
    can_edit = True if actor is not None and owner_uid == actor.user_uid else None
    return IndexDatasetDescriptor(
        meta_table_uid=str(meta_table.uid),
        identifier=identifier,
        namespace=getattr(meta_table, "namespace", None),
        cadence=cadence,
        physical_table_name=physical_table_name,
        time_index_name="time_index",
        index_names=index_names,
        columns=columns,
        foreign_keys=(
            IndexForeignKeyDescriptor(
                source_column=foreign_key.parent.name,
                target_table=foreign_key.column.table.fullname,
                target_column=foreign_key.column.name,
                on_delete=foreign_key.ondelete,
            ),
        ),
        description=getattr(meta_table, "description", None),
        storage_kind="canonical_index_values",
        discovery_source="core_model",
        access=IndexDatasetAccess(
            can_view=True,
            can_edit=can_edit,
            reason=None
            if can_edit
            else "Edit access is rechecked by the platform at mutation time.",
        ),
        producer_identifiers=_producer_identifiers(meta_table),
    )


def _dataset_model_and_handle(
    context: MarketsOperationContext,
    dataset: IndexDatasetDescriptor,
) -> tuple[type[Any], MarketsMetaTableHandle]:
    model = configured_index_values_storage(cadence=dataset.cadence)
    matches = TimeIndexMetaTable.filter_by_body(uid__in=[dataset.meta_table_uid], limit=1, offset=0)
    if not matches:
        raise LookupError(f"Canonical Index dataset {dataset.meta_table_uid!r} is not visible")
    meta_table = matches[0]
    verified = _canonical_descriptor(meta_table, actor=None)
    if verified is None or verified.meta_table_uid != dataset.meta_table_uid:
        raise ValueError(
            "Selected MetaTable no longer satisfies the canonical Index dataset contract"
        )
    handle = MarketsMetaTableHandle(
        model=model,
        meta_table=meta_table,
        limits=context.limits,
        data_source_uid=context.data_source_uid,
        timeout=context.timeout,
        namespace=context.namespace,
        reserved_policy=context.reserved_policy,
    )
    return model, handle


def _formula_summary(
    row: dict[str, Any],
    *,
    input_count: int,
) -> IndexFormulaSummary:
    return IndexFormulaSummary(
        uid=row["uid"],
        index_uid=row["index_uid"],
        version=row["version"],
        status=row["status"],
        valid_from=row["valid_from"],
        valid_to=row.get("valid_to"),
        formula=row["formula"],
        alignment_policy=row["alignment_policy"],
        missing_data_policy=row["missing_data_policy"],
        definition_hash=row["definition_hash"],
        input_count=input_count,
    )


def _formula_input(
    row: dict[str, Any],
    *,
    asset_identifiers: dict[str, str],
    index_identifiers: dict[str, str],
) -> IndexFormulaInput:
    asset_uid = row.get("asset_uid")
    component_index_uid = row.get("component_index_uid")
    source_type = "asset" if asset_uid is not None else "index"
    source_uid = asset_uid if asset_uid is not None else component_index_uid
    identifiers = asset_identifiers if source_type == "asset" else index_identifiers
    identifier = identifiers.get(str(source_uid))
    if identifier is None:
        raise LookupError(f"formula input {row['uid']} references a missing {source_type}")
    return IndexFormulaInput.model_validate(
        {
            "source_reference": {"type": source_type, "identifier": identifier},
            "meta_table_uid": row["meta_table_uid"],
            "observable": row["observable"],
        }
    )


def _identifiers_by_uid(
    context: MarketsOperationContext,
    *,
    model: type[Any],
    uids: Sequence[Any],
) -> dict[str, str]:
    if not uids:
        return {}
    rows = operation_result_rows(
        search_model(context, model=model, in_filters={"uid": list(uids)}, limit=len(uids))
    )
    return {str(row["uid"]): str(row["unique_identifier"]) for row in rows}


def _count(result: dict[str, Any] | list[Any] | None) -> int:
    rows = operation_result_rows(result)
    return int(rows[0].get("count") or 0) if rows else 0


def _delete_capability(on_delete: str) -> str:
    action = str(on_delete).upper().replace("_", " ")
    if action == "CASCADE":
        return "cascade"
    if action == "SET NULL":
        return "set_null"
    return "none"


def _bound_uid(model: type[Any]) -> str | None:
    get_uid = getattr(model, "get_meta_table_uid", None)
    if not callable(get_uid):
        return None
    try:
        value = get_uid()
    except Exception:
        return None
    return str(value) if value not in (None, "") else None


def _column_names(meta_table: Any) -> Sequence[str]:
    values: list[str] = []
    for column in getattr(meta_table, "columns", None) or ():
        name = column.get("name") if isinstance(column, dict) else getattr(column, "name", None)
        if name not in (None, ""):
            values.append(str(name))
    return values


def _producer_identifiers(meta_table: Any) -> tuple[str, ...]:
    registration = getattr(meta_table, "registration", None)
    values = getattr(registration, "producer_identifiers", None) if registration else None
    return tuple(str(item) for item in (values or ()) if str(item))


def _inferred_index_relationships(
    declared: Sequence[RelatedMetaTable],
    *,
    numeric: bool,
    timestamped: bool,
) -> list[RelatedMetaTable]:
    declared_identifiers = {item.identifier for item in declared}
    try:
        meta_tables = []
        offset = 0
        while True:
            page = list(MetaTable.filter_by_body(limit=500, offset=offset))
            meta_tables.extend(page)
            if len(page) < 500:
                break
            offset += len(page)
    except Exception:
        return []
    inferred: list[RelatedMetaTable] = []
    for meta_table in meta_tables:
        identifier = str(getattr(meta_table, "identifier", ""))
        if not identifier or identifier in declared_identifiers:
            continue
        for foreign_key in getattr(meta_table, "foreign_keys", None) or ():
            source_columns = tuple(getattr(foreign_key, "source_columns", None) or ())
            if len(source_columns) != 1 or not _catalog_fk_matches_index(
                foreign_key,
                source_column=str(source_columns[0]),
            ):
                continue
            target_columns = tuple(getattr(foreign_key, "target_columns", None) or ())
            target_column = str(target_columns[0])
            if not _matches_related_meta_table_filters(
                storage_model=None,
                meta_table=meta_table,
                join_column=str(source_columns[0]),
                numeric=numeric,
                timestamped=timestamped,
            ):
                continue
            inferred.append(
                RelatedMetaTable(
                    key=f"inferred:{getattr(meta_table, 'uid', identifier)}:{source_columns[0]}",
                    label=getattr(meta_table, "description", None) or identifier,
                    owning_package="unknown",
                    storage_kind="inferred_candidate",
                    meta_table_uid=str(getattr(meta_table, "uid", "")) or None,
                    identifier=identifier,
                    relationship_type="registered_foreign_key",
                    join_kind="uid" if target_column == "uid" else "unique_identifier",
                    join_column=str(source_columns[0]),
                    on_delete=str(getattr(foreign_key, "on_delete", None) or "UNKNOWN"),
                    authoritative=False,
                    discovery_source="inferred",
                    exploration_capability="none",
                    delete_capability="none",
                    count=None,
                    blocks_delete=False,
                    confidence_reason=(
                        "Registered catalog FK metadata targets IndexTable, but no owning "
                        "IndexRelationshipProvider declares product exploration or delete semantics."
                    ),
                )
            )
    return inferred


def _matches_related_meta_table_filters(
    *,
    storage_model: type[Any] | None,
    meta_table: Any | None,
    join_column: str | None,
    numeric: bool,
    timestamped: bool,
) -> bool:
    if timestamped and not _is_timestamped_meta_table(meta_table):
        return False
    if numeric and not _has_numeric_data_column(
        storage_model=storage_model,
        meta_table=meta_table,
        join_column=join_column,
    ):
        return False
    return True


def _is_timestamped_meta_table(meta_table: Any | None) -> bool:
    if meta_table is None:
        return False
    time_indexed = getattr(meta_table, "time_indexed", None)
    if time_indexed is not None:
        return bool(time_indexed)
    return getattr(meta_table, "time_indexed_profile", None) is not None or isinstance(
        meta_table, TimeIndexMetaTable
    )


def _has_numeric_data_column(
    *,
    storage_model: type[Any] | None,
    meta_table: Any | None,
    join_column: str | None,
) -> bool:
    excluded_columns = _relationship_column_names(
        storage_model=storage_model,
        meta_table=meta_table,
    )
    if join_column:
        excluded_columns.add(join_column)

    catalog_columns = getattr(meta_table, "columns", None) if meta_table is not None else None
    catalog_has_typed_columns = False
    for column in catalog_columns or ():
        name = column.get("name") if isinstance(column, dict) else getattr(column, "name", None)
        data_type = (
            column.get("data_type")
            if isinstance(column, dict)
            else getattr(column, "data_type", None)
        )
        primary_key = (
            column.get("primary_key", False)
            if isinstance(column, dict)
            else getattr(column, "primary_key", False)
        )
        if data_type not in (None, ""):
            catalog_has_typed_columns = True
        if (
            name not in (None, "")
            and str(name) not in excluded_columns
            and not primary_key
            and _is_numeric_dtype(data_type)
        ):
            return True
    if catalog_has_typed_columns:
        return False

    table = getattr(storage_model, "__table__", None) if storage_model is not None else None
    if table is None:
        return False
    return any(
        column.name not in excluded_columns
        and not column.primary_key
        and isinstance(column.type, (Integer, Float, Numeric))
        for column in table.columns
    )


def _relationship_column_names(
    *,
    storage_model: type[Any] | None,
    meta_table: Any | None,
) -> set[str]:
    names: set[str] = set()
    for foreign_key in getattr(meta_table, "foreign_keys", None) or ():
        source_columns = (
            foreign_key.get("source_columns")
            if isinstance(foreign_key, dict)
            else getattr(foreign_key, "source_columns", None)
        )
        names.update(str(name) for name in source_columns or ())
    table = getattr(storage_model, "__table__", None) if storage_model is not None else None
    if table is not None:
        names.update(str(foreign_key.parent.name) for foreign_key in table.foreign_keys)
    return names


def _is_numeric_dtype(data_type: Any) -> bool:
    normalized = " ".join(str(data_type or "").strip().lower().replace("_", " ").split())
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


def _catalog_fk_matches_index(foreign_key: Any, *, source_column: str) -> bool:
    source_columns = tuple(getattr(foreign_key, "source_columns", None) or ())
    target_columns = tuple(getattr(foreign_key, "target_columns", None) or ())
    if source_columns != (source_column,) or target_columns not in {
        ("uid",),
        ("unique_identifier",),
    }:
        return False
    target_uid = str(getattr(foreign_key, "target_table_uid", "") or "")
    index_uid = _bound_uid(IndexTable) or ""
    target_physical = str(getattr(foreign_key, "target_table_physical_table_name", "") or "")
    return bool(
        (index_uid and target_uid == index_uid) or target_physical == IndexTable.__table__.name
    )


def _cadence_sort_key(cadence: str) -> tuple[int, str]:
    units = {"s": 1, "m": 60, "h": 3_600, "d": 86_400, "w": 604_800}
    for unit, seconds in units.items():
        if cadence.endswith(unit) and cadence.removesuffix(unit).isdigit():
            return int(cadence.removesuffix(unit)) * seconds, cadence
    return 10**12, cadence


__all__ = [
    "dataset_summary",
    "discover_canonical_datasets",
    "get_canonical_dataset",
    "get_index_detail",
    "get_index_summary",
    "list_index_types",
    "get_formula",
    "list_indexes",
    "list_formulas",
    "list_related_meta_tables",
    "read_index_values",
]
