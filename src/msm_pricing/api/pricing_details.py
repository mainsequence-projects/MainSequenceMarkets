from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from msm.api.base import _warn_deprecated_create_schemas, operation_result_rows
from msm.models import AssetTable
from msm.repositories.crud import (
    bulk_upsert_model,
    create_model,
    get_model_by_uid,
    search_model,
    update_model,
    upsert_model,
)

from msm_pricing.bootstrap import attach_pricing_schemas, resolve_pricing_runtime
from msm_pricing.data_nodes.pricing_details.storage import AssetPricingDetailsStorage
from msm_pricing.models.pricing_details import AssetCurrentPricingDetailsTable

DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT = "msm_pricing.instrument.v1"
MAX_PRICING_DETAILS_UPSERT_OPERATION_ROWS = 10_000


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
        operation_batch_size = _operation_batch_size(batch_size)
        rows: list[AssetCurrentPricingDetails] = []
        for chunk in _chunks(values, batch_size=operation_batch_size):
            chunk_context = _context_with_return_row_limit(context, len(chunk))
            result = bulk_upsert_model(
                chunk_context,
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
    def get_many_by_asset_uid(
        cls,
        asset_uids: Sequence[uuid.UUID | str],
        *,
        batch_size: int = 1000,
    ) -> dict[uuid.UUID, AssetCurrentPricingDetails]:
        """Load current pricing details for many asset UIDs in chunked searches."""

        normalized_asset_uids = [uuid.UUID(str(asset_uid)) for asset_uid in asset_uids]
        if not normalized_asset_uids:
            return {}
        return _current_pricing_details_by_asset_uid(
            cls._active_context(),
            normalized_asset_uids,
            batch_size=_operation_batch_size(batch_size),
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
        current_values = _current_pricing_details_values_for_batch_update(
            context,
            values=[values],
            always_update_current=[update_current],
            batch_size=1,
        )
        current_rows = _bulk_upsert_current_pricing_details(
            context,
            current_values,
            batch_size=1,
        )
        current_pricing_details = current_rows[0] if current_rows else None
        return AssetPricingDetailsAddResult(
            pricing_details=pricing_details,
            current_pricing_details=current_pricing_details,
            updated_current=current_pricing_details is not None,
        )

    @classmethod
    def add_many(
        cls,
        payloads: Sequence[AssetPricingDetailsAdd | Mapping[str, Any]],
        *,
        batch_size: int = 1000,
    ) -> AssetPricingDetailsBatchAddResult:
        """Add or upsert pricing-details snapshots in bulk.

        Rows with ``pricing_details_date=None`` share one timestamp and always
        update the current pricing-details table through a second bulk upsert.
        Explicitly dated rows update current when no current row exists or when
        their date is newer than current.
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
        operation_batch_size = _operation_batch_size(batch_size)
        for chunk in _chunks(storage_values, batch_size=operation_batch_size):
            chunk_context = _context_with_return_row_limit(context, len(chunk))
            result = bulk_upsert_model(
                chunk_context,
                model=cls.__table__,
                values=chunk,
                conflict_columns=cls.__upsert_keys__,
            )
            chunk_rows = cls._from_operation_result_many(result)
            if len(chunk_rows) != len(chunk):
                raise RuntimeError(
                    "Pricing-details bulk upsert returned "
                    f"{len(chunk_rows)} rows for {len(chunk)} submitted rows."
                )
            pricing_details.extend(chunk_rows)

        current_values = _current_pricing_details_values_for_batch_update(
            context,
            values=values,
            always_update_current=update_current_by_index,
            batch_size=operation_batch_size,
        )
        current_pricing_details = _bulk_upsert_current_pricing_details(
            context,
            current_values,
            batch_size=operation_batch_size,
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


def _current_pricing_details_values_for_batch_update(
    context: Any,
    *,
    values: Sequence[Mapping[str, Any]],
    always_update_current: Sequence[bool],
    batch_size: int,
) -> list[dict[str, Any]]:
    explicit_values = [
        value
        for value, should_update in zip(values, always_update_current, strict=True)
        if not should_update
    ]
    current_by_asset_uid = _current_pricing_details_by_asset_uid(
        context,
        [value["asset_uid"] for value in explicit_values],
        batch_size=batch_size,
    )

    selected_by_asset_uid: dict[uuid.UUID, dict[str, Any]] = {}
    for value, should_always_update in zip(values, always_update_current, strict=True):
        asset_uid = value["asset_uid"]
        should_update = should_always_update
        if not should_update:
            current = current_by_asset_uid.get(asset_uid)
            should_update = (
                current is None or value["pricing_details_date"] > current.pricing_details_date
            )
        if not should_update:
            continue

        current_values = _current_pricing_details_values(value)
        previous = selected_by_asset_uid.get(asset_uid)
        if (
            previous is None
            or current_values["pricing_details_date"] >= previous["pricing_details_date"]
        ):
            selected_by_asset_uid[asset_uid] = current_values

    return list(selected_by_asset_uid.values())


def _current_pricing_details_by_asset_uid(
    context: Any,
    asset_uids: Sequence[uuid.UUID],
    *,
    batch_size: int,
) -> dict[uuid.UUID, AssetCurrentPricingDetails]:
    unique_asset_uids = list(dict.fromkeys(asset_uids))
    current_by_asset_uid: dict[uuid.UUID, AssetCurrentPricingDetails] = {}
    for chunk in _chunks(unique_asset_uids, batch_size=batch_size):
        chunk_context = _context_with_return_row_limit(context, len(chunk))
        result = search_model(
            chunk_context,
            model=AssetCurrentPricingDetailsTable,
            in_filters={"asset_uid": chunk},
            limit=len(chunk),
        )
        for row in operation_result_rows(result):
            current = AssetCurrentPricingDetails.model_validate(row)
            current_by_asset_uid[current.asset_uid] = current
    return current_by_asset_uid


def _bulk_upsert_current_pricing_details(
    context: Any,
    values: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
) -> list[AssetCurrentPricingDetails]:
    if not values:
        return []

    current_pricing_details: list[AssetCurrentPricingDetails] = []
    for chunk in _chunks(values, batch_size=batch_size):
        chunk_context = _context_with_return_row_limit(context, len(chunk))
        result = bulk_upsert_model(
            chunk_context,
            model=AssetCurrentPricingDetailsTable,
            values=chunk,
            conflict_columns=AssetCurrentPricingDetails.__upsert_keys__,
        )
        chunk_rows = AssetCurrentPricingDetails._from_operation_result_many(result)
        if len(chunk_rows) != len(chunk):
            raise RuntimeError(
                "Current pricing-details bulk upsert returned "
                f"{len(chunk_rows)} rows for {len(chunk)} submitted rows."
            )
        current_pricing_details.extend(chunk_rows)
    return current_pricing_details


def _context_with_return_row_limit(context: Any, row_count: int) -> Any:
    if row_count < 1:
        return context
    limits = _limits_with_return_row_limit(
        getattr(context, "limits", None),
        row_count=row_count,
    )
    try:
        return replace(context, limits=limits)
    except TypeError:
        return context


def _limits_with_return_row_limit(
    limits: Any,
    *,
    row_count: int,
) -> dict[str, Any]:
    if limits is None:
        values: dict[str, Any] = {}
    elif isinstance(limits, Mapping):
        values = dict(limits)
    elif hasattr(limits, "model_dump"):
        values = limits.model_dump(exclude_none=True)
    else:
        values = {
            key: getattr(limits, key)
            for key in ("max_rows", "offset", "statement_timeout_ms")
            if hasattr(limits, key) and getattr(limits, key) is not None
        }

    current_max_rows = values.get("max_rows")
    if current_max_rows is None or int(current_max_rows) < row_count:
        values["max_rows"] = row_count
    return values


def _operation_batch_size(batch_size: int) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be greater than zero.")
    return min(batch_size, MAX_PRICING_DETAILS_UPSERT_OPERATION_ROWS)


def _chunks(
    values: Sequence[Any],
    *,
    batch_size: int,
) -> Iterator[Sequence[Any]]:
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
