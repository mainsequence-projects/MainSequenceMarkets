from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal

from mainsequence.logconf import logger as _mainsequence_logger

from msm.base import markets_table_storage_name

if TYPE_CHECKING:
    from msm.models.registration import MarketsMetaTableRegistrationResult, MarketsModelSelector
    from msm.repositories.base import MarketsMetaTableHandle, MarketsRepositoryContext

MarketsManagementMode = Literal["platform_managed", "external_registered"]

_START_ENGINE_LOCK = Lock()
_RUNTIME: MarketsRuntime | None = None
_START_ENGINE_CONFIG: tuple[tuple[str, Any], ...] | None = None
_RUNTIME_BY_CONFIG: dict[tuple[tuple[str, Any], ...], MarketsRuntime] = {}
logger = _mainsequence_logger.bind(sub_application="markets", component="bootstrap")


@dataclass(frozen=True)
class MarketsRuntime:
    """Runtime handles created by `msm.start_engine()`."""

    registration: "MarketsMetaTableRegistrationResult"
    context: "MarketsRepositoryContext"

    @property
    def meta_tables(self) -> list[Any]:
        return self.registration.meta_tables

    @property
    def meta_table_models(self) -> list[type[Any]]:
        return list(self.registration.models)

    def table(self, model: "MarketsModelSelector") -> "MarketsMetaTableHandle":
        handle = self.context.table(model)
        meta_table = self.registration.meta_table_by_identifier.get(
            markets_table_storage_name(handle.model)
        )
        if meta_table is None:
            return handle
        return replace(handle, meta_table=meta_table)


