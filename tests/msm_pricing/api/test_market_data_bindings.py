from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm_pricing.api.market_data_bindings import (
    PricingMarketDataSet,
    PricingMarketDataSetBinding,
    PricingMarketDataSetBindingUpsert,
    PricingMarketDataSetUpsert,
)
from msm_pricing.models import (
    PricingMarketDataSetBindingTable,
    PricingMarketDataSetTable,
)
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_MARKET_DATA_SET_DEFAULT,
)


def test_pricing_market_data_set_api_declares_table_contract() -> None:
    assert PricingMarketDataSet.__table__ is PricingMarketDataSetTable
    assert PricingMarketDataSet.__required_tables__ == [PricingMarketDataSetTable]
    assert PricingMarketDataSet.__upsert_keys__ == ("set_key",)


def test_pricing_market_data_binding_api_declares_table_contract() -> None:
    assert PricingMarketDataSetBinding.__table__ is PricingMarketDataSetBindingTable
    assert PricingMarketDataSetBinding.__required_tables__ == [
        PricingMarketDataSetTable,
        PricingMarketDataSetBindingTable,
    ]
    assert PricingMarketDataSetBinding.__upsert_keys__ == (
        "market_data_set_uid",
        "concept_key",
    )


def test_pricing_market_data_set_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        PricingMarketDataSetUpsert(
            set_key=PRICING_MARKET_DATA_SET_DEFAULT,
            display_name="Default",
            context_key="legacy",
        )


def test_pricing_market_data_binding_payload_rejects_identifier_only_contract() -> None:
    market_data_set_uid = uuid.uuid4()

    with pytest.raises(ValidationError, match="Extra inputs"):
        PricingMarketDataSetBindingUpsert(
            market_data_set_uid=market_data_set_uid,
            concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
            data_node_uid=uuid.uuid4(),
            data_node_identifier="discount_curves",
        )


def test_pricing_market_data_binding_row_accepts_physical_metadata_alias() -> None:
    market_data_set_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()

    row = PricingMarketDataSetBinding.model_validate(
        {
            "uid": uuid.uuid4(),
            "market_data_set_uid": market_data_set_uid,
            "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
            "data_node_uid": data_node_uid,
            "storage_table_identifier": "registered.discount_curves",
            "metadata": {"provider": "unit-test"},
        }
    )

    assert row.metadata_json == {"provider": "unit-test"}


def test_pricing_market_data_set_upsert_uses_set_key(monkeypatch) -> None:
    market_data_set_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    def fake_resolve_pricing_runtime(**kwargs):
        calls.append(("runtime", kwargs))
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append(("upsert", active_context, model, values, conflict_columns))
        return {"row": {"uid": market_data_set_uid, **values}}

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        fake_resolve_pricing_runtime,
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.upsert_model",
        fake_upsert_model,
    )

    row = PricingMarketDataSet.upsert(
        set_key=PRICING_MARKET_DATA_SET_DEFAULT,
        display_name="Default",
        description="Default pricing sources.",
        metadata_json={"seeded": True},
    )

    assert row == PricingMarketDataSet(
        uid=market_data_set_uid,
        set_key=PRICING_MARKET_DATA_SET_DEFAULT,
        display_name="Default",
        description="Default pricing sources.",
        metadata_json={"seeded": True},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [PricingMarketDataSetTable],
                "row_model_name": "PricingMarketDataSet",
            },
        ),
        (
            "upsert",
            context,
            PricingMarketDataSetTable,
            {
                "set_key": PRICING_MARKET_DATA_SET_DEFAULT,
                "display_name": "Default",
                "description": "Default pricing sources.",
                "status": "ACTIVE",
                "metadata_json": {"seeded": True},
            },
            ("set_key",),
        ),
    ]


def test_pricing_market_data_binding_upsert_uses_set_uid_concept_key(
    monkeypatch,
) -> None:
    binding_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()
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

    row = PricingMarketDataSetBinding.upsert(
        market_data_set_uid=market_data_set_uid,
        concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
        data_node_uid=data_node_uid,
        storage_table_identifier="registered.discount_curves",
        source="unit-test",
        metadata_json={"seeded": True},
    )

    assert row == PricingMarketDataSetBinding(
        uid=binding_uid,
        market_data_set_uid=market_data_set_uid,
        concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
        data_node_uid=data_node_uid,
        storage_table_identifier="registered.discount_curves",
        source="unit-test",
        metadata_json={"seeded": True},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [
                    PricingMarketDataSetTable,
                    PricingMarketDataSetBindingTable,
                ],
                "row_model_name": "PricingMarketDataSetBinding",
            },
        ),
        (
            "upsert",
            context,
            PricingMarketDataSetBindingTable,
            {
                "market_data_set_uid": market_data_set_uid,
                "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
                "data_node_uid": data_node_uid,
                "storage_table_identifier": "registered.discount_curves",
                "source": "unit-test",
                "metadata_json": {"seeded": True},
            },
            ("market_data_set_uid", "concept_key"),
        ),
    ]


def test_pricing_market_data_binding_resolves_data_node_uid(monkeypatch) -> None:
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda market_data_set=None: market_data_set_uid),
    )
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
                    "market_data_set_uid": market_data_set_uid,
                    "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
                    "data_node_uid": data_node_uid,
                }
            ]
        }

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.search_model",
        fake_search_model,
    )

    assert (
        PricingMarketDataSetBinding.resolve_data_node_uid(
            market_data_set=PRICING_MARKET_DATA_SET_DEFAULT,
            concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
        )
        == data_node_uid
    )
    assert calls == [
        (
            context,
            PricingMarketDataSetBindingTable,
            {
                "market_data_set_uid": market_data_set_uid,
                "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
            },
            1,
        )
    ]


def test_pricing_market_data_binding_missing_concept_fails_before_data_node_lookup(
    monkeypatch,
) -> None:
    market_data_set_uid = uuid.uuid4()

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda market_data_set=None: market_data_set_uid),
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=object()),
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.search_model",
        lambda *_args, **_kwargs: {"rows": []},
    )

    with pytest.raises(LookupError, match=PRICING_CONCEPT_DISCOUNT_CURVES):
        PricingMarketDataSetBinding.resolve_data_node_uid(
            market_data_set=PRICING_MARKET_DATA_SET_DEFAULT,
            concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
        )
