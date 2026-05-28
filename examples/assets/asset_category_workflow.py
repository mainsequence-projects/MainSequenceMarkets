from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)
from examples.assets.utils import (
    EXAMPLE_ASSET_CATEGORY,
    EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX,
    EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_CRYPTO_ASSETS,
    EXAMPLE_CRYPTO_ASSET_TYPE,
    EXAMPLE_CURRENCY_ASSETS,
    EXAMPLE_CURRENCY_ASSET_TYPE,
    EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_EUR_CURRENCY,
    EXAMPLE_USD_CURRENCY,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm


def run_asset_category_workflow(*, delete_temporary_assets: bool = False) -> dict[str, Any]:
    """Create a category, add and remove assets, and print membership changes."""

    msm.start_engine(
        models=["AssetType", "Asset", "AssetCategory", "AssetCategoryMembership"],
    )

    from msm.api.assets import Asset, AssetCategory, AssetCategoryMembership, AssetType

    AssetType.upsert(**EXAMPLE_CRYPTO_ASSET_TYPE)
    AssetType.upsert(**EXAMPLE_CURRENCY_ASSET_TYPE)
    assets = [
        Asset.upsert(**payload)
        for payload in [
            *EXAMPLE_CRYPTO_ASSETS,
            *EXAMPLE_CURRENCY_ASSETS,
        ]
    ]
    assets_by_identifier = {asset.unique_identifier: asset for asset in assets}

    category = AssetCategory.upsert(**EXAMPLE_ASSET_CATEGORY)
    AssetCategory.replace_memberships(
        category_uid=category.uid,
        asset_uids=[assets_by_identifier[EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER].uid],
    )

    stages: list[dict[str, Any]] = []
    stages.append(_record_category_assets("created category with BTC", category))

    _add_category_assets(
        category_uid=category.uid,
        asset_uids=[
            assets_by_identifier[EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER].uid,
        ],
    )
    stages.append(_record_category_assets("added shared ETH asset", category))

    _add_category_assets(
        category_uid=category.uid,
        asset_uids=[
            assets_by_identifier[EXAMPLE_EUR_CURRENCY["code"]].uid,
            assets_by_identifier[EXAMPLE_USD_CURRENCY["code"]].uid,
        ],
    )
    stages.append(_record_category_assets("added shared currency assets", category))

    _remove_category_assets(
        category_uid=category.uid,
        asset_uids=[
            assets_by_identifier[EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER].uid,
            assets_by_identifier[EXAMPLE_USD_CURRENCY["code"]].uid,
        ],
    )
    stages.append(_record_category_assets("removed ETH and USD", category))

    deleted: dict[str, Any] = {"category": None, "assets": []}
    if delete_temporary_assets:
        AssetCategory.replace_memberships(category_uid=category.uid, asset_uids=[])
        deleted = {
            "category": AssetCategory.delete(category.uid),
            "assets": [
                Asset.delete(asset.uid)
                for asset in assets
                if asset.unique_identifier.startswith(EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX)
            ],
        }

    return {
        "category": category,
        "assets": assets,
        "stages": stages,
        "deleted": deleted,
        "membership_row_model": AssetCategoryMembership.__name__,
    }


def _add_category_assets(*, category_uid: Any, asset_uids: list[Any]) -> None:
    from msm.api.assets import AssetCategoryMembership

    for asset_uid in asset_uids:
        AssetCategoryMembership.upsert(category_uid=category_uid, asset_uid=asset_uid)


def _remove_category_assets(*, category_uid: Any, asset_uids: list[Any]) -> None:
    from msm.api.assets import AssetCategoryMembership

    for asset_uid in asset_uids:
        memberships = AssetCategoryMembership.filter(
            category_uid=category_uid,
            asset_uid=asset_uid,
            limit=10,
        )
        for membership in memberships:
            AssetCategoryMembership.delete(membership.uid)


def _category_assets(category_uid: Any):
    from msm.api.assets import Asset, AssetCategoryMembership

    memberships = AssetCategoryMembership.filter(category_uid=category_uid, limit=500)
    assets = []
    for membership in memberships:
        asset = Asset.get_by_uid(membership.asset_uid)
        if asset is not None:
            assets.append(asset)
    return sorted(assets, key=lambda asset: asset.unique_identifier)


def _record_category_assets(label: str, category) -> dict[str, Any]:
    assets = _category_assets(category.uid)
    asset_identifiers = [asset.unique_identifier for asset in assets]
    print(
        f"{label}: {category.unique_identifier} -> {asset_identifiers if asset_identifiers else []}"
    )
    return {
        "label": label,
        "category_uid": category.uid,
        "asset_unique_identifiers": asset_identifiers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--delete-temporary-assets",
        action="store_true",
        help="Delete the temporary example category and custom assets after the workflow.",
    )
    args = parser.parse_args()
    run_asset_category_workflow(delete_temporary_assets=args.delete_temporary_assets)


if __name__ == "__main__":
    main()
