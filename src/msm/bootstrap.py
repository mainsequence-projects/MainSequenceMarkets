from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal

from mainsequence.logconf import logger as _mainsequence_logger

from msm.base import MSM_AUTO_REGISTER_NAMESPACE_ENV

if TYPE_CHECKING:
    from msm.meta_tables import MarketsMetaTableRegistrationResult, MarketsModelSelector
    from msm.repositories.base import MarketsMetaTableHandle, MarketsRepositoryContext

MarketsManagementMode = Literal["platform_managed", "external_registered"]
DATA_NODE_HANDLE_NAMES = (
    "AccountHoldings",
    "AssetPricingDetail",
    "AssetSnapshot",
    "PortfolioWeights",
    "PortfoliosDataNode",
    "SignalWeights",
    "VirtualFundHoldings",
)

_CREATE_SCHEMAS_LOCK = Lock()
_RUNTIME: MarketsRuntime | None = None
_CREATE_SCHEMAS_CONFIG: tuple[tuple[str, Any], ...] | None = None
_RUNTIME_BY_CONFIG: dict[tuple[tuple[str, Any], ...], MarketsRuntime] = {}
logger = _mainsequence_logger.bind(sub_application="markets", component="bootstrap")


@dataclass(frozen=True)
class MarketsRuntime:
    """Runtime handles created by `msm.create_schemas()`."""

    registration: "MarketsMetaTableRegistrationResult"
    context: "MarketsRepositoryContext"
    namespace: str | None = None

    @property
    def meta_tables(self) -> list[Any]:
        return self.registration.meta_tables

    @property
    def target_meta_table_uid_by_fullname(self) -> dict[str, str]:
        return self.registration.target_meta_table_uid_by_fullname

    @property
    def meta_table_models(self) -> list[type[Any]]:
        return list(self.registration.models)

    def table(self, model: "MarketsModelSelector") -> "MarketsMetaTableHandle":
        handle = self.context.table(model)
        meta_table = self.registration.meta_table_by_fullname.get(
            str(handle.model.__table__.fullname)
        )
        if meta_table is None:
            return handle
        return replace(handle, meta_table=meta_table)

    @property
    def data_nodes(self) -> dict[str, type[Any]]:
        from msm.accounts.data_nodes import AccountHoldings, VirtualFundHoldings
        from msm.data_nodes import AssetPricingDetail, AssetSnapshot
        from msm.portfolios.data_nodes import (
            PortfolioWeights,
            PortfoliosDataNode,
            SignalWeights,
        )

        return {
            "AccountHoldings": AccountHoldings,
            "AssetPricingDetail": AssetPricingDetail,
            "AssetSnapshot": AssetSnapshot,
            "PortfolioWeights": PortfolioWeights,
            "PortfoliosDataNode": PortfoliosDataNode,
            "SignalWeights": SignalWeights,
            "VirtualFundHoldings": VirtualFundHoldings,
        }


def configure_metatable_namespace(namespace: str) -> None:
    """Set the MetaTable namespace before markets SQLAlchemy models are mapped."""

    loaded_model_modules = sorted(
        module_name
        for module_name in sys.modules
        if module_name == "msm.models"
        or module_name.startswith("msm.models.")
        or module_name == "msm.meta_tables"
    )
    if loaded_model_modules:
        raise RuntimeError(
            "Configure the MetaTable namespace before importing msm.models or "
            f"msm.meta_tables. Already loaded: {loaded_model_modules!r}."
        )

    from msm.base import MarketsMetaTableMixin

    MarketsMetaTableMixin.__metatable_namespace__ = namespace


