from __future__ import annotations

import uuid
from types import SimpleNamespace

from msm.api.indices import Index, IndexUpsert
from msm.models.registration import markets_meta_table_fullname
from msm.models import IndexTable


def test_index_api_declares_table_contract() -> None:
    assert Index.__table__ is IndexTable
    assert Index.__required_tables__ == [IndexTable]
    assert Index.__upsert_keys__ == ("unique_identifier",)


def test_index_create_schemas_delegates_to_required_table(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_create_schemas(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr("msm.bootstrap.create_schemas", fake_create_schemas)

    assert Index.create_schemas(namespace="mainsequence.examples") is runtime
    assert calls == [
        {
            "models": [IndexTable],
            "namespace": "mainsequence.examples",
        }
    ]


def test_index_upsert_uses_active_runtime(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(
        context=context,
        target_meta_table_uid_by_fullname={
            markets_meta_table_fullname(IndexTable): str(uuid.uuid4()),
        },
    )
    calls = []

    def fake_resolve_runtime(**kwargs):
        assert kwargs["models"] == Index.__required_tables__
        assert kwargs["row_model_name"] == "Index"
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append((active_context, model, values, conflict_columns))
        return {
            "row": {
                "uid": str(index_uid),
                **values,
            }
        }

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.api.base.upsert_model", fake_upsert_model)

    index = Index.upsert(
        IndexUpsert(
            unique_identifier="SPX",
            display_name="S&P 500 Index",
            provider="example",
        )
    )

    assert index == Index(
        uid=index_uid,
        unique_identifier="SPX",
        display_name="S&P 500 Index",
        provider="example",
    )
    assert calls == [
        (
            context,
            IndexTable,
            {
                "unique_identifier": "SPX",
                "display_name": "S&P 500 Index",
                "provider": "example",
            },
            ("unique_identifier",),
        )
    ]
