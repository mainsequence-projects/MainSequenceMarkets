from __future__ import annotations

import pytest
from pydantic import ValidationError

from msm.settings import MSM_AUTO_REGISTER_NAMESPACE_ENV
from msm_pricing.config import (
    PricingMarketDataConfiguration,
    default_pricing_market_data_configuration,
    get_pricing_market_data_configuration,
    reset_pricing_market_data_configuration,
    set_pricing_market_data_configuration,
)
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    PRICING_CONTEXT_DEFAULT,
    PRICING_DEFAULT_DISCOUNT_CURVES_DATA_NODE_IDENTIFIER,
    PRICING_DEFAULT_INDEX_FIXINGS_DATA_NODE_IDENTIFIER,
    default_pricing_market_data_bindings,
)


@pytest.fixture(autouse=True)
def reset_pricing_market_data(monkeypatch) -> None:
    reset_pricing_market_data_configuration()
    monkeypatch.delenv(MSM_AUTO_REGISTER_NAMESPACE_ENV, raising=False)
    yield
    reset_pricing_market_data_configuration()


def test_pricing_market_data_configuration_defaults_to_canonical_identifiers() -> None:
    configuration = default_pricing_market_data_configuration()

    assert configuration.context_key == PRICING_CONTEXT_DEFAULT
    assert configuration.data_node_identifiers == {}
    assert default_pricing_market_data_bindings() == {
        PRICING_CONCEPT_DISCOUNT_CURVES: PRICING_DEFAULT_DISCOUNT_CURVES_DATA_NODE_IDENTIFIER,
        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: (
            PRICING_DEFAULT_INDEX_FIXINGS_DATA_NODE_IDENTIFIER
        ),
    }


def test_pricing_market_data_configuration_defaults_follow_active_markets_namespace(
    monkeypatch,
) -> None:
    monkeypatch.setenv(MSM_AUTO_REGISTER_NAMESPACE_ENV, "mainsequence.examples")

    configuration = default_pricing_market_data_configuration()

    assert configuration.context_key == PRICING_CONTEXT_DEFAULT
    assert default_pricing_market_data_bindings() == {
        PRICING_CONCEPT_DISCOUNT_CURVES: "mainsequence.examples.DiscountCurvesTS",
        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: (
            "mainsequence.examples.IndexFixingsTS"
        ),
    }


def test_set_pricing_market_data_configuration_accepts_typed_override() -> None:
    override = PricingMarketDataConfiguration(
        context_key="eod",
        data_node_identifiers={
            PRICING_CONCEPT_DISCOUNT_CURVES: "vendor.discount_curves",
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: ("vendor.interest_rate_index_fixings"),
        },
    )

    configured = set_pricing_market_data_configuration(override)

    assert configured is override
    assert get_pricing_market_data_configuration() is override


def test_set_pricing_market_data_configuration_accepts_mapping_override() -> None:
    configured = set_pricing_market_data_configuration(
        {
            "context_key": "risk_manager",
            "data_node_identifiers": {
                PRICING_CONCEPT_DISCOUNT_CURVES: "vendor.discount_curves",
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: ("vendor.interest_rate_index_fixings"),
            },
        }
    )

    assert configured == PricingMarketDataConfiguration(
        context_key="risk_manager",
        data_node_identifiers={
            PRICING_CONCEPT_DISCOUNT_CURVES: "vendor.discount_curves",
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: ("vendor.interest_rate_index_fixings"),
        },
    )
    assert get_pricing_market_data_configuration() == configured


def test_set_pricing_market_data_configuration_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        set_pricing_market_data_configuration(
            {
                "unexpected_configuration": "bad-boundary",
            }
        )


def test_reset_pricing_market_data_configuration_restores_defaults() -> None:
    set_pricing_market_data_configuration(
        {
            "context_key": "eod",
            "data_node_identifiers": {
                PRICING_CONCEPT_DISCOUNT_CURVES: "vendor.discount_curves",
            },
        }
    )

    reset = reset_pricing_market_data_configuration()

    assert reset == PricingMarketDataConfiguration()
    assert get_pricing_market_data_configuration() == PricingMarketDataConfiguration()
