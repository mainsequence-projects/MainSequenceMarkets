from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Any

from msm.api.base import operation_result_rows
from msm.base import MarketsBase
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import create_model, search_model, upsert_model
from msm.settings import markets_namespace

from .config import (
    PricingMarketDataConfiguration,
    PricingMarketDataConfigurationInput,
    get_pricing_market_data_configuration,
    set_pricing_market_data_configuration,
)
from .meta_tables import (
    PricingManagementMode,
    PricingMetaTableRegistrationResult,
    PricingModelSelector,
    pricing_meta_table_identifier,
    resolve_pricing_meta_table_models,
)
from .models.market_data_bindings import (
    PricingMarketDataSetBindingTable,
    PricingMarketDataSetTable,
)
from .settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    PRICING_MARKET_DATA_SET_DEFAULT,
)

_CREATE_PRICING_SCHEMAS_LOCK = Lock()
_PRICING_RUNTIME: PricingRuntime | None = None
_CREATE_PRICING_SCHEMAS_CONFIG: tuple[tuple[str, Any], ...] | None = None
_PRICING_RUNTIME_BY_CONFIG: dict[tuple[tuple[str, Any], ...], PricingRuntime] = {}


@dataclass(frozen=True)
class PricingRuntime:
    """Runtime handles created for pricing MetaTable-backed APIs."""

    registration: PricingMetaTableRegistrationResult
    context: MarketsRepositoryContext
    namespace: str | None = None

    @property
    def meta_tables(self) -> list[Any]:
        return self.registration.meta_tables

    @property
    def meta_table_models(self) -> list[type[Any]]:
        return list(self.registration.models)


