from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm_pricing.api.curves import Curve, CurveDeleteConflictError, CurveUpsert
from msm_pricing.models import CurveTable


def _pricing_curve(*, uid: uuid.UUID | None = None) -> Curve:
    return Curve(
        uid=uid or uuid.uuid4(),
        unique_identifier="USD-SOFR-DISCOUNT",
        display_name="USD SOFR Discount Curve",
        curve_type="discount",
    )


def test_curve_api_declares_table_contract() -> None:
    assert Curve.__table__ is CurveTable
    assert Curve.__required_tables__ == [CurveTable]
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
            "models": [CurveTable],
            "namespace": "pricing-test",
        }
    ]


def test_curve_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        CurveUpsert(
            unique_identifier="USD-SOFR-DISCOUNT",
            display_name="USD SOFR Discount Curve",
            curve_type="discount",
            uid=uuid.uuid4(),
        )


def test_curve_row_accepts_physical_metadata_alias() -> None:
    row = Curve.model_validate(
        {
            "uid": uuid.uuid4(),
            "unique_identifier": "USD-SOFR-DISCOUNT",
            "display_name": "USD SOFR Discount Curve",
            "curve_type": "discount",
            "metadata": {"provider": "unit-test"},
        }
    )

    assert row.metadata_json == {"provider": "unit-test"}


def test_curve_upsert_uses_pricing_runtime_and_unique_identifier_key(
    monkeypatch,
) -> None:
    curve_uid = uuid.uuid4()
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
        currency_code="USD",
        quote_side="mid",
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
        currency_code="USD",
        quote_side="mid",
        interpolation_method="log_linear",
        compounding="continuous",
        source="unit-test",
        metadata_json={"provider": "test"},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [CurveTable],
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
                "currency_code": "USD",
                "quote_side": "mid",
                "interpolation_method": "log_linear",
                "compounding": "continuous",
                "source": "unit-test",
                "status": "ACTIVE",
                "metadata_json": {"provider": "test"},
            },
            ("unique_identifier",),
        ),
    ]


def test_curve_get_by_unique_identifier_uses_curve_lookup(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
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
                "status": "ACTIVE",
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


def test_curve_filters_uids_with_in_filter(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.curves.resolve_pricing_runtime",
        lambda **kwargs: calls.append(("runtime", kwargs)) or SimpleNamespace(context=context),
    )

    def fake_search_model(active_context, *, model, in_filters, limit):
        calls.append(("search", active_context, model, in_filters, limit))
        return {
            "rows": [
                {
                    "uid": curve_uid,
                    "unique_identifier": "USD-SOFR-DISCOUNT",
                    "display_name": "USD SOFR Discount Curve",
                    "curve_type": "discount",
                    "status": "ACTIVE",
                }
            ]
        }

    monkeypatch.setattr("msm_pricing.api.curves.search_model", fake_search_model)

    rows = Curve.filter_by_uids([curve_uid, str(curve_uid)])

    assert [row.uid for row in rows] == [curve_uid]
    assert calls == [
        (
            "runtime",
            {
                "models": [CurveTable],
                "row_model_name": "Curve",
            },
        ),
        ("search", context, CurveTable, {"uid": [curve_uid, curve_uid]}, 2),
    ]


def test_curve_frontend_detail_summary_uses_curve_row(monkeypatch) -> None:
    curve_uid = uuid.uuid4()

    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        classmethod(
            lambda cls, uid: Curve(
                uid=curve_uid,
                unique_identifier="USD-SOFR-DISCOUNT",
                display_name="USD SOFR Discount Curve",
                curve_type="discount",
                currency_code="USD",
                quote_side="mid",
                interpolation_method="log_linear_discount",
                compounding="compounded_annual",
                source="unit-test",
                metadata_json={"provider": "test"},
            )
        ),
    )
    monkeypatch.setattr(
        Curve,
        "count_curve_selections",
        classmethod(lambda cls, uid: 2),
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
                "key": "currency_code",
                "label": "USD",
                "tone": "neutral",
            },
            {
                "key": "quote_side",
                "label": "mid",
                "tone": "neutral",
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
                "key": "curve_selection_count",
                "label": "Curve Selections",
                "value": 2,
                "kind": "number",
                "link_url": f"/api/v1/pricing/curves/{curve_uid}/curve-selections/",
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
                "key": "currency_code",
                "label": "Currency",
                "value": "USD",
                "kind": "code",
                "icon": "circle-dollar-sign",
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
                "currency_code": "USD",
                "quote_side": "mid",
                "interpolation_method": "log_linear_discount",
                "compounding": "compounded_annual",
                "source": "unit-test",
                "status": "ACTIVE",
                "metadata_json": {"provider": "test"},
            },
            "curve_selection_count": 2,
            "curve_selections_url": f"/api/v1/pricing/curves/{curve_uid}/curve-selections/",
            "metadata_json": {"provider": "test"},
        },
    }


