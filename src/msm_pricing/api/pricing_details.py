from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from msm.api.base import _warn_deprecated_create_schemas, operation_result_rows
from msm.models import AssetTable
from msm.repositories.crud import (
    bulk_upsert_model,
    create_model,
    get_model_by_uid,
    update_model,
    upsert_model,
)

from msm_pricing.bootstrap import attach_pricing_schemas, resolve_pricing_runtime
from msm_pricing.data_nodes.pricing_details.storage import AssetPricingDetailsStorage
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

    __table__: ClassVar[type[AssetCurrentPricingDetailsTable]] = AssetCurrentPricingDetailsTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        AssetPricingDetailsStorage,
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
    def start_engine(cls, **kwargs: Any):
        """Attach the pricing runtime tables required by this row API."""

        requested_models = kwargs.pop("models", None)
        models = [*cls.__required_tables__, *(requested_models or [])]
        return attach_pricing_schemas(models=models, **kwargs)

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        """Deprecated compatibility alias for :meth:`start_engine`."""

        _warn_deprecated_create_schemas(cls.__name__)
        return cls.start_engine(**kwargs)

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
    def upsert_many(
        cls,
        payloads: Sequence[AssetCurrentPricingDetailsUpsert | Mapping[str, Any]],
        *,
        batch_size: int = 1000,
    ) -> list[AssetCurrentPricingDetails]:
        """Insert or replace current pricing details in bulk."""

        values = [
            _validate_payload(AssetCurrentPricingDetailsUpsert, payload, {}).model_dump()
            for payload in payloads
        ]
        if not values:
            return []

        context = cls._active_context()
        rows: list[AssetCurrentPricingDetails] = []
        for chunk in _chunks(values, batch_size=batch_size):
            result = bulk_upsert_model(
                context,
                model=cls.__table__,
                values=chunk,
                conflict_columns=cls.__upsert_keys__,
            )
            rows.extend(cls._from_operation_result_many(result))
        return rows

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
                "MetaTable operation result did not include an AssetCurrentPricingDetails row."
            )
        return None

    @classmethod
    def _from_operation_result_many(
        cls,
        result: Mapping[str, Any] | list[Any] | None,
    ) -> list[AssetCurrentPricingDetails]:
        return [cls.model_validate(row) for row in operation_result_rows(result)]


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


