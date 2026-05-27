from __future__ import annotations

from msm.models import AssetTable, markets_sqlalchemy_models
from msm_pricing.meta_tables import pricing_sqlalchemy_models
from msm_pricing.models import AssetCurrentPricingDetailsTable


def test_pricing_sqlalchemy_models_returns_pricing_dependency_order() -> None:
    assert pricing_sqlalchemy_models() == [
        AssetTable,
        AssetCurrentPricingDetailsTable,
    ]


def test_pricing_sqlalchemy_models_returns_a_fresh_model_list() -> None:
    models = pricing_sqlalchemy_models()

    models.clear()

    assert pricing_sqlalchemy_models() == [
        AssetTable,
        AssetCurrentPricingDetailsTable,
    ]


def test_core_markets_models_do_not_include_pricing_extension_table() -> None:
    assert AssetTable in markets_sqlalchemy_models()
    assert AssetCurrentPricingDetailsTable not in markets_sqlalchemy_models()
