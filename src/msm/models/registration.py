from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from mainsequence.client.metatables import MetaTable, MetaTableRegistrationRequest
from mainsequence.logconf import logger as _mainsequence_logger
from mainsequence.meta_tables import (
    PlatformTimeIndexMetaData,
    external_registered_registration_request_from_sqlalchemy_model,
)

from msm.base import (
    MARKETS_SCHEMA,
    MarketsBase,
    markets_meta_table_identifier as _markets_meta_table_identifier,
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
        keys = {
            candidate.__name__,
            str(getattr(candidate, "__markets_base_identifier__", "")),
            str(getattr(candidate, "__metatable_identifier__", "")),
            markets_meta_table_identifier(candidate),
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
    built_in_order = {model: index for index, model in enumerate(built_in_models)}
    caller_order = _model_order(requested_models)
    discovery_order: dict[type[MarketsBase], int] = {}

    def collect(model: type[MarketsBase]) -> None:
        if model in discovery_order:
            return
        discovery_order[model] = len(discovery_order)
        for dependency in _metatable_foreign_key_target_models(model):
            collect(dependency)

    for model in requested_models:
        collect(model)

    resolved_models = list(discovery_order)
    _validate_unique_markets_meta_table_identifiers(resolved_models)

    dependencies = {
        model: {
            dependency
            for dependency in _metatable_foreign_key_target_models(model)
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
    targets: set[str] = set()
    for foreign_key_constraint in model.__table__.foreign_key_constraints:
        for element in foreign_key_constraint.elements:
            target_model = _metatable_foreign_key_target_model(element)
            if target_model is not None:
                targets.add(markets_meta_table_identifier(target_model))
                continue
            targets.add(markets_meta_table_identifier(element.column.table))
    return sorted(targets)


def is_time_index_meta_table_model(model: type[MarketsBase]) -> bool:
    """True for ADR 0017 DataNode output storage classes.

    `PlatformTimeIndexMetaData` subclasses derive their own time-index/storage
    layout and register without the ``introspect`` / ``open_for_everyone``
    arguments accepted by domain `PlatformManagedMetaTable` models.
    """

    return isinstance(model, type) and issubclass(model, PlatformTimeIndexMetaData)


def _platform_registration_kwargs(
    model: type[MarketsBase],
    *,
    base_kwargs: Mapping[str, Any],
    introspect: bool | None,
) -> dict[str, Any]:
    """Shape platform-managed register/build kwargs for one model.

    DataNode storage classes (`PlatformTimeIndexMetaData`) reject ``introspect``
    and ``open_for_everyone``; domain MetaTables require ``introspect``.
    """

    if is_time_index_meta_table_model(model):
        return {key: value for key, value in base_kwargs.items() if key != "open_for_everyone"}
    return {**base_kwargs, "introspect": False if introspect is None else introspect}


def build_markets_registration_requests(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    labels: Sequence[str] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_identifier: Mapping[str, str] | None = None,
    models: Sequence[MarketsModelSelector] | None = None,
) -> list[MetaTableRegistrationRequest]:
    """Build MetaTable registration requests for all markets SQLAlchemy models.

    Platform-managed foreign keys are declared with SDK `MetaTableForeignKey`
    targets. Explicit target UIDs are needed only when constructing external
    registered contracts outside the SDK-managed lifecycle.
    """

    resolved_models = resolve_markets_meta_table_models(models)
    if management_mode == "external_registered" and not data_source_uid:
        raise ValueError("external_registered MetaTables require data_source_uid.")
    storage_hash_mapping = _identifier_mapping(storage_hash_by_identifier)
    requests: list[MetaTableRegistrationRequest] = []

    for model in resolved_models:
        target_meta_tables = _target_meta_tables_from_bound_models(resolved_models)
        platform_kwargs = {
            "labels": labels,
            "open_for_everyone": open_for_everyone,
            "protect_from_deletion": protect_from_deletion,
        }
        external_kwargs = {
            **platform_kwargs,
            "data_source_uid": data_source_uid,
            "schema": MARKETS_SCHEMA,
            "target_meta_tables": target_meta_tables,
        }
        if management_mode == "platform_managed":
            requests.append(
                model.build_registration_request(
                    **_platform_registration_kwargs(
                        model, base_kwargs=platform_kwargs, introspect=introspect
                    )
                )
            )
            continue
        if management_mode == "external_registered":
            if is_time_index_meta_table_model(model):
                requests.append(
                    model.build_registration_request(
                        **_platform_registration_kwargs(
                            model,
                            base_kwargs={
                                **platform_kwargs,
                                "_target_meta_tables": target_meta_tables,
                            },
                            introspect=introspect,
                        )
                    )
                )
                continue
            requests.append(
                external_registered_registration_request_from_sqlalchemy_model(
                    model,
                    introspect=True if introspect is None else introspect,
                    storage_hash=storage_hash_mapping.get(markets_meta_table_identifier(model)),
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
    identifiers_by_model = {
        model: markets_meta_table_identifier(model) for model in resolved_models
    }
    requested_identifiers = list(dict.fromkeys(identifiers_by_model.values()))
    filters = _registered_meta_table_bulk_filter(
        identifiers=requested_identifiers,
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        namespace=namespace,
    )
    logger.info(
        "Resolving registered markets MetaTable schemas",
        management_mode=management_mode,
        namespace=filters.get("namespace"),
        identifier_count=len(requested_identifiers),
        model_count=len(resolved_models),
        data_source_uid=data_source_uid,
    )
    matches = MetaTable.filter(timeout=timeout, **filters) if requested_identifiers else []
    matches_by_identifier: dict[str, MetaTable] = {}
    for meta_table in matches:
        identifier = str(getattr(meta_table, "identifier", "") or "")
        if identifier not in requested_identifiers:
            continue
        if identifier in matches_by_identifier:
            raise LookupError(
                "Multiple registered markets MetaTables matched "
                f"identifier {identifier!r} with filters {filters!r}. Pass data_source_uid "
                "or repair duplicate platform registrations."
            )
        matches_by_identifier[identifier] = meta_table

    missing_identifiers = [
        identifier
        for identifier in requested_identifiers
        if identifier not in matches_by_identifier
    ]
    if missing_identifiers:
        raise LookupError(
            "Could not resolve registered markets MetaTables for "
            f"{missing_identifiers!r} with filters {filters!r}."
        )

    meta_tables: list[MetaTable] = []
    meta_table_by_identifier: dict[str, MetaTable] = {}
    for model in resolved_models:
        identifier = identifiers_by_model[model]
        meta_table = matches_by_identifier[identifier]
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


def _registered_meta_table_bulk_filter(
    *,
    identifiers: Sequence[str],
    data_source_uid: str | None,
    management_mode: MarketsManagementMode,
    namespace: str | None,
) -> dict[str, Any]:
    base_filters: dict[str, Any] = {
        "identifier__in": sorted(dict.fromkeys(identifiers)),
        "management_mode": management_mode,
    }
    if namespace:
        base_filters["namespace"] = namespace
    if management_mode == "external_registered" and data_source_uid:
        base_filters["data_source__uid"] = data_source_uid

    return _clean_filters(base_filters)


def _clean_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if value not in (None, "")}


def _identifier_mapping(
    mapping: Mapping[str, Any] | None,
    *,
    value_transform: Any = str,
) -> dict[str, Any]:
    if mapping is None:
        return {}
    return {str(key): value_transform(value) for key, value in mapping.items()}


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


def _metatable_foreign_key_target_model(element: Any) -> type[MarketsBase] | None:
    info = getattr(element, "info", None)
    if not isinstance(info, Mapping):
        return None
    metadata = info.get("mainsequence_metatable_foreign_key")
    if not isinstance(metadata, Mapping):
        return None
    target_model = metadata.get("target_model")
    if isinstance(target_model, type):
        return target_model
    return None


def _metatable_foreign_key_target_models(model: type[MarketsBase]) -> list[type[MarketsBase]]:
    targets: list[type[MarketsBase]] = []
    seen: set[type[MarketsBase]] = set()
    for foreign_key_constraint in model.__table__.foreign_key_constraints:
        for element in foreign_key_constraint.elements:
            target_model = _metatable_foreign_key_target_model(element)
            if (
                target_model is None
                or not issubclass(target_model, MarketsBase)
                or target_model in seen
            ):
                continue
            seen.add(target_model)
            targets.append(target_model)
    return targets


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
