from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from msm.api.base import operation_result_rows
from msm.models import AssetTable
from msm.repositories.crud import (
    create_model,
    get_model_by_uid,
    update_model,
    upsert_model,
)

from msm_pricing.bootstrap import create_pricing_schemas, resolve_pricing_runtime
from msm_pricing.models.pricing_details import AssetCurrentPricingDetailsTable

DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT = "msm_pricing.instrument.v1"


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


class AssetCurrentPricingDetails(BaseModel):
    """Current priceable instrument terms attached to a canonical asset."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[AssetCurrentPricingDetailsTable]] = (
        AssetCurrentPricingDetailsTable
    )
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        AssetCurrentPricingDetailsTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("asset_uid",)

    asset_uid: uuid.UUID
    instrument_type: str
    instrument_dump: dict[str, Any]
    pricing_details_date: dt.datetime
    serialization_format: str = DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT
    pricing_package_version: str | None = None
    source: str | None = None
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )

    @field_validator("pricing_details_date")
    @classmethod
    def _require_timezone(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pricing_details_date must be timezone-aware.")
        return value

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        requested_models = kwargs.pop("models", None)
        models = [*cls.__required_tables__, *(requested_models or [])]
        return create_pricing_schemas(models=models, **kwargs)

    @classmethod
    def create(
        cls,
        payload: AssetCurrentPricingDetailsCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AssetCurrentPricingDetails:
        values = _validate_payload(AssetCurrentPricingDetailsCreate, payload, kwargs).model_dump()
        result = create_model(cls._active_context(), model=cls.__table__, values=values)
        return cls._from_operation_result(result)

    @classmethod
    def upsert(
        cls,
        payload: AssetCurrentPricingDetailsUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AssetCurrentPricingDetails:
        values = _validate_payload(AssetCurrentPricingDetailsUpsert, payload, kwargs).model_dump()
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
        asset_uid: uuid.UUID | str,
        payload: AssetCurrentPricingDetailsUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AssetCurrentPricingDetails:
        values = _validate_payload(AssetCurrentPricingDetailsUpdate, payload, kwargs).model_dump(
            exclude_unset=True,
        )
        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=asset_uid,
            values=values,
        )
        return cls._from_operation_result(result)

    @classmethod
    def get_by_asset_uid(
        cls,
        asset_uid: uuid.UUID | str,
    ) -> AssetCurrentPricingDetails | None:
        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=asset_uid)
        return cls._from_operation_result(result, required=False)

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
    ) -> AssetCurrentPricingDetails | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError(
                "MetaTable operation result did not include an "
                "AssetCurrentPricingDetails row."
            )
        return None


class AssetCurrentPricingDetailsCreate(BaseModel):
    """Payload for creating current pricing details for an asset."""

    model_config = ConfigDict(extra="forbid")

    asset_uid: uuid.UUID
    instrument_type: str = Field(min_length=1, max_length=128)
    instrument_dump: dict[str, Any]
    pricing_details_date: dt.datetime
    serialization_format: str = Field(
        default=DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
        min_length=1,
        max_length=128,
    )
    pricing_package_version: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("pricing_details_date")
    @classmethod
    def _require_timezone(cls, value: dt.datetime) -> dt.datetime:
        return AssetCurrentPricingDetails._require_timezone(value)


class AssetCurrentPricingDetailsUpsert(AssetCurrentPricingDetailsCreate):
    """Payload for inserting or replacing current pricing details by asset UID."""


class AssetCurrentPricingDetailsUpdate(BaseModel):
    """Payload for updating mutable current pricing detail fields."""

    model_config = ConfigDict(extra="forbid")

    instrument_type: str | None = Field(default=None, min_length=1, max_length=128)
    instrument_dump: dict[str, Any] | None = None
    pricing_details_date: dt.datetime | None = None
    serialization_format: str | None = Field(default=None, min_length=1, max_length=128)
    pricing_package_version: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("pricing_details_date")
    @classmethod
    def _require_timezone(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is None:
            return value
        return AssetCurrentPricingDetails._require_timezone(value)


__all__ = [
    "AssetCurrentPricingDetails",
    "AssetCurrentPricingDetailsCreate",
    "AssetCurrentPricingDetailsUpdate",
    "AssetCurrentPricingDetailsUpsert",
    "DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT",
]
