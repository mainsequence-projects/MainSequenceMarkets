"""Pricing-owned SQLAlchemy MetaTable declarations."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AssetCurrentPricingDetailsTable": ".pricing_details",
    "CurveBuildingDetailsTable": ".curve_building_details",
    "CurveTable": ".curves",
    "IndexConventionDetailsTable": ".index_convention_details",
    "PricingMarketDataSetBindingTable": ".market_data_bindings",
    "PricingMarketDataSetCurveBindingTable": ".market_data_bindings",
    "PricingMarketDataSetTable": ".market_data_bindings",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "AssetCurrentPricingDetailsTable",
    "CurveBuildingDetailsTable",
    "CurveTable",
    "IndexConventionDetailsTable",
    "PricingMarketDataSetBindingTable",
    "PricingMarketDataSetCurveBindingTable",
    "PricingMarketDataSetTable",
]
