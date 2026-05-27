from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from msm.api.base import operation_result_rows
from msm.models import IndexTable
from msm.repositories.crud import (
    create_model,
    get_model_by_uid,
    get_model_by_unique_identifier,
    search_model,
    update_model,
    upsert_model,
)

from msm_pricing.bootstrap import create_pricing_schemas, resolve_pricing_runtime
from msm_pricing.models.curves import CurveTable
from msm_pricing.models.index_convention_details import IndexConventionDetailsTable


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


class Curve(BaseModel):
    """Pricing-owned curve identity row used by curve DataNodes and runtime resolution."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[CurveTable]] = CurveTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        IndexTable,
        IndexConventionDetailsTable,
        CurveTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    uid: uuid.UUID
    unique_identifier: str
    display_name: str
    curve_type: str
    index_uid: uuid.UUID
    interpolation_method: str | None = None
    compounding: str | None = None
    source: str | None = None
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        requested_models = kwargs.pop("models", None)
        models = [*cls.__required_tables__, *(requested_models or [])]
        return create_pricing_schemas(models=models, **kwargs)

    @classmethod
    def create(
        cls,
        payload: CurveCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Curve:
        values = _validate_payload(CurveCreate, payload, kwargs).model_dump()
        result = create_model(cls._active_context(), model=cls.__table__, values=values)
        return cls._from_operation_result(result)

    @classmethod
    def upsert(
        cls,
        payload: CurveUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Curve:
        values = _validate_payload(CurveUpsert, payload, kwargs).model_dump()
        result = upsert_model(
            cls._active_context(),
            model=cls.__table__,
            values=values,
            conflict_columns=cls.__upsert_keys__,
        )
        return cls._from_operation_result(result)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: CurveUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Curve:
        values = _validate_payload(CurveUpdate, payload, kwargs).model_dump(
            exclude_unset=True,
        )
        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=uid,
            values=values,
        )
        return cls._from_operation_result(result)

    @classmethod
    def get_by_uid(cls, uid: uuid.UUID | str) -> Curve | None:
        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=uid)
        return cls._from_operation_result(result, required=False)

    @classmethod
    def get_by_unique_identifier(cls, unique_identifier: str) -> Curve | None:
        result = get_model_by_unique_identifier(
            cls._active_context(),
            model=cls.__table__,
            unique_identifier=unique_identifier,
        )
        return cls._from_operation_result(result, required=False)

    @classmethod
    def filter(cls, *, limit: int = 500, **filters: Any) -> list[Curve]:
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={key: value for key, value in filters.items() if value is not None},
            limit=limit,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def _active_context(cls):
        runtime = resolve_pricing_runtime(
            models=cls.__required_tables__,
            row_model_name=cls.__name__,
        )
        return runtime.context

    @classmethod
    def _from_operation_result(
        cls,
        result: Mapping[str, Any],
        *,
        required: bool = True,
    ) -> Curve | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError("MetaTable operation result did not include a Curve row.")
        return None


class CurveCreate(BaseModel):
    """Payload for creating a pricing curve identity row."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    curve_type: str = Field(min_length=1, max_length=64)
    index_uid: uuid.UUID
    interpolation_method: str | None = Field(default=None, max_length=64)
    compounding: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class CurveUpsert(CurveCreate):
    """Payload for inserting or replacing a curve by unique identifier."""


class CurveUpdate(BaseModel):
    """Payload for updating mutable curve fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    curve_type: str | None = Field(default=None, min_length=1, max_length=64)
    index_uid: uuid.UUID | None = None
    interpolation_method: str | None = Field(default=None, max_length=64)
    compounding: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


__all__ = [
    "Curve",
    "CurveCreate",
    "CurveUpdate",
    "CurveUpsert",
]
