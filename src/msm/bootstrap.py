from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal

from mainsequence.logconf import logger as _mainsequence_logger

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
        if _RUNTIME is not None:
            if _CREATE_SCHEMAS_CONFIG == schema_config:
                logger.info(
                    "Reusing cached markets runtime; no MetaTables registered",
                    management_mode=management_mode,
                    namespace=namespace,
                    meta_table_count=len(_RUNTIME.meta_tables),
                )
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
        logger.info(
            "Created markets runtime",
            namespace=namespace,
            meta_table_count=len(_RUNTIME.meta_tables),
            data_node_handles=list(DATA_NODE_HANDLE_NAMES),
        )
        return _RUNTIME


def get_runtime() -> MarketsRuntime:
    """Return the initialized markets runtime or fail with bootstrap guidance."""

    if _RUNTIME is None:
        raise RuntimeError(
            "Markets schemas are not initialized. Call msm.create_schemas(...) "
            "or the row model's create_schemas(...) classmethod before calling "
            "row operations."
        )
    return _RUNTIME


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
    "configure_metatable_namespace",
    "create_schemas",
    "get_runtime",
]
