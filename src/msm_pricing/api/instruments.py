from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from typing import Any

from msm.api.assets import Asset

from msm_pricing.instruments.base_instrument import InstrumentModel

from .pricing_details import (
    DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
    AssetCurrentPricingDetails,
)


def persist_current_pricing_details(
    *,
    asset: Asset,
    instrument: InstrumentModel,
    pricing_details_date: dt.datetime | None = None,
    serialization_format: str = DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
    pricing_package_version: str | None = None,
    source: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> AssetCurrentPricingDetails:
    """Persist the current priceable instrument terms for an asset."""

    instrument.validate_asset(asset)
    instrument_payload = _instrument_backend_payload(instrument)
    row = AssetCurrentPricingDetails.upsert(
        asset_uid=asset.uid,
        instrument_type=instrument_payload["instrument_type"],
        instrument_dump=instrument_payload["instrument"],
        pricing_details_date=pricing_details_date or dt.datetime.now(dt.UTC),
        serialization_format=serialization_format,
        pricing_package_version=pricing_package_version,
        source=source,
        metadata_json=metadata_json,
    )
    instrument._asset_uid = row.asset_uid
    return row


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
    "load_instrument_from_asset",
    "persist_current_pricing_details",
]
