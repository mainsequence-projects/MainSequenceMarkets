from __future__ import annotations

import datetime as dt
from typing import Any

from examples.assets.utils import EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER, EXAMPLE_BTC_TICKER

EXAMPLE_ACCOUNT_HOLDINGS_SOURCE = "examples/accounts/create_and_insert_holdings.py"

EXAMPLE_ACCOUNT = {
    "unique_identifier": "example-holdings-account",
    "account_name": "Example Holdings Account",
    "is_paper": True,
    "account_is_active": True,
    "metadata_json": {"source": EXAMPLE_ACCOUNT_HOLDINGS_SOURCE},
}


def example_account_holdings_positions(
    *,
    target_trade_time: dt.datetime,
) -> list[dict[str, Any]]:
    return [
        {
            "unique_identifier": EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
            "quantity": 10.0,
            "target_trade_time": target_trade_time,
            "extra_details": {"ticker": EXAMPLE_BTC_TICKER},
        }
    ]


__all__ = [
    "EXAMPLE_ACCOUNT",
    "EXAMPLE_ACCOUNT_HOLDINGS_SOURCE",
    "example_account_holdings_positions",
]
