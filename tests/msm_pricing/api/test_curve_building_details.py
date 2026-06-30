from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm_pricing.api.curve_building_details import (
    CurveBuildingDetails,
    CurveBuildingDetailsUpsert,
)
from msm_pricing.models import CurveBuildingDetailsTable, CurveTable


def _build_details_payload(curve_uid: uuid.UUID) -> dict[str, object]:
    return {
        "curve_uid": curve_uid,
        "builder_type": "zero_rate_curve",
        "quote_convention": "zero_rate",
        "rate_unit": "decimal",
        "day_counter_code": "Actual360",
        "calendar_code": "TARGET",
        "interpolation_method": "log_linear_discount",
        "compounding": "simple",
        "extrapolation_policy": "enabled",
        "source": "unit-test",
        "metadata_json": {"provider": "test"},
    }


def test_curve_building_details_api_declares_table_contract() -> None:
    assert CurveBuildingDetails.__table__ is CurveBuildingDetailsTable
    assert CurveBuildingDetails.__required_tables__ == [
        CurveTable,
        CurveBuildingDetailsTable,
    ]
    assert CurveBuildingDetails.__upsert_keys__ == ("curve_uid",)


def test_curve_building_details_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        CurveBuildingDetailsUpsert(
            **_build_details_payload(uuid.uuid4()),
            uid=uuid.uuid4(),
        )


def test_curve_building_details_row_accepts_physical_metadata_alias() -> None:
    curve_uid = uuid.uuid4()

    row = CurveBuildingDetails.model_validate(
        {
            **{
                key: value
                for key, value in _build_details_payload(curve_uid).items()
                if key != "metadata_json"
            },
            "metadata": {"provider": "physical"},
        }
    )

    assert row.metadata_json == {"provider": "physical"}


def test_curve_building_details_upsert_uses_curve_uid(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
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
        "msm_pricing.api.curve_building_details.resolve_pricing_runtime",
        fake_resolve_pricing_runtime,
    )
    monkeypatch.setattr(
        "msm_pricing.api.curve_building_details.upsert_model",
        fake_upsert_model,
    )

    row = CurveBuildingDetails.upsert(**_build_details_payload(curve_uid))

    assert row == CurveBuildingDetails(**_build_details_payload(curve_uid))
    assert calls == [
        (
            "runtime",
            {
                "models": [
                    CurveTable,
                    CurveBuildingDetailsTable,
                ],
                "row_model_name": "CurveBuildingDetails",
            },
        ),
        (
            "upsert",
            context,
            CurveBuildingDetailsTable,
            {
                **_build_details_payload(curve_uid),
                "compounding_frequency": None,
                "bootstrap_method": None,
                "builder_payload": None,
            },
            ("curve_uid",),
        ),
    ]


def test_curve_building_details_get_by_curve_uid_uses_primary_key(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.curve_building_details.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    def fake_get_model_by_uid(active_context, *, model, uid):
        calls.append((active_context, model, uid))
        return {"row": _build_details_payload(curve_uid)}

    monkeypatch.setattr(
        "msm_pricing.api.curve_building_details.get_model_by_uid",
        fake_get_model_by_uid,
    )

    row = CurveBuildingDetails.get_by_curve_uid(curve_uid)

    assert row is not None
    assert row.curve_uid == curve_uid
    assert calls == [(context, CurveBuildingDetailsTable, curve_uid)]
