from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from msm.api.assets import Asset

from msm_pricing.instruments.base_instrument import InstrumentModel

from .pricing_details import (
    DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
    AssetCurrentPricingDetails,
    AssetPricingDetailsAdd,
    AssetPricingDetailsBatchAddResult,
    AssetPricingDetails,
    AssetPricingDetailsAddResult,
)


class AssetInstrumentPricingDetailsAdd(BaseModel):
    """One asset/instrument pair for bulk pricing-details persistence."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    asset: Asset
    instrument: InstrumentModel
    pricing_details_date: dt.datetime | None = None
    serialization_format: str | None = Field(default=None, min_length=1, max_length=128)
    pricing_package_version: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("pricing_details_date")
    @classmethod
    def _require_timezone(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pricing_details_date must be timezone-aware.")
        return value


def add_pricing_details(
    *,
    asset: Asset,
    instrument: InstrumentModel,
    pricing_details_date: dt.datetime | None = None,
    serialization_format: str = DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
    pricing_package_version: str | None = None,
    source: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> AssetPricingDetailsAddResult:
    """Add/upsert pricing details and update current when no date is provided."""

    instrument.validate_asset(asset)
    instrument_payload = _instrument_backend_payload(instrument)
    result = AssetPricingDetails.add(
        asset_uid=asset.uid,
        asset_identifier=asset.unique_identifier,
        instrument_type=instrument_payload["instrument_type"],
        instrument_dump=instrument_payload["instrument"],
        pricing_details_date=pricing_details_date,
        serialization_format=serialization_format,
        pricing_package_version=pricing_package_version,
        source=source,
        metadata_json=metadata_json,
    )
    instrument._asset_uid = asset.uid
    return result


def add_many_pricing_details(
    items: Sequence[AssetInstrumentPricingDetailsAdd | Mapping[str, Any]],
    *,
    pricing_details_date: dt.datetime | None = None,
    serialization_format: str = DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
    pricing_package_version: str | None = None,
    source: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    batch_size: int = 1000,
) -> AssetPricingDetailsBatchAddResult:
    """Add/upsert pricing details for many asset/instrument pairs in bulk."""

    if pricing_details_date is not None:
        AssetInstrumentPricingDetailsAdd._require_timezone(pricing_details_date)

    payloads: list[AssetPricingDetailsAdd] = []
    validated_items = [_validate_instrument_pricing_details_item(item) for item in items]
    for item in validated_items:
        item.instrument.validate_asset(item.asset)
        instrument_payload = _instrument_backend_payload(item.instrument)
        payloads.append(
            AssetPricingDetailsAdd(
                asset_uid=item.asset.uid,
                asset_identifier=item.asset.unique_identifier,
                instrument_type=instrument_payload["instrument_type"],
                instrument_dump=instrument_payload["instrument"],
                pricing_details_date=(
                    item.pricing_details_date
                    if item.pricing_details_date is not None
                    else pricing_details_date
                ),
                serialization_format=item.serialization_format or serialization_format,
                pricing_package_version=(
                    item.pricing_package_version
                    if item.pricing_package_version is not None
                    else pricing_package_version
                ),
                source=item.source if item.source is not None else source,
                metadata_json=(
                    item.metadata_json if item.metadata_json is not None else metadata_json
                ),
            )
        )

    result = AssetPricingDetails.add_many(payloads, batch_size=batch_size)
    for item in validated_items:
        item.instrument._asset_uid = item.asset.uid
    return result


def load_instrument_from_asset(
    asset: Asset,
    *,
    registry: Mapping[str, type[InstrumentModel]] | None = None,
) -> InstrumentModel:
    """Load and rebuild the current concrete pricing instrument for an asset."""

    row = AssetCurrentPricingDetails.get_by_asset_uid(asset.uid)
    if row is None:
        raise LookupError(f"No current pricing details are attached to asset {asset.uid}.")

    instrument = InstrumentModel.rebuild(
        {
            "instrument_type": row.instrument_type,
            "instrument": row.instrument_dump,
        },
        registry=registry,
    )
    instrument.validate_asset(asset)
    instrument._asset_uid = asset.uid
    return instrument


def _validate_instrument_pricing_details_item(
    item: AssetInstrumentPricingDetailsAdd | Mapping[str, Any],
) -> AssetInstrumentPricingDetailsAdd:
    if isinstance(item, AssetInstrumentPricingDetailsAdd):
        return item
    if isinstance(item, Mapping):
        return AssetInstrumentPricingDetailsAdd.model_validate(dict(item))
    raise TypeError(
        "items must contain AssetInstrumentPricingDetailsAdd instances or mapping payloads."
    )


def _instrument_backend_payload(instrument: InstrumentModel) -> dict[str, Any]:
    payload = json.loads(instrument.serialize_for_backend())
    if not isinstance(payload, dict):
        raise ValueError("Instrument serialization did not produce a JSON object.")
    instrument_type = payload.get("instrument_type")
    instrument_dump = payload.get("instrument")
    if not isinstance(instrument_type, str) or not instrument_type:
        raise ValueError("Instrument serialization must include a non-empty instrument_type.")
    if not isinstance(instrument_dump, dict):
        raise ValueError("Instrument serialization must include an instrument object.")
    return {
        "instrument_type": instrument_type,
        "instrument": instrument_dump,
    }


__all__ = [
    "AssetInstrumentPricingDetailsAdd",
    "add_many_pricing_details",
    "add_pricing_details",
    "load_instrument_from_asset",
]