def start_engine(
    *,
    management_mode: MarketsManagementMode = "platform_managed",
    models: Sequence["MarketsModelSelector"] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Bootstrap the markets runtime once and return a repository context."""

    schema_config = _schema_config(
        management_mode=management_mode,
        models=models,
        timeout=timeout,
    )

    global _RUNTIME, _START_ENGINE_CONFIG
    with _START_ENGINE_LOCK:
        cached_runtime = _RUNTIME_BY_CONFIG.get(schema_config)
        if cached_runtime is not None:
            logger.info(
                "Reusing cached markets runtime; no schema mutation needed",
                management_mode=management_mode,
                meta_table_count=len(cached_runtime.meta_tables),
            )
            return cached_runtime

        if _START_ENGINE_CONFIG is not None:
            if _START_ENGINE_CONFIG == schema_config:
                if _RUNTIME is None:
                    raise RuntimeError("Markets runtime cache is inconsistent.")
                return _RUNTIME
            raise RuntimeError(
                "msm.start_engine() has already initialized this process with "
                "different schema arguments. Run it once at process startup, with every "
                "table the process needs."
            )

        logger.info(
            "Starting markets runtime attachment",
            management_mode=management_mode,
            requested_model_count=None if models is None else len(models),
            timeout=timeout,
        )
        from msm.models.registration import (
            resolve_markets_meta_table_models,
            resolve_registered_markets_meta_tables,
        )
        from msm.repositories.base import MarketsRepositoryContext

        meta_table_models = resolve_markets_meta_table_models(models)
        logger.info(
            "Resolved markets MetaTable models",
            model_count=len(meta_table_models),
            models=[_model_name(model) for model in meta_table_models],
        )
        registration = resolve_registered_markets_meta_tables(
            management_mode=management_mode,
            timeout=timeout,
            models=meta_table_models,
        )
        logger.info(
            "Resolved registered markets MetaTables",
            management_mode=management_mode,
            meta_table_count=len(registration.meta_tables),
        )
        context = MarketsRepositoryContext(timeout=timeout)
        logger.info("Created markets repository context", timeout=timeout)
        _RUNTIME = MarketsRuntime(
            registration=registration,
            context=context,
        )
        _START_ENGINE_CONFIG = schema_config
        _RUNTIME_BY_CONFIG[schema_config] = _RUNTIME
        logger.info(
            "Created markets runtime",
            meta_table_count=len(_RUNTIME.meta_tables),
        )
        return _RUNTIME


def attach_schemas(
    *,
    management_mode: MarketsManagementMode = "platform_managed",
    models: Sequence["MarketsModelSelector"] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Attach to already-registered markets MetaTables without creating schemas."""

    schema_config = _schema_config(
        action="attach",
        management_mode=management_mode,
        models=models,
        timeout=timeout,
    )

    global _RUNTIME
    with _START_ENGINE_LOCK:
        cached_runtime = _RUNTIME_BY_CONFIG.get(schema_config)
        if cached_runtime is not None:
            logger.info(
                "Reusing cached attached markets runtime",
                management_mode=management_mode,
                meta_table_count=len(cached_runtime.meta_tables),
            )
            return cached_runtime

        from msm.models.registration import (
            resolve_markets_meta_table_models,
            resolve_registered_markets_meta_tables,
        )
        from msm.repositories.base import MarketsRepositoryContext

        meta_table_models = resolve_markets_meta_table_models(models)
        registration = resolve_registered_markets_meta_tables(
            management_mode=management_mode,
            timeout=timeout,
            models=meta_table_models,
        )
        context = MarketsRepositoryContext(timeout=timeout)
        runtime = MarketsRuntime(
            registration=registration,
            context=context,
        )
        _RUNTIME_BY_CONFIG[schema_config] = runtime
        if _RUNTIME is None:
            _RUNTIME = runtime
        logger.info(
            "Attached markets runtime",
            management_mode=management_mode,
            meta_table_count=len(runtime.meta_tables),
        )
        return runtime


def resolve_runtime(
    *,
    models: Sequence["MarketsModelSelector"],
    row_model_name: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Resolve the active runtime for row operations."""

    _ = timeout

    from msm.models.registration import resolve_markets_meta_table_models

    resolved_models = resolve_markets_meta_table_models(models)
    missing_from_active = _missing_models_from_runtime(_RUNTIME, resolved_models)
    if _RUNTIME is not None and not missing_from_active:
        return _RUNTIME

    if _RUNTIME is None:
        raise RuntimeError(
            _runtime_not_initialized_error_message(
                row_model_name=row_model_name,
                models=resolved_models,
            )
        )
    raise RuntimeError(
        _runtime_missing_models_error_message(
            row_model_name=row_model_name,
            missing_models=missing_from_active,
            runtime=_RUNTIME,
        )
    )


def get_runtime() -> MarketsRuntime:
    """Return the initialized markets runtime or fail with bootstrap guidance."""

    if _RUNTIME is None:
        raise RuntimeError(
            "Markets engine is not initialized. Call msm.start_engine(...) "
            "during application initialization before calling row operations."
        )
    return _RUNTIME


def _missing_models_from_runtime(
    runtime: MarketsRuntime | None,
    models: Sequence[Any],
) -> list[Any]:
    if runtime is None:
        return list(models)

    return [
        model
        for model in models
        if model not in runtime.meta_table_models
        or (isinstance(model, type) and _model_meta_table_uid(model) is None)
    ]


def _runtime_not_initialized_error_message(
    *,
    row_model_name: str | None,
    models: Sequence[Any],
) -> str:
    row_name = row_model_name or "Markets row operation"
    missing_models = ", ".join(_model_name(model) for model in models)
    return (
        f"{row_name} requires an initialized markets runtime for {missing_models}. "
        "Run msm.start_engine(models=[...]) during application initialization "
        "before row operations."
    )


def _runtime_missing_models_error_message(
    *,
    row_model_name: str | None,
    missing_models: Sequence[Any],
    runtime: MarketsRuntime,
) -> str:
    from msm.models.registration import markets_meta_table_identifier

    row_name = row_model_name or "Markets row operation"
    missing_model_names = ", ".join(
        f"{_model_name(model)} ({markets_meta_table_identifier(model)})" for model in missing_models
    )
    initialized_model_names = ", ".join(_model_name(model) for model in runtime.meta_table_models)
    return (
        f"{row_name} requires {missing_model_names}, but the active markets runtime "
        "was initialized without those bound MetaTables. Initialized tables: "
        f"{initialized_model_names or 'none'}. Include the required tables in the "
        "process bootstrap before row operations."
    )


def _model_meta_table_uid(model: Any) -> str | None:
    get_meta_table_uid = getattr(model, "get_meta_table_uid", None)
    if not callable(get_meta_table_uid):
        return None
    uid = get_meta_table_uid()
    if uid in (None, ""):
        return None
    return str(uid)


def _schema_config(**kwargs: Any) -> tuple[tuple[str, Any], ...]:
    return tuple((key, _freeze_start_value(value)) for key, value in kwargs.items())


def _model_name(model: Any) -> str:
    return str(getattr(model, "__name__", model))


def _freeze_start_value(value: Any) -> Any:
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze_start_value(item)) for key, item in value.items()))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_start_value(item) for item in value)
    return value


__all__ = ["start_engine"]
