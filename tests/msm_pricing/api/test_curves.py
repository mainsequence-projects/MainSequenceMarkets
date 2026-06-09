from __future__ import annotations

import datetime as dt
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


def test_curve_start_engine_uses_pricing_dependencies(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_attach_pricing_schemas(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr(
        "msm_pricing.api.curves.attach_pricing_schemas",
        fake_attach_pricing_schemas,
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


def test_curve_frontend_detail_summary_uses_curve_row(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()

    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        classmethod(
            lambda cls, uid: Curve(
                uid=curve_uid,
                unique_identifier="USD-SOFR-DISCOUNT",
                display_name="USD SOFR Discount Curve",
                curve_type="discount",
                index_uid=index_uid,
                interpolation_method="log_linear_discount",
                compounding="compounded_annual",
                source="unit-test",
                metadata_json={"provider": "test"},
            )
        ),
    )

    summary = Curve.get_frontend_detail_summary(curve_uid)

    assert summary == {
        "entity": {
            "id": str(curve_uid),
            "type": "pricing_curve",
            "title": "USD SOFR Discount Curve",
        },
        "badges": [
            {
                "key": "curve_type",
                "label": "discount",
                "tone": "info",
            },
            {
                "key": "source",
                "label": "unit-test",
                "tone": "neutral",
            },
        ],
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": str(curve_uid),
                "kind": "code",
            },
            {
                "key": "unique_identifier",
                "label": "Identifier",
                "value": "USD-SOFR-DISCOUNT",
                "kind": "code",
            },
            {
                "key": "index_uid",
                "label": "Index UID",
                "value": str(index_uid),
                "kind": "code",
            },
        ],
        "highlight_fields": [
            {
                "key": "display_name",
                "label": "Display Name",
                "value": "USD SOFR Discount Curve",
                "kind": "text",
                "icon": "database",
            },
            {
                "key": "curve_type",
                "label": "Curve Type",
                "value": "discount",
                "kind": "code",
                "icon": "line-chart",
            },
            {
                "key": "interpolation_method",
                "label": "Interpolation",
                "value": "log_linear_discount",
                "kind": "code",
                "icon": "activity",
            },
            {
                "key": "compounding",
                "label": "Compounding",
                "value": "compounded_annual",
                "kind": "code",
                "icon": "activity",
            },
        ],
        "stats": [],
        "label_management": None,
        "summary_warning": None,
        "extensions": {
            "curve": {
                "uid": str(curve_uid),
                "unique_identifier": "USD-SOFR-DISCOUNT",
                "display_name": "USD SOFR Discount Curve",
                "curve_type": "discount",
                "index_uid": str(index_uid),
                "interpolation_method": "log_linear_discount",
                "compounding": "compounded_annual",
                "source": "unit-test",
                "metadata_json": {"provider": "test"},
            },
            "metadata_json": {"provider": "test"},
        },
    }


def test_curve_frontend_detail_summary_returns_none_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(Curve, "get_by_uid", classmethod(lambda cls, uid: None))

    assert Curve.get_frontend_detail_summary(uuid.uuid4()) is None


def test_curve_discount_curve_nodes_use_market_data_binding(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()
    valuation_date = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)
    calls: list[object] = []

    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        classmethod(
            lambda cls, uid: Curve(
                uid=curve_uid,
                unique_identifier="USD-SOFR-DISCOUNT",
                display_name="USD SOFR Discount Curve",
                curve_type="discount",
                index_uid=index_uid,
            )
        ),
    )

    from msm_pricing.api.market_data_bindings import (
        PricingMarketDataSet,
        PricingMarketDataSetBinding,
    )

    monkeypatch.setattr(
        PricingMarketDataSet,
        "resolve_uid",
        classmethod(lambda cls, market_data_set: market_data_set_uid),
    )
    monkeypatch.setattr(
        PricingMarketDataSet,
        "get_by_uid",
        classmethod(
            lambda cls, uid: PricingMarketDataSet(
                uid=market_data_set_uid,
                set_key="eod",
                display_name="End of day",
            )
        ),
    )
    monkeypatch.setattr(
        PricingMarketDataSetBinding,
        "get_by_set_and_concept",
        classmethod(
            lambda cls, market_data_set_uid, concept_key: PricingMarketDataSetBinding(
                uid=binding_uid,
                market_data_set_uid=market_data_set_uid,
                concept_key=concept_key,
                data_node_uid=data_node_uid,
                storage_table_identifier="DiscountCurvesStorage",
            )
        ),
    )

    class FakeMSDataInterface:
        def __init__(self, market_data_configuration):
            calls.append(("configuration", market_data_configuration))

        def get_historical_discount_curve(self, curve_identifier, target_date):
            calls.append(("historical", curve_identifier, target_date))
            return [{"days_to_maturity": 28, "zero": 0.11}], target_date

    monkeypatch.setattr("msm_pricing.data_interface.MSDataInterface", FakeMSDataInterface)

    response = Curve.get_discount_curve_nodes(
        uid=curve_uid,
        market_data_set="eod",
        valuation_date=valuation_date,
    )

    assert response == {
        "curve_uid": curve_uid,
        "curve_identifier": "USD-SOFR-DISCOUNT",
        "curve": {
            "uid": str(curve_uid),
            "unique_identifier": "USD-SOFR-DISCOUNT",
            "display_name": "USD SOFR Discount Curve",
            "curve_type": "discount",
            "index_uid": str(index_uid),
            "interpolation_method": None,
            "compounding": None,
            "source": None,
            "metadata_json": None,
        },
        "market_data_set": {
            "uid": market_data_set_uid,
            "set_key": "eod",
            "display_name": "End of day",
        },
        "binding": {
            "uid": binding_uid,
            "concept_key": "discount_curves",
            "data_node_uid": data_node_uid,
            "storage_table_identifier": "DiscountCurvesStorage",
        },
        "valuation_date": valuation_date,
        "effective_date": valuation_date,
        "request_mode": "historical",
        "nodes": [{"days_to_maturity": 28, "zero": 0.11}],
    }
    assert calls == [
        (
            "configuration",
            {"data_node_uids": {"discount_curves": data_node_uid}},
        ),
        ("historical", "USD-SOFR-DISCOUNT", valuation_date),
    ]


