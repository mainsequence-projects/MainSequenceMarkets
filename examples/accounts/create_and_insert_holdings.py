from __future__ import annotations

import datetime as dt
import os
import sys
from decimal import Decimal
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm

ACCOUNT_UNIQUE_IDENTIFIER = os.getenv(
    "MAINSEQUENCE_EXAMPLE_ACCOUNT_UNIQUE_IDENTIFIER",
    "example-holdings-account",
)
ASSET_UNIQUE_IDENTIFIER = os.getenv(
    "MAINSEQUENCE_EXAMPLE_ASSET_UNIQUE_IDENTIFIER",
    "example-holdings-btc",
)
HASH_NAMESPACE = os.getenv("MAINSEQUENCE_EXAMPLE_HASH_NAMESPACE", "account_holdings_example")
DATA_NODE_IDENTIFIER = os.getenv(
    "MAINSEQUENCE_EXAMPLE_DATA_NODE_IDENTIFIER",
    "examples.markets.accounts.account_holdings",
)


def main() -> None:
    msm.start_engine(
        models=["Asset", "Account"],
    )

    from msm.api.accounts import Account
    from msm.api.assets import Asset
    from msm.accounts import AccountHoldings

    asset = Asset.upsert(
        unique_identifier=ASSET_UNIQUE_IDENTIFIER,
        asset_type="crypto",
    )
    account = Account.upsert(
        unique_identifier=ACCOUNT_UNIQUE_IDENTIFIER,
        account_name="SDK Example Account",
        is_paper=True,
    )

    holdings_config = AccountHoldings.default_config(
        identifier=DATA_NODE_IDENTIFIER,
    )
    holdings_node = AccountHoldings(
        config=holdings_config,
        hash_namespace=HASH_NAMESPACE,
    )

    holdings_date = dt.datetime.now(dt.UTC).replace(microsecond=0)
    holdings_node.set_account_holdings_frame(
        holdings_date=holdings_date,
        account_uid=account.uid,
        positions=[
            {
                "unique_identifier": asset.unique_identifier,
                "quantity": Decimal("10.0"),
                "target_trade_time": holdings_date,
                "extra_details": {"source": "sdk-example"},
            }
        ],
    )
    updated_frame = holdings_node.run(debug_mode=True, force_update=True)

    print("Account UID:", account.uid)
    print("Asset unique_identifier:", asset.unique_identifier)
    print("Holdings data node identifier:", DATA_NODE_IDENTIFIER)
    print("Holdings date:", holdings_date.isoformat())
    print(updated_frame)


if __name__ == "__main__":
    main()