def create_pricing_schemas(
    *,
    management_mode: PricingManagementMode = "platform_managed",
    namespace: str | None = None,
    market_data_configuration: PricingMarketDataConfigurationInput | None = None,
    seed_default_market_data_bindings: bool = True,
    replace_default_market_data_bindings: bool = False,
    models: Sequence[PricingModelSelector] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> PricingRuntime:
    """Attach pricing schemas and return a pricing repository runtime.

    MetaTable registration is migration-owned. This legacy entrypoint remains
    for callers that also want pricing market-data configuration during startup.
    """

    resolved_models = _pricing_startup_models(
        models,
        seed_default_market_data_bindings=seed_default_market_data_bindings,
    )
    namespace = markets_namespace(namespace)
    schema_config = _schema_config(
        management_mode=management_mode,
        namespace=namespace,
        models=resolved_models,
        timeout=timeout,
    )

    global _PRICING_RUNTIME, _CREATE_PRICING_SCHEMAS_CONFIG
    with _CREATE_PRICING_SCHEMAS_LOCK:
        cached_runtime = _PRICING_RUNTIME_BY_CONFIG.get(schema_config)
        if cached_runtime is not None:
            _configure_pricing_runtime_market_data(
                cached_runtime,
                market_data_configuration=market_data_configuration,
                seed_default_market_data_bindings=seed_default_market_data_bindings,
                replace_default_market_data_bindings=replace_default_market_data_bindings,
            )
            return cached_runtime
        if _CREATE_PRICING_SCHEMAS_CONFIG is not None:
            if _CREATE_PRICING_SCHEMAS_CONFIG == schema_config:
                if _PRICING_RUNTIME is None:
                    raise RuntimeError("Pricing runtime cache is inconsistent.")
                _configure_pricing_runtime_market_data(
                    _PRICING_RUNTIME,
                    market_data_configuration=market_data_configuration,
                    seed_default_market_data_bindings=seed_default_market_data_bindings,
                    replace_default_market_data_bindings=replace_default_market_data_bindings,
                )
                return _PRICING_RUNTIME
            raise RuntimeError(
                "msm_pricing.create_pricing_schemas() has already initialized "
                "this process with different schema arguments. Run it once at "
                "process startup before pricing row operations."
            )

        registration = _resolve_registered_pricing_meta_tables(
            management_mode=management_mode,
            timeout=timeout,
            models=resolved_models,
        )
        runtime = PricingRuntime(
            registration=registration,
            context=MarketsRepositoryContext(
                timeout=timeout,
                namespace=namespace,
            ),
            namespace=namespace,
        )

        _PRICING_RUNTIME = runtime
        _CREATE_PRICING_SCHEMAS_CONFIG = schema_config
        _PRICING_RUNTIME_BY_CONFIG[schema_config] = runtime
        _configure_pricing_runtime_market_data(
            runtime,
            market_data_configuration=market_data_configuration,
            seed_default_market_data_bindings=seed_default_market_data_bindings,
            replace_default_market_data_bindings=replace_default_market_data_bindings,
        )
        return runtime


def attach_pricing_schemas(
    *,
    management_mode: PricingManagementMode = "platform_managed",
    namespace: str | None = None,
    market_data_configuration: PricingMarketDataConfigurationInput | None = None,
    seed_default_market_data_bindings: bool = False,
    replace_default_market_data_bindings: bool = False,
    models: Sequence[PricingModelSelector] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> PricingRuntime:
    """Attach to already-registered pricing MetaTables without creating schemas."""

    resolved_models = _pricing_startup_models(
        models,
        seed_default_market_data_bindings=seed_default_market_data_bindings,
    )
    namespace = markets_namespace(namespace)
    schema_config = _schema_config(
        action="attach",
        management_mode=management_mode,
        namespace=namespace,
        models=resolved_models,
        timeout=timeout,
    )

    global _PRICING_RUNTIME
    with _CREATE_PRICING_SCHEMAS_LOCK:
        cached_runtime = _PRICING_RUNTIME_BY_CONFIG.get(schema_config)
        if cached_runtime is not None:
            _configure_pricing_runtime_market_data(
                cached_runtime,
                market_data_configuration=market_data_configuration,
                seed_default_market_data_bindings=seed_default_market_data_bindings,
                replace_default_market_data_bindings=replace_default_market_data_bindings,
            )
            return cached_runtime
        registration = _resolve_registered_pricing_meta_tables(
            management_mode=management_mode,
            timeout=timeout,
            models=resolved_models,
        )
        runtime = PricingRuntime(
            registration=registration,
            context=MarketsRepositoryContext(
                timeout=timeout,
                namespace=namespace,
            ),
            namespace=namespace,
        )
        _PRICING_RUNTIME_BY_CONFIG[schema_config] = runtime
        _PRICING_RUNTIME = runtime
        _configure_pricing_runtime_market_data(
            runtime,
            market_data_configuration=market_data_configuration,
            seed_default_market_data_bindings=seed_default_market_data_bindings,
            replace_default_market_data_bindings=replace_default_market_data_bindings,
        )
        return runtime


def resolve_pricing_runtime(
    *,
    models: Sequence[PricingModelSelector],
    row_model_name: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> PricingRuntime:
    """Resolve the active pricing runtime for row operations."""

    _ = timeout

    resolved_models = resolve_pricing_meta_table_models(models)
    if _PRICING_RUNTIME is not None and not _missing_models_from_runtime(
        _PRICING_RUNTIME,
        resolved_models,
    ):
        return _PRICING_RUNTIME

    if _PRICING_RUNTIME is None:
        raise RuntimeError(
            _pricing_not_initialized_error_message(
                row_model_name=row_model_name,
                models=resolved_models,
            )
        )

    raise RuntimeError(
        _pricing_missing_models_error_message(
            row_model_name=row_model_name,
            missing_models=_missing_models_from_runtime(_PRICING_RUNTIME, resolved_models),
            runtime=_PRICING_RUNTIME,
        )
    )


def configure_pricing_market_data(
    configuration: PricingMarketDataConfigurationInput | None = None,
) -> PricingMarketDataConfiguration:
    """Install pricing market-data runtime configuration.

    When ``configuration`` is omitted, the default pricing context remains active
    and market-data DataNodes are resolved through persisted pricing bindings.
    Passing a typed configuration or mapping installs an explicit process-wide
    override.
    """

    if configuration is None:
        return get_pricing_market_data_configuration()
    return set_pricing_market_data_configuration(configuration)


def seed_default_pricing_market_data_bindings(
    runtime: PricingRuntime | None = None,
    *,
    market_data_set: str | uuid.UUID = PRICING_MARKET_DATA_SET_DEFAULT,
    replace: bool = False,
) -> list[dict[str, Any]]:
    """Seed built-in pricing market-data bindings for a runtime context."""

    if runtime is None:
        runtime = resolve_pricing_runtime(
            models=_pricing_default_market_data_binding_models(),
            row_model_name="PricingMarketDataSetBinding",
        )
    if (
        PricingMarketDataSetTable not in runtime.meta_table_models
        or PricingMarketDataSetBindingTable not in runtime.meta_table_models
    ):
        return []

    set_row = _upsert_pricing_market_data_set(
        runtime,
        market_data_set=market_data_set,
        replace=replace,
    )
    market_data_set_uid = uuid.UUID(str(set_row["uid"]))

    rows: list[dict[str, Any]] = [set_row]
    for concept_key, storage in _default_pricing_market_data_bindings_from_runtime(runtime).items():
        values = {
            "market_data_set_uid": market_data_set_uid,
            "concept_key": concept_key,
            "data_node_uid": storage["data_node_uid"],
            "storage_table_identifier": storage["storage_table_identifier"],
            "source": "msm_pricing.bootstrap",
            "metadata_json": {"seeded_default": True},
        }
        if replace:
            result = upsert_model(
                runtime.context,
                model=PricingMarketDataSetBindingTable,
                values=values,
                conflict_columns=("market_data_set_uid", "concept_key"),
            )
        else:
            existing = search_model(
                runtime.context,
                model=PricingMarketDataSetBindingTable,
                filters={
                    "market_data_set_uid": market_data_set_uid,
                    "concept_key": concept_key,
                },
                limit=1,
            )
            existing_rows = operation_result_rows(existing)
            if existing_rows:
                rows.extend(existing_rows)
                continue
            result = create_model(
                runtime.context,
                model=PricingMarketDataSetBindingTable,
                values=values,
            )
        rows.extend(operation_result_rows(result))
    return rows


def _configure_pricing_runtime_market_data(
    runtime: PricingRuntime,
    *,
    market_data_configuration: PricingMarketDataConfigurationInput | None,
    seed_default_market_data_bindings: bool,
    replace_default_market_data_bindings: bool,
) -> PricingMarketDataConfiguration:
    configuration = configure_pricing_market_data(market_data_configuration)
    if seed_default_market_data_bindings:
        seed_default_pricing_market_data_bindings(
            runtime,
            market_data_set=configuration.market_data_set,
            replace=replace_default_market_data_bindings,
        )
    return configuration


def _resolve_registered_pricing_meta_tables(
    *,
    management_mode: PricingManagementMode,
    timeout: int | float | tuple[float, float] | None,
    models: Sequence[type[MarketsBase]],
) -> PricingMetaTableRegistrationResult:
    from msm.models.registration import resolve_registered_markets_meta_tables

    return resolve_registered_markets_meta_tables(
        management_mode=management_mode,
        timeout=timeout,
        models=models,
    )


def _pricing_startup_models(
    models: Sequence[PricingModelSelector] | None,
    *,
    seed_default_market_data_bindings: bool,
) -> list[type[MarketsBase]]:
    resolved_models = resolve_pricing_meta_table_models(models)
    if not seed_default_market_data_bindings:
        return resolved_models
    return resolve_pricing_meta_table_models(
        [
            *resolved_models,
            *_pricing_default_market_data_binding_models(),
        ]
    )


def _pricing_default_market_data_binding_models() -> list[type[MarketsBase]]:
    from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
    from msm_pricing.data_nodes.index_fixings.storage import IndexFixingsStorage

    return [
        PricingMarketDataSetTable,
        PricingMarketDataSetBindingTable,
        DiscountCurvesStorage,
        IndexFixingsStorage,
    ]


def _default_pricing_market_data_bindings_from_runtime(
    runtime: PricingRuntime,
) -> dict[str, dict[str, str]]:
    from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
    from msm_pricing.data_nodes.index_fixings.storage import IndexFixingsStorage

    required_models = _pricing_default_market_data_binding_models()
    missing_models = [
        model
        for model in required_models
        if model not in runtime.meta_table_models or _model_meta_table_uid(model) is None
    ]
    if missing_models:
        missing_names = ", ".join(_model_name(model) for model in missing_models)
        raise RuntimeError(
            "Default pricing market-data binding seeding requires attached pricing "
            f"storage tables: {missing_names}."
        )

    return {
        PRICING_CONCEPT_DISCOUNT_CURVES: {
            "data_node_uid": _required_model_meta_table_uid(DiscountCurvesStorage),
            "storage_table_identifier": DiscountCurvesStorage.get_identifier(),
        },
        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: {
            "data_node_uid": _required_model_meta_table_uid(IndexFixingsStorage),
            "storage_table_identifier": IndexFixingsStorage.get_identifier(),
        },
    }


def _upsert_pricing_market_data_set(
    runtime: PricingRuntime,
    *,
    market_data_set: str | uuid.UUID,
    replace: bool,
) -> dict[str, Any]:
    try:
        set_uid = uuid.UUID(str(market_data_set))
    except (TypeError, ValueError):
        set_key = str(market_data_set).strip()
        if not set_key:
            raise ValueError("market_data_set cannot be empty.")
        values = {
            "set_key": set_key,
            "display_name": _display_name_from_set_key(set_key),
            "description": "Built-in pricing market-data set seeded during pricing bootstrap.",
            "status": "ACTIVE",
            "metadata_json": {"seeded_default": True},
        }
        result = upsert_model(
            runtime.context,
            model=PricingMarketDataSetTable,
            values=values,
            conflict_columns=("set_key",),
        )
        rows = operation_result_rows(result)
        if not rows:
            raise LookupError("Pricing market-data set upsert did not return a row.")
        return rows[0]

    existing = search_model(
        runtime.context,
        model=PricingMarketDataSetTable,
        filters={"uid": set_uid},
        limit=1,
    )
    rows = operation_result_rows(existing)
    if rows:
        return rows[0]
    if not replace:
        raise LookupError(f"No pricing market-data set found for uid={set_uid}.")
    values = {
        "uid": set_uid,
        "set_key": str(set_uid),
        "display_name": f"Pricing market-data set {set_uid}",
        "description": "Pricing market-data set seeded by UID during pricing bootstrap.",
        "status": "ACTIVE",
        "metadata_json": {"seeded_default": True},
    }
    result = upsert_model(
        runtime.context,
        model=PricingMarketDataSetTable,
        values=values,
        conflict_columns=("set_key",),
    )
    rows = operation_result_rows(result)
    if not rows:
        raise LookupError("Pricing market-data set upsert did not return a row.")
    return rows[0]


def _display_name_from_set_key(set_key: str) -> str:
    return set_key.replace("_", " ").replace("-", " ").title()


def _missing_models_from_runtime(
    runtime: PricingRuntime,
    models: Sequence[Any],
) -> list[Any]:
    return [
        model
        for model in models
        if model not in runtime.meta_table_models
        or (isinstance(model, type) and _model_meta_table_uid(model) is None)
    ]


def _pricing_not_initialized_error_message(
    *,
    row_model_name: str | None,
    models: Sequence[Any],
) -> str:
    model_names = ", ".join(_model_name(model) for model in models)
    prefix = f"{row_model_name} " if row_model_name else ""
    return (
        f"{prefix}requires an initialized pricing runtime for {model_names}. "
        "Call msm_pricing.bootstrap.attach_pricing_schemas(...) during application "
        "initialization before pricing row operations."
    )


def _pricing_missing_models_error_message(
    *,
    row_model_name: str | None,
    missing_models: Sequence[Any],
    runtime: PricingRuntime,
) -> str:
    missing_model_names = ", ".join(_model_name(model) for model in missing_models)
    missing_model_details = ", ".join(
        f"{_model_name(model)} ({pricing_meta_table_identifier(model)})" for model in missing_models
    )
    initialized_model_names = ", ".join(_model_name(model) for model in runtime.meta_table_models)
    prefix = f"{row_model_name} " if row_model_name else ""
    return (
        f"{prefix}requires {missing_model_details or missing_model_names}, but the active "
        "pricing runtime was initialized without those bound MetaTables. "
        f"Initialized tables: {initialized_model_names or 'none'}. "
        "Include the required tables in the pricing bootstrap before row operations."
    )


def _model_meta_table_uid(model: Any) -> str | None:
    get_meta_table_uid = getattr(model, "get_meta_table_uid", None)
    if not callable(get_meta_table_uid):
        return None
    uid = get_meta_table_uid()
    if uid in (None, ""):
        return None
    return str(uid)


def _required_model_meta_table_uid(model: Any) -> str:
    uid = _model_meta_table_uid(model)
    if uid is None:
        raise RuntimeError(f"{_model_name(model)} is not attached to a backend storage table.")
    return uid


def _model_name(model: Any) -> str:
    return str(getattr(model, "__name__", model))


def _schema_config(**kwargs: Any) -> tuple[tuple[str, Any], ...]:
    return tuple((key, _freeze_start_value(value)) for key, value in kwargs.items())


def _freeze_start_value(value: Any) -> Any:
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze_start_value(item)) for key, item in value.items()))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_start_value(item) for item in value)
    return value


__all__ = [
    "PricingRuntime",
    "attach_pricing_schemas",
    "configure_pricing_market_data",
    "create_pricing_schemas",
    "resolve_pricing_runtime",
]
