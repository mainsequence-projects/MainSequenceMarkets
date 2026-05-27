from __future__ import annotations

import datetime as dt
import os
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_AUTO_REGISTER_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_AUTO_REGISTER_ENV, EXAMPLE_METATABLE_NAMESPACE)

if TYPE_CHECKING:
    from msm.api.assets import Asset, OpenFigiDetails

EXAMPLE_EURUSD_OPENFIGI_FIGI = "BBG0013HGRV5"
EXAMPLE_EUR_CURRENCY = {
    "code": "EUR",
    "currency_name": "Euro",
}
EXAMPLE_USD_CURRENCY = {
    "code": "USD",
    "currency_name": "US Dollar",
}


def create_eurusd_currency_spot() -> dict[str, Any]:
    """Create EUR/USD from OpenFIGI and publish current display snapshots."""

    from msm.api.assets import Asset, AssetType, CurrencySpot
    from msm.data_nodes.assets import AssetSnapshot
    from msm.services.assets.openfigi import query_by_figi

    currency_asset_type = AssetType.upsert(
        asset_type="currency",
        display_name="Currency",
        description="Single currency assets used as base or quote legs.",
    )
    base_currency = _upsert_currency_asset(EXAMPLE_EUR_CURRENCY)
    quote_currency = _upsert_currency_asset(EXAMPLE_USD_CURRENCY)

    normalized_openfigi = query_by_figi(EXAMPLE_EURUSD_OPENFIGI_FIGI)
    eurusd = CurrencySpot.upsert(
        unique_identifier=normalized_openfigi["unique_identifier"],
        base_currency_uid=base_currency.uid,
        quote_currency_uid=quote_currency.uid,
    )
    eurusd_asset = Asset.get_by_uid(eurusd.asset_uid)
    if eurusd_asset is None:
        raise RuntimeError(f"Expected EUR/USD asset {eurusd.asset_uid} to exist after upsert.")
    openfigi_details = _ensure_openfigi_details(
        asset_uid=eurusd.asset_uid,
        normalized_openfigi=normalized_openfigi,
    )

    snapshot_time = dt.datetime.now(dt.UTC).replace(microsecond=0)
    asset_snapshot_node = AssetSnapshot().set_snapshots(
        _asset_snapshot_payloads(
            base_currency=base_currency,
            quote_currency=quote_currency,
            eurusd_asset=eurusd_asset,
            normalized_openfigi=normalized_openfigi,
            snapshot_time=snapshot_time,
        )
    )
    snapshot_frame = asset_snapshot_node.run(debug_mode=True, force_update=True)

    return {
        "currency_asset_type": currency_asset_type,
        "base_currency": base_currency,
        "quote_currency": quote_currency,
        "eurusd_asset": eurusd_asset,
        "eurusd": eurusd,
        "openfigi_details": openfigi_details,
        "asset_snapshot_time": snapshot_time,
        "asset_snapshot_node_identifier": asset_snapshot_node.config.node_metadata.identifier,
        "asset_snapshot_frame": snapshot_frame,
    }


def _upsert_currency_asset(currency: dict[str, str]) -> "Asset":
    from msm.api.assets import Asset

    return Asset.upsert(
        unique_identifier=currency["code"],
        asset_type="currency",
    )


def _ensure_openfigi_details(
    *,
    asset_uid: uuid.UUID | str,
    normalized_openfigi: dict[str, Any],
) -> "OpenFigiDetails":
    from msm.api.assets import OpenFigiDetails

    return OpenFigiDetails.upsert(
        asset_uid=asset_uid,
        figi=normalized_openfigi["figi"],
        composite=normalized_openfigi["composite"],
        share_class=normalized_openfigi["share_class"],
        isin=normalized_openfigi["isin"],
        ticker=normalized_openfigi["ticker"],
        name=normalized_openfigi["name"],
        exchange_code=normalized_openfigi["exchange_code"],
        security_type=normalized_openfigi["security_type"],
        security_type_2=normalized_openfigi["security_type_2"],
        security_market_sector=normalized_openfigi["security_market_sector"],
        security_description=normalized_openfigi["security_description"],
        unique_id=normalized_openfigi["unique_id"],
        unique_id_fut_opt=normalized_openfigi["unique_id_fut_opt"],
        metadata_text=normalized_openfigi["metadata"],
        raw_payload=normalized_openfigi["raw_payload"],
    )


def _asset_snapshot_payloads(
    *,
    base_currency: "Asset",
    quote_currency: "Asset",
    eurusd_asset: "Asset",
    normalized_openfigi: dict[str, Any],
    snapshot_time: dt.datetime,
) -> list[dict[str, Any]]:
    return [
        _currency_asset_snapshot(
            currency=EXAMPLE_EUR_CURRENCY,
            asset=base_currency,
            snapshot_time=snapshot_time,
        ),
        _currency_asset_snapshot(
            currency=EXAMPLE_USD_CURRENCY,
            asset=quote_currency,
            snapshot_time=snapshot_time,
        ),
        {
            "time_index": snapshot_time,
            "unique_identifier": eurusd_asset.unique_identifier,
            "name": (
                f"{EXAMPLE_EUR_CURRENCY['currency_name']} / "
                f"{EXAMPLE_USD_CURRENCY['currency_name']}"
            ),
            "ticker": f"{EXAMPLE_EUR_CURRENCY['code']}/{EXAMPLE_USD_CURRENCY['code']}",
            "exchange_code": normalized_openfigi["exchange_code"] or "CURRENCY",
            "asset_ticker_group_id": normalized_openfigi["share_class"] or "currency_spot",
        },
    ]


def _currency_asset_snapshot(
    *,
    currency: dict[str, str],
    asset: "Asset",
    snapshot_time: dt.datetime,
) -> dict[str, Any]:
    return {
        "time_index": snapshot_time,
        "unique_identifier": asset.unique_identifier,
        "name": currency["currency_name"],
        "ticker": currency["code"],
        "exchange_code": "CURRENCY",
        "asset_ticker_group_id": "currency",
    }


def main() -> None:
    print(create_eurusd_currency_spot())


if __name__ == "__main__":
    main()
