from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from msm.meta_tables import MarketsMetaTableRegistrationResult
    from msm.repositories.base import MarketsRepositoryContext

MarketsManagementMode = Literal["platform_managed", "external_registered"]

_START_LOCK = Lock()
_RUNTIME: MarketsRuntime | None = None
_START_CONFIG: tuple[tuple[str, Any], ...] | None = None


@dataclass(frozen=True)
class MarketsRuntime:
    """Runtime handles created by `msm.start()`."""

    registration: "MarketsMetaTableRegistrationResult"
    context: "MarketsRepositoryContext"

    @property
    def target_meta_table_uid_by_fullname(self) -> dict[str, str]:
        return self.registration.target_meta_table_uid_by_fullname


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


def start(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    namespace: str | None = None,
    metatable_namespace: str | None = None,
    target_meta_table_uid_by_fullname: Mapping[str, Any] | None = None,
    labels: Sequence[str] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_fullname: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRuntime:
    """Register markets MetaTables once and return a repository runtime context."""

    resolved_namespace = _resolve_namespace_alias(
        namespace=namespace,
        metatable_namespace=metatable_namespace,
    )
    start_config = _start_config(
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        namespace=resolved_namespace,
        target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
        labels=labels,
        open_for_everyone=open_for_everyone,
        protect_from_deletion=protect_from_deletion,
        introspect=introspect,
        storage_hash_by_fullname=storage_hash_by_fullname,
        timeout=timeout,
    )

    global _RUNTIME, _START_CONFIG
    with _START_LOCK:
        if _RUNTIME is not None:
            if _START_CONFIG == start_config:
                return _RUNTIME
            raise RuntimeError(
                "msm.start() has already initialized this process with different "
                "bootstrap arguments. Run it once at process startup before "
                "importing MetaTable-backed models, repositories, or services."
            )

        if resolved_namespace is not None:
            configure_metatable_namespace(resolved_namespace)

        from msm.meta_tables import register_markets_meta_tables
        from msm.repositories.base import MarketsRepositoryContext

        registration = register_markets_meta_tables(
            data_source_uid=data_source_uid,
            management_mode=management_mode,
            target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
            labels=labels,
            open_for_everyone=open_for_everyone,
            protect_from_deletion=protect_from_deletion,
            introspect=introspect,
            storage_hash_by_fullname=storage_hash_by_fullname,
            timeout=timeout,
        )
        _RUNTIME = MarketsRuntime(
            registration=registration,
            context=MarketsRepositoryContext(
                target_meta_table_uid_by_fullname=registration.target_meta_table_uid_by_fullname,
                timeout=timeout,
            ),
        )
        _START_CONFIG = start_config
        return _RUNTIME


def _resolve_namespace_alias(
    *,
    namespace: str | None,
    metatable_namespace: str | None,
) -> str | None:
    if namespace is None:
        return metatable_namespace
    if metatable_namespace is None:
        return namespace
    if namespace != metatable_namespace:
        raise ValueError("Pass either namespace or metatable_namespace, not both.")
    return namespace


def _start_config(**kwargs: Any) -> tuple[tuple[str, Any], ...]:
    return tuple((key, _freeze_start_value(value)) for key, value in kwargs.items())


def _freeze_start_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (str(key), _freeze_start_value(item))
                for key, item in value.items()
            )
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_start_value(item) for item in value)
    return value


__all__ = [
    "MarketsRuntime",
    "configure_metatable_namespace",
    "start",
]
