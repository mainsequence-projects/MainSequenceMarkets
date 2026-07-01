from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm_pricing.api.market_data_bindings import (
    IndexCurveSelection,
    IndexCurveSelectionUpsert,
    PricingMarketDataSet,
    PricingMarketDataSetBinding,
    PricingMarketDataSetBindingUpsert,
    PricingMarketDataSetCurveBinding,
    PricingMarketDataSetCurveBindingUpsert,
    PricingMarketDataSetUpsert,
    curve_binding_key,
)
from msm_pricing.models import (
    CurveTable,
    PricingMarketDataSetBindingTable,
    PricingMarketDataSetCurveBindingTable,
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


def test_pricing_market_data_curve_binding_api_declares_table_contract() -> None:
    assert PricingMarketDataSetCurveBinding.__table__ is PricingMarketDataSetCurveBindingTable
    assert PricingMarketDataSetCurveBinding.__required_tables__ == [
        PricingMarketDataSetTable,
        CurveTable,
        PricingMarketDataSetCurveBindingTable,
    ]
    assert PricingMarketDataSetCurveBinding.__upsert_keys__ == (
        "market_data_set_uid",
        "binding_key",
    )


def test_curve_binding_key_normalizes_role_selector_and_quote_side() -> None:
    assert (
        curve_binding_key(
            role_key=" Discount ",
            selector_type=" Currency ",
            selector_key=" usd ",
            quote_side=" MID ",
        )
        == "discount:currency:USD:mid"
    )
    assert (
        curve_binding_key(
            role_key="projection",
            selector_type="index",
            selector_key="00000000-0000-0000-0000-000000000001",
        )
        == "projection:index:00000000-0000-0000-0000-000000000001:default"
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


def test_pricing_market_data_curve_binding_payload_rejects_identifier_only_contract() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        PricingMarketDataSetCurveBindingUpsert(
            market_data_set_uid=uuid.uuid4(),
            role_key="discount",
            selector_type="currency",
            selector_key="USD",
            curve_uid=uuid.uuid4(),
            curve_unique_identifier="USD-OIS-DISCOUNT",
        )


def test_index_curve_selection_payload_rejects_selector_plumbing() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        IndexCurveSelectionUpsert(
            market_data_set_uid=uuid.uuid4(),
            role_key="projection",
            index_uid=uuid.uuid4(),
            selector_type="index",
            curve_uid=uuid.uuid4(),
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


def test_pricing_market_data_curve_binding_row_accepts_physical_metadata_alias() -> None:
    market_data_set_uid = uuid.uuid4()
    curve_uid = uuid.uuid4()

    row = PricingMarketDataSetCurveBinding.model_validate(
        {
            "uid": uuid.uuid4(),
            "market_data_set_uid": market_data_set_uid,
            "binding_key": "discount:currency:USD:mid",
            "role_key": "discount",
            "selector_type": "currency",
            "selector_key": "USD",
            "quote_side": "mid",
            "curve_uid": curve_uid,
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


def test_pricing_market_data_curve_binding_upsert_derives_binding_key(
    monkeypatch,
) -> None:
    binding_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    curve_uid = uuid.uuid4()
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

    row = PricingMarketDataSetCurveBinding.upsert(
        market_data_set_uid=market_data_set_uid,
        role_key="Discount",
        selector_type="Currency",
        selector_key="usd",
        quote_side="MID",
        curve_uid=curve_uid,
        source="unit-test",
        metadata_json={"seeded": True},
    )

    assert row == PricingMarketDataSetCurveBinding(
        uid=binding_uid,
        market_data_set_uid=market_data_set_uid,
        binding_key="discount:currency:USD:mid",
        role_key="discount",
        selector_type="currency",
        selector_key="USD",
        quote_side="mid",
        curve_uid=curve_uid,
        source="unit-test",
        metadata_json={"seeded": True},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [
                    PricingMarketDataSetTable,
                    CurveTable,
                    PricingMarketDataSetCurveBindingTable,
                ],
                "row_model_name": "PricingMarketDataSetCurveBinding",
            },
        ),
        (
            "upsert",
            context,
            PricingMarketDataSetCurveBindingTable,
            {
                "market_data_set_uid": market_data_set_uid,
                "binding_key": "discount:currency:USD:mid",
                "role_key": "discount",
                "selector_type": "currency",
                "selector_key": "USD",
                "quote_side": "mid",
                "curve_uid": curve_uid,
                "source": "unit-test",
                "priority": 0,
                "status": "ACTIVE",
                "metadata_json": {"seeded": True},
            },
            ("market_data_set_uid", "binding_key"),
        ),
    ]


def test_pricing_market_data_curve_binding_counts_reverse_relationships(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    def fake_count_model(active_context, *, model, filters):
        calls.append((active_context, model, filters))
        return {"rows": [{"count": 4}]}

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.count_model",
        fake_count_model,
    )

    assert PricingMarketDataSetCurveBinding.count_for_curve(curve_uid=curve_uid) == 4
    assert (
        PricingMarketDataSetCurveBinding.count_index_selector_references(index_uid=index_uid) == 4
    )
    assert calls == [
        (
            context,
            PricingMarketDataSetCurveBindingTable,
            {"curve_uid": curve_uid},
        ),
        (
            context,
            PricingMarketDataSetCurveBindingTable,
            {
                "selector_type": "index",
                "selector_key": str(index_uid),
            },
        ),
    ]


def test_index_curve_selection_upsert_hides_selector_plumbing(monkeypatch) -> None:
    binding_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    curve_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda market_data_set=None: market_data_set_uid),
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        lambda **kwargs: calls.append(("runtime", kwargs)) or runtime,
    )

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append(("upsert", active_context, model, values, conflict_columns))
        return {"row": {"uid": binding_uid, **values}}

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.upsert_model",
        fake_upsert_model,
    )

    selection = PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
        market_data_set="eod",
        role_key=" Projection ",
        index_uid=index_uid,
        quote_side=" MID ",
        curve_uid=curve_uid,
        source="unit-test",
        metadata_json={"seeded": True},
    )

    assert selection == IndexCurveSelection(
        uid=binding_uid,
        market_data_set_uid=market_data_set_uid,
        role_key="projection",
        index_uid=index_uid,
        quote_side="mid",
        curve_uid=curve_uid,
        source="unit-test",
        metadata_json={"seeded": True},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [
                    PricingMarketDataSetTable,
                    CurveTable,
                    PricingMarketDataSetCurveBindingTable,
                ],
                "row_model_name": "PricingMarketDataSetCurveBinding",
            },
        ),
        (
            "upsert",
            context,
            PricingMarketDataSetCurveBindingTable,
            {
                "market_data_set_uid": market_data_set_uid,
                "binding_key": f"projection:index:{index_uid}:mid",
                "role_key": "projection",
                "selector_type": "index",
                "selector_key": str(index_uid),
                "quote_side": "mid",
                "curve_uid": curve_uid,
                "source": "unit-test",
                "priority": 0,
                "status": "ACTIVE",
                "metadata_json": {"seeded": True},
            },
            ("market_data_set_uid", "binding_key"),
        ),
    ]


