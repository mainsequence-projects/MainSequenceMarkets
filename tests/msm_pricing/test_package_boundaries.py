from importlib.util import find_spec


def test_models_package_is_metatable_only() -> None:
    import msm_pricing.models as models

    assert models.__all__ == [
        "AssetCurrentPricingDetailsTable",
        "CurveBuildingDetailsTable",
        "CurveTable",
        "IndexConventionDetailsTable",
        "PricingMarketDataSetBindingTable",
        "PricingMarketDataSetCurveBindingTable",
        "PricingMarketDataSetTable",
    ]
    assert not hasattr(models, "get_index")
    assert not hasattr(models, "register_index_spec")
    assert find_spec("msm_pricing.models.indices") is None
    assert find_spec("msm_pricing.models.bond_pricer") is None
    assert find_spec("msm_pricing.models.swap_pricer") is None


def test_pricing_engine_owns_runtime_helpers() -> None:
    import msm_pricing.pricing_engine as pricing_engine

    assert "resolve_quantlib_index" in pricing_engine.__all__
    assert "resolve_pricing_curve" in pricing_engine.__all__
    assert "resolve_curve_building_details" in pricing_engine.__all__
    assert "build_curve_from_curve_row" in pricing_engine.__all__
    assert "get_index" not in pricing_engine.__all__
    assert "register_index_spec" not in pricing_engine.__all__
    assert "IndexSpec" not in pricing_engine.__all__
    assert find_spec("msm_pricing.pricing_engine.indices") is not None
    assert find_spec("msm_pricing.pricing_engine.bond_pricer") is not None
    assert find_spec("msm_pricing.pricing_engine.swap_pricer") is not None


def test_obsolete_interest_rates_package_is_removed() -> None:
    assert find_spec("msm_pricing.interest_rates") is None


def test_pricing_settings_module_contains_public_constants() -> None:
    import msm_pricing.settings as settings

    assert settings.PRICING_CONCEPT_DISCOUNT_CURVES == "discount_curves"
    assert settings.PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS == "interest_rate_index_fixings"
    assert settings.PRICING_MARKET_DATA_SET_DEFAULT == "default"
    assert settings.PRICING_MARKET_DATA_SET_EOD == "eod"
    assert settings.PRICING_MARKET_DATA_SET_LIVE == "live"
    assert settings.PRICING_MARKET_DATA_SET_RISK_MANAGER == "risk_manager"
    assert not hasattr(settings, "PRICING_DEFAULT_DISCOUNT_CURVES_DATA_NODE_IDENTIFIER")
    assert not hasattr(settings, "PRICING_DEFAULT_INDEX_FIXINGS_DATA_NODE_IDENTIFIER")
    assert not hasattr(settings, "PRICING_CONTEXT_DEFAULT")
    assert not hasattr(settings, "default_pricing_market_data_bindings")
    assert not hasattr(settings, "default_pricing_market_data_identifier")
