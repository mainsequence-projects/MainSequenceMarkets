from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Any

from msm.api.base import operation_result_rows
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
    register_pricing_meta_tables,
    resolve_pricing_meta_table_models,
)
from .models.market_data_bindings import PricingMarketDataBindingTable
from .settings import (
    PRICING_CONTEXT_DEFAULT,
    default_pricing_market_data_bindings,
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
    data_source_uid: str | None = None,
    management_mode: PricingManagementMode = "platform_managed",
    namespace: str | None = None,
    market_data_configuration: PricingMarketDataConfigurationInput | None = None,
    seed_default_market_data_bindings: bool = True,
    replace_default_market_data_bindings: bool = False,
    models: Sequence[PricingModelSelector] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_identifier: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> PricingRuntime:
    """Register pricing schemas and return a pricing repository runtime."""

    resolved_models = resolve_pricing_meta_table_models(models)
    namespace = markets_namespace(namespace)
    schema_config = _schema_config(
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        namespace=namespace,
        models=resolved_models,
        open_for_everyone=open_for_everyone,
        protect_from_deletion=protect_from_deletion,
        introspect=introspect,
        storage_hash_by_identifier=storage_hash_by_identifier,
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

        registration = register_pricing_meta_tables(
            data_source_uid=data_source_uid,
            management_mode=management_mode,
            open_for_everyone=open_for_everyone,
            protect_from_deletion=protect_from_deletion,
            introspect=introspect,
            storage_hash_by_identifier=storage_hash_by_identifier,
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
    data_source_uid: str | None = None,
    management_mode: PricingManagementMode = "platform_managed",
    namespace: str | None = None,
    market_data_configuration: PricingMarketDataConfigurationInput | None = None,
    seed_default_market_data_bindings: bool = False,
    replace_default_market_data_bindings: bool = False,
    models: Sequence[PricingModelSelector] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> PricingRuntime:
    """Attach to already-registered pricing MetaTables without creating schemas."""

    from msm.models.registration import resolve_registered_markets_meta_tables

    resolved_models = resolve_pricing_meta_table_models(models)
    namespace = markets_namespace(namespace)
    schema_config = _schema_config(
        action="attach",
        data_source_uid=data_source_uid,
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
        registration = resolve_registered_markets_meta_tables(
            data_source_uid=data_source_uid,
            management_mode=management_mode,
            namespace=namespace,
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

    When ``configuration`` is omitted, the canonical package defaults remain
    active. Passing a typed configuration or mapping installs an explicit
    process-wide override.
    """

    if configuration is None:
        return get_pricing_market_data_configuration()
    return set_pricing_market_data_configuration(configuration)


def seed_default_pricing_market_data_bindings(
    runtime: PricingRuntime | None = None,
    *,
    context_key: str = PRICING_CONTEXT_DEFAULT,
    replace: bool = False,
) -> list[dict[str, Any]]:
    """Seed built-in pricing market-data bindings for a runtime context."""

    if runtime is None:
        runtime = resolve_pricing_runtime(
            models=[PricingMarketDataBindingTable],
            row_model_name="PricingMarketDataBinding",
        )
    if PricingMarketDataBindingTable not in runtime.meta_table_models:
        return []

    rows: list[dict[str, Any]] = []
    for concept_key, data_node_identifier in default_pricing_market_data_bindings(
        namespace=runtime.namespace,
    ).items():
        values = {
            "context_key": context_key,
            "concept_key": concept_key,
            "data_node_identifier": data_node_identifier,
            "source": "msm_pricing.bootstrap",
            "metadata_json": {"seeded_default": True},
        }
        if replace:
            result = upsert_model(
                runtime.context,
                model=PricingMarketDataBindingTable,
                values=values,
                conflict_columns=("context_key", "concept_key"),
            )
        else:
            existing = search_model(
                runtime.context,
                model=PricingMarketDataBindingTable,
                filters={
                    "context_key": context_key,
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
                model=PricingMarketDataBindingTable,
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
            context_key=configuration.context_key,
            replace=replace_default_market_data_bindings,
        )
    return configuration


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
        "Call msm_pricing.bootstrap.create_pricing_schemas(...) during application "
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
