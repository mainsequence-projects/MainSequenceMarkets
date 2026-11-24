from __future__ import annotations

from typing import TYPE_CHECKING, Any

from msm.distribution import package_version
from msm.constants import (
    ASSET_TYPE_BOND,
    ASSET_TYPE_CRYPTO,
    ASSET_TYPE_CURRENCY,
    ASSET_TYPE_CURRENCY_SPOT,
    ASSET_TYPE_EQUITY,
    ASSET_TYPE_FUTURE,
    BOND_ASSET_TYPE,
    BUILT_IN_ASSET_TYPE_DEFINITIONS,
    BUILT_IN_ASSET_TYPES,
    BUILT_IN_INDEX_TYPE_DEFINITIONS,
    BUILT_IN_INDEX_TYPES,
    CRYPTO_ASSET_TYPE,
    CURRENCY_ASSET_TYPE,
    CURRENCY_SPOT_ASSET_TYPE,
    EQUITY_ASSET_TYPE,
    EVENT_TYPE_COUPON,
    EVENT_TYPE_DIVIDEND,
    EVENT_TYPE_EXPIRY,
    EVENT_TYPE_REDEMPTION,
    EVENT_TYPE_SPLIT,
    FUTURE_ASSET_TYPE,
    INDEX_TYPE_CRYPTO,
    INDEX_TYPE_CRYPTO_DEFINITION,
    INDEX_TYPE_EQUITY,
    INDEX_TYPE_EQUITY_DEFINITION,
    INDEX_TYPE_DERIVED,
    INDEX_TYPE_DERIVED_DEFINITION,
    INDEX_TYPE_INTEREST_RATE,
    INDEX_TYPE_INTEREST_RATE_DEFINITION,
)

if TYPE_CHECKING:
    from msm.bootstrap import start_engine

__version__ = package_version()


def __getattr__(name: str) -> Any:
    # `start_engine` loads MetaTables, SQLAlchemy and the SDK; importing `msm`
    # or one of its light modules (constants, settings) does not.
    if name == "start_engine":
        from msm.bootstrap import start_engine

        return start_engine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "__version__",
    "ASSET_TYPE_BOND",
    "ASSET_TYPE_CRYPTO",
    "ASSET_TYPE_CURRENCY",
    "ASSET_TYPE_CURRENCY_SPOT",
    "ASSET_TYPE_EQUITY",
    "ASSET_TYPE_FUTURE",
    "BOND_ASSET_TYPE",
    "BUILT_IN_ASSET_TYPE_DEFINITIONS",
    "BUILT_IN_ASSET_TYPES",
    "BUILT_IN_INDEX_TYPE_DEFINITIONS",
    "BUILT_IN_INDEX_TYPES",
    "CRYPTO_ASSET_TYPE",
    "CURRENCY_ASSET_TYPE",
    "CURRENCY_SPOT_ASSET_TYPE",
    "EQUITY_ASSET_TYPE",
    "EVENT_TYPE_COUPON",
    "EVENT_TYPE_DIVIDEND",
    "EVENT_TYPE_EXPIRY",
    "EVENT_TYPE_REDEMPTION",
    "EVENT_TYPE_SPLIT",
    "FUTURE_ASSET_TYPE",
    "INDEX_TYPE_CRYPTO",
    "INDEX_TYPE_CRYPTO_DEFINITION",
    "INDEX_TYPE_EQUITY",
    "INDEX_TYPE_EQUITY_DEFINITION",
    "INDEX_TYPE_DERIVED",
    "INDEX_TYPE_DERIVED_DEFINITION",
    "INDEX_TYPE_INTEREST_RATE",
    "INDEX_TYPE_INTEREST_RATE_DEFINITION",
    "api",
    "time_index",
    "models",
    "portfolios",
    "services",
    "start_engine",
]
