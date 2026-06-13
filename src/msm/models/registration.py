from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from mainsequence.client.metatables import (
    MetaTable,
    MetaTableRegistrationRequest,
    TimeIndexMetaTable,
)
from mainsequence.logconf import logger as _mainsequence_logger
from mainsequence.meta_tables import (
    PlatformTimeIndexMetaTable,
    external_registered_registration_request_from_sqlalchemy_model,
    platform_managed_registration_request_from_sqlalchemy_model,
    time_indexed_registration_request_from_sqlalchemy_model,
)

from msm.base import (
    MarketsBase,
    markets_meta_table_identifier as _markets_meta_table_identifier,
    markets_table_storage_name,
)
from msm.models import markets_sqlalchemy_models


MarketsManagementMode = Literal["platform_managed", "external_registered"]
MarketsModelSelector = str | type[Any]
logger = _mainsequence_logger.bind(sub_application="markets", component="meta_tables")


@dataclass(frozen=True)
class MarketsMetaTableRegistrationResult:
    meta_tables: list[MetaTable]
    models: list[type[MarketsBase]]
    meta_table_by_identifier: dict[str, MetaTable]


def markets_meta_table_models() -> list[type[MarketsBase]]:
    return list(markets_sqlalchemy_models())


def markets_meta_table_identifier(model: type[MarketsBase]) -> str:
    return _markets_meta_table_identifier(model)


def resolve_markets_meta_table_model(model: MarketsModelSelector) -> type[MarketsBase]:
    """Resolve a markets MetaTable model class by class, row API, or selector."""

    if isinstance(model, type):
        return _normalize_markets_meta_table_model_class(model)

    model_key = str(model)
    for candidate in markets_meta_table_models():
        identifier = candidate.__metatable_identifier__
        keys = {
            candidate.__name__,
            identifier,
            identifier.rsplit(".", 1)[-1],
            markets_meta_table_identifier(candidate),
            candidate.__table__.name,
        }
        if model_key in keys:
            return candidate
    raise ValueError(f"Unknown markets MetaTable model {model_key!r}.")


def resolve_markets_meta_table_models(
    models: Sequence[MarketsModelSelector] | None = None,
) -> list[type[MarketsBase]]:
    """Resolve selected markets MetaTable models in dependency order."""

    if models is None:
        return markets_meta_table_models()

    requested_models = [resolve_markets_meta_table_model(model) for model in models]
    return _dependency_ordered_markets_meta_table_models(requested_models)


def _normalize_markets_meta_table_model_class(model: type[Any]) -> type[MarketsBase]:
    if issubclass(model, MarketsBase):
        return model

    table_model = getattr(model, "__table__", None)
    if isinstance(table_model, type) and issubclass(table_model, MarketsBase):
        return table_model

    raise ValueError(
        "Markets MetaTable model selectors must be built-in names, "
        "MarketsBase subclasses, or row API classes with __table__ pointing to "
        f"a MarketsBase subclass. Got {model.__module__}.{model.__qualname__}."
    )


