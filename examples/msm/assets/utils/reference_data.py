from __future__ import annotations

from msm.constants import (
    ASSET_TYPE_CRYPTO,
    ASSET_TYPE_CRYPTO_DEFINITION,
    ASSET_TYPE_CURRENCY,
    ASSET_TYPE_CURRENCY_DEFINITION,
    ASSET_TYPE_EQUITY_DEFINITION,
)

EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX = "example-asset-"
EXAMPLE_BTC_TICKER = "BTC"
EXAMPLE_ETH_TICKER = "ETH"
EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER = f"{EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX}btc"
EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER = f"{EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX}eth"

EXAMPLE_CRYPTO_ASSET_TYPE = {
    **ASSET_TYPE_CRYPTO_DEFINITION.as_payload(),
    "metadata_json": {"source": "examples/msm/assets/utils/reference_data.py"},
}
EXAMPLE_EQUITY_ASSET_TYPE = {
    **ASSET_TYPE_EQUITY_DEFINITION.as_payload(),
    "metadata_json": {"source": "examples/msm/assets/utils/reference_data.py"},
}
EXAMPLE_CURRENCY_ASSET_TYPE = {
    **ASSET_TYPE_CURRENCY_DEFINITION.as_payload(),
    "metadata_json": {"source": "examples/msm/assets/utils/reference_data.py"},
}

EXAMPLE_BTC_ASSET = {
    "unique_identifier": EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
    "asset_type": ASSET_TYPE_CRYPTO,
}
EXAMPLE_ETH_ASSET = {
    "unique_identifier": EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
    "asset_type": ASSET_TYPE_CRYPTO,
}
EXAMPLE_CRYPTO_ASSETS = [
    EXAMPLE_BTC_ASSET,
    EXAMPLE_ETH_ASSET,
]

EXAMPLE_EUR_CURRENCY = {
    "code": "EUR",
    "currency_name": "Euro",
}
EXAMPLE_USD_CURRENCY = {
    "code": "USD",
    "currency_name": "US Dollar",
}
EXAMPLE_CURRENCIES = [
    EXAMPLE_EUR_CURRENCY,
    EXAMPLE_USD_CURRENCY,
]
EXAMPLE_CURRENCY_ASSETS = [
    {
        "unique_identifier": EXAMPLE_EUR_CURRENCY["code"],
        "asset_type": ASSET_TYPE_CURRENCY,
    },
    {
        "unique_identifier": EXAMPLE_USD_CURRENCY["code"],
        "asset_type": ASSET_TYPE_CURRENCY,
    },
]

EXAMPLE_ASSET_CATEGORY = {
    "unique_identifier": "example-category-cross-asset-watchlist",
    "display_name": "Example Cross-Asset Watchlist",
    "description": (
        "Temporary category used to demonstrate membership changes across the "
        "shared asset examples."
    ),
    "metadata_json": {"source": "examples/msm/assets/utils/reference_data.py"},
}

EXAMPLE_OPENFIGI_EQUITY_FIGI = "BBG00FNFPQH4"
EXAMPLE_EURUSD_OPENFIGI_FIGI = "BBG0013HGRV5"

__all__ = [
    "EXAMPLE_ASSET_CATEGORY",
    "EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX",
    "EXAMPLE_BTC_ASSET",
    "EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER",
    "EXAMPLE_BTC_TICKER",
    "EXAMPLE_CRYPTO_ASSETS",
    "EXAMPLE_CRYPTO_ASSET_TYPE",
    "EXAMPLE_CURRENCIES",
    "EXAMPLE_CURRENCY_ASSETS",
    "EXAMPLE_CURRENCY_ASSET_TYPE",
    "EXAMPLE_EQUITY_ASSET_TYPE",
    "EXAMPLE_ETH_ASSET",
    "EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER",
    "EXAMPLE_ETH_TICKER",
    "EXAMPLE_EURUSD_OPENFIGI_FIGI",
    "EXAMPLE_EUR_CURRENCY",
    "EXAMPLE_OPENFIGI_EQUITY_FIGI",
    "EXAMPLE_USD_CURRENCY",
]
