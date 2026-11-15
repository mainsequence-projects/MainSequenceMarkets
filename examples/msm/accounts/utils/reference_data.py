from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from examples.msm.assets.utils import (
    EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_BTC_TICKER,
    EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_ETH_TICKER,
)
from msm.time_index.accounts.constants import (
    TARGET_TYPE_ASSET,
    TARGET_TYPE_PORTFOLIO,
)

EXAMPLE_ACCOUNT_WORKFLOW_SOURCE = "examples/msm/accounts/account_portfolio_full_workflow.py"

EXAMPLE_ACCOUNT_ALLOCATION_MODEL = {
    "allocation_model_name": "Example Balanced Account Model",
    "allocation_model_description": (
        "Example reusable account-level allocation model tracked by multiple accounts."
    ),
    "metadata_json": {"source": EXAMPLE_ACCOUNT_WORKFLOW_SOURCE},
}

EXAMPLE_ACCOUNT_GROUP = {
    "group_name": "Example High Risk Accounts",
    "group_description": "Example grouping for accounts that share a risk bucket.",
    "metadata_json": {"source": EXAMPLE_ACCOUNT_WORKFLOW_SOURCE},
}

EXAMPLE_ACCOUNTS = [
    {
        "unique_identifier": "example-account-alpha",
        "account_name": "Example Account Alpha",
        "is_paper": True,
        "account_is_active": True,
        "metadata_json": {"source": EXAMPLE_ACCOUNT_WORKFLOW_SOURCE, "workflow_account": "alpha"},
    },
    {
        "unique_identifier": "example-account-beta",
        "account_name": "Example Account Beta",
        "is_paper": True,
        "account_is_active": True,
        "metadata_json": {"source": EXAMPLE_ACCOUNT_WORKFLOW_SOURCE, "workflow_account": "beta"},
    },
]

EXAMPLE_ACCOUNT_TARGET_ALLOCATION = {
    "unique_identifier": "example-account-target",
    "display_name": "Example Account Target",
    "is_active": True,
    "source": EXAMPLE_ACCOUNT_WORKFLOW_SOURCE,
    "metadata_json": {"source": EXAMPLE_ACCOUNT_WORKFLOW_SOURCE},
}

EXAMPLE_ACCOUNT_TARGET_SLEEVE_PORTFOLIO = {
    "unique_identifier": "example-account-target-sleeve",
}

EXAMPLE_ACCOUNT_PORTFOLIO_GROUP = {
    "unique_identifier": "example-account-target-sleeves",
    "display_name": "Example Account Target Sleeves",
    "description": "Example group for portfolio sleeves used by account target allocations.",
    "metadata_json": {"source": EXAMPLE_ACCOUNT_WORKFLOW_SOURCE},
}


def example_account_holdings_positions(
    *,
    target_trade_time: dt.datetime,
    btc_quantity: float,
    eth_quantity: float,
    eth_direction: int = 1,
) -> list[dict[str, Any]]:
    return [
        {
            "asset_identifier": EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
            "quantity": btc_quantity,
            "direction": 1,
            "target_trade_time": target_trade_time,
            "extra_details": {"ticker": EXAMPLE_BTC_TICKER, "name": "Bitcoin"},
        },
        {
            "asset_identifier": EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
            "quantity": eth_quantity,
            "direction": eth_direction,
            "target_trade_time": target_trade_time,
            "extra_details": {"ticker": EXAMPLE_ETH_TICKER, "name": "Ethereum"},
        },
    ]


def example_account_target_positions(
    *,
    direct_asset_uid: Any,
    direct_quantity: float,
    portfolio_uid: Any,
    basket: Mapping[Any, float],
    sizing: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return one account target in units (ADR 0052).

    One asset row is the direct target. The portfolio rows are the target sleeve's
    unit basket, one row per asset. ``sizing`` records how the caller sized the
    rows; ms-markets stores it and never reads it.
    """

    metadata = {"portfolio_role": "satellite_sleeve", **dict(sizing or {})}
    return [
        {
            "target_type": TARGET_TYPE_ASSET,
            "target_uid": direct_asset_uid,
            "asset_uid": direct_asset_uid,
            "quantity": direct_quantity,
            "direction": 1,
            "metadata_json": dict(sizing or {}),
        },
        *(
            {
                "target_type": TARGET_TYPE_PORTFOLIO,
                "target_uid": portfolio_uid,
                "portfolio_uid": portfolio_uid,
                "asset_uid": asset_uid,
                "quantity": quantity,
                "direction": 1,
                "metadata_json": metadata,
            }
            for asset_uid, quantity in basket.items()
        ),
    ]


__all__ = [
    "EXAMPLE_ACCOUNTS",
    "EXAMPLE_ACCOUNT_GROUP",
    "EXAMPLE_ACCOUNT_WORKFLOW_SOURCE",
    "EXAMPLE_ACCOUNT_ALLOCATION_MODEL",
    "EXAMPLE_ACCOUNT_TARGET_ALLOCATION",
    "EXAMPLE_ACCOUNT_TARGET_SLEEVE_PORTFOLIO",
    "EXAMPLE_ACCOUNT_PORTFOLIO_GROUP",
    "example_account_holdings_positions",
    "example_account_target_positions",
]
