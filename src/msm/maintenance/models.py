from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

from mainsequence.client.metatables import MetaTable
from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)


class MarketsMetaTableCatalogTable(MarketsMetaTableMixin, MarketsBase):
    """Internal catalog of markets MetaTable registrations."""

    __metatable_identifier__ = "MarketsMetaTableCatalog"
    __metatable_description__ = (
        "Internal maintenance catalog keyed by migration-managed SQLAlchemy table name. "
        "Tracks registered platform MetaTable UIDs, descriptions, model names, "
        "SDK version, and catalog timestamps for runtime pointer attachment."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "table_name",
            unique=True,
        ),
        Index(
            None,
            "meta_table_uid",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this MetaTable row.",
        },
    )
    namespace: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Namespace",
            "description": "Markets namespace used to scope migration-managed MetaTables.",
        },
    )
    table_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Table Name",
            "description": "SQLAlchemy table name used as the catalog identity for this MetaTable.",
        },
    )
    description: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        info={
            "label": "Description",
            "description": "Human-readable description of the registry row and its intended use.",
        },
    )
    model_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Model Name",
            "description": "Python SQLAlchemy model class name that owns the MetaTable contract.",
        },
    )
    meta_table_uid: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Meta Table UID",
            "description": "Platform MetaTable UID bound to the markets SQLAlchemy table name.",
        },
    )
    sdk_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Sdk Version",
            "description": "Main Sequence SDK version that wrote or last refreshed the catalog row.",
        },
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(dt.UTC),
        info={
            "label": "Created At",
            "description": "UTC timestamp when the catalog row was first written.",
        },
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
        info={
            "label": "Updated At",
            "description": "UTC timestamp when the catalog row was last updated.",
        },
    )


@dataclass(frozen=True, slots=True)
class MarketsMetaTableCatalogRow:
    """Typed internal payload for catalog row writes."""

    namespace: str
    table_name: str
    description: str | None
    model_name: str
    meta_table_uid: str
    sdk_version: str | None = None

    @classmethod
    def from_meta_table(
        cls,
        *,
        model: type[MarketsBase],
        meta_table: MetaTable,
        sdk_version: str | None = None,
    ) -> "MarketsMetaTableCatalogRow":
        model_table_name = _required_text(model.__table__.name, "table_name")
        meta_table_identifier = _required_text(meta_table.identifier, "identifier")
        if meta_table_identifier != model_table_name:
            raise ValueError(
                "MetaTable identifier does not match the provider model table name. "
                f"model={model_table_name!r} meta_table={meta_table_identifier!r}."
            )
        meta_table_physical_table_name = _required_text(
            meta_table.physical_table_name,
            "physical_table_name",
        )
        if meta_table_physical_table_name != model_table_name:
            raise ValueError(
                "MetaTable physical table does not match the provider model. "
                f"model={model_table_name!r} meta_table={meta_table_physical_table_name!r}."
            )

        return cls(
            namespace=_required_text(model.__metatable_namespace__, "namespace"),
            table_name=model_table_name,
            description=_optional_text(model.__metatable_description__),
            model_name=model.__name__,
            meta_table_uid=_required_text(
                meta_table.uid,
                "meta_table_uid",
            ),
            sdk_version=sdk_version,
        )

    @property
    def identity_key(self) -> str:
        return self.table_name

    def to_payload(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "table_name": self.table_name,
            "description": self.description,
            "model_name": self.model_name,
            "meta_table_uid": self.meta_table_uid,
            "sdk_version": self.sdk_version,
        }


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
]
