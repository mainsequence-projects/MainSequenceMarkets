from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

import msm
from msm.api.assets import Asset

from examples.platform.bootstrap import EXAMPLE_METATABLE_NAMESPACE

if TYPE_CHECKING:
    from msm.repositories.base import MarketsRepositoryContext


EXAMPLE_ASSETS = [
    {
        "unique_identifier": "example-asset-btc",
        "asset_type": "crypto",
    },
    {
        "unique_identifier": "example-asset-eth",
        "asset_type": "crypto",
    },
]
EXAMPLE_OPENFIGI_RESULT = {
    "figi": "BBG00FNFPQH4",
    "name": "CEREBRAS SYSTEMS INC - A",
    "ticker": "CBRS",
    "exchCode": "US",
    "compositeFIGI": "BBG00FNFPQH4",
    "securityType": "Common Stock",
    "marketSector": "Equity",
    "shareClassFIGI": "BBG00FNFPQJ2",
    "securityType2": "Common Stock",
    "securityDescription": "CBRS",
}
EXAMPLE_ASSET_SNAPSHOT_IDENTIFIER = "examples.mainsequence.markets.asset_snapshots"


def create_query_assets(
    *,
    context: "MarketsRepositoryContext",
    delete_temporary_assets: bool = False,
) -> dict[str, Any]:
    """Create example assets, register FIGI details, write snapshots, and list them."""

    from msm.services import (
        create_openfigi_details,
        delete_asset,
        search_openfigi_details,
        update_asset_snapshot_frame,
    )
    from msm.services.assets.openfigi import normalize_openfigi_result

    created_assets = [Asset.upsert(**payload) for payload in EXAMPLE_ASSETS]
    openfigi_asset = Asset.upsert(
        unique_identifier=EXAMPLE_OPENFIGI_RESULT["figi"],
        asset_type="equity",
    )
    created_assets.append(openfigi_asset)

    btc_by_identifier = Asset.get_by_unique_identifier(
        unique_identifier="example-asset-btc",
    )
    if btc_by_identifier is None:
        raise RuntimeError("Expected example-asset-btc to exist after upsert.")

    btc_by_uid = Asset.get_by_uid(btc_by_identifier.uid)
    crypto_examples = Asset.filter(
        unique_identifier_contains="example-asset-",
        asset_type="crypto",
        limit=20,
    )
    normalized_openfigi = normalize_openfigi_result(EXAMPLE_OPENFIGI_RESULT)
    figi_details = _ensure_openfigi_details(
        context,
        asset_uid=str(openfigi_asset.uid),
        normalized_openfigi=normalized_openfigi,
        create_openfigi_details=create_openfigi_details,
        search_openfigi_details=search_openfigi_details,
    )
    snapshot_frame = update_asset_snapshot_frame(
        [
            {
                "unique_identifier": "example-asset-btc",
                "name": "Bitcoin",
                "ticker": "BTC",
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "crypto-majors",
                "venue_specific_properties": {"source": "example"},
            },
            {
                "unique_identifier": "example-asset-eth",
                "name": "Ethereum",
                "ticker": "ETH",
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "crypto-majors",
                "venue_specific_properties": {"source": "example"},
            },
            {
                "unique_identifier": normalized_openfigi["unique_identifier"],
                "name": normalized_openfigi["name"],
                "ticker": normalized_openfigi["ticker"],
                "exchange_code": normalized_openfigi["exchange_code"],
                "asset_ticker_group_id": normalized_openfigi["share_class"],
                "venue_specific_properties": {
                    "openfigi": {
                        key: value
                        for key, value in normalized_openfigi.items()
                        if key != "raw_payload"
                    }
                },
            },
        ],
        time_index=dt.datetime.now(dt.UTC),
        identifier=EXAMPLE_ASSET_SNAPSHOT_IDENTIFIER,
        hash_namespace="examples",
    )
    created_asset_listing = [
        Asset.get_by_unique_identifier(unique_identifier=payload["unique_identifier"])
        for payload in [
            *EXAMPLE_ASSETS,
            {"unique_identifier": EXAMPLE_OPENFIGI_RESULT["figi"]},
        ]
    ]
    deleted_assets = []
    if delete_temporary_assets:
        asset_table = msm.get_runtime().table("Asset")
        deleted_assets = [
            delete_asset(asset_table, uid=result.uid)
            for result in created_assets
            if result.unique_identifier.startswith("example-asset-")
        ]

    return {
        "created_assets": created_assets,
        "btc_by_identifier": btc_by_identifier,
        "btc_by_uid": btc_by_uid,
        "crypto_examples": crypto_examples,
        "openfigi_details": figi_details,
        "asset_snapshot_frame": snapshot_frame,
        "created_asset_listing": created_asset_listing,
        "deleted_assets": deleted_assets,
    }


def _ensure_openfigi_details(
    context: "MarketsRepositoryContext",
    *,
    asset_uid: str,
    normalized_openfigi: dict[str, Any],
    create_openfigi_details,
    search_openfigi_details,
) -> dict[str, Any]:
    existing = search_openfigi_details(
        context,
        figi=normalized_openfigi["figi"],
        limit=1,
    )
    if _rows(existing):
        return existing
    return create_openfigi_details(
        context,
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


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("rows", "results", "data"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        if isinstance(rows, dict):
            nested_rows = _rows(rows)
            return nested_rows or [rows]
    for key in ("row",):
        row = result.get(key)
        if isinstance(row, dict):
            return [row]
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--delete-temporary-assets",
        action="store_true",
        help="Delete only the temporary example-asset-* custom assets after listing them.",
    )
    args = parser.parse_args()
    runtime = Asset.create_schemas(
        namespace=EXAMPLE_METATABLE_NAMESPACE,
        models=["Asset", "OpenFigiDetails"],
    )
    result = create_query_assets(
        context=runtime.context,
        delete_temporary_assets=args.delete_temporary_assets,
    )
    print(result)


if __name__ == "__main__":
    main()
