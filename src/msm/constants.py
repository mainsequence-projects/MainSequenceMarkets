from __future__ import annotations

from typing import Any, Final, NamedTuple


class AssetTypeDefinition(NamedTuple):
    """Static definition for a built-in asset type key.

    ``event_types`` are the events an asset of the type can have (ADR 0065): on
    unadjusted prices, a portfolio's ledger must book each of them.
    """

    asset_type: str
    display_name: str
    description: str
    event_types: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        """Return a mutable payload suitable for ``AssetType.upsert(...)``."""

        return {
            "asset_type": self.asset_type,
            "display_name": self.display_name,
            "description": self.description,
            "event_types": list(self.event_types),
        }


class IndexTypeDefinition(NamedTuple):
    """Static definition for a built-in index type key."""

    index_type: str
    display_name: str
    description: str

    def as_payload(self) -> dict[str, str]:
        """Return a mutable payload suitable for ``IndexType.upsert(...)``."""

        return {
            "index_type": self.index_type,
            "display_name": self.display_name,
            "description": self.description,
        }


ASSET_TYPE_CURRENCY: Final[str] = "currency"
ASSET_TYPE_CURRENCY_SPOT: Final[str] = "currency_spot"
ASSET_TYPE_BOND: Final[str] = "bond"
ASSET_TYPE_FUTURE: Final[str] = "future"
ASSET_TYPE_CRYPTO: Final[str] = "crypto"
ASSET_TYPE_EQUITY: Final[str] = "equity"

# Events an asset can have (ADR 0065). An asset type lists those of its assets; a
# portfolio's lifecycle models, or adjusted prices, book them.
EVENT_TYPE_DIVIDEND: Final[str] = "dividend"
EVENT_TYPE_SPLIT: Final[str] = "split"
EVENT_TYPE_COUPON: Final[str] = "coupon"
EVENT_TYPE_REDEMPTION: Final[str] = "redemption"
EVENT_TYPE_EXPIRY: Final[str] = "expiry"
INDEX_TYPE_INTEREST_RATE: Final[str] = "interest_rate"
INDEX_TYPE_EQUITY: Final[str] = "equity"
INDEX_TYPE_CRYPTO: Final[str] = "crypto"
INDEX_TYPE_DERIVED: Final[str] = "derived"

# Compatibility aliases for the older API-module naming style.
CURRENCY_ASSET_TYPE: Final[str] = ASSET_TYPE_CURRENCY
CURRENCY_SPOT_ASSET_TYPE: Final[str] = ASSET_TYPE_CURRENCY_SPOT
BOND_ASSET_TYPE: Final[str] = ASSET_TYPE_BOND
FUTURE_ASSET_TYPE: Final[str] = ASSET_TYPE_FUTURE
CRYPTO_ASSET_TYPE: Final[str] = ASSET_TYPE_CRYPTO
EQUITY_ASSET_TYPE: Final[str] = ASSET_TYPE_EQUITY

ASSET_TYPE_CURRENCY_DEFINITION: Final[AssetTypeDefinition] = AssetTypeDefinition(
    asset_type=ASSET_TYPE_CURRENCY,
    display_name="Currency",
    description="Single currency assets used as denomination, base, or quote units.",
)
ASSET_TYPE_CURRENCY_SPOT_DEFINITION: Final[AssetTypeDefinition] = AssetTypeDefinition(
    asset_type=ASSET_TYPE_CURRENCY_SPOT,
    display_name="Currency Spot",
    description="Tradable currency spot pair asset.",
)
ASSET_TYPE_BOND_DEFINITION: Final[AssetTypeDefinition] = AssetTypeDefinition(
    asset_type=ASSET_TYPE_BOND,
    display_name="Bond",
    description="Debt instruments represented as tradable assets.",
    event_types=(EVENT_TYPE_COUPON, EVENT_TYPE_REDEMPTION),
)
ASSET_TYPE_FUTURE_DEFINITION: Final[AssetTypeDefinition] = AssetTypeDefinition(
    asset_type=ASSET_TYPE_FUTURE,
    display_name="Future",
    description="Futures contracts represented as tradable assets.",
    event_types=(EVENT_TYPE_EXPIRY,),
)
ASSET_TYPE_CRYPTO_DEFINITION: Final[AssetTypeDefinition] = AssetTypeDefinition(
    asset_type=ASSET_TYPE_CRYPTO,
    display_name="Crypto",
    description="Crypto spot and token assets used by the asset examples.",
)
ASSET_TYPE_EQUITY_DEFINITION: Final[AssetTypeDefinition] = AssetTypeDefinition(
    asset_type=ASSET_TYPE_EQUITY,
    display_name="Equity",
    description="Listed equity assets resolved through OpenFIGI.",
    event_types=(EVENT_TYPE_DIVIDEND, EVENT_TYPE_SPLIT),
)
INDEX_TYPE_INTEREST_RATE_DEFINITION: Final[IndexTypeDefinition] = IndexTypeDefinition(
    index_type=INDEX_TYPE_INTEREST_RATE,
    display_name="Interest Rate",
    description="Interest-rate indexes used for fixings, curves, swaps, and floating-rate bonds.",
)
INDEX_TYPE_EQUITY_DEFINITION: Final[IndexTypeDefinition] = IndexTypeDefinition(
    index_type=INDEX_TYPE_EQUITY,
    display_name="Equity",
    description="Equity and equity-index references used as derivative underlyings.",
)
INDEX_TYPE_CRYPTO_DEFINITION: Final[IndexTypeDefinition] = IndexTypeDefinition(
    index_type=INDEX_TYPE_CRYPTO,
    display_name="Crypto",
    description="Crypto venue reference indexes used as derivative underlyings.",
)
INDEX_TYPE_DERIVED_DEFINITION: Final[IndexTypeDefinition] = IndexTypeDefinition(
    index_type=INDEX_TYPE_DERIVED,
    display_name="Derived",
    description=(
        "Calculated market indexes with an owned, versioned methodology and canonical "
        "published value history."
    ),
)