def test_pricing_market_data_set_delete_uses_active_context(monkeypatch) -> None:
    market_data_set_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        lambda **kwargs: calls.append(("runtime", kwargs)) or SimpleNamespace(context=context),
    )

    def fake_delete_model(active_context, *, model, uid):
        calls.append(("delete", active_context, model, uid))
        return {"deleted_count": 1}

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.delete_model",
        fake_delete_model,
    )

    assert PricingMarketDataSet.delete(market_data_set_uid) == {"deleted_count": 1}
    assert calls == [
        (
            "runtime",
            {
                "models": [PricingMarketDataSetTable],
                "row_model_name": "PricingMarketDataSet",
            },
        ),
        ("delete", context, PricingMarketDataSetTable, market_data_set_uid),
    ]


def test_pricing_market_data_set_list_uses_true_pagination(monkeypatch) -> None:
    market_data_set_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        lambda **kwargs: calls.append(("runtime", kwargs)) or SimpleNamespace(context=context),
    )

    def fake_count_model(active_context, *, model, filters):
        calls.append(("count", active_context, model, filters))
        return {"rows": [{"count": 3}]}

    def fake_search_model(active_context, *, model, filters, limit, offset=0):
        calls.append(("search", active_context, model, filters, limit, offset))
        return {
            "rows": [
                {
                    "uid": market_data_set_uid,
                    "set_key": "default",
                    "display_name": "Default",
                    "status": "ACTIVE",
                }
            ]
        }

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.count_model",
        fake_count_model,
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.search_model",
        fake_search_model,
    )

    response = PricingMarketDataSet.list(limit=1, offset=2, status="ACTIVE")

    assert response == {
        "count": 3,
        "limit": 1,
        "offset": 2,
        "results": [
            PricingMarketDataSet(
                uid=market_data_set_uid,
                set_key="default",
                display_name="Default",
                status="ACTIVE",
            )
        ],
    }
    assert calls == [
        (
            "runtime",
            {
                "models": [PricingMarketDataSetTable],
                "row_model_name": "PricingMarketDataSet",
            },
        ),
        ("count", context, PricingMarketDataSetTable, {"status": "ACTIVE"}),
        ("search", context, PricingMarketDataSetTable, {"status": "ACTIVE"}, 1, 2),
    ]


