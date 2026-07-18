from __future__ import annotations

from msm import (
    ASSET_TYPE_BOND,
    ASSET_TYPE_CRYPTO,
    ASSET_TYPE_CURRENCY,
    ASSET_TYPE_CURRENCY_SPOT,
    ASSET_TYPE_EQUITY,
    ASSET_TYPE_FUTURE,
    INDEX_TYPE_CRYPTO,
    INDEX_TYPE_DERIVED,
    INDEX_TYPE_EQUITY,
    INDEX_TYPE_INTEREST_RATE,
)
from msm.api.assets import (
    BOND_ASSET_TYPE,
    CRYPTO_ASSET_TYPE,
    CURRENCY_ASSET_TYPE,
    CURRENCY_SPOT_ASSET_TYPE,
    EQUITY_ASSET_TYPE,
)
from msm.api.derivatives import FUTURE_ASSET_TYPE
from msm.constants import (
    ASSET_TYPE_BOND_DEFINITION,
    ASSET_TYPE_CRYPTO_DEFINITION,
    BUILT_IN_ASSET_TYPE_DEFINITIONS,
    BUILT_IN_ASSET_TYPES,
    BUILT_IN_INDEX_TYPE_DEFINITIONS,
    BUILT_IN_INDEX_TYPES,
    INDEX_TYPE_CRYPTO_DEFINITION,
    INDEX_TYPE_DERIVED_DEFINITION,
    INDEX_TYPE_EQUITY_DEFINITION,
    INDEX_TYPE_INTEREST_RATE_DEFINITION,
)


def test_asset_type_constants_are_canonical_values() -> None:
    assert ASSET_TYPE_CURRENCY == "currency"
    assert ASSET_TYPE_CURRENCY_SPOT == "currency_spot"
    assert ASSET_TYPE_BOND == "bond"
    assert ASSET_TYPE_FUTURE == "future"
    assert ASSET_TYPE_CRYPTO == "crypto"
    assert ASSET_TYPE_EQUITY == "equity"
    assert BUILT_IN_ASSET_TYPES == (
        "currency",
        "currency_spot",
        "bond",
        "future",
        "crypto",
        "equity",
    )
    assert INDEX_TYPE_INTEREST_RATE == "interest_rate"
    assert INDEX_TYPE_EQUITY == "equity"
    assert INDEX_TYPE_CRYPTO == "crypto"
    assert INDEX_TYPE_DERIVED == "derived"
    assert BUILT_IN_INDEX_TYPES == ("interest_rate", "equity", "crypto", "derived")


def test_legacy_api_asset_type_names_alias_static_constants() -> None:
    assert CURRENCY_ASSET_TYPE == ASSET_TYPE_CURRENCY
    assert CURRENCY_SPOT_ASSET_TYPE == ASSET_TYPE_CURRENCY_SPOT
    assert BOND_ASSET_TYPE == ASSET_TYPE_BOND
    assert FUTURE_ASSET_TYPE == ASSET_TYPE_FUTURE
    assert CRYPTO_ASSET_TYPE == ASSET_TYPE_CRYPTO
    assert EQUITY_ASSET_TYPE == ASSET_TYPE_EQUITY


def test_asset_type_definitions_build_upsert_payloads() -> None:
    assert ASSET_TYPE_BOND_DEFINITION.as_payload() == {
        "asset_type": "bond",
        "display_name": "Bond",
        "description": "Debt instruments represented as tradable assets.",
    }
    assert ASSET_TYPE_CRYPTO_DEFINITION.as_payload() == {
        "asset_type": "crypto",
        "display_name": "Crypto",
        "description": "Crypto spot and token assets used by the asset examples.",
    }
    assert [definition.asset_type for definition in BUILT_IN_ASSET_TYPE_DEFINITIONS] == [
        "currency",
        "currency_spot",
        "bond",
        "future",
        "crypto",
        "equity",
    ]


def test_index_type_definitions_build_upsert_payloads() -> None:
    assert INDEX_TYPE_INTEREST_RATE_DEFINITION.as_payload() == {
        "index_type": "interest_rate",
        "display_name": "Interest Rate",
        "description": (
            "Interest-rate indexes used for fixings, curves, swaps, and floating-rate bonds."
        ),
    }
    assert INDEX_TYPE_EQUITY_DEFINITION.as_payload() == {
        "index_type": "equity",
        "display_name": "Equity",
        "description": "Equity and equity-index references used as derivative underlyings.",
    }
    assert INDEX_TYPE_CRYPTO_DEFINITION.as_payload() == {
        "index_type": "crypto",
        "display_name": "Crypto",
        "description": "Crypto venue reference indexes used as derivative underlyings.",
    }
    assert INDEX_TYPE_DERIVED_DEFINITION.as_payload() == {
        "index_type": "derived",
        "display_name": "Derived",
        "description": (
            "Calculated market indexes with an owned, versioned methodology and canonical "
            "published value history."
        ),
    }
    assert [definition.index_type for definition in BUILT_IN_INDEX_TYPE_DEFINITIONS] == [
        "interest_rate",
        "equity",
        "crypto",
        "derived",
    ]
