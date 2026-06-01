from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from mainsequence.client.exceptions import ConflictError
from mainsequence.client.models_metatables import MetaTable, MetaTableRegistrationRequest
from mainsequence.logconf import logger as _mainsequence_logger
from mainsequence.meta_tables import (
    PlatformTimeIndexMetaData,
    external_registered_registration_request_from_sqlalchemy_model,
    register_external_sqlalchemy_model,
)

from msm.base import (
    MARKETS_SCHEMA,
    MarketsBase,
    markets_meta_table_identifier as _markets_meta_table_identifier,
)
from msm.models import markets_sqlalchemy_models


MarketsManagementMode = Literal["platform_managed", "external_registered"]
MarketsModelSelector = str | type[MarketsBase]
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
    """Resolve a markets MetaTable model class by class, name, or identifier."""

    if isinstance(model, type):
        return model

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
    """Resolve selected markets MetaTable models in library dependency order."""

    all_models = markets_meta_table_models()
    if models is None:
        return all_models

    selected = {resolve_markets_meta_table_model(model) for model in models}
    resolved = [model for model in all_models if model in selected]
    missing = selected.difference(resolved)
    if missing:
        missing_names = ", ".join(sorted(model.__name__ for model in missing))
        raise ValueError(f"Unsupported markets MetaTable model selection: {missing_names}.")
    return resolved


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
    models: Sequence[type[MarketsBase]] | None = None,
) -> list[MetaTableRegistrationRequest]:
    """Build MetaTable registration requests for all markets SQLAlchemy models.

    Platform-managed foreign keys are declared with SDK `MetaTableForeignKey`
    targets. Explicit target UIDs are needed only when constructing external
    registered contracts outside the SDK-managed lifecycle.
    """

    resolved_models = list(models or markets_meta_table_models())
    if management_mode == "external_registered" and not data_source_uid:
        raise ValueError("external_registered MetaTables require data_source_uid.")
    storage_hash_mapping = _identifier_mapping(storage_hash_by_identifier)
    requests: list[MetaTableRegistrationRequest] = []

    for model in resolved_models:
        target_meta_tables = _target_meta_tables_from_bound_models()
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


