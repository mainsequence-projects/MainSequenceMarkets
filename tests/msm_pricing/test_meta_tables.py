from __future__ import annotations

from types import SimpleNamespace

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
    register_pricing_meta_tables,
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


def test_register_pricing_meta_tables_delegates_with_pricing_models(monkeypatch) -> None:
    calls = []

    def fake_catalog_bootstrap(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(registration=SimpleNamespace(models=kwargs["models"]))

    monkeypatch.setattr(
        pricing_meta_tables,
        "bootstrap_markets_meta_tables_from_catalog",
        fake_catalog_bootstrap,
    )

    result = register_pricing_meta_tables(
        data_source_uid="data-source-uid",
        management_mode="external_registered",
        target_meta_table_uid_by_identifier={"Asset": "asset-meta-table-uid"},
        open_for_everyone=True,
        protect_from_deletion=True,
        introspect=True,
        storage_hash_by_identifier={"Asset": "asset-storage-hash"},
        timeout=5,
    )

    assert result.models == EXPECTED_PRICING_MODELS
    assert calls == [
        {
            "data_source_uid": "data-source-uid",
            "management_mode": "external_registered",
            "target_meta_table_uid_by_identifier": {"Asset": "asset-meta-table-uid"},
            "target_meta_table_uid_by_fullname": None,
            "open_for_everyone": True,
            "protect_from_deletion": True,
            "introspect": True,
            "storage_hash_by_identifier": {"Asset": "asset-storage-hash"},
            "storage_hash_by_fullname": None,
            "timeout": 5,
            "models": EXPECTED_PRICING_MODELS,
        }
    ]


def test_register_pricing_meta_tables_registration_request_modes_use_dependency_order(
    monkeypatch,
) -> None:
    calls = []

    def fake_catalog_bootstrap(**kwargs):
        calls.append((kwargs["management_mode"], kwargs["models"]))
        return SimpleNamespace(
            registration=SimpleNamespace(
                management_mode=kwargs["management_mode"],
                models=kwargs["models"],
            ),
        )

    monkeypatch.setattr(
        pricing_meta_tables,
        "bootstrap_markets_meta_tables_from_catalog",
        fake_catalog_bootstrap,
    )

    for management_mode in ("platform_managed", "external_registered"):
        result = register_pricing_meta_tables(
            data_source_uid="data-source-uid",
            management_mode=management_mode,
            target_meta_table_uid_by_identifier={
                AssetTable.__metatable_identifier__: "asset-meta-table-uid",
                IndexTable.__metatable_identifier__: "index-meta-table-uid",
            },
        )
        assert result.models == EXPECTED_PRICING_MODELS

    assert calls == [
        ("platform_managed", EXPECTED_PRICING_MODELS),
        ("external_registered", EXPECTED_PRICING_MODELS),
    ]


def test_register_pricing_meta_tables_uses_catalog_bootstrap_in_dependency_order(
    monkeypatch,
) -> None:
    calls = []

    def fail_direct_register(cls, **_kwargs):
        raise AssertionError(f"{cls.__name__}.register should not run directly")

    def fake_catalog_bootstrap(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            registration=SimpleNamespace(
                models=kwargs["models"],
                target_meta_table_uid_by_identifier={
                    model.__metatable_identifier__: f"{model.__name__}-meta-table-uid"
                    for model in kwargs["models"]
                },
            ),
        )

    for model in EXPECTED_PRICING_MODELS:
        monkeypatch.setattr(model, "register", classmethod(fail_direct_register))
    monkeypatch.setattr(
        pricing_meta_tables,
        "bootstrap_markets_meta_tables_from_catalog",
        fake_catalog_bootstrap,
    )

    result = register_pricing_meta_tables(data_source_uid="data-source-uid")

    assert len(calls) == 1
    assert calls[0]["data_source_uid"] == "data-source-uid"
    assert calls[0]["models"] == EXPECTED_PRICING_MODELS
    assert result.target_meta_table_uid_by_identifier == {
        model.__metatable_identifier__: f"{model.__name__}-meta-table-uid"
        for model in EXPECTED_PRICING_MODELS
    }
