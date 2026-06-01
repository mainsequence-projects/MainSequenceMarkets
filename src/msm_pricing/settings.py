from __future__ import annotations

from msm.settings import markets_data_node_identifier

PRICING_CONTEXT_DEFAULT = "default"
PRICING_CONTEXT_EOD = "eod"
PRICING_CONTEXT_LIVE = "live"
PRICING_CONTEXT_RISK_MANAGER = "risk_manager"

PRICING_CONCEPT_DISCOUNT_CURVES = "discount_curves"
PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS = "interest_rate_index_fixings"
PRICING_CONCEPT_EQUITY_VOL_CURVES = "equity_vol_curves"
PRICING_DEFAULT_DISCOUNT_CURVES_DATA_NODE_IDENTIFIER = "DiscountCurvesTS"
PRICING_DEFAULT_INDEX_FIXINGS_DATA_NODE_IDENTIFIER = "IndexFixingsTS"


def default_pricing_market_data_bindings(
    *,
    namespace: str | None = None,
) -> dict[str, str]:
    """Return built-in pricing concept to DataNode identifier bindings."""

    return {
        PRICING_CONCEPT_DISCOUNT_CURVES: markets_data_node_identifier(
            PRICING_DEFAULT_DISCOUNT_CURVES_DATA_NODE_IDENTIFIER,
            namespace=namespace,
        ),
        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: markets_data_node_identifier(
            PRICING_DEFAULT_INDEX_FIXINGS_DATA_NODE_IDENTIFIER,
            namespace=namespace,
        ),
    }


def default_pricing_market_data_identifier(
    concept_key: str,
    *,
    namespace: str | None = None,
) -> str | None:
    """Return the built-in DataNode identifier for a pricing concept."""

    return default_pricing_market_data_bindings(namespace=namespace).get(concept_key)


__all__ = [
    "PRICING_CONCEPT_DISCOUNT_CURVES",
    "PRICING_CONCEPT_EQUITY_VOL_CURVES",
    "PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS",
    "PRICING_CONTEXT_DEFAULT",
    "PRICING_CONTEXT_EOD",
    "PRICING_CONTEXT_LIVE",
    "PRICING_CONTEXT_RISK_MANAGER",
    "PRICING_DEFAULT_DISCOUNT_CURVES_DATA_NODE_IDENTIFIER",
    "PRICING_DEFAULT_INDEX_FIXINGS_DATA_NODE_IDENTIFIER",
    "default_pricing_market_data_bindings",
    "default_pricing_market_data_identifier",
]