def create_schemas(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    namespace: str | None = None,
    models: Sequence["MarketsModelSelector"] | None = None,
    target_meta_table_uid_by_fullname: Mapping[str, Any] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_fullname: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Create markets schemas once and return a repository runtime context."""

    schema_config = _schema_config(
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        namespace=namespace,
        models=models,
        target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
        open_for_everyone=open_for_everyone,
        protect_from_deletion=protect_from_deletion,
        introspect=introspect,
        storage_hash_by_fullname=storage_hash_by_fullname,
        timeout=timeout,
    )

    global _RUNTIME, _CREATE_SCHEMAS_CONFIG
    with _CREATE_SCHEMAS_LOCK:
        cached_runtime = _RUNTIME_BY_CONFIG.get(schema_config)
        if cached_runtime is not None:
            logger.info(
                "Reusing cached markets runtime; no MetaTables registered",
                management_mode=management_mode,
                namespace=namespace,
                meta_table_count=len(cached_runtime.meta_tables),
            )
            return cached_runtime

        if _CREATE_SCHEMAS_CONFIG is not None:
            if _CREATE_SCHEMAS_CONFIG == schema_config:
                if _RUNTIME is None:
                    raise RuntimeError("Markets runtime cache is inconsistent.")
                return _RUNTIME
            raise RuntimeError(
                "msm.create_schemas() has already initialized this process with "
                "different schema arguments. Run it once at process startup before "
                "importing MetaTable-backed models, repositories, or services."
            )

        logger.info(
            "Starting markets bootstrap",
            management_mode=management_mode,
            namespace=namespace,
            data_source_uid=data_source_uid,
            target_meta_table_count=len(target_meta_table_uid_by_fullname or {}),
            storage_hash_count=len(storage_hash_by_fullname or {}),
            requested_model_count=None if models is None else len(models),
            open_for_everyone=open_for_everyone,
            protect_from_deletion=protect_from_deletion,
            introspect=introspect,
            timeout=timeout,
        )
        if namespace is not None:
            logger.info("Configuring markets MetaTable namespace", namespace=namespace)
            configure_metatable_namespace(namespace)

        from msm.meta_tables import (
            register_markets_meta_tables,
            resolve_markets_meta_table_models,
        )
        from msm.repositories.base import MarketsRepositoryContext

        meta_table_models = resolve_markets_meta_table_models(models)
        logger.info(
            "Resolved markets MetaTable models",
            namespace=namespace,
            model_count=len(meta_table_models),
            models=[_model_name(model) for model in meta_table_models],
        )
        registration = register_markets_meta_tables(
            data_source_uid=data_source_uid,
            management_mode=management_mode,
            target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
            open_for_everyone=open_for_everyone,
            protect_from_deletion=protect_from_deletion,
            introspect=introspect,
            storage_hash_by_fullname=storage_hash_by_fullname,
            timeout=timeout,
            models=meta_table_models,
        )
        logger.info(
            "Registered markets MetaTables",
            management_mode=management_mode,
            namespace=namespace,
            meta_table_count=len(registration.meta_tables),
            target_meta_table_count=len(registration.target_meta_table_uid_by_fullname),
        )
        context = MarketsRepositoryContext(
            target_meta_table_uid_by_fullname=registration.target_meta_table_uid_by_fullname,
            timeout=timeout,
            namespace=namespace,
        )
        logger.info(
            "Created markets repository context",
            namespace=namespace,
            target_meta_table_count=len(context.target_meta_table_uid_by_fullname),
            timeout=timeout,
        )
        _RUNTIME = MarketsRuntime(
            registration=registration,
            context=context,
            namespace=namespace,
        )
        _CREATE_SCHEMAS_CONFIG = schema_config
        _RUNTIME_BY_CONFIG[schema_config] = _RUNTIME
        logger.info(
            "Created markets runtime",
            namespace=namespace,
            meta_table_count=len(_RUNTIME.meta_tables),
            data_node_handles=list(DATA_NODE_HANDLE_NAMES),
        )
        return _RUNTIME


def attach_schemas(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    namespace: str | None = None,
    models: Sequence["MarketsModelSelector"] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Attach to already-registered markets MetaTables without creating schemas."""

    schema_config = _schema_config(
        action="attach",
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        namespace=namespace,
        models=models,
        timeout=timeout,
    )

    global _RUNTIME
    with _CREATE_SCHEMAS_LOCK:
        cached_runtime = _RUNTIME_BY_CONFIG.get(schema_config)
        if cached_runtime is not None:
            logger.info(
                "Reusing cached attached markets runtime",
                management_mode=management_mode,
                namespace=namespace,
                meta_table_count=len(cached_runtime.meta_tables),
            )
            return cached_runtime

        from msm.meta_tables import (
            resolve_markets_meta_table_models,
            resolve_registered_markets_meta_tables,
        )
        from msm.repositories.base import MarketsRepositoryContext

        meta_table_models = resolve_markets_meta_table_models(models)
        registration = resolve_registered_markets_meta_tables(
            data_source_uid=data_source_uid,
            management_mode=management_mode,
            namespace=namespace,
            timeout=timeout,
            models=meta_table_models,
        )
        context = MarketsRepositoryContext(
            target_meta_table_uid_by_fullname=registration.target_meta_table_uid_by_fullname,
            timeout=timeout,
            namespace=namespace,
        )
        runtime = MarketsRuntime(
            registration=registration,
            context=context,
            namespace=namespace,
        )
        _RUNTIME_BY_CONFIG[schema_config] = runtime
        if _RUNTIME is None:
            _RUNTIME = runtime
        logger.info(
            "Attached markets runtime",
            management_mode=management_mode,
            namespace=namespace,
            meta_table_count=len(runtime.meta_tables),
        )
        return runtime


def resolve_runtime(
    *,
    models: Sequence["MarketsModelSelector"],
    row_model_name: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Resolve runtime for row operations with attach-first semantics."""

    from msm.meta_tables import resolve_markets_meta_table_models

    resolved_models = resolve_markets_meta_table_models(models)
    missing_from_active = _missing_models_from_runtime(_RUNTIME, resolved_models)
    if _RUNTIME is not None and not missing_from_active:
        return _RUNTIME

    auto_namespace = os.getenv(MSM_AUTO_REGISTER_NAMESPACE_ENV)
    namespace = auto_namespace or _common_model_namespace(resolved_models)
    try:
        return attach_schemas(
            models=resolved_models,
            namespace=namespace,
            timeout=timeout,
        )
    except Exception as attach_error:
        if auto_namespace:
            try:
                return auto_register_schemas(
                    namespace=auto_namespace,
                    models=resolved_models,
                    timeout=timeout,
                )
            except Exception as register_error:
                raise RuntimeError(
                    _schema_resolution_error_message(
                        row_model_name=row_model_name,
                        models=resolved_models,
                        cause=register_error,
                    )
                ) from register_error
        raise RuntimeError(
            _schema_resolution_error_message(
                row_model_name=row_model_name,
                models=resolved_models,
                cause=attach_error,
            )
        ) from attach_error


def auto_register_schemas(
    *,
    namespace: str,
    models: Sequence["MarketsModelSelector"],
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Register one required model set for opt-in row API auto-registration."""

    schema_config = _schema_config(
        action="auto_register",
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        namespace=namespace,
        models=models,
        timeout=timeout,
    )

    global _RUNTIME
    with _CREATE_SCHEMAS_LOCK:
        cached_runtime = _RUNTIME_BY_CONFIG.get(schema_config)
        if cached_runtime is not None:
            logger.info(
                "Reusing cached auto-registered markets runtime",
                management_mode=management_mode,
                namespace=namespace,
                meta_table_count=len(cached_runtime.meta_tables),
            )
            return cached_runtime

        from msm.meta_tables import (
            register_markets_meta_tables,
            resolve_markets_meta_table_models,
        )
        from msm.repositories.base import MarketsRepositoryContext

        meta_table_models = resolve_markets_meta_table_models(models)
        _ensure_models_match_namespace(meta_table_models, namespace=namespace)
        registration = register_markets_meta_tables(
            data_source_uid=data_source_uid,
            management_mode=management_mode,
            timeout=timeout,
            models=meta_table_models,
        )
        context = MarketsRepositoryContext(
            target_meta_table_uid_by_fullname=registration.target_meta_table_uid_by_fullname,
            timeout=timeout,
            namespace=namespace,
        )
        runtime = MarketsRuntime(
            registration=registration,
            context=context,
            namespace=namespace,
        )
        _RUNTIME_BY_CONFIG[schema_config] = runtime
        if _RUNTIME is None:
            _RUNTIME = runtime
        logger.info(
            "Auto-registered markets runtime",
            management_mode=management_mode,
            namespace=namespace,
            meta_table_count=len(runtime.meta_tables),
        )
        return runtime


def get_runtime() -> MarketsRuntime:
    """Return the initialized markets runtime or fail with bootstrap guidance."""

    if _RUNTIME is None:
        raise RuntimeError(
            "Markets schemas are not initialized. Call msm.create_schemas(...) "
            "or the row model's create_schemas(...) classmethod before calling "
            "row operations."
        )
    return _RUNTIME


def _missing_models_from_runtime(
    runtime: MarketsRuntime | None,
    models: Sequence[Any],
) -> list[Any]:
    if runtime is None:
        return list(models)

    from msm.meta_tables import markets_meta_table_fullname

    return [
        model
        for model in models
        if markets_meta_table_fullname(model) not in runtime.target_meta_table_uid_by_fullname
    ]


def _common_model_namespace(models: Sequence[Any]) -> str | None:
    namespaces = {
        str(namespace)
        for model in models
        if (namespace := getattr(model, "__metatable_namespace__", None))
    }
    if len(namespaces) == 1:
        return next(iter(namespaces))
    if not namespaces:
        return None
    return None


def _schema_resolution_error_message(
    *,
    row_model_name: str | None,
    models: Sequence[Any],
    cause: BaseException,
) -> str:
    row_name = row_model_name or "Markets row operation"
    missing_models = ", ".join(_model_name(model) for model in models)
    return (
        f"{row_name} requires registered markets MetaTables for {missing_models}. "
        f"Run {row_name}.create_schemas(...) during application initialization, "
        f"or set {MSM_AUTO_REGISTER_NAMESPACE_ENV} for development/example "
        f"auto-registration. Original error: {cause}"
    )


def _ensure_models_match_namespace(models: Sequence[Any], *, namespace: str) -> None:
    mismatched = [
        f"{_model_name(model)}={getattr(model, '__metatable_namespace__', None)!r}"
        for model in models
        if hasattr(model, "__metatable_namespace__")
        and getattr(model, "__metatable_namespace__", None) != namespace
    ]
    if mismatched:
        raise RuntimeError(
            f"{MSM_AUTO_REGISTER_NAMESPACE_ENV}={namespace!r} was set after markets "
            "MetaTable models were imported. Set the environment variable before "
            f"importing msm.api/msm.models. Mismatched models: {', '.join(mismatched)}."
        )


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


__all__ = [
    "DATA_NODE_HANDLE_NAMES",
    "MarketsRuntime",
    "attach_schemas",
    "auto_register_schemas",
    "configure_metatable_namespace",
    "create_schemas",
    "get_runtime",
    "resolve_runtime",
]
