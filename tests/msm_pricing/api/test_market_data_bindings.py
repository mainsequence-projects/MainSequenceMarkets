from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm_pricing.api.market_data_bindings import (
    PricingMarketDataBinding,
    PricingMarketDataBindingUpsert,
)
from msm_pricing.models import PricingMarketDataBindingTable
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONTEXT_DEFAULT,
)


def test_pricing_market_data_binding_api_declares_table_contract() -> None:
    assert PricingMarketDataBinding.__table__ is PricingMarketDataBindingTable
    assert PricingMarketDataBinding.__required_tables__ == [PricingMarketDataBindingTable]
    assert PricingMarketDataBinding.__upsert_keys__ == ("context_key", "concept_key")


def test_pricing_market_data_binding_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        PricingMarketDataBindingUpsert(
            context_key=PRICING_CONTEXT_DEFAULT,
            concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
            data_node_identifier="discount_curves",
            data_node_uid=uuid.uuid4(),
        )


def test_pricing_market_data_binding_row_accepts_physical_metadata_alias() -> None:
    row = PricingMarketDataBinding.model_validate(
        {
            "uid": uuid.uuid4(),
            "context_key": PRICING_CONTEXT_DEFAULT,
            "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
            "data_node_identifier": "discount_curves",
            "metadata": {"provider": "unit-test"},
        }
    )

    assert row.metadata_json == {"provider": "unit-test"}


def test_pricing_market_data_binding_upsert_uses_context_concept_key(
    monkeypatch,
) -> None:
    binding_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    def fake_resolve_pricing_runtime(**kwargs):
        calls.append(("runtime", kwargs))
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append(("upsert", active_context, model, values, conflict_columns))
        return {"row": {"uid": binding_uid, **values}}

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        fake_resolve_pricing_runtime,
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.upsert_model",
        fake_upsert_model,
    )

    row = PricingMarketDataBinding.upsert(
        context_key=PRICING_CONTEXT_DEFAULT,
        concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
        data_node_identifier="discount_curves",
        source="unit-test",
        metadata_json={"seeded": True},
    )

    assert row == PricingMarketDataBinding(
        uid=binding_uid,
        context_key=PRICING_CONTEXT_DEFAULT,
        concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
        data_node_identifier="discount_curves",
        source="unit-test",
        metadata_json={"seeded": True},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [PricingMarketDataBindingTable],
                "row_model_name": "PricingMarketDataBinding",
            },
        ),
        (
            "upsert",
            context,
            PricingMarketDataBindingTable,
            {
                "context_key": PRICING_CONTEXT_DEFAULT,
                "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
                "data_node_identifier": "discount_curves",
                "source": "unit-test",
                "metadata_json": {"seeded": True},
            },
            ("context_key", "concept_key"),
        ),
    ]


def test_pricing_market_data_binding_resolves_identifier(monkeypatch) -> None:
    binding_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    def fake_search_model(active_context, *, model, filters, limit):
        calls.append((active_context, model, filters, limit))
        return {
            "rows": [
                {
                    "uid": binding_uid,
                    "context_key": PRICING_CONTEXT_DEFAULT,
                    "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
                    "data_node_identifier": "discount_curves",
                }
            ]
        }

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.search_model",
        fake_search_model,
    )

    assert (
        PricingMarketDataBinding.resolve_data_node_identifier(
            context_key=PRICING_CONTEXT_DEFAULT,
            concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
        )
        == "discount_curves"
    )
    assert calls == [
        (
            context,
            PricingMarketDataBindingTable,
            {
                "context_key": PRICING_CONTEXT_DEFAULT,
                "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
            },
            1,
        )
    ]
