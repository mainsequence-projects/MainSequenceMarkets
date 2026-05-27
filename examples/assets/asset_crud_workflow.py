from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
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
    from msm.api.assets import OpenFigiDetails

EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX = "example-asset-"
EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER = f"{EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX}btc"
EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER = f"{EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX}eth"
EXAMPLE_ASSET_TYPES = [
    {
        "asset_type": "crypto",
        "display_name": "Crypto",
        "description": "Crypto spot and token assets used by the example workflow.",
        "metadata_json": {"source": "examples/assets/asset_crud_workflow.py"},
    },
    {
        "asset_type": "equity",
        "display_name": "Equity",
        "description": "Listed equity assets resolved through OpenFIGI.",
        "metadata_json": {"source": "examples/assets/asset_crud_workflow.py"},
    },
]
EXAMPLE_ASSETS = [
    {
        "unique_identifier": EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
        "asset_type": "crypto",
    },
    {
        "unique_identifier": EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
        "asset_type": "crypto",
    },
]
EXAMPLE_OPENFIGI_FIGI = "BBG00FNFPQH4"


def create_query_assets(
    *,
    delete_temporary_assets: bool = False,
) -> dict[str, Any]:
    """Resolve FIGI data, register asset types, create assets, and list them."""

    from msm.api.assets import Asset, AssetType
    from msm.data_nodes.assets import AssetSnapshot
    from msm.services.assets.openfigi import query_by_figi

    normalized_openfigi = query_by_figi(EXAMPLE_OPENFIGI_FIGI)
    registered_asset_types = [AssetType.upsert(**payload) for payload in EXAMPLE_ASSET_TYPES]
    created_assets = [Asset.upsert(**payload) for payload in EXAMPLE_ASSETS]
    openfigi_asset = Asset.upsert(
        unique_identifier=normalized_openfigi["unique_identifier"],
        asset_type="equity",
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
        asset_type="crypto",
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
    created_asset_listing = [
        Asset.get_by_unique_identifier(unique_identifier=payload["unique_identifier"])
        for payload in [
            *EXAMPLE_ASSETS,
            {"unique_identifier": normalized_openfigi["unique_identifier"]},
        ]
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
        "asset_snapshot_node_identifier": asset_snapshot_node.config.node_metadata.identifier,
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
            "unique_identifier": EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
            "name": "Bitcoin",
            "ticker": "BTC",
            "exchange_code": "CRYPTO",
            "asset_ticker_group_id": "crypto-majors",
        },
        {
            "time_index": snapshot_time,
            "unique_identifier": EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
            "name": "Ethereum",
            "ticker": "ETH",
            "exchange_code": "CRYPTO",
            "asset_ticker_group_id": "crypto-majors",
        },
        {
            "time_index": snapshot_time,
            "unique_identifier": normalized_openfigi["unique_identifier"],
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
