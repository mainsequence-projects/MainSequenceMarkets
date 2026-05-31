from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal

from mainsequence.logconf import logger as _mainsequence_logger

from msm.base import markets_meta_table_identifier
from msm.settings import (
    markets_auto_register_namespace,
    markets_namespace,
)

if TYPE_CHECKING:
    from msm.models.registration import MarketsMetaTableRegistrationResult, MarketsModelSelector
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
    namespace: str | None = None

    @property
    def meta_tables(self) -> list[Any]:
        return self.registration.meta_tables

    @property
    def target_meta_table_uid_by_identifier(self) -> dict[str, str]:
        return self.registration.target_meta_table_uid_by_identifier

    @property
    def target_meta_table_uid_by_fullname(self) -> dict[str, str]:
        return self.target_meta_table_uid_by_identifier

    @property
    def meta_table_models(self) -> list[type[Any]]:
        return list(self.registration.models)

    def table(self, model: "MarketsModelSelector") -> "MarketsMetaTableHandle":
        handle = self.context.table(model)
        meta_table = self.registration.meta_table_by_identifier.get(
            markets_meta_table_identifier(handle.model)
        )
        if meta_table is None:
            return handle
        return replace(handle, meta_table=meta_table)

    @property
    def data_nodes(self) -> dict[str, type[Any]]:
        from msm.data_nodes.accounts import AccountHoldings, VirtualFundHoldings
        from msm.data_nodes.assets import AssetSnapshot
        from msm.portfolios.data_nodes import (
            PortfolioWeights,
            PortfoliosDataNode,
            SignalWeights,
        )
        from msm_pricing.data_nodes import AssetPricingDetail

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

    loaded_model_modules = _loaded_metatable_modules()
    if loaded_model_modules:
        loaded_namespace = _loaded_metatable_namespace()
        if loaded_namespace == namespace:
            return
        raise RuntimeError(
            "Configure the MetaTable namespace before importing msm.models or "
            f"msm.models.registration. Requested namespace {namespace!r}, but "
            f"MetaTable models are already loaded with namespace "
            f"{loaded_namespace!r}. Already loaded: {loaded_model_modules!r}."
        )

    from msm.base import MarketsMetaTableMixin

    MarketsMetaTableMixin.__metatable_namespace__ = namespace


def _loaded_metatable_modules() -> list[str]:
    return sorted(
        module_name
        for module_name in sys.modules
        if module_name == "msm.models"
        or module_name.startswith("msm.models.")
        or module_name == "msm.maintenance"
        or module_name.startswith("msm.maintenance.")
    )


def _loaded_metatable_namespace() -> str | None:
    base_module = sys.modules.get("msm.base")
    mixin = getattr(base_module, "MarketsMetaTableMixin", None)
    if mixin is None:
        return None
    return getattr(mixin, "__metatable_namespace__", None)