def _dependency_ordered_markets_meta_table_models(
    requested_models: Sequence[type[MarketsBase]],
) -> list[type[MarketsBase]]:
    built_in_models = markets_meta_table_models()
    candidate_models = _dependency_candidate_models(built_in_models, requested_models)
    built_in_order = {model: index for index, model in enumerate(built_in_models)}
    caller_order = _model_order(requested_models)
    discovery_order: dict[type[MarketsBase], int] = {}

    def collect(model: type[MarketsBase]) -> None:
        if model in discovery_order:
            return
        discovery_order[model] = len(discovery_order)
        for dependency in _metatable_foreign_key_target_models(
            model,
            candidate_models=candidate_models,
        ):
            collect(dependency)

    for model in requested_models:
        collect(model)

    resolved_models = list(discovery_order)
    _validate_unique_markets_meta_table_identifiers(resolved_models)

    dependencies = {
        model: {
            dependency
            for dependency in _metatable_foreign_key_target_models(
                model,
                candidate_models=candidate_models,
            )
            if dependency in discovery_order
        }
        for model in resolved_models
    }
    ordered: list[type[MarketsBase]] = []
    ready = [model for model, model_dependencies in dependencies.items() if not model_dependencies]

    def sort_key(model: type[MarketsBase]) -> tuple[int, int]:
        if model in built_in_order:
            return (0, built_in_order[model])
        if model in caller_order:
            return (1, caller_order[model])
        return (2, discovery_order[model])

    while ready:
        ready.sort(key=sort_key)
        model = ready.pop(0)
        ordered.append(model)
        for candidate, candidate_dependencies in dependencies.items():
            if model not in candidate_dependencies:
                continue
            candidate_dependencies.remove(model)
            if not candidate_dependencies and candidate not in ordered and candidate not in ready:
                ready.append(candidate)

    if len(ordered) != len(resolved_models):
        remaining = [model for model in resolved_models if model not in ordered]
        raise ValueError(
            "Markets MetaTable dependency cycle detected: "
            f"{_dependency_cycle_message(remaining, dependencies)}."
        )

    return ordered


def _model_order(models: Sequence[type[MarketsBase]]) -> dict[type[MarketsBase], int]:
    order: dict[type[MarketsBase], int] = {}
    for model in models:
        order.setdefault(model, len(order))
    return order


def _validate_unique_markets_meta_table_identifiers(models: Sequence[type[MarketsBase]]) -> None:
    models_by_identifier: dict[str, type[MarketsBase]] = {}
    for model in models:
        identifier = markets_meta_table_identifier(model)
        existing = models_by_identifier.get(identifier)
        if existing is not None and existing is not model:
            raise ValueError(
                "Duplicate markets MetaTable identifier "
                f"{identifier!r} for {existing.__name__} and {model.__name__}."
            )
        models_by_identifier[identifier] = model


def _dependency_candidate_models(
    *model_groups: Sequence[type[MarketsBase]],
) -> list[type[MarketsBase]]:
    candidates: list[type[MarketsBase]] = []
    seen: set[type[MarketsBase]] = set()
    for model in [
        *_loaded_markets_meta_table_models(),
        *(model for group in model_groups for model in group),
    ]:
        if model in seen:
            continue
        seen.add(model)
        candidates.append(model)
    return candidates


def _loaded_markets_meta_table_models() -> list[type[MarketsBase]]:
    models: list[type[MarketsBase]] = []
    for mapper in MarketsBase.registry.mappers:
        model = mapper.class_
        if isinstance(model, type) and issubclass(model, MarketsBase):
            models.append(model)
    return models


def _dependency_cycle_message(
    remaining_models: Sequence[type[MarketsBase]],
    dependencies: Mapping[type[MarketsBase], set[type[MarketsBase]]],
) -> str:
    remaining = set(remaining_models)
    start = remaining_models[0]
    path: list[type[MarketsBase]] = []
    visiting: set[type[MarketsBase]] = set()

    def visit(model: type[MarketsBase]) -> list[type[MarketsBase]] | None:
        if model in visiting:
            if model in path:
                return [*path[path.index(model) :], model]
            return [model, model]
        if model in path:
            return None
        visiting.add(model)
        path.append(model)
        for dependency in dependencies.get(model, set()):
            if dependency not in remaining:
                continue
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        path.pop()
        visiting.remove(model)
        return None

    cycle = visit(start) or list(remaining_models)
    return " -> ".join(model.__name__ for model in cycle)


def markets_foreign_key_target_identifiers(model: type[MarketsBase]) -> list[str]:
    candidate_models = _dependency_candidate_models(markets_meta_table_models(), [model])
    targets: set[str] = set()
    for foreign_key_constraint in model.__table__.foreign_key_constraints:
        for element in foreign_key_constraint.elements:
            target_model = _metatable_foreign_key_target_model(
                element,
                candidate_models=candidate_models,
            )
            targets.add(markets_table_storage_name(target_model))
    return sorted(targets)