def register_markets_meta_tables(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    labels: Sequence[str] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_identifier: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> MarketsMetaTableRegistrationResult:
    """Register markets SQLAlchemy models as MetaTables in FK dependency order."""

    if management_mode == "external_registered" and not data_source_uid:
        raise ValueError("external_registered MetaTables require data_source_uid.")

    registered_meta_tables: list[MetaTable] = []
    meta_table_by_identifier: dict[str, MetaTable] = {}
    storage_hash_mapping = _identifier_mapping(storage_hash_by_identifier)

    resolved_models = list(models or markets_meta_table_models())
    for position, model in enumerate(resolved_models, start=1):
        target_meta_tables = _target_meta_tables_from_bound_models()
        platform_kwargs = {
            "labels": labels,
            "open_for_everyone": open_for_everyone,
            "protect_from_deletion": protect_from_deletion,
            "timeout": timeout,
        }
        external_kwargs = {
            **platform_kwargs,
            "data_source_uid": data_source_uid,
            "schema": MARKETS_SCHEMA,
            "target_meta_tables": target_meta_tables,
        }
        identifier = markets_meta_table_identifier(model)
        storage_hash = storage_hash_mapping.get(identifier)
        logger.info(
            "Registering markets MetaTable schema",
            management_mode=management_mode,
            model=model.__name__,
            namespace=getattr(model, "__metatable_namespace__", None),
            identifier=identifier,
            model_index=position,
            model_count=len(resolved_models),
            storage_hash=storage_hash,
            target_meta_table_count=len(target_meta_tables),
        )
        try:
            if is_time_index_meta_table_model(model):
                meta_table = model.register(timeout=timeout)
            elif management_mode == "platform_managed":
                meta_table = model.register(timeout=timeout)
            elif management_mode == "external_registered":
                meta_table = register_external_sqlalchemy_model(
                    model,
                    introspect=True if introspect is None else introspect,
                    storage_hash=storage_hash,
                    **external_kwargs,
                )
            else:
                raise ValueError(
                    "management_mode must be 'platform_managed' or 'external_registered'."
                )
        except ConflictError as exc:
            if is_time_index_meta_table_model(model):
                raise
            meta_table = _duplicate_meta_table_from_conflict(
                exc,
                model=model,
                management_mode=management_mode,
                timeout=timeout,
            )
            if meta_table is None:
                raise
            logger.info(
                "Reusing existing markets MetaTable schema after duplicate registration",
                management_mode=management_mode,
                model=model.__name__,
                namespace=getattr(model, "__metatable_namespace__", None),
                identifier=identifier,
                model_index=position,
                model_count=len(resolved_models),
                meta_table_uid=_meta_table_uid(meta_table),
            )

        _bind_model_meta_table(model, meta_table)
        registered_meta_tables.append(meta_table)
        meta_table_uid = _meta_table_uid(meta_table)
        meta_table_by_identifier[identifier] = meta_table
        logger.info(
            "Registered markets MetaTable schema",
            management_mode=management_mode,
            model=model.__name__,
            namespace=getattr(model, "__metatable_namespace__", None),
            identifier=identifier,
            model_index=position,
            model_count=len(resolved_models),
            meta_table_uid=meta_table_uid,
        )

    return MarketsMetaTableRegistrationResult(
        meta_tables=registered_meta_tables,
        models=resolved_models,
        meta_table_by_identifier=meta_table_by_identifier,
    )


def resolve_registered_markets_meta_tables(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    namespace: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> MarketsMetaTableRegistrationResult:
    """Resolve already-registered markets MetaTables without creating schemas."""

    resolved_models = list(models or markets_meta_table_models())
    meta_tables: list[MetaTable] = []
    meta_table_by_identifier: dict[str, MetaTable] = {}

    for model in resolved_models:
        identifier = markets_meta_table_identifier(model)
        filter_candidates = _registered_meta_table_filter_candidates(
            model,
            data_source_uid=data_source_uid,
            management_mode=management_mode,
            namespace=namespace,
        )
        matches = []
        matched_filters: dict[str, Any] | None = None
        for filters in filter_candidates:
            logger.info(
                "Resolving registered markets MetaTable schema",
                management_mode=management_mode,
                model=model.__name__,
                namespace=filters.get("namespace"),
                identifier=identifier,
                data_source_uid=data_source_uid,
            )
            matches = MetaTable.filter(timeout=timeout, **filters)
            if matches:
                matched_filters = filters
                break
        if not matches:
            raise LookupError(
                "Could not resolve registered markets MetaTable for "
                f"{model.__name__} with filters {filter_candidates!r}."
            )
        if len(matches) > 1:
            raise LookupError(
                "Multiple registered markets MetaTables matched "
                f"{model.__name__} with filters {matched_filters!r}. Pass data_source_uid "
                "or use explicit schema initialization."
            )

        meta_table = matches[0]
        _bind_model_meta_table(model, meta_table)
        meta_tables.append(meta_table)
        meta_table_by_identifier[identifier] = meta_table
        logger.info(
            "Resolved registered markets MetaTable schema",
            management_mode=management_mode,
            model=model.__name__,
            namespace=getattr(meta_table, "namespace", None),
            identifier=identifier,
            meta_table_uid=_meta_table_uid(meta_table),
        )

    return MarketsMetaTableRegistrationResult(
        meta_tables=meta_tables,
        models=resolved_models,
        meta_table_by_identifier=meta_table_by_identifier,
    )


def _registered_meta_table_filter_candidates(
    model: type[MarketsBase],
    *,
    data_source_uid: str | None,
    management_mode: MarketsManagementMode,
    namespace: str | None,
) -> list[dict[str, Any]]:
    base_filters: dict[str, Any] = {
        "identifier": getattr(model, "__metatable_identifier__", model.__name__),
        "management_mode": management_mode,
    }
    if namespace:
        base_filters["namespace"] = namespace
    if management_mode == "external_registered" and data_source_uid:
        base_filters["data_source__uid"] = data_source_uid

    return [_clean_filters(base_filters)]


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


def _target_meta_tables_from_bound_models() -> dict[type[MarketsBase], str]:
    target_meta_tables: dict[type[MarketsBase], str] = {}
    for model in markets_meta_table_models():
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


def _duplicate_meta_table_from_conflict(
    exc: ConflictError,
    *,
    model: type[MarketsBase],
    management_mode: MarketsManagementMode,
    timeout: int | float | tuple[float, float] | None,
) -> MetaTable | None:
    payload = _conflict_payload(exc)
    if payload.get("code") != "duplicate_meta_table":
        return None

    existing_uid = payload.get("existing_meta_table_uid")
    if not existing_uid:
        return None

    try:
        return MetaTable.get_by_uid(uid=str(existing_uid), timeout=timeout)
    except Exception:
        table_name = str(payload.get("physical_table_name") or model.__table__.name)
        storage_hash = str(payload.get("storage_hash") or table_name)
        return MetaTable(
            uid=str(existing_uid),
            data_source_uid=payload.get("data_source_uid"),
            storage_hash=storage_hash,
            identifier=getattr(model, "__metatable_identifier__", model.__name__),
            namespace=getattr(model, "__metatable_namespace__", None),
            management_mode=management_mode,
            physical_table_name=table_name,
        )


def _conflict_payload(exc: ConflictError) -> dict[str, Any]:
    payload = getattr(exc, "payload", None)
    if isinstance(payload, Mapping):
        return dict(payload)

    response = getattr(exc, "response", None)
    if response is None:
        return {}
    try:
        response_payload = response.json()
    except Exception:
        return {}
    if isinstance(response_payload, Mapping):
        return dict(response_payload)
    return {}


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
    "register_markets_meta_tables",
    "resolve_registered_markets_meta_tables",
    "resolve_markets_meta_table_model",
    "resolve_markets_meta_table_models",
]