def test_pricing_market_data_binding_delete_uses_active_context(monkeypatch) -> None:
    binding_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        lambda **kwargs: calls.append(("runtime", kwargs)) or SimpleNamespace(context=context),
    )

    def fake_delete_model(active_context, *, model, uid):
        calls.append(("delete", active_context, model, uid))
        return {"deleted_count": 1}

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.delete_model",
        fake_delete_model,
    )

    assert PricingMarketDataSetBinding.delete(binding_uid) == {"deleted_count": 1}
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
        ("delete", context, PricingMarketDataSetBindingTable, binding_uid),
    ]


def test_pricing_market_data_binding_list_uses_true_pagination(monkeypatch) -> None:
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.resolve_pricing_runtime",
        lambda **kwargs: calls.append(("runtime", kwargs)) or SimpleNamespace(context=context),
    )

    def fake_count_model(active_context, *, model, filters):
        calls.append(("count", active_context, model, filters))
        return {"rows": [{"count": 4}]}

    def fake_search_model(active_context, *, model, filters, limit, offset=0):
        calls.append(("search", active_context, model, filters, limit, offset))
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
        "msm_pricing.api.market_data_bindings.count_model",
        fake_count_model,
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.search_model",
        fake_search_model,
    )

    response = PricingMarketDataSetBinding.list(
        limit=1,
        offset=3,
        market_data_set_uid=market_data_set_uid,
        concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
    )

    assert response == {
        "count": 4,
        "limit": 1,
        "offset": 3,
        "results": [
            PricingMarketDataSetBinding(
                uid=binding_uid,
                market_data_set_uid=market_data_set_uid,
                concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
                data_node_uid=data_node_uid,
            )
        ],
    }
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
            "count",
            context,
            PricingMarketDataSetBindingTable,
            {
                "market_data_set_uid": market_data_set_uid,
                "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
            },
        ),
        (
            "search",
            context,
            PricingMarketDataSetBindingTable,
            {
                "market_data_set_uid": market_data_set_uid,
                "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
            },
            1,
            3,
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


def test_pricing_market_data_curve_binding_resolves_curve_uid(monkeypatch) -> None:
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    curve_uid = uuid.uuid4()
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
                    "binding_key": "projection:index:00000000-0000-0000-0000-000000000001:mid",
                    "role_key": "projection",
                    "selector_type": "index",
                    "selector_key": "00000000-0000-0000-0000-000000000001",
                    "quote_side": "mid",
                    "curve_uid": curve_uid,
                    "status": "ACTIVE",
                }
            ]
        }

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.search_model",
        fake_search_model,
    )

    assert (
        PricingMarketDataSetCurveBinding.resolve_curve_uid(
            market_data_set="eod",
            role_key="projection",
            selector_type="index",
            selector_key="00000000-0000-0000-0000-000000000001",
            quote_side="mid",
        )
        == curve_uid
    )
    assert calls == [
        (
            context,
            PricingMarketDataSetCurveBindingTable,
            {
                "market_data_set_uid": market_data_set_uid,
                "binding_key": "projection:index:00000000-0000-0000-0000-000000000001:mid",
                "status": "ACTIVE",
            },
            2,
        )
    ]


def test_pricing_market_data_index_curve_selection_resolves_curve_uid(monkeypatch) -> None:
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    curve_uid = uuid.uuid4()
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
                    "binding_key": f"z_spread_base:index:{index_uid}:offer",
                    "role_key": "z_spread_base",
                    "selector_type": "index",
                    "selector_key": str(index_uid),
                    "quote_side": "offer",
                    "curve_uid": curve_uid,
                    "status": "ACTIVE",
                }
            ]
        }

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.search_model",
        fake_search_model,
    )

    assert (
        PricingMarketDataSetCurveBinding.resolve_index_curve_uid(
            market_data_set="eod",
            role_key="z_spread_base",
            index_uid=index_uid,
            quote_side="offer",
        )
        == curve_uid
    )
    assert calls == [
        (
            context,
            PricingMarketDataSetCurveBindingTable,
            {
                "market_data_set_uid": market_data_set_uid,
                "binding_key": f"z_spread_base:index:{index_uid}:offer",
                "status": "ACTIVE",
            },
            2,
        )
    ]


def test_pricing_market_data_curve_binding_missing_selector_fails_loudly(
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

    with pytest.raises(LookupError, match="No pricing market-data curve binding found"):
        PricingMarketDataSetCurveBinding.resolve_curve_uid(
            market_data_set=PRICING_MARKET_DATA_SET_DEFAULT,
            role_key="discount",
            selector_type="currency",
            selector_key="USD",
            quote_side="mid",
        )
