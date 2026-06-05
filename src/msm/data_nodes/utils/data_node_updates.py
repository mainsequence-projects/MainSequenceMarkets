from __future__ import annotations

from typing import Any
from uuid import UUID


def data_node_update_storage(data_node_update: Any) -> Any | None:
    """Return the storage object related to a DataNodeUpdate."""

    return get_mapping_or_attr(data_node_update, "data_node_storage")


def storage_source_config(storage: Any) -> Any | None:
    """Return a storage source-table configuration across SDK response shapes."""

    return (
        get_mapping_or_attr(storage, "sourcetableconfiguration")
        or get_mapping_or_attr(storage, "source_table_configuration")
        or get_mapping_or_attr(storage, "source_table_config")
    )


def get_mapping_or_attr(value: Any, field_name: str) -> Any:
    if isinstance(value, dict):
        return value.get(field_name)
    return getattr(value, field_name, None)


def coerce_required_uid(value: Any, *, field_name: str) -> str:
    value_uid = coerce_optional_uid(value)
    if value_uid is None:
        raise ValueError(f"{field_name} must expose a public uid.")
    return value_uid


def coerce_optional_uid(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, UUID):
        return str(value)
    uid = value.get("uid") if isinstance(value, dict) else getattr(value, "uid", None)
    if uid in (None, ""):
        return None
    return str(uid)


__all__ = [
    "coerce_optional_uid",
    "coerce_required_uid",
    "data_node_update_storage",
    "get_mapping_or_attr",
    "storage_source_config",
]
