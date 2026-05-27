from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from msm.api.derivatives import (
    FUTURE_ASSET_TYPE,
    Future,
    FutureKind,
    FutureSettlementMethod,
    FutureSettlementModel,
    FutureUpsert,
)
from msm.models import AssetTable, AssetTypeTable, FutureDetailsTable, IndexTable


def test_future_api_declares_required_table_contract() -> None:
    assert Future.__required_tables__ == [
        AssetTypeTable,
        AssetTable,
        IndexTable,
        FutureDetailsTable,
    ]


def test_future_payload_normalizes_enum_and_unit_values() -> None:
    payload = FutureUpsert(
        unique_identifier="CME:ESZ6",
        kind="expiring",
        underlying_index_uid=uuid.uuid4(),
        quote_unit=" index_point ",
        settlement_asset=uuid.uuid4(),
        margin_asset=uuid.uuid4(),
        settlement_model="linear",
        settlement_method="cash",
        contract_size=Decimal("50"),
        contract_unit=" index_point ",
        expires_at=dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC),
    )

    assert payload.kind == FutureKind.EXPIRING.value
    assert payload.quote_unit == "INDEX_POINT"
    assert payload.settlement_model == FutureSettlementModel.LINEAR.value
    assert payload.settlement_method == FutureSettlementMethod.CASH.value
    assert payload.contract_unit == "INDEX_POINT"


def test_future_payload_rejects_invalid_contract_terms() -> None:
    base_payload = {
        "unique_identifier": "CME:ESZ6",
        "underlying_index_uid": uuid.uuid4(),
        "quote_unit": "INDEX_POINT",
        "settlement_asset": uuid.uuid4(),
        "margin_asset": uuid.uuid4(),
        "settlement_model": "LINEAR",
        "settlement_method": "CASH",
        "contract_size": Decimal("50"),
        "contract_unit": "INDEX_POINT",
    }

    with pytest.raises(ValueError, match="PERPETUAL"):
        FutureUpsert(
            **base_payload,
            kind="PERPETUAL",
            expires_at=dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC),
        )

    with pytest.raises(ValueError, match="EXPIRING"):
        FutureUpsert(
            **base_payload,
            kind="EXPIRING",
        )

    with pytest.raises(ValueError, match="contract_size"):
        FutureUpsert(
            **{**base_payload, "contract_size": Decimal("0")},
            kind="PERPETUAL",
        )


def test_future_upsert_owns_multitable_workflow(monkeypatch) -> None:
    future_uid = uuid.uuid4()
    underlying_index_uid = uuid.uuid4()
    settlement_uid = uuid.uuid4()
    margin_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    def fake_resolve_runtime(**kwargs):
        assert kwargs["models"] == Future.__required_tables__
        assert kwargs["row_model_name"] == "Future"
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append((active_context, model, values, conflict_columns))
        if model is AssetTypeTable:
            return {"row": {"uid": str(uuid.uuid4()), **values}}
        if model is AssetTable:
            return {"row": {"uid": str(future_uid), **values}}
        if model is FutureDetailsTable:
            return {"row": {**values}}
        raise AssertionError(model)

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.api.derivatives.upsert_model", fake_upsert_model)

    future = Future.upsert(
        FutureUpsert(
            unique_identifier="CME:ESZ6",
            kind="expiring",
            underlying_index_uid=underlying_index_uid,
            quote_unit="index_point",
            settlement_asset=settlement_uid,
            margin_asset=margin_uid,
            settlement_model="linear",
            settlement_method="cash",
            contract_size=Decimal("50"),
            contract_unit="index_point",
            expires_at=dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC),
            settles_at=dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC),
            metadata={"venue": "CME", "root": "ES"},
        )
    )

    assert future == Future(
        uid=future_uid,
        asset_uid=future_uid,
        unique_identifier="CME:ESZ6",
        asset_type=FUTURE_ASSET_TYPE,
        kind="EXPIRING",
        underlying_index_uid=underlying_index_uid,
        quote_unit="INDEX_POINT",
        settlement_asset=settlement_uid,
        margin_asset=margin_uid,
        settlement_model="LINEAR",
        settlement_method="CASH",
        contract_size=Decimal("50"),
        contract_unit="INDEX_POINT",
        expires_at=dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC),
        settles_at=dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC),
        metadata={"venue": "CME", "root": "ES"},
    )
    assert calls == [
        (
            context,
            AssetTypeTable,
            {
                "asset_type": FUTURE_ASSET_TYPE,
                "display_name": "Future",
                "description": "Futures contracts represented as tradable assets.",
            },
            ("asset_type",),
        ),
        (
            context,
            AssetTable,
            {
                "unique_identifier": "CME:ESZ6",
                "asset_type": FUTURE_ASSET_TYPE,
            },
            ("unique_identifier",),
        ),
        (
            context,
            FutureDetailsTable,
            {
                "asset_uid": future_uid,
                "kind": "EXPIRING",
                "underlying_index_uid": underlying_index_uid,
                "quote_unit": "INDEX_POINT",
                "settlement_asset": settlement_uid,
                "margin_asset": margin_uid,
                "settlement_model": "LINEAR",
                "settlement_method": "CASH",
                "contract_size": Decimal("50"),
                "contract_unit": "INDEX_POINT",
                "expires_at": dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC),
                "settles_at": dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC),
                "metadata": {"venue": "CME", "root": "ES"},
            },
            ("asset_uid",),
        ),
    ]