def is_time_index_meta_table_model(model: type[MarketsBase]) -> bool:
    """True for ADR 0017 DataNode output storage classes.

    `PlatformTimeIndexMetaTable` subclasses derive their own time-index/storage
    layout and register without the ``introspect`` argument accepted by domain
    `PlatformManagedMetaTable` models.
    """

    return isinstance(model, type) and issubclass(model, PlatformTimeIndexMetaTable)


def _platform_registration_kwargs(
    model: type[MarketsBase],
    *,
    base_kwargs: Mapping[str, Any],
    introspect: bool | None,
) -> dict[str, Any]:
    """Shape platform-managed register/build kwargs for one model.

    DataNode storage classes (`PlatformTimeIndexMetaTable`) reject ``introspect``;
    domain MetaTables require ``introspect``.
    """

    request_kwargs = {
        key: value for key, value in base_kwargs.items() if key != "open_for_everyone"
    }
    if is_time_index_meta_table_model(model):
        return request_kwargs
    return {**request_kwargs, "introspect": False if introspect is None else introspect}


def build_markets_registration_requests(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    labels: Sequence[str] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    models: Sequence[MarketsModelSelector] | None = None,
) -> list[MetaTableRegistrationRequest]:
    """Build MetaTable registration requests for all markets SQLAlchemy models.

    Platform-managed foreign keys are declared with normal SQLAlchemy
    ``ForeignKey`` targets. Explicit target UIDs are needed only when
    constructing external registered contracts outside the SDK-managed
    lifecycle.
    """

    resolved_models = resolve_markets_meta_table_models(models)
    if management_mode == "external_registered" and not data_source_uid:
        raise ValueError("external_registered MetaTables require data_source_uid.")
    requests: list[MetaTableRegistrationRequest] = []

    for model in resolved_models:
        platform_kwargs = {
            "labels": labels,
            "protect_from_deletion": protect_from_deletion,
        }
        external_kwargs = {
            **platform_kwargs,
            "data_source_uid": data_source_uid,
        }
        if management_mode == "platform_managed":
            registration_builder = (
                time_indexed_registration_request_from_sqlalchemy_model
                if is_time_index_meta_table_model(model)
                else platform_managed_registration_request_from_sqlalchemy_model
            )
            requests.append(
                registration_builder(
                    model,
                    identifier=markets_table_storage_name(model),
                    **_platform_registration_kwargs(
                        model, base_kwargs=platform_kwargs, introspect=introspect
                    ),
                )
            )
            continue
        if management_mode == "external_registered":
            if is_time_index_meta_table_model(model):
                requests.append(
                    time_indexed_registration_request_from_sqlalchemy_model(
                        model,
                        identifier=markets_table_storage_name(model),
                        **_platform_registration_kwargs(
                            model,
                            base_kwargs=platform_kwargs,
                            introspect=introspect,
                        ),
                    )
                )
                continue
            requests.append(
                external_registered_registration_request_from_sqlalchemy_model(
                    model,
                    identifier=markets_table_storage_name(model),
                    introspect=True if introspect is None else introspect,
                    **external_kwargs,
                )
            )
            continue
        raise ValueError("management_mode must be 'platform_managed' or 'external_registered'.")

    return requests


