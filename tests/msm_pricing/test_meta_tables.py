from __future__ import annotations

from types import SimpleNamespace

from msm.models import AssetTable, IndexTable, markets_sqlalchemy_models
import msm_pricing.meta_tables as pricing_meta_tables
from msm_pricing.meta_tables import pricing_sqlalchemy_models, register_pricing_meta_tables
from msm_pricing.models import (
    AssetCurrentPricingDetailsTable,
    CurveTable,
    IndexConventionDetailsTable,
)


def test_pricing_sqlalchemy_models_returns_pricing_dependency_order() -> None:
    assert pricing_sqlalchemy_models() == [
        AssetTable,
        IndexTable,
        IndexConventionDetailsTable,
        CurveTable,
        AssetCurrentPricingDetailsTable,
    ]


def test_pricing_sqlalchemy_models_returns_a_fresh_model_list() -> None:
    models = pricing_sqlalchemy_models()

    models.clear()

    assert pricing_sqlalchemy_models() == [
        AssetTable,
        IndexTable,
        IndexConventionDetailsTable,
        CurveTable,
        AssetCurrentPricingDetailsTable,
    ]


def test_core_markets_models_do_not_include_pricing_extension_table() -> None:
    assert AssetTable in markets_sqlalchemy_models()
    assert IndexTable in markets_sqlalchemy_models()
    assert IndexConventionDetailsTable not in markets_sqlalchemy_models()
    assert CurveTable not in markets_sqlalchemy_models()
    assert AssetCurrentPricingDetailsTable not in markets_sqlalchemy_models()


def test_register_pricing_meta_tables_delegates_with_pricing_models(monkeypatch) -> None:
    calls = []

    def fake_register_markets_meta_tables(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(models=kwargs["models"])

    monkeypatch.setattr(
        pricing_meta_tables,
        "register_markets_meta_tables",
        fake_register_markets_meta_tables,
    )

    result = register_pricing_meta_tables(
        data_source_uid="data-source-uid",
        management_mode="external_registered",
        target_meta_table_uid_by_fullname={"public.asset": "asset-meta-table-uid"},
        labels=["pricing"],
        open_for_everyone=True,
        protect_from_deletion=True,
        introspect=True,
        storage_hash_by_fullname={"public.asset": "asset-storage-hash"},
        timeout=5,
    )

    assert result.models == [
        AssetTable,
        IndexTable,
        IndexConventionDetailsTable,
        CurveTable,
        AssetCurrentPricingDetailsTable,
    ]
    assert calls == [
        {
            "data_source_uid": "data-source-uid",
            "management_mode": "external_registered",
            "target_meta_table_uid_by_fullname": {
                "public.asset": "asset-meta-table-uid"
            },
            "labels": ["pricing"],
            "open_for_everyone": True,
            "protect_from_deletion": True,
            "introspect": True,
            "storage_hash_by_fullname": {"public.asset": "asset-storage-hash"},
            "timeout": 5,
            "models": [
                AssetTable,
                IndexTable,
                IndexConventionDetailsTable,
                CurveTable,
                AssetCurrentPricingDetailsTable,
            ],
        }
    ]


def test_register_pricing_meta_tables_populates_asset_target_before_pricing_child(
    monkeypatch,
) -> None:
    calls = []

    def fake_register(cls, **kwargs):
        snapshot = dict(kwargs)
        snapshot["target_meta_table_uid_by_fullname"] = dict(
            snapshot["target_meta_table_uid_by_fullname"]
        )
        calls.append((cls, snapshot))
        return SimpleNamespace(uid=f"{cls.__name__}-meta-table-uid")

    monkeypatch.setattr(AssetTable, "register", classmethod(fake_register))
    monkeypatch.setattr(
        AssetCurrentPricingDetailsTable,
        "register",
        classmethod(fake_register),
    )
    monkeypatch.setattr(IndexTable, "register", classmethod(fake_register))
    monkeypatch.setattr(
        IndexConventionDetailsTable,
        "register",
        classmethod(fake_register),
    )
    monkeypatch.setattr(CurveTable, "register", classmethod(fake_register))

    result = register_pricing_meta_tables(data_source_uid="data-source-uid")

    assert [model for model, _kwargs in calls] == [
        AssetTable,
        IndexTable,
        IndexConventionDetailsTable,
        CurveTable,
        AssetCurrentPricingDetailsTable,
    ]
    assert calls[0][1]["target_meta_table_uid_by_fullname"] == {}
    assert calls[1][1]["target_meta_table_uid_by_fullname"] == {
        str(AssetTable.__table__.fullname): "AssetTable-meta-table-uid"
    }
    assert calls[2][1]["target_meta_table_uid_by_fullname"] == {
        str(AssetTable.__table__.fullname): "AssetTable-meta-table-uid",
        str(IndexTable.__table__.fullname): "IndexTable-meta-table-uid",
    }
    assert calls[3][1]["target_meta_table_uid_by_fullname"] == {
        str(AssetTable.__table__.fullname): "AssetTable-meta-table-uid",
        str(IndexTable.__table__.fullname): "IndexTable-meta-table-uid",
        str(IndexConventionDetailsTable.__table__.fullname): (
            "IndexConventionDetailsTable-meta-table-uid"
        ),
    }
    assert calls[4][1]["target_meta_table_uid_by_fullname"] == {
        str(AssetTable.__table__.fullname): "AssetTable-meta-table-uid",
        str(IndexTable.__table__.fullname): "IndexTable-meta-table-uid",
        str(IndexConventionDetailsTable.__table__.fullname): (
            "IndexConventionDetailsTable-meta-table-uid"
        ),
        str(CurveTable.__table__.fullname): "CurveTable-meta-table-uid",
    }
    assert result.target_meta_table_uid_by_fullname == {
        str(AssetTable.__table__.fullname): "AssetTable-meta-table-uid",
        str(IndexTable.__table__.fullname): "IndexTable-meta-table-uid",
        str(IndexConventionDetailsTable.__table__.fullname): (
            "IndexConventionDetailsTable-meta-table-uid"
        ),
        str(CurveTable.__table__.fullname): "CurveTable-meta-table-uid",
        str(AssetCurrentPricingDetailsTable.__table__.fullname): (
            "AssetCurrentPricingDetailsTable-meta-table-uid"
        ),
    }
