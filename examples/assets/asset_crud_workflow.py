from __future__ import annotations

from typing import TYPE_CHECKING, Any

from examples.platform.bootstrap import start_examples_runtime

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


def create_query_delete_assets(context: "MarketsRepositoryContext") -> dict[str, Any]:
    """Create temporary custom assets, query them, then delete one."""

    from msm.services import (
        delete_asset,
        get_asset_by_uid,
        get_asset_by_unique_identifier,
        search_assets,
        upsert_asset,
    )

    created_assets = [upsert_asset(context, **payload) for payload in EXAMPLE_ASSETS]

    btc_by_identifier = get_asset_by_unique_identifier(
        context,
        unique_identifier="example-asset-btc",
    )
    btc_uid = _uid(btc_by_identifier)

    btc_by_uid = get_asset_by_uid(context, uid=btc_uid)
    crypto_examples = search_assets(
        context,
        unique_identifier_contains="example-asset-",
        asset_type="crypto",
        limit=20,
    )
    deleted_btc = delete_asset(context, uid=btc_uid)

    return {
        "created_assets": created_assets,
        "btc_by_identifier": btc_by_identifier,
        "btc_by_uid": btc_by_uid,
        "crypto_examples": crypto_examples,
        "deleted_btc": deleted_btc,
    }


def _uid(result: dict[str, Any]) -> str:
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
    runtime = start_examples_runtime(
        labels=["asset-crud-example"],
    )
    result = create_query_delete_assets(runtime.context)
    print(result)


if __name__ == "__main__":
    main()