def resolve_registered_markets_meta_tables(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    namespace: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[MarketsModelSelector] | None = None,
) -> MarketsMetaTableRegistrationResult:
    """Resolve already-registered markets MetaTables without creating schemas."""

    resolved_models = resolve_markets_meta_table_models(models)
    table_names_by_model = {model: markets_table_storage_name(model) for model in resolved_models}
    normal_models = [
        model for model in resolved_models if not is_time_index_meta_table_model(model)
    ]
    time_index_models = [
        model for model in resolved_models if is_time_index_meta_table_model(model)
    ]
    normal_table_names = list(dict.fromkeys(table_names_by_model[model] for model in normal_models))
    time_index_table_names = list(
        dict.fromkeys(table_names_by_model[model] for model in time_index_models)
    )
    normal_filters = _registered_meta_table_bulk_body_filter(
        table_names=normal_table_names,
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        namespace=namespace,
    )
    time_index_filters = _registered_time_index_meta_table_bulk_body_filter(
        table_names=time_index_table_names,
        namespace=namespace,
    )
    logger.info(
        "Resolving registered markets MetaTable schemas",
        management_mode=management_mode,
        namespace=normal_filters.get("namespace") or time_index_filters.get("namespace"),
        meta_table_table_name_count=len(normal_table_names),
        time_index_table_name_count=len(time_index_table_names),
        model_count=len(resolved_models),
        data_source_uid=data_source_uid,
    )
    matches_by_table_name: dict[str, MetaTable] = {}
    matches_by_table_name.update(
        _unique_matches_by_physical_table_name(
            resource_name="MetaTable",
            matches=MetaTable.filter_by_body(timeout=timeout, **normal_filters)
            if normal_table_names
            else [],
            requested_table_names=normal_table_names,
            filters=normal_filters,
        )
    )
    matches_by_table_name.update(
        _unique_matches_by_physical_table_name(
            resource_name="TimeIndexMetaTable",
            matches=TimeIndexMetaTable.filter_by_body(timeout=timeout, **time_index_filters)
            if time_index_table_names
            else [],
            requested_table_names=time_index_table_names,
            filters=time_index_filters,
        )
    )
    _raise_for_missing_registered_table_names(
        table_names=[*normal_table_names, *time_index_table_names],
        matches_by_table_name=matches_by_table_name,
        normal_filters=normal_filters,
        time_index_filters=time_index_filters,
    )

    meta_tables: list[MetaTable] = []
    meta_table_by_identifier: dict[str, MetaTable] = {}
    for model in resolved_models:
        identifier = table_names_by_model[model]
        meta_table = matches_by_table_name[identifier]
        _bind_model_meta_table(model, meta_table)
        meta_tables.append(meta_table)
        meta_table_by_identifier[identifier] = meta_table

    logger.info(
        "Resolved registered markets MetaTable schemas",
        management_mode=management_mode,
        namespace=namespace,
        meta_table_count=len(meta_tables),
        model_count=len(resolved_models),
    )

    return MarketsMetaTableRegistrationResult(
        meta_tables=meta_tables,
        models=resolved_models,
        meta_table_by_identifier=meta_table_by_identifier,
    )


def _registered_meta_table_bulk_body_filter(
    *,
    table_names: Sequence[str],
    data_source_uid: str | None,
    management_mode: MarketsManagementMode,
    namespace: str | None,
) -> dict[str, Any]:
    unique_table_names = sorted(dict.fromkeys(table_names))
    base_filters: dict[str, Any] = {
        "physical_table_name__in": unique_table_names,
        "management_mode": management_mode,
        "limit": max(5000, len(unique_table_names)),
        "offset": 0,
    }
    if namespace:
        base_filters["namespace"] = namespace
    if management_mode == "external_registered" and data_source_uid:
        base_filters["data_source__uid"] = data_source_uid

    return _clean_filters(base_filters)


def _registered_time_index_meta_table_bulk_body_filter(
    *,
    table_names: Sequence[str],
    namespace: str | None,
) -> dict[str, Any]:
    unique_table_names = sorted(dict.fromkeys(table_names))
    return _clean_filters(
        {
            "physical_table_name__in": unique_table_names,
            "namespace": namespace,
            "limit": max(5000, len(unique_table_names)),
            "offset": 0,
        }
    )


def _unique_matches_by_physical_table_name(
    *,
    resource_name: str,
    matches: Sequence[MetaTable],
    requested_table_names: Sequence[str],
    filters: Mapping[str, Any],
) -> dict[str, MetaTable]:
    requested = set(requested_table_names)
    matches_by_table_name: dict[str, MetaTable] = {}
    for meta_table in matches:
        table_name = str(getattr(meta_table, "physical_table_name", None) or "")
        if table_name not in requested:
            raise LookupError(
                f"Registered markets {resource_name} lookup returned unexpected "
                f"physical_table_name {table_name!r} for filters {filters!r}."
            )
        if table_name in matches_by_table_name:
            raise LookupError(
                f"Multiple registered markets {resource_name} rows matched "
                f"physical_table_name {table_name!r} with filters {filters!r}. "
                "Pass a narrower runtime selection or repair duplicate platform "
                "registrations."
            )
        matches_by_table_name[table_name] = meta_table
    return matches_by_table_name


