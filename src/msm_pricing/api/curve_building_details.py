from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from msm.api.base import _warn_deprecated_create_schemas, operation_result_rows
from msm.repositories.crud import (
    count_model,
    create_model,
    get_model_by_uid,
    search_model,
    update_model,
    upsert_model,
)

from msm_pricing.bootstrap import attach_pricing_schemas, resolve_pricing_runtime
from msm_pricing.models.curve_building_details import CurveBuildingDetailsTable
from msm_pricing.models.curves import CurveTable

DEFAULT_CURVE_BUILDING_DETAILS_SERIALIZATION_FORMAT = "msm_pricing.curve_building_details.v1"


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


class CurveBuildingDetails(BaseModel):
    """Curve-owned build specification used by pricing resolvers."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[CurveBuildingDetailsTable]] = CurveBuildingDetailsTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        CurveTable,
        CurveBuildingDetailsTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("curve_uid",)

    curve_uid: uuid.UUID
    builder_type: str
    quote_convention: str
    rate_unit: str
    day_counter_code: str
    calendar_code: str
    interpolation_method: str
    compounding: str
    compounding_frequency: str | None = None
    extrapolation_policy: str
    bootstrap_method: str | None = None
    builder_payload: dict[str, Any] | None = None
    source: str | None = None
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )

    @classmethod
    def start_engine(cls, **kwargs: Any):
        requested_models = kwargs.pop("models", None)
        models = [*cls.__required_tables__, *(requested_models or [])]
        return attach_pricing_schemas(models=models, **kwargs)

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        _warn_deprecated_create_schemas(cls.__name__)
        return cls.start_engine(**kwargs)

    @classmethod
    def create(
        cls,
        payload: CurveBuildingDetailsCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CurveBuildingDetails:
        values = _validate_payload(CurveBuildingDetailsCreate, payload, kwargs).model_dump()
        result = create_model(cls._active_context(), model=cls.__table__, values=values)
        return cls._from_operation_result(result)

    @classmethod
    def upsert(
        cls,
        payload: CurveBuildingDetailsUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CurveBuildingDetails:
        values = _validate_payload(CurveBuildingDetailsUpsert, payload, kwargs).model_dump()
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
        curve_uid: uuid.UUID | str,
        payload: CurveBuildingDetailsUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CurveBuildingDetails:
        values = _validate_payload(CurveBuildingDetailsUpdate, payload, kwargs).model_dump(
            exclude_unset=True,
        )
        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=curve_uid,
            values=values,
        )
        return cls._from_operation_result(result)

    @classmethod
    def get_by_curve_uid(cls, curve_uid: uuid.UUID | str) -> CurveBuildingDetails | None:
        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=curve_uid)
        return cls._from_operation_result(result, required=False)

    @classmethod
    def filter(cls, *, limit: int = 500, **filters: Any) -> list[CurveBuildingDetails]:
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={key: value for key, value in filters.items() if value is not None},
            limit=limit,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def list(
        cls,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> dict[str, Any]:
        limit, offset = _validate_pagination(limit=limit, offset=offset)
        exact_filters = {key: value for key, value in filters.items() if value is not None}
        context = cls._active_context()
        count_result = count_model(context, model=cls.__table__, filters=exact_filters)
        result = search_model(
            context,
            model=cls.__table__,
            filters=exact_filters,
            limit=limit,
            offset=offset,
        )
        return {
            "count": _count_from_operation_result(count_result),
            "limit": limit,
            "offset": offset,
            "results": [cls.model_validate(row) for row in operation_result_rows(result)],
        }

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
    ) -> CurveBuildingDetails | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError("MetaTable operation result did not include a CurveBuildingDetails row.")
        return None


class CurveBuildingDetailsCreate(BaseModel):
    """Payload for creating curve-owned build details."""

    model_config = ConfigDict(extra="forbid")

    curve_uid: uuid.UUID
    builder_type: str = Field(min_length=1, max_length=64)
    quote_convention: str = Field(min_length=1, max_length=64)
    rate_unit: str = Field(min_length=1, max_length=32)
    day_counter_code: str = Field(min_length=1, max_length=64)
    calendar_code: str = Field(min_length=1, max_length=64)
    interpolation_method: str = Field(min_length=1, max_length=64)
    compounding: str = Field(min_length=1, max_length=64)
    compounding_frequency: str | None = Field(default=None, max_length=64)
    extrapolation_policy: str = Field(min_length=1, max_length=64)
    bootstrap_method: str | None = Field(default=None, max_length=64)
    builder_payload: dict[str, Any] | None = None
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class CurveBuildingDetailsUpsert(CurveBuildingDetailsCreate):
    """Payload for inserting or replacing curve build details by curve_uid."""


class CurveBuildingDetailsUpdate(BaseModel):
    """Payload for updating mutable curve build detail fields."""

    model_config = ConfigDict(extra="forbid")

    builder_type: str | None = Field(default=None, min_length=1, max_length=64)
    quote_convention: str | None = Field(default=None, min_length=1, max_length=64)
    rate_unit: str | None = Field(default=None, min_length=1, max_length=32)
    day_counter_code: str | None = Field(default=None, min_length=1, max_length=64)
    calendar_code: str | None = Field(default=None, min_length=1, max_length=64)
    interpolation_method: str | None = Field(default=None, min_length=1, max_length=64)
    compounding: str | None = Field(default=None, min_length=1, max_length=64)
    compounding_frequency: str | None = Field(default=None, max_length=64)
    extrapolation_policy: str | None = Field(default=None, min_length=1, max_length=64)
    bootstrap_method: str | None = Field(default=None, max_length=64)
    builder_payload: dict[str, Any] | None = None
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


def _validate_pagination(*, limit: int, offset: int) -> tuple[int, int]:
    if limit < 0:
        raise ValueError("limit must be greater than or equal to 0.")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0.")
    return limit, offset


def _count_from_operation_result(result: Mapping[str, Any] | list[Any] | None) -> int:
    rows = operation_result_rows(result)
    if not rows:
        return 0
    return int(rows[0].get("count") or 0)


__all__ = [
    "CurveBuildingDetails",
    "CurveBuildingDetailsCreate",
    "CurveBuildingDetailsUpdate",
    "CurveBuildingDetailsUpsert",
    "DEFAULT_CURVE_BUILDING_DETAILS_SERIALIZATION_FORMAT",
]