def test_curve_frontend_detail_summary_returns_none_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(Curve, "get_by_uid", classmethod(lambda cls, uid: None))

    assert Curve.get_frontend_detail_summary(uuid.uuid4()) is None


def test_curve_list_curve_selections_returns_reverse_binding_view(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    binding_uid_1 = uuid.uuid4()
    binding_uid_2 = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    calls: list[object] = []

    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        classmethod(
            lambda cls, uid: Curve(
                uid=curve_uid,
                unique_identifier="USD-SOFR-OFFER-BENCHMARK",
                display_name="USD SOFR offer benchmark",
                curve_type="discount",
            )
        ),
    )

    from msm.api.indices import Index
    from msm_pricing.api.market_data_bindings import (
        PricingMarketDataSet,
        PricingMarketDataSetCurveBinding,
    )

    def fake_filter_for_curve(cls, *, curve_uid, limit, status=None):
        calls.append(("filter_for_curve", curve_uid, limit, status))
        return [
            PricingMarketDataSetCurveBinding(
                uid=binding_uid_1,
                market_data_set_uid=market_data_set_uid,
                binding_key=f"z_spread_base:index:{index_uid}:offer",
                role_key="z_spread_base",
                selector_type="index",
                selector_key=str(index_uid),
                quote_side="offer",
                curve_uid=curve_uid,
                status="ACTIVE",
                source="example",
            ),
            PricingMarketDataSetCurveBinding(
                uid=binding_uid_2,
                market_data_set_uid=market_data_set_uid,
                binding_key=f"projection:index:{index_uid}:mid",
                role_key="projection",
                selector_type="index",
                selector_key=str(index_uid),
                quote_side="mid",
                curve_uid=curve_uid,
                status="ACTIVE",
                source="example",
            ),
        ]

    monkeypatch.setattr(
        PricingMarketDataSetCurveBinding,
        "filter_for_curve",
        classmethod(fake_filter_for_curve),
    )
    monkeypatch.setattr(
        PricingMarketDataSet,
        "get_by_uid",
        classmethod(lambda cls, uid: pytest.fail("market-data set lookup must be batched")),
    )
    monkeypatch.setattr(
        Index,
        "get_by_uid",
        classmethod(lambda cls, uid: pytest.fail("index lookup must be batched")),
    )
    monkeypatch.setattr(
        PricingMarketDataSet,
        "_active_context",
        classmethod(lambda cls: "pricing-context"),
    )
    monkeypatch.setattr(
        Index,
        "_active_context",
        classmethod(lambda cls: "core-context"),
    )

    def fake_search_model(active_context, *, model, in_filters, limit):
        calls.append(("search", active_context, model.__name__, in_filters, limit))
        if model.__name__ == "PricingMarketDataSetTable":
            return {
                "rows": [
                    {
                        "uid": market_data_set_uid,
                        "set_key": "eod",
                        "display_name": "End of day",
                    }
                ]
            }
        if model.__name__ == "IndexTable":
            return {
                "rows": [
                    {
                        "uid": index_uid,
                        "unique_identifier": "USD-SOFR",
                        "index_type": "interest_rate",
                        "display_name": "USD SOFR",
                        "calculation_method": "custom",
                        "value_format": "percent",
                    }
                ]
            }
        raise AssertionError(model.__name__)

    monkeypatch.setattr("msm_pricing.api.curves.search_model", fake_search_model)

    response = Curve.list_curve_selections(curve_uid)

    assert response == {
        "curve": {
            "uid": curve_uid,
            "unique_identifier": "USD-SOFR-OFFER-BENCHMARK",
            "display_name": "USD SOFR offer benchmark",
            "curve_type": "discount",
        },
        "count": 2,
        "results": [
            {
                "binding_uid": binding_uid_1,
                "market_data_set": {
                    "uid": market_data_set_uid,
                    "set_key": "eod",
                    "display_name": "End of day",
                },
                "role_key": "z_spread_base",
                "quote_side": "offer",
                "selector": {
                    "type": "index",
                    "selector_key": str(index_uid),
                    "index_uid": index_uid,
                    "index_identifier": "USD-SOFR",
                    "display_name": "USD SOFR",
                },
                "status": "ACTIVE",
                "source": "example",
            },
            {
                "binding_uid": binding_uid_2,
                "market_data_set": {
                    "uid": market_data_set_uid,
                    "set_key": "eod",
                    "display_name": "End of day",
                },
                "role_key": "projection",
                "quote_side": "mid",
                "selector": {
                    "type": "index",
                    "selector_key": str(index_uid),
                    "index_uid": index_uid,
                    "index_identifier": "USD-SOFR",
                    "display_name": "USD SOFR",
                },
                "status": "ACTIVE",
                "source": "example",
            },
        ],
    }
    assert calls == [
        ("filter_for_curve", curve_uid, 5000, None),
        (
            "search",
            "pricing-context",
            "PricingMarketDataSetTable",
            {"uid": [market_data_set_uid]},
            1,
        ),
        (
            "search",
            "core-context",
            "IndexTable",
            {"uid": [index_uid]},
            1,
        ),
    ]


