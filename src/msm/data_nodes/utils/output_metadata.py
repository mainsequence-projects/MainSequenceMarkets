from __future__ import annotations

import inspect
from typing import Any


def storage_table_identifier(output_table: Any) -> str:
    """Return the TimeIndexTableUpdater identifier owned by a storage MetaTable class."""

    get_identifier = getattr(output_table, "get_identifier", None)
    if callable(get_identifier):
        identifier = get_identifier()
        if identifier not in (None, ""):
            return str(identifier)

    raise NotImplementedError(f"{output_table!r} must define get_identifier().")


def storage_table_description(output_table: Any) -> str:
    """Return the TimeIndexTableUpdater description owned by a storage MetaTable class."""

    metatable_description = getattr(output_table, "__metatable_description__", None)
    if isinstance(metatable_description, str) and metatable_description.strip():
        return metatable_description.strip()

    description = inspect.getdoc(output_table)
    if description:
        return description
    return f"Time-indexed storage table {storage_table_identifier(output_table)!r}."


__all__ = [
    "storage_table_description",
    "storage_table_identifier",
]
