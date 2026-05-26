from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

import msm

from examples.platform.bootstrap import EXAMPLE_METATABLE_NAMESPACE

if TYPE_CHECKING:
    from msm.repositories.base import MarketsRepositoryContext


def create_crypto_category(context: "MarketsRepositoryContext") -> None:
    """Create assets and a category through MetaTable-backed services."""

    from msm.services import (
        create_asset_category,
        replace_asset_category_memberships,
        upsert_asset,
    )

    btc = upsert_asset(
        context,
        unique_identifier="BTC",
        asset_type="crypto",
    )
    eth = upsert_asset(
        context,
        unique_identifier="ETH",
        asset_type="crypto",
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


def main() -> None:
    runtime = msm.create_schemas(namespace=EXAMPLE_METATABLE_NAMESPACE)
    context = runtime.context
    create_crypto_category(context)


if __name__ == "__main__":
    main()
