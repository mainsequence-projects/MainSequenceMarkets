from __future__ import annotations

from msm.repositories import MarketsRepositoryContext
from msm.services import (
    create_asset_category,
    replace_asset_category_memberships,
    upsert_asset,
)


def create_crypto_category(context: MarketsRepositoryContext) -> None:
    """Create assets and a category through MetaTable-backed services."""

    btc = upsert_asset(
        context,
        unique_identifier="BTC",
        asset_type="crypto",
        metadata_json={"ticker": "BTC", "name": "Bitcoin", "calendar": "24/7"},
    )
    eth = upsert_asset(
        context,
        unique_identifier="ETH",
        asset_type="crypto",
        metadata_json={"ticker": "ETH", "name": "Ethereum", "calendar": "24/7"},
    )
    category = create_asset_category(
        context,
        unique_identifier="crypto-majors",
        display_name="Crypto Majors",
        description="Large crypto assets used by example portfolios.",
    )
    replace_asset_category_memberships(
        context,
        category_uid=_uid(category),
        asset_uids=[_uid(btc), _uid(eth)],
    )


def _uid(result: dict) -> str:
    if "uid" in result:
        return str(result["uid"])
    for key in ("row", "data"):
        row = result.get(key)
        if isinstance(row, dict) and "uid" in row:
            return str(row["uid"])
    rows = result.get("rows") or result.get("results")
    if isinstance(rows, list) and rows and "uid" in rows[0]:
        return str(rows[0]["uid"])
    raise KeyError("Could not resolve uid from MetaTable operation result.")
