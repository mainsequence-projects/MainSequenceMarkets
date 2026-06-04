from __future__ import annotations

import inspect
from typing import Any


def storage_data_node_identifier(storage_table: Any) -> str:
    """Return the DataNode identifier owned by a storage MetaTable class."""

    get_identifier = getattr(storage_table, "get_identifier", None)
    if callable(get_identifier):
        identifier = get_identifier()
        if identifier not in (None, ""):
            return str(identifier)

    raise NotImplementedError(f"{storage_table!r} must define get_identifier().")


def storage_data_node_description(storage_table: Any) -> str:
    """Return the DataNode description owned by a storage MetaTable class."""

    metatable_description = getattr(storage_table, "__metatable_description__", None)
    if isinstance(metatable_description, str) and metatable_description.strip():
        return metatable_description.strip()

    description = inspect.getdoc(storage_table)
    if description:
        return description
    return f"Time-indexed storage table {storage_data_node_identifier(storage_table)!r}."


__all__ = [
    "storage_data_node_description",
    "storage_data_node_identifier",
]
