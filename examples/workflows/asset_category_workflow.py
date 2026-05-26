from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_AUTO_REGISTER_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_AUTO_REGISTER_ENV, EXAMPLE_METATABLE_NAMESPACE)


def create_crypto_category() -> dict:
    """Create assets and a category through the public typed row API."""

    from msm.api.assets import Asset, AssetCategory

    btc = Asset.upsert(
        unique_identifier="BTC",
        asset_type="crypto",
    )
    eth = Asset.upsert(
        unique_identifier="ETH",
        asset_type="crypto",
    )
    category = AssetCategory.upsert(
        unique_identifier="crypto-majors",
        display_name="Crypto Majors",
        description="Large crypto assets used by example portfolios.",
    )
    memberships = AssetCategory.replace_memberships(
        category_uid=category.uid,
        asset_uids=[btc.uid, eth.uid],
    )
    return {
        "assets": [btc, eth],
        "category": category,
        "memberships": memberships,
    }


def main() -> None:
    result = create_crypto_category()
    print(result)


if __name__ == "__main__":
    main()