def test_curve_discount_curve_nodes_use_latest_when_valuation_date_missing(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()
    latest_date = dt.datetime(2026, 6, 2, tzinfo=dt.UTC)

    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        classmethod(
            lambda cls, uid: Curve(
                uid=curve_uid,
                unique_identifier="USD-SOFR-DISCOUNT",
                display_name="USD SOFR Discount Curve",
                curve_type="discount",
                index_uid=index_uid,
            )
        ),
    )

    from msm_pricing.api.market_data_bindings import (
        PricingMarketDataSet,
        PricingMarketDataSetBinding,
    )

    monkeypatch.setattr(
        PricingMarketDataSet,
        "resolve_uid",
        classmethod(lambda cls, market_data_set: market_data_set_uid),
    )
    monkeypatch.setattr(
        PricingMarketDataSet,
        "get_by_uid",
        classmethod(
            lambda cls, uid: PricingMarketDataSet(
                uid=market_data_set_uid,
                set_key="live",
                display_name="Live",
            )
        ),
    )
    monkeypatch.setattr(
        PricingMarketDataSetBinding,
        "get_by_set_and_concept",
        classmethod(
            lambda cls, market_data_set_uid, concept_key: PricingMarketDataSetBinding(
                uid=binding_uid,
                market_data_set_uid=market_data_set_uid,
                concept_key=concept_key,
                data_node_uid=data_node_uid,
            )
        ),
    )

    class FakeMSDataInterface:
        def __init__(self, market_data_configuration):
            pass

        def get_latest_discount_curve(self, curve_identifier):
            assert curve_identifier == "USD-SOFR-DISCOUNT"
            return [{"days_to_maturity": 91, "zero": 0.105}], latest_date

    monkeypatch.setattr("msm_pricing.data_interface.MSDataInterface", FakeMSDataInterface)

    response = Curve.get_discount_curve_nodes(uid=curve_uid, market_data_set="live")

    assert response is not None
    assert response["valuation_date"] is None
    assert response["effective_date"] == latest_date
    assert response["request_mode"] == "latest"
    assert response["nodes"] == [{"days_to_maturity": 91, "zero": 0.105}]


def test_curve_discount_curve_nodes_return_none_when_curve_missing(monkeypatch) -> None:
    monkeypatch.setattr(Curve, "get_by_uid", classmethod(lambda cls, uid: None))

    assert Curve.get_discount_curve_nodes(uid=uuid.uuid4(), market_data_set="eod") is None


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


def test_curve_list_uses_paginated_runtime_search(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.curves.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    def fake_count_model(active_context, *, model, filters, contains_filters):
        calls.append(("count", active_context, model, filters, contains_filters))
        return {"rows": [{"count": 2}]}

    def fake_search_model(
        active_context,
        *,
        model,
        filters,
        contains_filters,
        limit,
        offset,
    ):
        calls.append(("search", active_context, model, filters, contains_filters, limit, offset))
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

    monkeypatch.setattr("msm_pricing.api.curves.count_model", fake_count_model)
    monkeypatch.setattr("msm_pricing.api.curves.search_model", fake_search_model)

    response = Curve.list(
        limit=1,
        offset=1,
        search="SOFR",
        curve_type="discount",
        index_uid=index_uid,
        source=None,
    )

    assert response == {
        "count": 2,
        "limit": 1,
        "offset": 1,
        "results": [
            Curve(
                uid=curve_uid,
                unique_identifier="USD-SOFR-DISCOUNT",
                display_name="USD SOFR Discount Curve",
                curve_type="discount",
                index_uid=index_uid,
            )
        ],
    }
    assert calls == [
        (
            "count",
            context,
            CurveTable,
            {"curve_type": "discount", "index_uid": index_uid},
            {"unique_identifier": "SOFR"},
        ),
        (
            "search",
            context,
            CurveTable,
            {"curve_type": "discount", "index_uid": index_uid},
            {"unique_identifier": "SOFR"},
            1,
            1,
        ),
    ]


def test_curve_list_validates_pagination() -> None:
    with pytest.raises(ValueError, match="limit"):
        Curve.list(limit=0)

    with pytest.raises(ValueError, match="offset"):
        Curve.list(offset=-1)