def test_curve_list_curve_selections_returns_none_when_curve_missing(monkeypatch) -> None:
    monkeypatch.setattr(Curve, "get_by_uid", classmethod(lambda cls, uid: None))

    assert Curve.list_curve_selections(uuid.uuid4()) is None


def test_curve_discount_curve_nodes_use_market_data_binding(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
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

        def get_historical_discount_curve_observation(self, curve_identifier, target_date):
            calls.append(("historical", curve_identifier, target_date))
            return {
                "nodes": [{"days_to_maturity": 28, "zero": 0.11}],
                "key_nodes": [
                    {
                        "maturity_date": "2026-06-29",
                        "source_reference": {
                            "type": "index",
                            "identifier": "USD_SOFR_SWAP_1M",
                        },
                        "quote": 0.11,
                    }
                ],
                "metadata_json": {"source_snapshot": "mock"},
            }, target_date

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
            "currency_code": None,
            "quote_side": None,
            "interpolation_method": None,
            "compounding": None,
            "source": None,
            "status": "ACTIVE",
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
        "key_nodes": [
            {
                "maturity_date": "2026-06-29",
                "source_reference": {
                    "type": "index",
                    "identifier": "USD_SOFR_SWAP_1M",
                },
                "quote": 0.11,
            }
        ],
        "metadata_json": {"source_snapshot": "mock"},
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

        def get_latest_discount_curve_observation(self, curve_identifier):
            assert curve_identifier == "USD-SOFR-DISCOUNT"
            return {
                "nodes": [{"days_to_maturity": 91, "zero": 0.105}],
                "key_nodes": [{"maturity_date": "2026-08-31", "quote": 0.105}],
                "metadata_json": {"source_snapshot": "mock-latest"},
            }, latest_date

    monkeypatch.setattr("msm_pricing.data_interface.MSDataInterface", FakeMSDataInterface)

    response = Curve.get_discount_curve_nodes(uid=curve_uid, market_data_set="live")

    assert response is not None
    assert response["valuation_date"] is None
    assert response["effective_date"] == latest_date
    assert response["request_mode"] == "latest"
    assert response["nodes"] == [{"days_to_maturity": 91, "zero": 0.105}]
    assert response["key_nodes"] == [{"maturity_date": "2026-08-31", "quote": 0.105}]
    assert response["metadata_json"] == {"source_snapshot": "mock-latest"}


def test_curve_discount_curve_nodes_explain_missing_latest_observation(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()

    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        classmethod(
            lambda cls, uid: Curve(
                uid=curve_uid,
                unique_identifier="VALMER_TIIE_28",
                display_name="Valmer TIIE 28 zero curve",
                curve_type="discount",
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
                set_key="default",
                display_name="Default",
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
                storage_table_identifier="ms_markets__discountcurvests",
            )
        ),
    )

    class FakeMSDataInterface:
        def __init__(self, market_data_configuration):
            pass

        def get_latest_discount_curve(self, curve_identifier):
            raise LookupError(
                f"No latest discount curve observation found for {curve_identifier!r}."
            )

    monkeypatch.setattr("msm_pricing.data_interface.MSDataInterface", FakeMSDataInterface)

    with pytest.raises(LookupError) as exc_info:
        Curve.get_discount_curve_nodes(uid=curve_uid, market_data_set="default")

    message = str(exc_info.value)
    assert "No discount-curve data has been published" in message
    assert "VALMER_TIIE_28" in message
    assert "pricing market-data set 'default'" in message
    assert f"bound DataNode {data_node_uid}" in message
    assert "has no latest ms_markets__discountcurvests observation" in message


def test_curve_discount_curve_nodes_return_none_when_curve_missing(monkeypatch) -> None:
    monkeypatch.setattr(Curve, "get_by_uid", classmethod(lambda cls, uid: None))

    assert Curve.get_discount_curve_nodes(uid=uuid.uuid4(), market_data_set="eod") is None


def test_curve_filter_uses_pricing_runtime_filters(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
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
                }
            ]
        }

    monkeypatch.setattr(
        "msm_pricing.api.curves.search_model",
        fake_search_model,
    )

    rows = Curve.filter(curve_type="discount", source=None, limit=2)

    assert rows == [
        Curve(
            uid=curve_uid,
            unique_identifier="USD-SOFR-DISCOUNT",
            display_name="USD SOFR Discount Curve",
            curve_type="discount",
        )
    ]
    assert calls == [
        (
            context,
            CurveTable,
            {
                "curve_type": "discount",
            },
            2,
        )
    ]


