from importlib.util import find_spec


def test_models_package_is_metatable_only() -> None:
    import msm_pricing.models as models

    assert models.__all__ == [
        "AssetCurrentPricingDetailsTable",
        "CurveTable",
        "IndexConventionDetailsTable",
    ]
    assert not hasattr(models, "get_index")
    assert not hasattr(models, "register_index_spec")
    assert find_spec("msm_pricing.models.indices") is None
    assert find_spec("msm_pricing.models.bond_pricer") is None
    assert find_spec("msm_pricing.models.swap_pricer") is None


def test_pricing_engine_owns_runtime_helpers() -> None:
    import msm_pricing.pricing_engine as pricing_engine

    assert "get_index" in pricing_engine.__all__
    assert "register_index_spec" in pricing_engine.__all__
    assert find_spec("msm_pricing.pricing_engine.indices") is not None
    assert find_spec("msm_pricing.pricing_engine.bond_pricer") is not None
    assert find_spec("msm_pricing.pricing_engine.swap_pricer") is not None


def test_obsolete_interest_rates_package_is_removed() -> None:
    assert find_spec("msm_pricing.interest_rates") is None
