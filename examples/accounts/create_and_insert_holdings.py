from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.accounts.utils import (
    EXAMPLE_ACCOUNT,
    example_account_holdings_positions,
)
from examples.assets.utils import EXAMPLE_BTC_ASSET, EXAMPLE_CRYPTO_ASSET_TYPE

import msm


def create_and_insert_account_holdings() -> dict[str, Any]:
    """Create an account, reuse the shared BTC asset, and publish holdings."""

    msm.start_engine(
        models=["AssetType", "Asset", "Account"],
    )

    from msm.api.accounts import Account
    from msm.api.assets import Asset, AssetType
    from msm.data_nodes.accounts import AccountHoldings

    asset_type = AssetType.upsert(**EXAMPLE_CRYPTO_ASSET_TYPE)
    asset = Asset.upsert(**EXAMPLE_BTC_ASSET)
    account = Account.upsert(**EXAMPLE_ACCOUNT)

    holdings_node = AccountHoldings(config=AccountHoldings.default_config())

    holdings_date = dt.datetime.now(dt.UTC).replace(microsecond=0)
    holdings_node.set_account_holdings_frame(
        holdings_date=holdings_date,
        account_uid=account.uid,
        positions=example_account_holdings_positions(target_trade_time=holdings_date),
    )
    updated_frame = holdings_node.run(debug_mode=True, force_update=True)
    pretty_positions = account.pretty_print_positions(updated_frame)

    return {
        "asset_type": asset_type,
        "asset": asset,
        "account": account,
        "holdings_data_node_identifier": holdings_node._default_identifier(),
        "holdings_date": holdings_date,
        "pretty_positions": pretty_positions,
        "updated_frame": updated_frame,
    }


def main() -> None:
    result = create_and_insert_account_holdings()
    print("Account UID:", result["account"].uid)
    print("Asset unique_identifier:", result["asset"].unique_identifier)
    print("Holdings DataNode identifier:", result["holdings_data_node_identifier"])
    print("Holdings date:", result["holdings_date"].isoformat())


if __name__ == "__main__":
    main()
