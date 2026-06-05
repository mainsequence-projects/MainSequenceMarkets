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
    PRICING_MARKET_DATA_SET_DEFAULT,
)


@pytest.fixture(autouse=True)
def reset_pricing_market_data(monkeypatch) -> None:
    reset_pricing_market_data_configuration()
    monkeypatch.delenv(MSM_AUTO_REGISTER_NAMESPACE_ENV, raising=False)
    yield
    reset_pricing_market_data_configuration()


def test_pricing_market_data_configuration_defaults_to_empty_runtime_overrides() -> None:
    configuration = default_pricing_market_data_configuration()

    assert configuration.market_data_set == PRICING_MARKET_DATA_SET_DEFAULT
    assert configuration.data_node_uids == {}


def test_set_pricing_market_data_configuration_accepts_typed_override() -> None:
    discount_curves_uid = "00000000-0000-0000-0000-000000000101"
    fixings_uid = "00000000-0000-0000-0000-000000000102"
    override = PricingMarketDataConfiguration(
        market_data_set="eod",
        data_node_uids={
            PRICING_CONCEPT_DISCOUNT_CURVES: discount_curves_uid,
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: fixings_uid,
        },
    )

    configured = set_pricing_market_data_configuration(override)

    assert configured is override
    assert get_pricing_market_data_configuration() is override


def test_set_pricing_market_data_configuration_accepts_mapping_override() -> None:
    discount_curves_uid = "00000000-0000-0000-0000-000000000201"
    fixings_uid = "00000000-0000-0000-0000-000000000202"
    configured = set_pricing_market_data_configuration(
        {
            "market_data_set": "risk_manager",
            "data_node_uids": {
                PRICING_CONCEPT_DISCOUNT_CURVES: discount_curves_uid,
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: fixings_uid,
            },
        }
    )

    assert configured == PricingMarketDataConfiguration(
        market_data_set="risk_manager",
        data_node_uids={
            PRICING_CONCEPT_DISCOUNT_CURVES: discount_curves_uid,
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: fixings_uid,
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
            "market_data_set": "eod",
            "data_node_uids": {
                PRICING_CONCEPT_DISCOUNT_CURVES: "00000000-0000-0000-0000-000000000301",
            },
        }
    )

    reset = reset_pricing_market_data_configuration()

    assert reset == PricingMarketDataConfiguration()
    assert get_pricing_market_data_configuration() == PricingMarketDataConfiguration()
