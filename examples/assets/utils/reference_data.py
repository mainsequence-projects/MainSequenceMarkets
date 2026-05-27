from __future__ import annotations

EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX = "example-asset-"
EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER = f"{EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX}btc"
EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER = f"{EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX}eth"

EXAMPLE_CRYPTO_ASSET_TYPE = {
    "asset_type": "crypto",
    "display_name": "Crypto",
    "description": "Crypto spot and token assets used by the asset examples.",
    "metadata_json": {"source": "examples/assets/utils/reference_data.py"},
}
EXAMPLE_EQUITY_ASSET_TYPE = {
    "asset_type": "equity",
    "display_name": "Equity",
    "description": "Listed equity assets resolved through OpenFIGI.",
    "metadata_json": {"source": "examples/assets/utils/reference_data.py"},
}
EXAMPLE_CURRENCY_ASSET_TYPE = {
    "asset_type": "currency",
    "display_name": "Currency",
    "description": "Single currency assets used as base or quote legs.",
    "metadata_json": {"source": "examples/assets/utils/reference_data.py"},
}

EXAMPLE_BTC_ASSET = {
    "unique_identifier": EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER,
    "asset_type": "crypto",
}
EXAMPLE_ETH_ASSET = {
    "unique_identifier": EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER,
    "asset_type": "crypto",
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
        "asset_type": "currency",
    },
    {
        "unique_identifier": EXAMPLE_USD_CURRENCY["code"],
        "asset_type": "currency",
    },
]

EXAMPLE_ASSET_CATEGORY = {
    "unique_identifier": "example-category-cross-asset-watchlist",
    "display_name": "Example Cross-Asset Watchlist",
    "description": (
        "Temporary category used to demonstrate membership changes across the "
        "shared asset examples."
    ),
    "metadata_json": {"source": "examples/assets/utils/reference_data.py"},
}

EXAMPLE_OPENFIGI_EQUITY_FIGI = "BBG00FNFPQH4"
EXAMPLE_EURUSD_OPENFIGI_FIGI = "BBG0013HGRV5"

__all__ = [
    "EXAMPLE_ASSET_CATEGORY",
    "EXAMPLE_ASSET_UNIQUE_IDENTIFIER_PREFIX",
    "EXAMPLE_BTC_ASSET",
    "EXAMPLE_BTC_ASSET_UNIQUE_IDENTIFIER",
    "EXAMPLE_CRYPTO_ASSETS",
    "EXAMPLE_CRYPTO_ASSET_TYPE",
    "EXAMPLE_CURRENCIES",
    "EXAMPLE_CURRENCY_ASSETS",
    "EXAMPLE_CURRENCY_ASSET_TYPE",
    "EXAMPLE_EQUITY_ASSET_TYPE",
    "EXAMPLE_ETH_ASSET",
    "EXAMPLE_ETH_ASSET_UNIQUE_IDENTIFIER",
    "EXAMPLE_EURUSD_OPENFIGI_FIGI",
    "EXAMPLE_EUR_CURRENCY",
    "EXAMPLE_OPENFIGI_EQUITY_FIGI",
    "EXAMPLE_USD_CURRENCY",
]
