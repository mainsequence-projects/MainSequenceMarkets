"""Derive DataNode frame-validation schema from storage-first metatables.

These helpers read the column schema, index names, and time index directly
from a ``PlatformTimeIndexMetaData`` storage class (the storage-first single
source of truth, ADR 0017) so DataNode validators never duplicate that schema.

Dtype tokens are produced by the SDK's own ``sqlalchemy_type_to_token`` so the
MetaTable column types remain the single definition of dtypes and never drift
from the SDK vocabulary.
"""

from __future__ import annotations

from typing import Any

from mainsequence.client.dtype_codec import sqlalchemy_type_to_token


def storage_column_dtypes_map(storage_table: Any) -> dict[str, str]:
    """Map each storage column name to its SDK dtype token."""

    return {
        column.name: sqlalchemy_type_to_token(column.type, remote=True)
        for column in storage_table.__table__.columns
    }


def storage_index_names(storage_table: Any) -> list[str]:
    """Return the storage class' declared index names."""

    return list(storage_table.__index_names__)


def storage_time_index_name(storage_table: Any) -> str:
    """Return the storage class' declared time index column name."""

    return storage_table.__time_index_name__


__all__ = [
    "storage_column_dtypes_map",
    "storage_index_names",
    "storage_time_index_name",
]
