from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm.models import IndexTable, IndexTypeTable
from msm_pricing.api.curves import Curve, CurveUpsert
from msm_pricing.models import CurveTable, IndexConventionDetailsTable


def test_curve_api_declares_table_contract() -> None:
    assert Curve.__table__ is CurveTable
    assert Curve.__required_tables__ == [
        IndexTypeTable,
        IndexTable,
        IndexConventionDetailsTable,
        CurveTable,
    ]
    assert Curve.__upsert_keys__ == ("unique_identifier",)


def test_curve_create_schemas_uses_pricing_dependencies(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_create_pricing_schemas(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr(
        "msm_pricing.api.curves.create_pricing_schemas",
        fake_create_pricing_schemas,
    )

    assert Curve.start_engine(namespace="pricing-test") is runtime
    assert calls == [
        {
            "models": [IndexTypeTable, IndexTable, IndexConventionDetailsTable, CurveTable],
            "namespace": "pricing-test",
        }
    ]


def test_curve_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        CurveUpsert(
            unique_identifier="USD-SOFR-DISCOUNT",
            display_name="USD SOFR Discount Curve",
            curve_type="discount",
            index_uid=uuid.uuid4(),
            uid=uuid.uuid4(),
        )


def test_curve_row_accepts_physical_metadata_alias() -> None:
    row = Curve.model_validate(
        {
            "uid": uuid.uuid4(),
            "unique_identifier": "USD-SOFR-DISCOUNT",
            "display_name": "USD SOFR Discount Curve",
            "curve_type": "discount",
            "index_uid": uuid.uuid4(),
            "metadata": {"provider": "unit-test"},
        }
    )

    assert row.metadata_json == {"provider": "unit-test"}


def test_curve_upsert_uses_pricing_runtime_and_unique_identifier_key(
    monkeypatch,
) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    def fake_resolve_pricing_runtime(**kwargs):
        calls.append(("runtime", kwargs))
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append(("upsert", active_context, model, values, conflict_columns))
        return {"row": {"uid": curve_uid, **values}}

    monkeypatch.setattr(
        "msm_pricing.api.curves.resolve_pricing_runtime",
        fake_resolve_pricing_runtime,
    )
    monkeypatch.setattr("msm_pricing.api.curves.upsert_model", fake_upsert_model)

    row = Curve.upsert(
        unique_identifier="USD-SOFR-DISCOUNT",
        display_name="USD SOFR Discount Curve",
        curve_type="discount",
        index_uid=index_uid,
        interpolation_method="log_linear",
        compounding="continuous",
        source="unit-test",
        metadata_json={"provider": "test"},
    )

    assert row == Curve(
        uid=curve_uid,
        unique_identifier="USD-SOFR-DISCOUNT",
        display_name="USD SOFR Discount Curve",
        curve_type="discount",
        index_uid=index_uid,
        interpolation_method="log_linear",
        compounding="continuous",
        source="unit-test",
        metadata_json={"provider": "test"},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [IndexTypeTable, IndexTable, IndexConventionDetailsTable, CurveTable],
                "row_model_name": "Curve",
            },
        ),
        (
            "upsert",
            context,
            CurveTable,
            {
                "unique_identifier": "USD-SOFR-DISCOUNT",
                "display_name": "USD SOFR Discount Curve",
                "curve_type": "discount",
                "index_uid": index_uid,
                "interpolation_method": "log_linear",
                "compounding": "continuous",
                "source": "unit-test",
                "metadata_json": {"provider": "test"},
            },
            ("unique_identifier",),
        ),
    ]


def test_curve_get_by_unique_identifier_uses_curve_lookup(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.curves.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    def fake_get_model_by_unique_identifier(active_context, *, model, unique_identifier):
        calls.append((active_context, model, unique_identifier))
        return {
            "row": {
                "uid": curve_uid,
                "unique_identifier": "USD-SOFR-DISCOUNT",
                "display_name": "USD SOFR Discount Curve",
                "curve_type": "discount",
                "index_uid": index_uid,
            }
        }

    monkeypatch.setattr(
        "msm_pricing.api.curves.get_model_by_unique_identifier",
        fake_get_model_by_unique_identifier,
    )

    row = Curve.get_by_unique_identifier("USD-SOFR-DISCOUNT")

    assert row is not None
    assert row.uid == curve_uid
    assert calls == [(context, CurveTable, "USD-SOFR-DISCOUNT")]


def test_curve_filter_uses_pricing_runtime_filters(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.curves.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    def fake_search_model(active_context, *, model, filters, limit):
        calls.append((active_context, model, filters, limit))
        return {
            "rows": [
                {
                    "uid": curve_uid,
                    "unique_identifier": "USD-SOFR-DISCOUNT",
                    "display_name": "USD SOFR Discount Curve",
                    "curve_type": "discount",
                    "index_uid": index_uid,
                }
            ]
        }

    monkeypatch.setattr(
        "msm_pricing.api.curves.search_model",
        fake_search_model,
    )

    rows = Curve.filter(index_uid=index_uid, curve_type="discount", source=None, limit=2)

    assert rows == [
        Curve(
            uid=curve_uid,
            unique_identifier="USD-SOFR-DISCOUNT",
            display_name="USD SOFR Discount Curve",
            curve_type="discount",
            index_uid=index_uid,
        )
    ]
    assert calls == [
        (
            context,
            CurveTable,
            {
                "index_uid": index_uid,
                "curve_type": "discount",
            },
            2,
        )
    ]