def test_curve_list_uses_paginated_runtime_search(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
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
            )
        ],
    }
    assert calls == [
        (
            "count",
            context,
            CurveTable,
            {"curve_type": "discount"},
            {"unique_identifier": "SOFR"},
        ),
        (
            "search",
            context,
            CurveTable,
            {"curve_type": "discount"},
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


def test_curve_delete_impact_blocks_until_explicit_cleanup_flags(monkeypatch) -> None:
    curve = _pricing_curve()
    context = SimpleNamespace(timeout=30)
    calls: list[object] = []

    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        classmethod(lambda cls, uid: curve),
    )
    monkeypatch.setattr(
        "msm_pricing.api.curves._active_curve_delete_context",
        lambda: context,
    )

    def fake_count_model_rows(active_context, *, model, filters):
        calls.append(("count", active_context, model.__name__, filters))
        if model.__name__ == "CurveBuildingDetailsTable":
            return 1
        if model.__name__ == "PricingMarketDataSetCurveBindingTable":
            return 2
        raise AssertionError(model.__name__)

    def fake_observation_counts(**kwargs):
        calls.append(("observations", kwargs))
        return 3, 0, 1

    monkeypatch.setattr(
        "msm_pricing.api.curves._count_model_rows",
        fake_count_model_rows,
    )
    monkeypatch.setattr(
        "msm_pricing.api.curves._discount_curve_observation_impact_counts",
        fake_observation_counts,
    )

    blocked = Curve.get_delete_impact(uid=curve.uid)
    allowed = Curve.get_delete_impact(
        uid=curve.uid,
        delete_values=True,
        delete_curve_selections=True,
    )

    assert blocked is not None
    assert blocked["can_delete"] is False
    assert blocked["blocking_count"] == 5
    assert {
        relationship["key"]: relationship["blocks_delete"]
        for relationship in blocked["relationships"]
    } == {
        "curve_building_details": False,
        "pricing_curve_selections": True,
        "discount_curve_observations": True,
        "discount_curve_storage_sources": False,
    }

    assert allowed is not None
    assert allowed["can_delete"] is True
    assert allowed["blocking_count"] == 0
    assert {
        relationship["key"]: relationship["effect"] for relationship in allowed["relationships"]
    }["discount_curve_observations"] == "delete_cleanup"
    assert calls[0] == (
        "count",
        context,
        "CurveBuildingDetailsTable",
        {"curve_uid": curve.uid},
    )


def test_curve_delete_runs_value_and_selection_cleanup_before_row_delete(monkeypatch) -> None:
    curve = _pricing_curve()
    context = SimpleNamespace(timeout=30)
    calls: list[object] = []

    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        classmethod(lambda cls, uid: curve),
    )

    def fake_delete_impact(cls, *, uid, delete_values, delete_curve_selections):
        calls.append(("impact", uid, delete_values, delete_curve_selections))
        return {
            "can_delete": True,
            "relationships": [
                {
                    "key": "curve_building_details",
                    "label": "Curve building details",
                    "count": 1,
                    "blocks_delete": False,
                }
            ],
        }

    def fake_delete_values(**kwargs):
        calls.append(("values", kwargs["context"], kwargs["curve_identifier"]))
        return [
            {
                "data_node_uid": str(uuid.uuid4()),
                "storage_table_identifier": "DiscountCurvesStorage",
                "deleted_count": 3,
                "table_empty": False,
            }
        ]

    def fake_delete_selections(*, curve_uid):
        calls.append(("selections", curve_uid))
        return 2

    def fake_delete_model(active_context, *, model, uid):
        calls.append(("delete", active_context, model, uid))
        return {"deleted_count": 1}

    monkeypatch.setattr(Curve, "get_delete_impact", classmethod(fake_delete_impact))
    monkeypatch.setattr(
        "msm_pricing.api.curves._active_curve_delete_context",
        lambda: context,
    )
    monkeypatch.setattr(
        "msm_pricing.api.curves._delete_discount_curve_values",
        fake_delete_values,
    )
    monkeypatch.setattr(
        "msm_pricing.api.curves._delete_curve_selection_rows",
        fake_delete_selections,
    )
    monkeypatch.setattr("msm_pricing.api.curves.delete_model", fake_delete_model)

    response = Curve.delete(
        curve.uid,
        delete_values=True,
        delete_curve_selections=True,
    )

    assert response is not None
    assert response["deleted_count"] == 1
    assert response["deleted_values_count"] == 3
    assert response["deleted_curve_selections_count"] == 2
    assert response["deleted_curve_building_details_count"] == 1
    assert calls == [
        ("impact", curve.uid, True, True),
        ("values", context, "USD-SOFR-DISCOUNT"),
        ("selections", curve.uid),
        ("delete", context, CurveTable, curve.uid),
    ]


