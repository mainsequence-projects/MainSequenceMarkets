from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm.models import IndexTable, IndexTypeTable
from msm_pricing.api.index_convention_details import (
    DEFAULT_INDEX_CONVENTION_SERIALIZATION_FORMAT,
    IndexConventionDetails,
    IndexConventionDetailsUpsert,
)
from msm_pricing.models import IndexConventionDetailsTable


def test_index_convention_details_api_declares_table_contract() -> None:
    assert IndexConventionDetails.__table__ is IndexConventionDetailsTable
    assert IndexConventionDetails.__required_tables__ == [
        IndexTypeTable,
        IndexTable,
        IndexConventionDetailsTable,
    ]
    assert IndexConventionDetails.__upsert_keys__ == ("index_uid",)


def test_index_convention_details_start_engine_uses_pricing_dependencies(
    monkeypatch,
) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_attach_pricing_schemas(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr(
        "msm_pricing.api.index_convention_details.attach_pricing_schemas",
        fake_attach_pricing_schemas,
    )

    assert IndexConventionDetails.start_engine(namespace="pricing-test") is runtime
    assert calls == [
        {
            "models": [IndexTypeTable, IndexTable, IndexConventionDetailsTable],
            "namespace": "pricing-test",
        }
    ]


def test_index_convention_details_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        IndexConventionDetailsUpsert(
            index_uid=uuid.uuid4(),
            index_family="overnight",
            convention_dump={"day_counter": "Actual360"},
            unexpected=True,
        )


def test_index_convention_details_row_accepts_physical_metadata_alias() -> None:
    row = IndexConventionDetails.model_validate(
        {
            "index_uid": uuid.uuid4(),
            "index_family": "overnight",
            "convention_dump": {"day_counter": "Actual360"},
            "serialization_format": DEFAULT_INDEX_CONVENTION_SERIALIZATION_FORMAT,
            "metadata": {"provider": "unit-test"},
        }
    )

    assert row.metadata_json == {"provider": "unit-test"}


def test_index_convention_details_upsert_uses_pricing_runtime_and_index_uid_key(
    monkeypatch,
) -> None:
    index_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    def fake_resolve_pricing_runtime(**kwargs):
        calls.append(("runtime", kwargs))
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append(("upsert", active_context, model, values, conflict_columns))
        return {"row": values}

    monkeypatch.setattr(
        "msm_pricing.api.index_convention_details.resolve_pricing_runtime",
        fake_resolve_pricing_runtime,
    )
    monkeypatch.setattr(
        "msm_pricing.api.index_convention_details.upsert_model",
        fake_upsert_model,
    )

    row = IndexConventionDetails.upsert(
        index_uid=index_uid,
        index_family="overnight",
        convention_dump={"day_counter": "Actual360", "calendar": "US"},
        source="unit-test",
        metadata_json={"provider": "test"},
    )

    assert row == IndexConventionDetails(
        index_uid=index_uid,
        index_family="overnight",
        convention_dump={"day_counter": "Actual360", "calendar": "US"},
        serialization_format=DEFAULT_INDEX_CONVENTION_SERIALIZATION_FORMAT,
        source="unit-test",
        metadata_json={"provider": "test"},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [IndexTypeTable, IndexTable, IndexConventionDetailsTable],
                "row_model_name": "IndexConventionDetails",
            },
        ),
        (
            "upsert",
            context,
            IndexConventionDetailsTable,
            {
                "index_uid": index_uid,
                "index_family": "overnight",
                "convention_dump": {"day_counter": "Actual360", "calendar": "US"},
                "serialization_format": DEFAULT_INDEX_CONVENTION_SERIALIZATION_FORMAT,
                "source": "unit-test",
                "metadata_json": {"provider": "test"},
            },
            ("index_uid",),
        ),
    ]


def test_index_convention_details_get_by_index_uid_uses_primary_key_lookup(
    monkeypatch,
) -> None:
    index_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.index_convention_details.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    def fake_get_model_by_uid(active_context, *, model, uid):
        calls.append((active_context, model, uid))
        return {
            "row": {
                "index_uid": index_uid,
                "index_family": "overnight",
                "convention_dump": {"day_counter": "Actual360"},
                "serialization_format": DEFAULT_INDEX_CONVENTION_SERIALIZATION_FORMAT,
            }
        }

    monkeypatch.setattr(
        "msm_pricing.api.index_convention_details.get_model_by_uid",
        fake_get_model_by_uid,
    )

    row = IndexConventionDetails.get_by_index_uid(index_uid)

    assert row is not None
    assert row.index_uid == index_uid
    assert calls == [(context, IndexConventionDetailsTable, index_uid)]