def start_engine(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    namespace: str | None = None,
    models: Sequence["MarketsModelSelector"] | None = None,
    target_meta_table_uid_by_identifier: Mapping[str, Any] | None = None,
    target_meta_table_uid_by_fullname: Mapping[str, Any] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_identifier: Mapping[str, str] | None = None,
    storage_hash_by_fullname: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Bootstrap the markets runtime once and return a repository context."""

    requested_namespace = namespace
    namespace = markets_namespace(namespace)
    schema_config = _schema_config(
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        namespace=namespace,
        models=models,
        target_meta_table_uid_by_identifier=target_meta_table_uid_by_identifier,
        target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
        open_for_everyone=open_for_everyone,
        protect_from_deletion=protect_from_deletion,
        introspect=introspect,
        storage_hash_by_identifier=storage_hash_by_identifier,
        storage_hash_by_fullname=storage_hash_by_fullname,
        timeout=timeout,
    )

    global _RUNTIME, _START_ENGINE_CONFIG
    with _START_ENGINE_LOCK:
        cached_runtime = _RUNTIME_BY_CONFIG.get(schema_config)
        if cached_runtime is not None:
            logger.info(
                "Reusing cached markets runtime; no MetaTables registered",
                management_mode=management_mode,
                namespace=namespace,
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
                "different schema arguments. Run it once at process startup before "
                "importing MetaTable-backed models, repositories, or services."
            )

        logger.info(
            "Starting markets bootstrap",
            management_mode=management_mode,
            namespace=namespace,
            data_source_uid=data_source_uid,
            target_meta_table_count=len(
                target_meta_table_uid_by_identifier or target_meta_table_uid_by_fullname or {}
            ),
            storage_hash_count=len(storage_hash_by_identifier or storage_hash_by_fullname or {}),
            requested_model_count=None if models is None else len(models),
            open_for_everyone=open_for_everyone,
            protect_from_deletion=protect_from_deletion,
            introspect=introspect,
            timeout=timeout,
        )
        if _should_configure_metatable_namespace(requested_namespace):
            logger.info("Configuring markets MetaTable namespace", namespace=namespace)
            configure_metatable_namespace(namespace)

        from msm.maintenance.catalog import bootstrap_markets_meta_tables_from_catalog
        from msm.models.registration import resolve_markets_meta_table_models
        from msm.repositories.base import MarketsRepositoryContext

        meta_table_models = resolve_markets_meta_table_models(models)
        logger.info(
            "Resolved markets MetaTable models",
            namespace=namespace,
            model_count=len(meta_table_models),
            models=[_model_name(model) for model in meta_table_models],
        )
        catalog_bootstrap = bootstrap_markets_meta_tables_from_catalog(
            data_source_uid=data_source_uid,
            management_mode=management_mode,
            target_meta_table_uid_by_identifier=target_meta_table_uid_by_identifier,
            target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
            open_for_everyone=open_for_everyone,
            protect_from_deletion=protect_from_deletion,
            introspect=introspect,
            storage_hash_by_identifier=storage_hash_by_identifier,
            storage_hash_by_fullname=storage_hash_by_fullname,
            timeout=timeout,
            models=meta_table_models,
        )
        registration = catalog_bootstrap.registration
        logger.info(
            "Catalog bootstrapped markets MetaTables",
            management_mode=management_mode,
            namespace=namespace,
            meta_table_count=len(registration.meta_tables),
            target_meta_table_count=len(registration.target_meta_table_uid_by_identifier),
            attached_count=catalog_bootstrap.attached_count,
            imported_count=catalog_bootstrap.imported_count,
            registered_count=catalog_bootstrap.registered_count,
            catalog_meta_table_uid=getattr(catalog_bootstrap.catalog_meta_table, "uid", None),
        )
        context = MarketsRepositoryContext(
            target_meta_table_uid_by_identifier=registration.target_meta_table_uid_by_identifier,
            timeout=timeout,
            namespace=namespace,
        )
        logger.info(
            "Created markets repository context",
            namespace=namespace,
            target_meta_table_count=len(context.target_meta_table_uid_by_identifier),
            timeout=timeout,
        )
        _RUNTIME = MarketsRuntime(
            registration=registration,
            context=context,
            namespace=namespace,
        )
        _START_ENGINE_CONFIG = schema_config
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

    namespace = markets_namespace(namespace)
    schema_config = _schema_config(
        action="attach",
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        namespace=namespace,
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
                namespace=namespace,
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
            data_source_uid=data_source_uid,
            management_mode=management_mode,
            namespace=namespace,
            timeout=timeout,
            models=meta_table_models,
        )
        context = MarketsRepositoryContext(
            target_meta_table_uid_by_identifier=registration.target_meta_table_uid_by_identifier,
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

    from msm.models.registration import markets_meta_table_identifier

    return [
        model
        for model in models
        if markets_meta_table_identifier(model) not in runtime.target_meta_table_uid_by_identifier
    ]


def _should_configure_metatable_namespace(requested_namespace: str | None) -> bool:
    return requested_namespace is not None or markets_auto_register_namespace() is not None


def _runtime_not_initialized_error_message(
    *,
    row_model_name: str | None,
    models: Sequence[Any],
) -> str:
    row_name = row_model_name or "Markets row operation"
    missing_models = ", ".join(_model_name(model) for model in models)
    return (
        f"{row_name} requires an initialized markets runtime for {missing_models}. "
        f"Run {row_name}.create_schemas(...) or msm.start_engine(models=[...]) "
        "during application initialization before row operations."
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
    initialized_identifiers = ", ".join(sorted(runtime.target_meta_table_uid_by_identifier))
    return (
        f"{row_name} requires {missing_model_names}, but the active markets runtime "
        "was initialized without those MetaTable identifiers. Initialized tables: "
        f"{initialized_model_names or 'none'}. Initialized identifiers: "
        f"{initialized_identifiers or 'none'}. Include the required tables in the "
        "process bootstrap before row operations."
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
    "configure_metatable_namespace",
    "get_runtime",
    "resolve_runtime",
    "start_engine",
]
