from __future__ import annotations

import inspect
from typing import Any

from msm.settings import markets_data_node_identifier


def storage_data_node_identifier(storage_table: Any) -> str:
    """Return the DataNode identifier owned by a storage MetaTable class."""

    metatable_identifier = getattr(storage_table, "metatable_identifier", None)
    if callable(metatable_identifier):
        identifier = metatable_identifier()
        if identifier not in (None, ""):
            return str(identifier)

    base_identifier = getattr(storage_table, "__markets_base_identifier__", None)
    if base_identifier not in (None, ""):
        return markets_data_node_identifier(str(base_identifier))

    raise NotImplementedError(
        f"{storage_table!r} must define metatable_identifier() or __markets_base_identifier__."
    )


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
