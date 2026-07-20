from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import String, and_, cast, exists, func, or_, select

from mainsequence.client.metatables import MetaTable, TimeIndexMetaTable

from msm.api.base import operation_result_rows
from msm.api.indices import Index, IndexType
from msm.data_nodes.indices.storage import (
    INDEX_VALUES_CADENCE_COMPONENT,
    INDEX_VALUES_STORAGE_NAME_COMPONENT,
    IndexResolvedLegsStorage,
    configured_index_values_storage,
)
from msm.models import (
    IndexCalculationDefinitionTable,
    IndexCalculationLegTable,
    IndexDatasetAvailabilityTable,
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
    IndexDatasetState,
    IndexDatasetSummary,
    IndexDetail,
    IndexForeignKeyDescriptor,
    IndexListRequest,
    IndexMethodologyDetail,
    IndexMethodologyLeg,
    IndexMethodologySummary,
    IndexPage,
    IndexRelatedMetaTable,
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
                func.lower(func.coalesce(IndexTable.provider, "")).like(needle),
            )
        )
    if request.uids:
        conditions.append(IndexTable.uid.in_(request.uids))
    if request.unique_identifiers:
        conditions.append(IndexTable.unique_identifier.in_(request.unique_identifiers))
    if request.index_type:
        conditions.append(IndexTable.index_type == request.index_type)
    if request.provider:
        conditions.append(IndexTable.provider == request.provider)
    if request.has_definition is not None:
        models.append(IndexCalculationDefinitionTable)
        definition_exists = exists(
            select(IndexCalculationDefinitionTable.uid).where(
                IndexCalculationDefinitionTable.index_uid == IndexTable.uid
            )
        )
        conditions.append(definition_exists if request.has_definition else ~definition_exists)

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
        "provider": IndexTable.provider,
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
    base = select(IndexTypeTable).order_by(IndexTypeTable.index_type, IndexTypeTable.uid)
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


def list_methodologies(
    context: MarketsOperationContext,
    *,
    index_uid: uuid.UUID | str,
) -> tuple[IndexMethodologySummary, ...]:
    definition_rows = operation_result_rows(
        search_model(
            context,
            model=IndexCalculationDefinitionTable,
            filters={"index_uid": uuid.UUID(str(index_uid))},
            limit=500,
        )
    )
    definition_uids = [row["uid"] for row in definition_rows]
    leg_counts: dict[str, int] = {}
    if definition_uids:
        count_statement = (
            select(
                IndexCalculationLegTable.definition_uid,
                func.count().label("leg_count"),
            )
            .where(IndexCalculationLegTable.definition_uid.in_(definition_uids))
            .group_by(IndexCalculationLegTable.definition_uid)
        )
        count_rows = operation_result_rows(
            execute_markets_operation(
                compile_markets_statement(
                    count_statement,
                    context=context,
                    operation="select",
                    models=[IndexCalculationLegTable],
                    access="read",
                ),
                context=context,
            )
        )
        leg_counts = {
            str(row["definition_uid"]): int(row.get("leg_count") or 0) for row in count_rows
        }
    summaries = [
        _methodology_summary(row, leg_count=leg_counts.get(str(row["uid"]), 0))
        for row in sorted(
            definition_rows,
            key=lambda item: (int(item["definition_version"]), str(item["uid"])),
            reverse=True,
        )
    ]
    return tuple(summaries)


