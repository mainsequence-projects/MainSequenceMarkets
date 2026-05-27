from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsRow
from msm.models import IndexTable


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


class Index(MarketsRow):
    """User-facing market index reference row."""

    __table__: ClassVar[type[IndexTable]] = IndexTable
    __required_tables__: ClassVar[list[type[IndexTable]]] = [IndexTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    display_name: str
    description: str | None = None
    provider: str | None = None
    metadata_json: dict[str, Any] | None = None

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
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    provider: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class IndexUpsert(IndexCreate):
    """Payload for inserting or updating an index by unique identifier."""


class IndexUpdate(BaseModel):
    """Payload for updating mutable index reference fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    provider: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


__all__ = [
    "Index",
    "IndexCreate",
    "IndexUpdate",
    "IndexUpsert",
]
