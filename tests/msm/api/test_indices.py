from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm.api.indices import (
    Index,
    IndexType,
    IndexTypeUpsert,
    IndexUpdate,
    IndexUpsert,
    normalize_index_type,
)
from msm.constants import INDEX_TYPE_EQUITY, INDEX_TYPE_INTEREST_RATE
from msm.models import (
    IndexDatasetAvailabilityTable,
    IndexFormulaDefinitionTable,
    IndexFormulaInputTable,
    IndexTable,
    IndexTypeTable,
)


def test_index_api_declares_table_contract() -> None:
    assert Index.__table__ is IndexTable
    assert Index.__required_tables__ == [
        IndexTypeTable,
        IndexTable,
        IndexDatasetAvailabilityTable,
        IndexFormulaDefinitionTable,
        IndexFormulaInputTable,
    ]
    assert Index.__upsert_keys__ == ("unique_identifier",)


def test_index_type_api_declares_table_contract() -> None:
    assert IndexType.__table__ is IndexTypeTable
    assert IndexType.__required_tables__ == [IndexTypeTable]
    assert IndexType.__upsert_keys__ == ("index_type",)


def test_index_type_normalization_for_typed_payloads() -> None:
    assert normalize_index_type(" Interest Rate ") == INDEX_TYPE_INTEREST_RATE
    assert IndexTypeUpsert(index_type="Interest Rate").index_type == INDEX_TYPE_INTEREST_RATE
    assert (
        IndexUpsert(
            unique_identifier="USD-SOFR-3M",
            index_type="Interest Rate",
            display_name="USD SOFR 3M",
            calculation_method="formula",
            value_format="decimal",
        ).index_type
        == INDEX_TYPE_INTEREST_RATE
    )


def test_index_type_normalization_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="index_type"):
        normalize_index_type(" ")


def test_index_create_schemas_delegates_to_required_table(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_start_engine(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr("msm.bootstrap.start_engine", fake_start_engine)

    assert Index.start_engine(namespace="mainsequence.examples") is runtime
    assert calls == [
        {
            "models": [
                IndexTypeTable,
                IndexTable,
                IndexDatasetAvailabilityTable,
                IndexFormulaDefinitionTable,
                IndexFormulaInputTable,
            ],
            "namespace": "mainsequence.examples",
        }
    ]


def test_index_upsert_uses_active_runtime(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(
        context=context,
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
    monkeypatch.setattr("msm.repositories.crud.upsert_model", fake_upsert_model)
    monkeypatch.setattr(
        Index,
        "get_by_unique_identifier",
        classmethod(lambda _cls, _identifier: None),
    )

    index = Index.upsert(
        IndexUpsert(
            unique_identifier="SPX",
            index_type=INDEX_TYPE_EQUITY,
            display_name="S&P 500 Index",
            calculation_method="custom",
            value_format="decimal",
        )
    )

    assert index == Index(
        uid=index_uid,
        unique_identifier="SPX",
        index_type=INDEX_TYPE_EQUITY,
        display_name="S&P 500 Index",
        calculation_method="custom",
        value_format="decimal",
    )
    assert calls == [
        (
            context,
            IndexTable,
            {
                "unique_identifier": "SPX",
                "index_type": INDEX_TYPE_EQUITY,
                "display_name": "S&P 500 Index",
                "calculation_method": "custom",
                "value_format": "decimal",
            },
            ("unique_identifier",),
        )
    ]


def test_index_filter_by_uids_uses_single_in_filter(monkeypatch) -> None:
    first_uid = uuid.uuid4()
    second_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", lambda **_kwargs: runtime)

    def fake_search_model(active_context, *, model, in_filters, limit):
        calls.append((active_context, model, in_filters, limit))
        return {
            "rows": [
                {
                    "uid": first_uid,
                    "unique_identifier": "USD-SOFR",
                    "index_type": INDEX_TYPE_INTEREST_RATE,
                    "display_name": "USD SOFR",
                    "calculation_method": "custom",
                    "value_format": "decimal",
                },
                {
                    "uid": second_uid,
                    "unique_identifier": "MXN-TIIE",
                    "index_type": INDEX_TYPE_INTEREST_RATE,
                    "display_name": "MXN TIIE",
                    "calculation_method": "custom",
                    "value_format": "percent",
                },
            ]
        }

    monkeypatch.setattr("msm.api.indices.search_model", fake_search_model)

    rows = Index.filter_by_uids([first_uid, second_uid])

    assert [row.uid for row in rows] == [first_uid, second_uid]
    assert calls == [
        (
            context,
            IndexTable,
            {"uid": [first_uid, second_uid]},
            2,
        )
    ]


def test_index_delete_uses_standard_row_api(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", lambda **_kwargs: runtime)

    def fake_delete_model(active_context, *, model, uid):
        calls.append((active_context, model, uid))
        return {"deleted_count": 1}

    monkeypatch.setattr("msm.repositories.crud.delete_model", fake_delete_model)

    result = Index.delete(index_uid)

    assert result == {"deleted_count": 1}
    assert calls == [(context, IndexTable, index_uid)]


def test_index_related_meta_tables_forwards_optional_filters(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    index = Index(
        uid=index_uid,
        unique_identifier="USD-SOFR-3M",
        index_type=INDEX_TYPE_INTEREST_RATE,
        display_name="USD SOFR 3M",
        calculation_method="custom",
        value_format="decimal",
    )
    context = object()
    calls = []

    monkeypatch.setattr(Index, "get_by_uid", classmethod(lambda _cls, _uid: index))
    monkeypatch.setattr(Index, "_service_context", classmethod(lambda _cls: context))

    def fake_list_related_meta_tables(
        active_context,
        *,
        index,
        numeric,
        timestamped,
    ):
        calls.append((active_context, index.uid, numeric, timestamped))
        return ()

    monkeypatch.setattr(
        "msm.services.indices.list_related_meta_tables",
        fake_list_related_meta_tables,
    )

    assert Index.list_related_meta_tables(index_uid) == ()
    assert Index.list_related_meta_tables(
        index_uid,
        numeric=False,
        timestamped=False,
    ) == ()
    assert calls == [
        (context, index_uid, True, True),
        (context, index_uid, False, False),
    ]


def test_index_payloads_reject_constant_name_field() -> None:
    removed_constant_name_field = "legacy_" + "constant_name"

    with pytest.raises(ValidationError, match=removed_constant_name_field):
        IndexUpsert(
            unique_identifier="SPX",
            index_type=INDEX_TYPE_EQUITY,
            display_name="S&P 500 Index",
            **{removed_constant_name_field: "INDEX__SPX"},
        )

    with pytest.raises(ValidationError, match=removed_constant_name_field):
        IndexUpdate(**{removed_constant_name_field: "INDEX__SPX"})


def test_index_payloads_reject_removed_provider_field() -> None:
    with pytest.raises(ValidationError, match="provider"):
        IndexUpsert(
            unique_identifier="SPX",
            index_type=INDEX_TYPE_EQUITY,
            display_name="S&P 500 Index",
            provider="example",
        )

    with pytest.raises(ValidationError, match="provider"):
        IndexUpdate(provider="example")


def test_index_create_payload_requires_index_type() -> None:
    with pytest.raises(ValidationError, match="index_type"):
        IndexUpsert(
            unique_identifier="SPX",
            display_name="S&P 500 Index",
        )


def test_index_update_payload_rejects_null_index_type() -> None:
    with pytest.raises(ValidationError, match="index_type"):
        IndexUpdate(index_type=None)
