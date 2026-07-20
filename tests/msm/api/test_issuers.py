from __future__ import annotations

import uuid
from types import SimpleNamespace

from msm.api.issuers import Issuer, IssuerUpsert
from msm.models import IssuerTable


def test_issuer_api_declares_table_contract() -> None:
    assert Issuer.__table__ is IssuerTable
    assert Issuer.__required_tables__ == [IssuerTable]
    assert Issuer.__upsert_keys__ == ("unique_identifier",)


def test_issuer_upsert_uses_active_runtime(monkeypatch) -> None:
    issuer_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    def fake_resolve_runtime(**kwargs):
        assert kwargs["models"] == Issuer.__required_tables__
        assert kwargs["row_model_name"] == "Issuer"
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append((active_context, model, values, conflict_columns))
        return {"row": {"uid": str(issuer_uid), **values}}

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.repositories.crud.upsert_model", fake_upsert_model)

    issuer = Issuer.upsert(
        IssuerUpsert(
            unique_identifier="example-issuer",
            display_name="Example Issuer",
            metadata_json={"country": "US"},
        )
    )

    assert issuer == Issuer(
        uid=issuer_uid,
        unique_identifier="example-issuer",
        display_name="Example Issuer",
        metadata_json={"country": "US"},
    )
    assert calls == [
        (
            context,
            IssuerTable,
            {
                "unique_identifier": "example-issuer",
                "display_name": "Example Issuer",
                "metadata_json": {"country": "US"},
            },
            ("unique_identifier",),
        )
    ]
