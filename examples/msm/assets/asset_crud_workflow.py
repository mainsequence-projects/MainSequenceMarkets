from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)
from examples.msm.assets.utils import (
    EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX,
    EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_CRYPTO_ASSETS,
    EXAMPLE_CRYPTO_ASSET_TYPE,
    EXAMPLE_EQUITY_ASSET_TYPE,
    EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_OPENFIGI_EQUITY_FIGI,
)
from msm.constants import ASSET_TYPE_CRYPTO, ASSET_TYPE_EQUITY

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm

if TYPE_CHECKING:
    from msm.api.assets import OpenFigiDetails

EXAMPLE_ASSET_TYPES = [
    EXAMPLE_CRYPTO_ASSET_TYPE,
    EXAMPLE_EQUITY_ASSET_TYPE,
]


def create_query_assets(
    *,
    delete_temporary_assets: bool = False,
) -> dict[str, Any]:
    """Resolve FIGI data, register asset types, create assets, and list them."""

    msm.start_engine(
        models=["AssetType", "Asset", "OpenFigiAssetDetails"],
    )

    from msm.api.assets import Asset, AssetType
    from msm.data_nodes.assets import AssetSnapshot
    from msm.services.assets.openfigi import query_by_figi

    normalized_openfigi = query_by_figi(EXAMPLE_OPENFIGI_EQUITY_FIGI)
    registered_asset_types = [AssetType.upsert(**payload) for payload in EXAMPLE_ASSET_TYPES]
    created_assets = [Asset.upsert(**payload) for payload in EXAMPLE_CRYPTO_ASSETS]
    openfigi_asset = Asset.upsert(
        unique_identifier=normalized_openfigi["unique_identifier"],
        asset_type=ASSET_TYPE_EQUITY,
    )
    created_assets.append(openfigi_asset)

    btc_by_identifier = Asset.get_by_unique_identifier(
        unique_identifier=EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
    )
    if btc_by_identifier is None:
        raise RuntimeError(f"Expected {EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER} to exist after upsert.")

    btc_by_uid = Asset.get_by_uid(btc_by_identifier.uid)
    crypto_examples = Asset.filter(
        unique_identifier_contains=EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX,
        asset_type=ASSET_TYPE_CRYPTO,
        limit=20,
    )
    figi_details = _ensure_openfigi_details(
        asset_uid=str(openfigi_asset.uid),
        normalized_openfigi=normalized_openfigi,
    )
    asset_snapshot_time = dt.datetime.now(dt.UTC).replace(microsecond=0)
    asset_snapshot_node = AssetSnapshot().set_snapshots(
        _asset_snapshot_payloads(
            normalized_openfigi,
            snapshot_time=asset_snapshot_time,
        ),
    )
    snapshot_frame = asset_snapshot_node.run(debug_mode=True, force_update=True)
    created_asset_identifiers = [
        payload["unique_identifier"]
        for payload in [
            *EXAMPLE_CRYPTO_ASSETS,
            {"unique_identifier": normalized_openfigi["unique_identifier"]},
        ]
    ]
    created_assets_by_identifier = Asset.get_many_by_unique_identifier(
        created_asset_identifiers
    )
    created_asset_listing = [
        created_assets_by_identifier.get(identifier)
        for identifier in created_asset_identifiers
    ]
    deleted_assets = []
    if delete_temporary_assets:
        deleted_assets = [
            Asset.delete(result.uid)
            for result in created_assets
            if result.unique_identifier.startswith(EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX)
        ]

    return {
        "registered_asset_types": registered_asset_types,
        "created_assets": created_assets,
        "btc_by_identifier": btc_by_identifier,
        "btc_by_uid": btc_by_uid,
        "crypto_examples": crypto_examples,
        "openfigi_details": figi_details,
        "asset_snapshot_time": asset_snapshot_time,
        "asset_snapshot_node_identifier": asset_snapshot_node._default_identifier(),
        "asset_snapshot_frame": snapshot_frame,
        "created_asset_listing": created_asset_listing,
        "deleted_assets": deleted_assets,
    }


def _ensure_openfigi_details(
    *,
    asset_uid: str,
    normalized_openfigi: dict[str, Any],
) -> OpenFigiDetails:
    from msm.api.assets import OpenFigiDetails

    existing = OpenFigiDetails.filter(
        figi=normalized_openfigi["figi"],
        limit=1,
    )
    if existing:
        return existing[0]
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
    normalized_openfigi: dict[str, Any],
    *,
    snapshot_time: dt.datetime,
) -> list[dict[str, Any]]:
    return [
        {
            "time_index": snapshot_time,
            "asset_identifier": EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
            "name": "Bitcoin",
            "ticker": "BTC",
            "exchange_code": "CRYPTO",
            "asset_ticker_group_id": "crypto-majors",
        },
        {
            "time_index": snapshot_time,
            "asset_identifier": EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
            "name": "Ethereum",
            "ticker": "ETH",
            "exchange_code": "CRYPTO",
            "asset_ticker_group_id": "crypto-majors",
        },
        {
            "time_index": snapshot_time,
            "asset_identifier": normalized_openfigi["unique_identifier"],
            "name": normalized_openfigi["name"],
            "ticker": normalized_openfigi["ticker"],
            "exchange_code": normalized_openfigi["exchange_code"],
            "asset_ticker_group_id": normalized_openfigi["share_class"],
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--delete-temporary-assets",
        action="store_true",
        help=(
            "Delete only the temporary "
            f"{EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX}* custom assets after listing them."
        ),
    )
    args = parser.parse_args()
    result = create_query_assets(
        delete_temporary_assets=args.delete_temporary_assets,
    )
    print(result)


if __name__ == "__main__":
    main()