class AssetPricingDetails(BaseModel):
    """Timestamped priceable instrument terms observed for a canonical asset."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[AssetPricingDetailsStorage]] = AssetPricingDetailsStorage
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        AssetPricingDetailsStorage,
        AssetCurrentPricingDetailsTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("time_index", "asset_identifier")

    time_index: dt.datetime
    asset_identifier: str
    instrument_type: str
    instrument_dump: dict[str, Any]
    serialization_format: str = DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT
    pricing_package_version: str | None = None
    source: str | None = None
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )

    @field_validator("time_index")
    @classmethod
    def _require_timezone(cls, value: dt.datetime) -> dt.datetime:
        return AssetCurrentPricingDetails._require_timezone(value)

    @classmethod
    def add(
        cls,
        payload: AssetPricingDetailsAdd | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AssetPricingDetailsAddResult:
        """Add or upsert a pricing-details snapshot."""

        values = _validate_payload(AssetPricingDetailsAdd, payload, kwargs).model_dump()
        update_current = values["pricing_details_date"] is None
        if values["pricing_details_date"] is None:
            values["pricing_details_date"] = dt.datetime.now(dt.UTC)
        context = cls._active_context()
        storage_values = _pricing_details_storage_values(values)
        storage_result = upsert_model(
            context,
            model=cls.__table__,
            values=storage_values,
            conflict_columns=cls.__upsert_keys__,
        )
        pricing_details = cls._from_operation_result(storage_result)
        if update_current:
            current_pricing_details = AssetCurrentPricingDetails.upsert(
                asset_uid=values["asset_uid"],
                instrument_type=pricing_details.instrument_type,
                instrument_dump=pricing_details.instrument_dump,
                pricing_details_date=pricing_details.time_index,
                serialization_format=pricing_details.serialization_format,
                pricing_package_version=pricing_details.pricing_package_version,
                source=pricing_details.source,
                metadata_json=pricing_details.metadata_json,
            )
        else:
            current_pricing_details = None
        return AssetPricingDetailsAddResult(
            pricing_details=pricing_details,
            current_pricing_details=current_pricing_details,
            updated_current=update_current,
        )

    @classmethod
    def add_many(
        cls,
        payloads: Sequence[AssetPricingDetailsAdd | Mapping[str, Any]],
        *,
        batch_size: int = 1000,
    ) -> AssetPricingDetailsBatchAddResult:
        """Add or upsert pricing-details snapshots in bulk.

        Rows with ``pricing_details_date=None`` share one timestamp and update
        the current pricing-details table through a second bulk upsert.
        Explicitly dated rows are treated as historical snapshots and do not
        update current pricing details.
        """

        values = [
            _validate_payload(AssetPricingDetailsAdd, payload, {}).model_dump()
            for payload in payloads
        ]
        if not values:
            return AssetPricingDetailsBatchAddResult(
                pricing_details=[],
                current_pricing_details=[],
                updated_current=False,
                updated_current_count=0,
            )

        default_pricing_details_date = dt.datetime.now(dt.UTC)
        update_current_by_index: list[bool] = []
        for value in values:
            update_current = value["pricing_details_date"] is None
            update_current_by_index.append(update_current)
            if update_current:
                value["pricing_details_date"] = default_pricing_details_date

        context = cls._active_context()
        storage_values = [_pricing_details_storage_values(value) for value in values]
        pricing_details: list[AssetPricingDetails] = []
        for chunk in _chunks(storage_values, batch_size=batch_size):
            result = bulk_upsert_model(
                context,
                model=cls.__table__,
                values=chunk,
                conflict_columns=cls.__upsert_keys__,
            )
            pricing_details.extend(cls._from_operation_result_many(result))

        current_values = [
            _current_pricing_details_values(value)
            for value, update_current in zip(values, update_current_by_index, strict=True)
            if update_current
        ]
        current_pricing_details = AssetCurrentPricingDetails.upsert_many(
            current_values,
            batch_size=batch_size,
        )
        return AssetPricingDetailsBatchAddResult(
            pricing_details=pricing_details,
            current_pricing_details=current_pricing_details,
            updated_current=bool(current_pricing_details),
            updated_current_count=len(current_pricing_details),
        )

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
    ) -> AssetPricingDetails | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError(
                "MetaTable operation result did not include an AssetPricingDetails row."
            )
        return None

    @classmethod
    def _from_operation_result_many(
        cls,
        result: Mapping[str, Any] | list[Any] | None,
    ) -> list[AssetPricingDetails]:
        return [cls.model_validate(row) for row in operation_result_rows(result)]


class AssetPricingDetailsAdd(BaseModel):
    """Payload for adding timestamped pricing details for an asset."""

    model_config = ConfigDict(extra="forbid")

    asset_uid: uuid.UUID
    asset_identifier: str = Field(min_length=1, max_length=255)
    instrument_type: str = Field(min_length=1, max_length=128)
    instrument_dump: dict[str, Any]
    pricing_details_date: dt.datetime | None = None
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
    def _require_timezone(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is None:
            return None
        return AssetCurrentPricingDetails._require_timezone(value)


class AssetPricingDetailsAddResult(BaseModel):
    """Result of adding/upserting pricing details and optional current update."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pricing_details: AssetPricingDetails
    current_pricing_details: AssetCurrentPricingDetails | None
    updated_current: bool


class AssetPricingDetailsBatchAddResult(BaseModel):
    """Result of bulk pricing-details upsert."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pricing_details: list[AssetPricingDetails]
    current_pricing_details: list[AssetCurrentPricingDetails]
    updated_current: bool
    updated_current_count: int


def _pricing_details_storage_values(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "time_index": values["pricing_details_date"],
        "asset_identifier": values["asset_identifier"],
        "instrument_type": values["instrument_type"],
        "instrument_dump": values["instrument_dump"],
        "serialization_format": values["serialization_format"],
        "pricing_package_version": values["pricing_package_version"],
        "source": values["source"],
        "metadata_json": values["metadata_json"],
    }


def _current_pricing_details_values(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "asset_uid": values["asset_uid"],
        "instrument_type": values["instrument_type"],
        "instrument_dump": values["instrument_dump"],
        "pricing_details_date": values["pricing_details_date"],
        "serialization_format": values["serialization_format"],
        "pricing_package_version": values["pricing_package_version"],
        "source": values["source"],
        "metadata_json": values["metadata_json"],
    }


def _chunks(
    values: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
) -> Iterator[Sequence[Mapping[str, Any]]]:
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero.")
    for index in range(0, len(values), batch_size):
        yield values[index : index + batch_size]


__all__ = [
    "AssetCurrentPricingDetails",
    "AssetCurrentPricingDetailsCreate",
    "AssetCurrentPricingDetailsUpdate",
    "AssetCurrentPricingDetailsUpsert",
    "AssetPricingDetails",
    "AssetPricingDetailsAdd",
    "AssetPricingDetailsBatchAddResult",
    "AssetPricingDetailsAddResult",
    "DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT",
]