def _raise_for_missing_registered_table_names(
    *,
    table_names: Sequence[str],
    matches_by_table_name: Mapping[str, MetaTable],
    normal_filters: Mapping[str, Any],
    time_index_filters: Mapping[str, Any],
) -> None:
    missing_table_names = [
        table_name for table_name in table_names if table_name not in matches_by_table_name
    ]
    if missing_table_names:
        raise LookupError(
            "Could not resolve registered markets MetaTables for "
            f"{missing_table_names!r}. MetaTable filters={normal_filters!r}; "
            f"TimeIndexMetaTable filters={time_index_filters!r}."
        )


def _clean_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if value not in (None, "")}


def _target_meta_tables_from_bound_models(
    models: Sequence[type[MarketsBase]] | None = None,
) -> dict[type[MarketsBase], str]:
    target_meta_tables: dict[type[MarketsBase], str] = {}
    candidates: list[type[MarketsBase]] = []
    seen: set[type[MarketsBase]] = set()
    for model in [*markets_meta_table_models(), *(models or [])]:
        if model in seen:
            continue
        seen.add(model)
        candidates.append(model)
    for model in candidates:
        get_meta_table_uid = getattr(model, "get_meta_table_uid", None)
        if not callable(get_meta_table_uid):
            continue
        meta_table_uid = get_meta_table_uid()
        if meta_table_uid in (None, ""):
            continue
        target_meta_tables[model] = str(meta_table_uid)
    return target_meta_tables


def _metatable_foreign_key_target_model(
    element: Any,
    *,
    candidate_models: Sequence[type[MarketsBase]],
) -> type[MarketsBase]:
    target_table = element.column.table
    models_by_table = _models_by_table_fullname(candidate_models)
    target_model = models_by_table.get(str(target_table.fullname))
    if target_model is None:
        raise ValueError(
            "Markets MetaTable foreign key target is not in the loaded provider model graph: "
            f"{target_table.fullname!r}."
        )
    return target_model


def _metatable_foreign_key_target_models(
    model: type[MarketsBase],
    *,
    candidate_models: Sequence[type[MarketsBase]],
) -> list[type[MarketsBase]]:
    targets: list[type[MarketsBase]] = []
    seen: set[type[MarketsBase]] = set()
    for foreign_key_constraint in model.__table__.foreign_key_constraints:
        for element in foreign_key_constraint.elements:
            target_model = _metatable_foreign_key_target_model(
                element,
                candidate_models=candidate_models,
            )
            if target_model in seen:
                continue
            seen.add(target_model)
            targets.append(target_model)
    return targets


def _models_by_table_fullname(
    models: Sequence[type[MarketsBase]],
) -> dict[str, type[MarketsBase]]:
    models_by_table: dict[str, type[MarketsBase]] = {}
    for model in models:
        table_fullname = str(model.__table__.fullname)
        existing = models_by_table.get(table_fullname)
        if existing is not None and existing is not model:
            raise ValueError(
                "Duplicate markets SQLAlchemy table name "
                f"{table_fullname!r} for {existing.__name__} and {model.__name__}."
            )
        models_by_table[table_fullname] = model
    return models_by_table


def _bind_model_meta_table(model: type[MarketsBase], meta_table: MetaTable) -> None:
    model._bind_meta_table(meta_table)


__all__ = [
    "MarketsManagementMode",
    "MarketsModelSelector",
    "MarketsMetaTableRegistrationResult",
    "build_markets_registration_requests",
    "markets_foreign_key_target_identifiers",
    "markets_meta_table_identifier",
    "markets_meta_table_models",
    "resolve_registered_markets_meta_tables",
    "resolve_markets_meta_table_model",
    "resolve_markets_meta_table_models",
]
