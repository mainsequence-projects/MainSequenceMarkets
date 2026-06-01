from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow
from msm.models import IssuerTable


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


class Issuer(MarketsMetaTableRow):
    """User-facing issuer reference row."""

    __table__: ClassVar[type[IssuerTable]] = IssuerTable
    __required_tables__: ClassVar[list[type[IssuerTable]]] = [IssuerTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    display_name: str
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        payload: IssuerCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Issuer:
        return super().create(_validate_payload(IssuerCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: IssuerUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Issuer:
        return super().upsert(_validate_payload(IssuerUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: IssuerUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Issuer:
        return super().update(uid, _validate_payload(IssuerUpdate, payload, kwargs))


class IssuerCreate(BaseModel):
    """Payload for creating an issuer reference row."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    metadata_json: dict[str, Any] | None = None


class IssuerUpsert(IssuerCreate):
    """Payload for inserting or updating an issuer by unique identifier."""


class IssuerUpdate(BaseModel):
    """Payload for updating mutable issuer reference fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


__all__ = [
    "Issuer",
    "IssuerCreate",
    "IssuerUpdate",
    "IssuerUpsert",
]
