from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from msm.api.assets import (
    BOND_ASSET_TYPE,
    Bond,
    BondStatus,
    BondUpsert,
)
from msm.models import AssetTable, AssetTypeTable, BondDetailsTable, IssuerTable


def test_bond_api_declares_required_table_contract() -> None:
    assert Bond.__required_tables__ == [
        AssetTypeTable,
        AssetTable,
        IssuerTable,
        BondDetailsTable,
    ]


def test_bond_payload_normalizes_status() -> None:
    payload = BondUpsert(
        unique_identifier="example-bond",
        issuer_uid=uuid.uuid4(),
        currency_asset_uid=uuid.uuid4(),
        issue_date=dt.date(2026, 5, 27),
        maturity_date=dt.date(2031, 5, 27),
        status=" active ",
    )

    assert payload.status == BondStatus.ACTIVE.value


def test_bond_payload_rejects_invalid_terms() -> None:
    base_payload = {
        "unique_identifier": "example-bond",
        "issuer_uid": uuid.uuid4(),
        "currency_asset_uid": uuid.uuid4(),
        "issue_date": dt.date(2026, 5, 27),
        "status": "ACTIVE",
    }

    with pytest.raises(ValueError, match="Bond status"):
        BondUpsert(**{**base_payload, "status": "retired"})

    with pytest.raises(ValueError, match="maturity_date"):
        BondUpsert(
            **base_payload,
            maturity_date=dt.date(2026, 5, 26),
        )


def test_bond_upsert_owns_multitable_workflow(monkeypatch) -> None:
    bond_uid = uuid.uuid4()
    issuer_uid = uuid.uuid4()
    currency_asset_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    reads = []
    writes = []

    def fake_resolve_runtime(**kwargs):
        assert kwargs["models"] == Bond.__required_tables__
        assert kwargs["row_model_name"] == "Bond"
        return runtime

    def fake_get_model_by_uid(active_context, *, model, uid):
        reads.append((active_context, model, uid))
        return {"row": {"uid": str(uid)}}

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        writes.append((active_context, model, values, conflict_columns))
        if model is AssetTypeTable:
            return {"row": {"uid": str(uuid.uuid4()), **values}}
        if model is AssetTable:
            return {"row": {"uid": str(bond_uid), **values}}
        if model is BondDetailsTable:
            return {"row": {**values}}
        raise AssertionError(model)

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.api.assets.get_model_by_uid", fake_get_model_by_uid)
    monkeypatch.setattr("msm.api.assets.upsert_model", fake_upsert_model)

    bond = Bond.upsert(
        BondUpsert(
            unique_identifier="example-usd-bond-2031",
            issuer_uid=issuer_uid,
            currency_asset_uid=currency_asset_uid,
            issue_date=dt.date(2026, 5, 27),
            maturity_date=dt.date(2031, 5, 27),
            status="active",
        )
    )

    assert bond == Bond(
        uid=bond_uid,
        asset_uid=bond_uid,
        unique_identifier="example-usd-bond-2031",
        asset_type=BOND_ASSET_TYPE,
        issuer_uid=issuer_uid,
        currency_asset_uid=currency_asset_uid,
        issue_date=dt.date(2026, 5, 27),
        maturity_date=dt.date(2031, 5, 27),
        status=BondStatus.ACTIVE.value,
    )
    assert reads == [
        (context, IssuerTable, issuer_uid),
        (context, AssetTable, currency_asset_uid),
    ]
    assert writes == [
        (
            context,
            AssetTypeTable,
            {
                "asset_type": BOND_ASSET_TYPE,
                "display_name": "Bond",
                "description": "Debt instruments represented as tradable assets.",
            },
            ("asset_type",),
        ),
        (
            context,
            AssetTable,
            {
                "unique_identifier": "example-usd-bond-2031",
                "asset_type": BOND_ASSET_TYPE,
            },
            ("unique_identifier",),
        ),
        (
            context,
            BondDetailsTable,
            {
                "asset_uid": bond_uid,
                "issuer_uid": issuer_uid,
                "currency_asset_uid": currency_asset_uid,
                "issue_date": dt.date(2026, 5, 27),
                "maturity_date": dt.date(2031, 5, 27),
                "status": "ACTIVE",
            },
            ("asset_uid",),
        ),
    ]


def test_bond_upsert_rejects_missing_references(monkeypatch) -> None:
    context = object()
    runtime = SimpleNamespace(context=context)

    def fake_resolve_runtime(**_kwargs):
        return runtime

    def fake_get_model_by_uid(_active_context, *, model, uid):
        return {"rows": []}

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.api.assets.get_model_by_uid", fake_get_model_by_uid)

    with pytest.raises(LookupError, match="issuer_uid"):
        Bond.upsert(
            unique_identifier="example-usd-bond-2031",
            issuer_uid=uuid.uuid4(),
            currency_asset_uid=uuid.uuid4(),
            issue_date=dt.date(2026, 5, 27),
            status="ACTIVE",
        )
