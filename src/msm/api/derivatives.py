from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.assets import Asset
from msm.api.base import _dedupe_models, operation_result_rows
from msm.models import AssetTable, AssetTypeTable, FutureDetailsTable, IndexTable
from msm.repositories.crud import upsert_model

FUTURE_ASSET_TYPE = "future"


class FutureKind(str, Enum):
    """Canonical future contract lifecycle kinds."""

    PERPETUAL = "PERPETUAL"
    EXPIRING = "EXPIRING"


class FutureSettlementModel(str, Enum):
    """Canonical futures settlement model keys."""

    LINEAR = "LINEAR"
    INVERSE = "INVERSE"
    QUANTO = "QUANTO"
    UNKNOWN = "UNKNOWN"


class FutureSettlementMethod(str, Enum):
    """Canonical futures settlement method keys."""

    CASH = "CASH"
    PHYSICAL = "PHYSICAL"
    UNKNOWN = "UNKNOWN"


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


def _normalize_future_enum(enum_type: type[Enum], value: Enum | str) -> str:
    if isinstance(value, enum_type):
        return str(value.value)
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError("Future enum value cannot be empty.")
    valid_values = {str(member.value) for member in enum_type}
    if normalized not in valid_values:
        valid_display = ", ".join(sorted(valid_values))
        raise ValueError(f"Future enum value must be one of: {valid_display}.")
    return normalized


def _normalize_unit(value: str) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError("Future unit cannot be empty.")
    return normalized


class Future(BaseModel):
    """Typed future asset with contract terms backed by a detail MetaTable row."""

    model_config = ConfigDict(extra="ignore", frozen=True, use_enum_values=True)

    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTypeTable,
        AssetTable,
        IndexTable,
        FutureDetailsTable,
    ]

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
    unique_identifier: str
    asset_type: str = FUTURE_ASSET_TYPE
    kind: FutureKind
    underlying_index_uid: uuid.UUID
    quote_unit: str
    settlement_asset: uuid.UUID
    margin_asset: uuid.UUID
    settlement_model: FutureSettlementModel
    settlement_method: FutureSettlementMethod
    contract_size: Decimal
    contract_unit: str
    expires_at: dt.datetime | None = None
    settles_at: dt.datetime | None = None
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata", "metadata_payload"),
    )

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        """Create the MetaTable schemas required by the future API."""

        from msm.bootstrap import create_schemas

        requested_models = kwargs.pop("models", None)
        models = _dedupe_models([*cls.__required_tables__, *(requested_models or [])])
        return create_schemas(models=models, **kwargs)

    @classmethod
    def upsert(
        cls,
        payload: FutureUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Future:
        """Upsert a future asset and its contract-detail row."""

        values = _validate_payload(FutureUpsert, payload, kwargs).model_dump()
        context = cls._active_context()

        upsert_model(
            context,
            model=AssetTypeTable,
            values={
                "asset_type": FUTURE_ASSET_TYPE,
                "display_name": "Future",
                "description": "Futures contracts represented as tradable assets.",
            },
            conflict_columns=("asset_type",),
        )
        future_asset = Asset._from_operation_result(
            upsert_model(
                context,
                model=AssetTable,
                values={
                    "unique_identifier": values["unique_identifier"],
                    "asset_type": FUTURE_ASSET_TYPE,
                },
                conflict_columns=("unique_identifier",),
            )
        )
        detail_rows = operation_result_rows(
            upsert_model(
                context,
                model=FutureDetailsTable,
                values={
                    "asset_uid": future_asset.uid,
                    "kind": values["kind"],
                    "underlying_index_uid": values["underlying_index_uid"],
                    "quote_unit": values["quote_unit"],
                    "settlement_asset": values["settlement_asset"],
                    "margin_asset": values["margin_asset"],
                    "settlement_model": values["settlement_model"],
                    "settlement_method": values["settlement_method"],
                    "contract_size": values["contract_size"],
                    "contract_unit": values["contract_unit"],
                    "expires_at": values["expires_at"],
                    "settles_at": values["settles_at"],
                    "metadata": values["metadata"],
                },
                conflict_columns=("asset_uid",),
            )
        )
        if not detail_rows:
            raise LookupError("Future upsert did not return a row.")

        return cls.model_validate(
            {
                **detail_rows[0],
                "uid": detail_rows[0].get("asset_uid"),
                "unique_identifier": future_asset.unique_identifier,
                "asset_type": future_asset.asset_type,
            }
        )

    @classmethod
    def _active_context(cls):
        from msm.bootstrap import resolve_runtime

        runtime = resolve_runtime(
            models=cls.__required_tables__,
            row_model_name=cls.__name__,
        )
        return runtime.context


class FutureCreate(BaseModel):
    """Payload for creating a future asset and contract-detail row."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    unique_identifier: str = Field(min_length=1, max_length=255)
    kind: FutureKind
    underlying_index_uid: uuid.UUID | str
    quote_unit: str = Field(min_length=1, max_length=64)
    settlement_asset: uuid.UUID | str
    margin_asset: uuid.UUID | str
    settlement_model: FutureSettlementModel
    settlement_method: FutureSettlementMethod
    contract_size: Decimal
    contract_unit: str = Field(min_length=1, max_length=64)
    expires_at: dt.datetime | None = None
    settles_at: dt.datetime | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind(cls, value: FutureKind | str) -> str:
        return _normalize_future_enum(FutureKind, value)

    @field_validator("settlement_model", mode="before")
    @classmethod
    def _normalize_settlement_model(cls, value: FutureSettlementModel | str) -> str:
        return _normalize_future_enum(FutureSettlementModel, value)

    @field_validator("settlement_method", mode="before")
    @classmethod
    def _normalize_settlement_method(cls, value: FutureSettlementMethod | str) -> str:
        return _normalize_future_enum(FutureSettlementMethod, value)

    @field_validator("quote_unit", "contract_unit", mode="before")
    @classmethod
    def _normalize_units(cls, value: str) -> str:
        return _normalize_unit(value)

    @field_validator("contract_size")
    @classmethod
    def _contract_size_must_be_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Future contract_size must be positive.")
        return value

    @model_validator(mode="after")
    def _validate_expiration_contract(self) -> FutureCreate:
        kind = self.kind.value if isinstance(self.kind, FutureKind) else str(self.kind)
        if kind == FutureKind.PERPETUAL.value and self.expires_at is not None:
            raise ValueError("Future kind PERPETUAL requires expires_at to be null.")
        if kind == FutureKind.EXPIRING.value and self.expires_at is None:
            raise ValueError("Future kind EXPIRING requires expires_at.")
        return self


class FutureUpsert(FutureCreate):
    """Payload for inserting or updating a future by unique identifier."""


__all__ = [
    "FUTURE_ASSET_TYPE",
    "Future",
    "FutureCreate",
    "FutureKind",
    "FutureSettlementMethod",
    "FutureSettlementModel",
    "FutureUpsert",
]
