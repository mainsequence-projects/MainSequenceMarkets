from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Any

from msm.repositories.base import MarketsRepositoryContext
from msm.settings import markets_auto_register_namespace, markets_namespace

from .meta_tables import (
    PricingManagementMode,
    PricingMetaTableRegistrationResult,
    PricingModelSelector,
    pricing_meta_table_fullname,
    register_pricing_meta_tables,
    resolve_pricing_meta_table_models,
)

_CREATE_PRICING_SCHEMAS_LOCK = Lock()
_PRICING_RUNTIME: PricingRuntime | None = None


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
    def target_meta_table_uid_by_fullname(self) -> dict[str, str]:
        return self.registration.target_meta_table_uid_by_fullname

    @property
    def meta_table_models(self) -> list[type[Any]]:
        return list(self.registration.models)


def create_pricing_schemas(
    *,
    data_source_uid: str | None = None,
    management_mode: PricingManagementMode = "platform_managed",
    namespace: str | None = None,
    models: Sequence[PricingModelSelector] | None = None,
    target_meta_table_uid_by_fullname: Mapping[str, Any] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_fullname: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> PricingRuntime:
    """Register pricing schemas and return a pricing repository runtime."""

    resolved_models = resolve_pricing_meta_table_models(models)
    namespace = markets_namespace(namespace)
    registration = register_pricing_meta_tables(
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
        open_for_everyone=open_for_everyone,
        protect_from_deletion=protect_from_deletion,
        introspect=introspect,
        storage_hash_by_fullname=storage_hash_by_fullname,
        timeout=timeout,
        models=resolved_models,
    )
    runtime = PricingRuntime(
        registration=registration,
        context=MarketsRepositoryContext(
            target_meta_table_uid_by_fullname=registration.target_meta_table_uid_by_fullname,
            timeout=timeout,
            namespace=namespace,
        ),
        namespace=namespace,
    )

    global _PRICING_RUNTIME
    with _CREATE_PRICING_SCHEMAS_LOCK:
        _PRICING_RUNTIME = runtime
    return runtime


def attach_pricing_schemas(
    *,
    data_source_uid: str | None = None,
    management_mode: PricingManagementMode = "platform_managed",
    namespace: str | None = None,
    models: Sequence[PricingModelSelector] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> PricingRuntime:
    """Attach to already-registered pricing MetaTables without creating schemas."""

    from msm.models.registration import resolve_registered_markets_meta_tables

    resolved_models = resolve_pricing_meta_table_models(models)
    namespace = markets_namespace(namespace)
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
            target_meta_table_uid_by_fullname=registration.target_meta_table_uid_by_fullname,
            timeout=timeout,
            namespace=namespace,
        ),
        namespace=namespace,
    )

    global _PRICING_RUNTIME
    with _CREATE_PRICING_SCHEMAS_LOCK:
        _PRICING_RUNTIME = runtime
    return runtime


def resolve_pricing_runtime(
    *,
    models: Sequence[PricingModelSelector],
    row_model_name: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> PricingRuntime:
    """Resolve a pricing runtime with attach-first semantics."""

    resolved_models = resolve_pricing_meta_table_models(models)
    if _PRICING_RUNTIME is not None and not _missing_models_from_runtime(
        _PRICING_RUNTIME,
        resolved_models,
    ):
        return _PRICING_RUNTIME

    namespace = markets_auto_register_namespace() or _common_model_namespace(resolved_models)
    try:
        return attach_pricing_schemas(
            models=resolved_models,
            namespace=namespace,
            timeout=timeout,
        )
    except Exception as attach_error:
        auto_namespace = markets_auto_register_namespace()
        if auto_namespace:
            try:
                return create_pricing_schemas(
                    models=resolved_models,
                    namespace=auto_namespace,
                    timeout=timeout,
                )
            except Exception as register_error:
                raise RuntimeError(
                    _pricing_resolution_error_message(
                        row_model_name=row_model_name,
                        models=resolved_models,
                        cause=register_error,
                    )
                ) from register_error
        raise RuntimeError(
            _pricing_resolution_error_message(
                row_model_name=row_model_name,
                models=resolved_models,
                cause=attach_error,
            )
        ) from attach_error


def _missing_models_from_runtime(
    runtime: PricingRuntime,
    models: Sequence[Any],
) -> list[Any]:
    return [
        model
        for model in models
        if pricing_meta_table_fullname(model) not in runtime.target_meta_table_uid_by_fullname
    ]


def _common_model_namespace(models: Sequence[Any]) -> str | None:
    namespaces = {
        str(namespace)
        for model in models
        if (namespace := getattr(model, "__metatable_namespace__", None))
    }
    if len(namespaces) == 1:
        return next(iter(namespaces))
    return None


def _pricing_resolution_error_message(
    *,
    row_model_name: str | None,
    models: Sequence[Any],
    cause: Exception,
) -> str:
    model_names = ", ".join(model.__name__ for model in models)
    prefix = f"{row_model_name} " if row_model_name else ""
    return (
        f"{prefix}requires registered pricing MetaTables [{model_names}]. "
        "Call msm_pricing.bootstrap.create_pricing_schemas(...) before row operations "
        "or set MSM_AUTO_REGISTER_NAMESPACE for development auto-registration. "
        f"Resolution failed with {type(cause).__name__}: {cause}"
    )


__all__ = [
    "PricingRuntime",
    "attach_pricing_schemas",
    "create_pricing_schemas",
    "resolve_pricing_runtime",
]
