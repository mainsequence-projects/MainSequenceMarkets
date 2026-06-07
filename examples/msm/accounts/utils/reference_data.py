from __future__ import annotations

import datetime as dt
from typing import Any

from examples.msm.assets.utils import (
    EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_BTC_TICKER,
    EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
    EXAMPLE_ETH_TICKER,
)

EXAMPLE_ACCOUNT_WORKFLOW_SOURCE = "examples/msm/accounts/account_portfolio_full_workflow.py"

EXAMPLE_ACCOUNT_MODEL_PORTFOLIO = {
    "model_portfolio_name": "Example Balanced Account Model",
    "model_portfolio_description": (
        "Example reusable account-level model portfolio tracked by multiple accounts."
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

EXAMPLE_ACCOUNT_TARGET_PORTFOLIO = {
    "unique_identifier": "example-account-target",
    "display_name": "Example Account Target",
    "is_active": True,
    "source": EXAMPLE_ACCOUNT_WORKFLOW_SOURCE,
    "metadata_json": {"source": EXAMPLE_ACCOUNT_WORKFLOW_SOURCE},
}

EXAMPLE_ACCOUNT_TARGET_SLEEVE_PORTFOLIO = {
    "unique_identifier": "example-account-target-sleeve",
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
    asset_uid: Any,
    portfolio_uid: Any,
) -> list[dict[str, Any]]:
    return [
        {
            "asset_uid": asset_uid,
            "weight_notional_exposure": 0.6,
        },
        {
            "portfolio_uid": portfolio_uid,
            "weight_notional_exposure": 0.4,
            "metadata_json": {"portfolio_role": "satellite_sleeve"},
        },
    ]


__all__ = [
    "EXAMPLE_ACCOUNTS",
    "EXAMPLE_ACCOUNT_GROUP",
    "EXAMPLE_ACCOUNT_WORKFLOW_SOURCE",
    "EXAMPLE_ACCOUNT_MODEL_PORTFOLIO",
    "EXAMPLE_ACCOUNT_TARGET_PORTFOLIO",
    "EXAMPLE_ACCOUNT_TARGET_SLEEVE_PORTFOLIO",
    "example_account_holdings_positions",
    "example_account_target_positions",
]