def get_methodology(
    context: MarketsOperationContext,
    *,
    index_uid: uuid.UUID | str,
    definition_uid: uuid.UUID | str,
) -> IndexMethodologyDetail | None:
    row_result = get_model_by_uid(
        context,
        model=IndexCalculationDefinitionTable,
        uid=definition_uid,
    )
    rows = operation_result_rows(row_result)
    if not rows or str(rows[0]["index_uid"]) != str(index_uid):
        return None
    definition = rows[0]
    leg_rows = operation_result_rows(
        search_model(
            context,
            model=IndexCalculationLegTable,
            filters={"definition_uid": uuid.UUID(str(definition_uid))},
            limit=500,
        )
    )
    legs = tuple(
        _methodology_leg(row)
        for row in sorted(leg_rows, key=lambda item: (int(item["leg_order"]), str(item["uid"])))
    )
    summary = _methodology_summary(definition, leg_count=len(legs))
    return IndexMethodologyDetail(
        **summary.model_dump(),
        calculation_parameters_json=definition.get("calculation_parameters_json"),
        alignment_policy=str(definition["alignment_policy"]),
        alignment_parameters_json=definition.get("alignment_parameters_json"),
        missing_data_policy=str(definition["missing_data_policy"]),
        missing_data_parameters_json=definition.get("missing_data_parameters_json"),
        rebalance_policy=definition.get("rebalance_policy"),
        rebalance_parameters_json=definition.get("rebalance_parameters_json"),
        source=definition.get("source"),
        metadata_json=definition.get("metadata_json"),
        legs=legs,
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
                model.unit,
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
            latest_unit=latest.get("unit"),
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
            model.unit,
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
) -> tuple[IndexRelatedMetaTable, ...]:
    definitions = _count(
        count_model(
            context,
            model=IndexCalculationDefinitionTable,
            filters={"index_uid": index.uid},
        )
    )
    component_dependencies = _count(
        count_model(
            context,
            model=IndexCalculationLegTable,
            filters={"component_index_uid": index.uid},
        )
    )
    resolved_meta_table = None
    resolved_leg_count: int | None = None
    try:
        resolved_meta_table = IndexResolvedLegsStorage.get_time_index_meta_table()
        if resolved_meta_table is not None:
            resolved_handle = MarketsMetaTableHandle(
                model=IndexResolvedLegsStorage,
                meta_table=resolved_meta_table,
                limits=context.limits,
                data_source_uid=context.data_source_uid,
                timeout=context.timeout,
                namespace=context.namespace,
                reserved_policy=context.reserved_policy,
            )
            resolved_leg_count = _count(
                count_model(
                    resolved_handle,
                    model=IndexResolvedLegsStorage,
                    filters={"index_identifier": index.unique_identifier},
                )
            )
    except Exception:
        resolved_meta_table = None
    results = [
        IndexRelatedMetaTable(
            key="calculation_definitions",
            label="Calculation definitions",
            owning_package="msm",
            storage_kind="related_reference_table",
            meta_table_uid=_bound_uid(IndexCalculationDefinitionTable),
            identifier=str(IndexCalculationDefinitionTable.__metatable_identifier__),
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
        IndexRelatedMetaTable(
            key="component_index_dependencies",
            label="Methodologies using this component Index",
            owning_package="msm",
            storage_kind="related_reference_table",
            meta_table_uid=_bound_uid(IndexCalculationLegTable),
            identifier=str(IndexCalculationLegTable.__metatable_identifier__),
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
        IndexRelatedMetaTable(
            key="resolved_index_legs",
            label="Resolved methodology legs",
            owning_package="msm",
            storage_kind="resolved_index_legs",
            meta_table_uid=str(getattr(resolved_meta_table, "uid", "")) or None,
            identifier=str(
                getattr(
                    resolved_meta_table,
                    "identifier",
                    IndexResolvedLegsStorage.__metatable_identifier__,
                )
            ),
            relationship_type="direct",
            join_kind="unique_identifier",
            join_column="index_identifier",
            on_delete="RESTRICT",
            authoritative=True,
            discovery_source="core_model",
            exploration_capability="count",
            delete_capability="none",
            count=resolved_leg_count,
            blocks_delete=bool(resolved_leg_count),
            confidence_reason=(
                None
                if resolved_meta_table is not None
                else "The resolved-leg MetaTable binding or count is unavailable."
            ),
        ),
    ]
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
            IndexRelatedMetaTable(
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
    results.extend(_inferred_index_relationships(results))
    return tuple(sorted(results, key=lambda item: item.key))


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
        methodologies=list_methodologies(context, index_uid=index.uid),
        datasets=datasets,
        related_meta_tables=list_related_meta_tables(context, index=index),
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
    methodologies = detail.methodologies
    active = next((item for item in methodologies if item.status == "active"), None)
    relationships = detail.related_meta_tables
    return IndexSummary(
        index=index,
        definition_count=len(methodologies),
        leg_count=sum(item.leg_count for item in methodologies),
        active_definition=active,
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
    if not {"time_index", "index_identifier", "value", "unit"}.issubset(columns):
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


def _methodology_summary(
    row: dict[str, Any],
    *,
    leg_count: int,
) -> IndexMethodologySummary:
    return IndexMethodologySummary(
        uid=row["uid"],
        index_uid=row["index_uid"],
        definition_version=row["definition_version"],
        status=row["status"],
        effective_from=row["effective_from"],
        effective_to=row.get("effective_to"),
        calculation_kind=row["calculation_kind"],
        calculation_family=row["calculation_family"],
        output_unit=row["output_unit"],
        composition_mode=row["composition_mode"],
        definition_hash=row["definition_hash"],
        leg_count=leg_count,
    )


def _methodology_leg(row: dict[str, Any]) -> IndexMethodologyLeg:
    return IndexMethodologyLeg(
        uid=row["uid"],
        definition_uid=row["definition_uid"],
        leg_key=row["leg_key"],
        leg_order=row["leg_order"],
        leg_role=row.get("leg_role"),
        component_kind=row["component_kind"],
        asset_uid=row.get("asset_uid"),
        component_index_uid=row.get("component_index_uid"),
        selector_code=row.get("selector_code"),
        selector_parameters_json=row.get("selector_parameters_json"),
        observable_code=row["observable_code"],
        input_unit=row["input_unit"],
        transform_code=row["transform_code"],
        transform_parameters_json=row.get("transform_parameters_json"),
        coefficient_method=row["coefficient_method"],
        coefficient=row.get("coefficient"),
        coefficient_parameters_json=row.get("coefficient_parameters_json"),
        metadata_json=row.get("metadata_json"),
    )


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
    declared: Sequence[IndexRelatedMetaTable],
) -> list[IndexRelatedMetaTable]:
    declared_identifiers = {item.identifier for item in declared}
    try:
        meta_tables = MetaTable.filter_by_body(limit=500, offset=0)
    except Exception:
        return []
    inferred: list[IndexRelatedMetaTable] = []
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
            inferred.append(
                IndexRelatedMetaTable(
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
    "get_methodology",
    "list_indexes",
    "list_methodologies",
    "list_related_meta_tables",
    "read_index_values",
]
