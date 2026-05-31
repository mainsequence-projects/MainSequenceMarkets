from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_meta_table_identifier,
    markets_table_args,
    new_markets_uid,
)


class MarketsMetaTableCatalogTable(MarketsMetaTableMixin, MarketsBase):
    """Internal catalog of markets MetaTable registrations."""

    __metatable_identifier__ = "MarketsMetaTableCatalog"
    __metatable_description__ = (
        "Internal maintenance catalog keyed by logical markets MetaTable identifier. "
        "Tracks registered platform MetaTable UIDs, descriptions, model names, "
        "contract hashes, SDK version, and catalog timestamps for runtime bootstrap."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(
                __metatable_identifier__,
                "identifier",
                unique=True,
            ),
            "identifier",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "meta_table_uid", unique=True),
            "meta_table_uid",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    namespace: Mapped[str] = mapped_column(String(255), nullable=False)
    identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    meta_table_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sdk_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(dt.UTC),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


@dataclass(frozen=True, slots=True)
class MarketsMetaTableCatalogRow:
    """Typed internal payload for catalog row writes."""

    namespace: str
    identifier: str
    description: str | None
    model_name: str
    meta_table_uid: str
    contract_hash: str
    sdk_version: str | None = None

    @classmethod
    def from_meta_table(
        cls,
        *,
        model: type[MarketsBase],
        meta_table: Any,
        contract_hash: str | None = None,
        sdk_version: str | None = None,
    ) -> "MarketsMetaTableCatalogRow":
        return cls(
            namespace=_required_text(
                getattr(meta_table, "namespace", None)
                or getattr(model, "__metatable_namespace__", None),
                "namespace",
            ),
            identifier=_required_text(
                getattr(meta_table, "identifier", None)
                or getattr(model, "__metatable_identifier__", None),
                "identifier",
            ),
            description=_optional_text(getattr(meta_table, "description", None)),
            model_name=model.__name__,
            meta_table_uid=_required_text(getattr(meta_table, "uid", None), "meta_table_uid"),
            contract_hash=contract_hash or markets_meta_table_contract_hash(model),
            sdk_version=sdk_version,
        )

    @property
    def identity_key(self) -> str:
        return self.identifier

    def to_payload(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "identifier": self.identifier,
            "description": self.description,
            "model_name": self.model_name,
            "meta_table_uid": self.meta_table_uid,
            "contract_hash": self.contract_hash,
            "sdk_version": self.sdk_version,
        }


def markets_meta_table_contract_hash(model: type[MarketsBase]) -> str:
    payload = markets_meta_table_contract_payload(model)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def markets_meta_table_contract_payload(model: type[MarketsBase]) -> dict[str, Any]:
    table = model.__table__
    return {
        "model_name": model.__name__,
        "namespace": getattr(model, "__metatable_namespace__", None),
        "identifier": getattr(model, "__metatable_identifier__", None),
        "schema": table.schema,
        "columns": [
            {
                "name": column.name,
                "type": str(column.type),
                "nullable": bool(column.nullable),
                "primary_key": bool(column.primary_key),
                "unique": bool(column.unique),
                "server_default": str(column.server_default)
                if column.server_default is not None
                else None,
                "has_python_default": column.default is not None,
            }
            for column in table.columns
        ],
        "foreign_keys": _sort_contract_items(
            {
                "name": constraint.name,
                "columns": [element.parent.name for element in constraint.elements],
                "target_columns": [
                    f"{_foreign_key_target_identifier(element)}."
                    f"{_foreign_key_target_column_name(element)}"
                    for element in constraint.elements
                ],
                "ondelete": [element.ondelete for element in constraint.elements],
            }
            for constraint in table.foreign_key_constraints
        ),
        "indexes": _sort_contract_items(
            {
                "name": index.name,
                "unique": bool(index.unique),
                "columns": [column.name for column in index.columns],
            }
            for index in table.indexes
        ),
        "unique_constraints": _sort_contract_items(
            {
                "name": constraint.name,
                "columns": [column.name for column in constraint.columns],
            }
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        ),
    }


def _sort_contract_items(items: Any) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))


def _foreign_key_target_identifier(element: Any) -> str:
    target_model = _metatable_foreign_key_target_model(element)
    if target_model is not None:
        return markets_meta_table_identifier(target_model)
    return markets_meta_table_identifier(element.column.table)


def _foreign_key_target_column_name(element: Any) -> str:
    metadata = _metatable_foreign_key_metadata(element)
    if metadata is not None:
        target_column = metadata.get("target_column")
        if target_column not in (None, ""):
            return str(target_column)
    return str(element.column.name)


def _metatable_foreign_key_target_model(element: Any) -> type[MarketsBase] | None:
    metadata = _metatable_foreign_key_metadata(element)
    if metadata is None:
        return None
    target_model = metadata.get("target_model")
    if isinstance(target_model, type):
        return target_model
    return None


def _metatable_foreign_key_metadata(element: Any) -> dict[str, Any] | None:
    info = getattr(element, "info", None)
    if not isinstance(info, dict):
        return None
    metadata = info.get("mainsequence_metatable_foreign_key")
    if isinstance(metadata, dict):
        return metadata
    return None


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} is required for MetaTable catalog rows.")
    return text


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


__all__ = [
    "MarketsMetaTableCatalogRow",
    "MarketsMetaTableCatalogTable",
    "markets_meta_table_contract_hash",
    "markets_meta_table_contract_payload",
]