BUILT_IN_ASSET_TYPE_DEFINITIONS: Final[tuple[AssetTypeDefinition, ...]] = (
    ASSET_TYPE_CURRENCY_DEFINITION,
    ASSET_TYPE_CURRENCY_SPOT_DEFINITION,
    ASSET_TYPE_BOND_DEFINITION,
    ASSET_TYPE_FUTURE_DEFINITION,
    ASSET_TYPE_CRYPTO_DEFINITION,
    ASSET_TYPE_EQUITY_DEFINITION,
)
BUILT_IN_ASSET_TYPES: Final[tuple[str, ...]] = tuple(
    definition.asset_type for definition in BUILT_IN_ASSET_TYPE_DEFINITIONS
)
BUILT_IN_INDEX_TYPE_DEFINITIONS: Final[tuple[IndexTypeDefinition, ...]] = (
    INDEX_TYPE_INTEREST_RATE_DEFINITION,
    INDEX_TYPE_EQUITY_DEFINITION,
    INDEX_TYPE_CRYPTO_DEFINITION,
    INDEX_TYPE_DERIVED_DEFINITION,
)
BUILT_IN_INDEX_TYPES: Final[tuple[str, ...]] = tuple(
    definition.index_type for definition in BUILT_IN_INDEX_TYPE_DEFINITIONS
)


__all__ = [
    "ASSET_TYPE_BOND",
    "ASSET_TYPE_BOND_DEFINITION",
    "ASSET_TYPE_CURRENCY",
    "ASSET_TYPE_CURRENCY_DEFINITION",
    "ASSET_TYPE_CURRENCY_SPOT",
    "ASSET_TYPE_CURRENCY_SPOT_DEFINITION",
    "ASSET_TYPE_CRYPTO",
    "ASSET_TYPE_CRYPTO_DEFINITION",
    "ASSET_TYPE_EQUITY",
    "ASSET_TYPE_EQUITY_DEFINITION",
    "ASSET_TYPE_FUTURE",
    "ASSET_TYPE_FUTURE_DEFINITION",
    "AssetTypeDefinition",
    "EVENT_TYPE_COUPON",
    "EVENT_TYPE_DIVIDEND",
    "EVENT_TYPE_EXPIRY",
    "EVENT_TYPE_REDEMPTION",
    "EVENT_TYPE_SPLIT",
    "BOND_ASSET_TYPE",
    "BUILT_IN_ASSET_TYPE_DEFINITIONS",
    "BUILT_IN_ASSET_TYPES",
    "BUILT_IN_INDEX_TYPE_DEFINITIONS",
    "BUILT_IN_INDEX_TYPES",
    "CRYPTO_ASSET_TYPE",
    "CURRENCY_ASSET_TYPE",
    "CURRENCY_SPOT_ASSET_TYPE",
    "EQUITY_ASSET_TYPE",
    "FUTURE_ASSET_TYPE",
    "INDEX_TYPE_CRYPTO",
    "INDEX_TYPE_CRYPTO_DEFINITION",
    "INDEX_TYPE_EQUITY",
    "INDEX_TYPE_EQUITY_DEFINITION",
    "INDEX_TYPE_INTEREST_RATE",
    "INDEX_TYPE_INTEREST_RATE_DEFINITION",
    "INDEX_TYPE_DERIVED",
    "INDEX_TYPE_DERIVED_DEFINITION",
    "IndexTypeDefinition",
]
