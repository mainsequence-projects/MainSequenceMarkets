from __future__ import annotations

from typing import Final, NamedTuple


class AssetTypeDefinition(NamedTuple):
    """Static definition for a built-in asset type key."""

    asset_type: str
    display_name: str
    description: str

    def as_payload(self) -> dict[str, str]:
        """Return a mutable payload suitable for ``AssetType.upsert(...)``."""

        return {
            "asset_type": self.asset_type,
            "display_name": self.display_name,
            "description": self.description,
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
)
ASSET_TYPE_FUTURE_DEFINITION: Final[AssetTypeDefinition] = AssetTypeDefinition(
    asset_type=ASSET_TYPE_FUTURE,
    display_name="Future",
    description="Futures contracts represented as tradable assets.",
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