def test_curve_delete_raises_conflict_when_preflight_blocks(monkeypatch) -> None:
    curve = _pricing_curve()

    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        classmethod(lambda cls, uid: curve),
    )
    monkeypatch.setattr(
        Curve,
        "get_delete_impact",
        classmethod(
            lambda cls, **kwargs: {
                "can_delete": False,
                "relationships": [
                    {
                        "key": "pricing_curve_selections",
                        "label": "Pricing curve selections",
                        "count": 2,
                        "blocks_delete": True,
                    }
                ],
            }
        ),
    )

    with pytest.raises(CurveDeleteConflictError, match="Pricing curve selections"):
        Curve.delete(curve.uid)


def test_curve_value_cleanup_uses_scoped_time_index_delete(monkeypatch) -> None:
    import msm_pricing.api.curves as curves_api

    data_node_uid = uuid.uuid4()
    calls: list[object] = []

    class FakeDiscountCurveTable:
        uid = data_node_uid
        identifier = "DiscountCurvesStorage"
        columns = [SimpleNamespace(name="curve_identifier")]
        table_index_names = ["curve_identifier"]

        def delete_after_date(self, after_date, *, dimension_filters, timeout):
            calls.append((after_date, dimension_filters, timeout))
            return {"deleted_count": 3, "table_empty": False}

    table = FakeDiscountCurveTable()
    monkeypatch.setattr(
        curves_api,
        "_discount_curve_storage_scopes",
        lambda *, context: [
            {
                "data_node_uid": str(data_node_uid),
                "storage_table_identifier": "DiscountCurvesStorage",
                "time_index_meta_table": table,
                "unsupported_reason": None,
            }
        ],
    )

    response = curves_api._delete_discount_curve_values(
        context=SimpleNamespace(timeout=99),
        curve_identifier="USD'SOFR",
    )

    assert calls == [
        (
            None,
            {"curve_identifier": ["USD'SOFR"]},
            99,
        )
    ]
    assert response == [
        {
            "data_node_uid": str(data_node_uid),
            "storage_table_identifier": "DiscountCurvesStorage",
            "deleted_count": 3,
            "table_empty": False,
        }
    ]
