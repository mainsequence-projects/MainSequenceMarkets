from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.base import MarketsRow
from msm.models import IndexTable, IndexTypeTable


def _validate_payload(
    payload_model: type[BaseModel],
    payload: BaseModel | Mapping[str, Any] | None,
    kwargs: Mapping[str, Any],
) -> BaseModel:
    if payload is None:
        return payload_model(**dict(kwargs))
    if kwargs:
        raise TypeError("Pass either a payload object or keyword fields, not both.")
    if isinstance(payload, payload_model):
        return payload
    if isinstance(payload, BaseModel):
        return payload_model.model_validate(payload.model_dump(exclude_unset=True))
    if isinstance(payload, Mapping):
        return payload_model.model_validate(dict(payload))
    raise TypeError("Payload must be a Pydantic model, mapping, or None.")


def normalize_index_type(index_type: str | None) -> str | None:
    """Return the canonical index type key stored by the typed API."""

    if index_type is None:
        return None

    normalized = re.sub(r"\s+", "_", str(index_type).strip().lower())
    if not normalized:
        raise ValueError("index_type cannot be empty.")
    return normalized


class IndexType(MarketsRow):
    """Typed row for the index type registry."""

    __table__: ClassVar[type[IndexTypeTable]] = IndexTypeTable
    __required_tables__: ClassVar[list[type[IndexTypeTable]]] = [IndexTypeTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("index_type",)

    index_type: str
    display_name: str | None = None
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_row_index_type(cls, value: str) -> str:
        normalized = normalize_index_type(value)
        if normalized is None:
            raise ValueError("index_type cannot be empty.")
        return normalized

    @classmethod
    def create(
        cls,
        payload: IndexTypeCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexType:
        return super().create(_validate_payload(IndexTypeCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: IndexTypeUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexType:
        return super().upsert(_validate_payload(IndexTypeUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: IndexTypeUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexType:
        return super().update(uid, _validate_payload(IndexTypeUpdate, payload, kwargs))


class IndexTypeCreate(BaseModel):
    """Payload for creating an index type registry row."""

    model_config = ConfigDict(extra="forbid")

    index_type: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_index_type(cls, value: str) -> str:
        normalized = normalize_index_type(value)
        if normalized is None:
            raise ValueError("index_type cannot be empty.")
        return normalized


class IndexTypeUpsert(IndexTypeCreate):
    """Payload for inserting or updating an index type by registry key."""


class IndexTypeUpdate(BaseModel):
    """Payload for updating mutable index type fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class Index(MarketsRow):
    """User-facing market index reference row."""

    __table__: ClassVar[type[IndexTable]] = IndexTable
    __required_tables__: ClassVar[list[type[Any]]] = [IndexTypeTable, IndexTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    index_type: str
    display_name: str
    description: str | None = None
    provider: str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_row_index_type(cls, value: str) -> str:
        normalized = normalize_index_type(value)
        if normalized is None:
            raise ValueError("index_type is required.")
        return normalized

    @classmethod
    def create(cls, payload: IndexCreate | Mapping[str, Any] | None = None, **kwargs: Any) -> Index:
        return super().create(_validate_payload(IndexCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: IndexUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Index:
        return super().upsert(_validate_payload(IndexUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: IndexUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Index:
        return super().update(uid, _validate_payload(IndexUpdate, payload, kwargs))


class IndexCreate(BaseModel):
    """Payload for creating an index reference row."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    index_type: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    provider: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_index_type(cls, value: str) -> str:
        normalized = normalize_index_type(value)
        if normalized is None:
            raise ValueError("index_type is required.")
        return normalized


class IndexUpsert(IndexCreate):
    """Payload for inserting or updating an index by unique identifier."""


class IndexUpdate(BaseModel):
    """Payload for updating mutable index reference fields."""

    model_config = ConfigDict(extra="forbid")

    index_type: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    provider: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_index_type(cls, value: str | None) -> str | None:
        return normalize_index_type(value)

    @model_validator(mode="after")
    def _reject_explicit_null_index_type(self) -> IndexUpdate:
        if "index_type" in self.model_fields_set and self.index_type is None:
            raise ValueError("index_type cannot be null.")
        return self


__all__ = [
    "Index",
    "IndexCreate",
    "IndexType",
    "IndexTypeCreate",
    "IndexTypeUpdate",
    "IndexTypeUpsert",
    "IndexUpdate",
    "IndexUpsert",
    "normalize_index_type",
]
