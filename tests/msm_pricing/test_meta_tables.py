from __future__ import annotations

from msm.models import AssetTable, IndexTable, IndexTypeTable, markets_sqlalchemy_models
import msm_pricing.meta_tables as pricing_meta_tables
from msm_pricing.data_nodes.storage import (
    AssetPricingDetailsStorage,
    DiscountCurvesStorage,
    IndexFixingsStorage,
)
from msm_pricing.meta_tables import (
    pricing_meta_table_identifier,
    pricing_sqlalchemy_models,
)
from msm_pricing.models import (
    AssetCurrentPricingDetailsTable,
    CurveTable,
    IndexConventionDetailsTable,
    PricingMarketDataBindingTable,
)

# ADR 0017: pricing_sqlalchemy_models() appends the pricing DataNode storage
# MetaTables after their FK target MetaTables (Asset/Index/Curve).
EXPECTED_PRICING_MODELS = [
    AssetTable,
    IndexTypeTable,
    IndexTable,
    IndexConventionDetailsTable,
    CurveTable,
    AssetCurrentPricingDetailsTable,
    PricingMarketDataBindingTable,
    DiscountCurvesStorage,
    IndexFixingsStorage,
    AssetPricingDetailsStorage,
]


def test_pricing_sqlalchemy_models_returns_pricing_dependency_order() -> None:
    assert pricing_sqlalchemy_models() == EXPECTED_PRICING_MODELS


def test_pricing_models_declare_metatable_descriptions() -> None:
    for model in pricing_sqlalchemy_models():
        description = getattr(model, "__metatable_description__", None)

        assert isinstance(description, str), model.__name__
        assert description.strip() == description
        assert len(description.split()) >= 8, model.__name__


def test_pricing_sqlalchemy_models_returns_a_fresh_model_list() -> None:
    models = pricing_sqlalchemy_models()

    models.clear()

    assert pricing_sqlalchemy_models() == EXPECTED_PRICING_MODELS


def test_core_markets_models_do_not_include_pricing_extension_table() -> None:
    assert AssetTable in markets_sqlalchemy_models()
    assert IndexTypeTable in markets_sqlalchemy_models()
    assert IndexTable in markets_sqlalchemy_models()
    assert IndexConventionDetailsTable not in markets_sqlalchemy_models()
    assert CurveTable not in markets_sqlalchemy_models()
    assert AssetCurrentPricingDetailsTable not in markets_sqlalchemy_models()
    assert PricingMarketDataBindingTable not in markets_sqlalchemy_models()
    # ADR 0017: pricing DataNode storage registers through the pricing registry only.
    assert DiscountCurvesStorage not in markets_sqlalchemy_models()
    assert IndexFixingsStorage not in markets_sqlalchemy_models()
    assert AssetPricingDetailsStorage not in markets_sqlalchemy_models()


def test_pricing_meta_table_identifier_survives_sdk_physical_binding(monkeypatch) -> None:
    identifier = pricing_meta_table_identifier(CurveTable)
    storage_name = str(CurveTable.__table__.name)

    monkeypatch.setitem(CurveTable.__table__.info, "identifier", identifier)
    monkeypatch.setattr(CurveTable, "__metatable_storage_hash__", storage_name)
    monkeypatch.setattr(CurveTable.__table__, "name", "backend_physical_curve")
    monkeypatch.setattr(
        CurveTable.__table__,
        "fullname",
        "public.backend_physical_curve",
        raising=False,
    )

    assert pricing_meta_table_identifier(CurveTable) == identifier


def test_pricing_meta_tables_do_not_expose_direct_registration_helper() -> None:
    assert not hasattr(pricing_meta_tables, "register_pricing_meta_tables")
