from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm.models import AssetTable
from msm_pricing.api.pricing_details import (
    DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
    AssetCurrentPricingDetails,
    AssetCurrentPricingDetailsUpsert,
    AssetPricingDetails,
)
from msm_pricing.data_nodes.pricing_details.storage import AssetPricingDetailsStorage
from msm_pricing.models import AssetCurrentPricingDetailsTable


def test_asset_current_pricing_details_api_declares_table_contract() -> None:
    assert AssetCurrentPricingDetails.__table__ is AssetCurrentPricingDetailsTable
    assert AssetCurrentPricingDetails.__required_tables__ == [
        AssetTable,
        AssetPricingDetailsStorage,
        AssetCurrentPricingDetailsTable,
    ]
    assert AssetCurrentPricingDetails.__upsert_keys__ == ("asset_uid",)


def test_asset_pricing_details_api_declares_storage_contract() -> None:
    assert AssetPricingDetails.__table__ is AssetPricingDetailsStorage
    assert AssetPricingDetails.__required_tables__ == [
        AssetTable,
        AssetPricingDetailsStorage,
        AssetCurrentPricingDetailsTable,
    ]
    assert AssetPricingDetails.__upsert_keys__ == ("time_index", "asset_identifier")


def test_pricing_details_payload_requires_timezone_aware_date() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        AssetCurrentPricingDetailsUpsert(
            asset_uid=uuid.uuid4(),
            instrument_type="ExampleInstrument",
            instrument_dump={"notional": 100},
            pricing_details_date=dt.datetime(2026, 5, 27),
        )


def test_pricing_details_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        AssetCurrentPricingDetailsUpsert(
            asset_uid=uuid.uuid4(),
            instrument_type="ExampleInstrument",
            instrument_dump={"notional": 100},
            pricing_details_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
            uid=uuid.uuid4(),
        )


def test_pricing_details_upsert_uses_pricing_runtime_and_asset_uid_conflict_key(
    monkeypatch,
) -> None:
    asset_uid = uuid.uuid4()
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
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
        "msm_pricing.api.pricing_details.resolve_pricing_runtime",
        fake_resolve_pricing_runtime,
    )
    monkeypatch.setattr("msm_pricing.api.pricing_details.upsert_model", fake_upsert_model)

    row = AssetCurrentPricingDetails.upsert(
        asset_uid=asset_uid,
        instrument_type="ExampleInstrument",
        instrument_dump={"notional": 100},
        pricing_details_date=pricing_details_date,
        source="unit-test",
        metadata_json={"provider": "test"},
    )

    assert row == AssetCurrentPricingDetails(
        asset_uid=asset_uid,
        instrument_type="ExampleInstrument",
        instrument_dump={"notional": 100},
        pricing_details_date=pricing_details_date,
        serialization_format=DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
        source="unit-test",
        metadata_json={"provider": "test"},
    )
    assert calls == [
        (
            "runtime",
            {
                "models": [
                    AssetTable,
                    AssetPricingDetailsStorage,
                    AssetCurrentPricingDetailsTable,
                ],
                "row_model_name": "AssetCurrentPricingDetails",
            },
        ),
        (
            "upsert",
            context,
            AssetCurrentPricingDetailsTable,
            {
                "asset_uid": asset_uid,
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 100},
                "pricing_details_date": pricing_details_date,
                "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
                "pricing_package_version": None,
                "source": "unit-test",
                "metadata_json": {"provider": "test"},
            },
            ("asset_uid",),
        ),
    ]


def test_pricing_details_get_by_asset_uid_uses_primary_key_lookup(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    context = object()

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    calls = []

    def fake_get_model_by_uid(active_context, *, model, uid):
        calls.append((active_context, model, uid))
        return {
            "row": {
                "asset_uid": asset_uid,
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 100},
                "pricing_details_date": pricing_details_date,
                "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
            }
        }

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.get_model_by_uid",
        fake_get_model_by_uid,
    )

    row = AssetCurrentPricingDetails.get_by_asset_uid(asset_uid)

    assert row is not None
    assert row.asset_uid == asset_uid
    assert calls == [(context, AssetCurrentPricingDetailsTable, asset_uid)]


def test_asset_pricing_details_add_without_date_uses_now_and_updates_current(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    now = dt.datetime(2026, 5, 27, 12, 30, tzinfo=dt.UTC)
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.resolve_pricing_runtime",
        lambda **kwargs: calls.append(("runtime", kwargs)) or runtime,
    )

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append(("history-upsert", active_context, model, values, conflict_columns))
        return {"row": values}

    monkeypatch.setattr("msm_pricing.api.pricing_details.upsert_model", fake_upsert_model)
    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.dt",
        SimpleNamespace(datetime=SimpleNamespace(now=lambda _tz: now), UTC=dt.UTC),
    )

    def fake_current_upsert(**kwargs):
        calls.append(("current-upsert", kwargs))
        return AssetCurrentPricingDetails(**kwargs)

    monkeypatch.setattr(AssetCurrentPricingDetails, "upsert", staticmethod(fake_current_upsert))

    result = AssetPricingDetails.add(
        asset_uid=asset_uid,
        asset_identifier="example-asset",
        instrument_type="ExampleInstrument",
        instrument_dump={"notional": 100},
        source="unit-test",
        metadata_json={"provider": "test"},
    )

    assert result.updated_current is True
    assert result.current_pricing_details is not None
    assert result.current_pricing_details.asset_uid == asset_uid
    assert calls[1] == (
        "history-upsert",
        context,
        AssetPricingDetailsStorage,
        {
            "time_index": now,
            "asset_identifier": "example-asset",
            "instrument_type": "ExampleInstrument",
            "instrument_dump": {"notional": 100},
            "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
            "pricing_package_version": None,
            "source": "unit-test",
            "metadata_json": {"provider": "test"},
        },
        ("time_index", "asset_identifier"),
    )
    assert calls[-1] == (
        "current-upsert",
        {
            "asset_uid": asset_uid,
            "instrument_type": "ExampleInstrument",
            "instrument_dump": {"notional": 100},
            "pricing_details_date": now,
            "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
            "pricing_package_version": None,
            "source": "unit-test",
            "metadata_json": {"provider": "test"},
        },
    )


def test_asset_pricing_details_add_with_date_upserts_snapshot_only(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append((active_context, model, values, conflict_columns))
        return {
            "row": {
                "time_index": values["time_index"],
                "asset_identifier": values["asset_identifier"],
                "instrument_type": values["instrument_type"],
                "instrument_dump": values["instrument_dump"],
                "serialization_format": values["serialization_format"],
                "pricing_package_version": values["pricing_package_version"],
                "source": values["source"],
                "metadata_json": values["metadata_json"],
            }
        }

    monkeypatch.setattr("msm_pricing.api.pricing_details.upsert_model", fake_upsert_model)
    monkeypatch.setattr(
        AssetCurrentPricingDetails,
        "upsert",
        staticmethod(lambda **_kwargs: pytest.fail("dated snapshots must not update current")),
    )

    result = AssetPricingDetails.add(
        asset_uid=asset_uid,
        asset_identifier="example-asset",
        instrument_type="ExampleInstrument",
        instrument_dump={"notional": 100},
        pricing_details_date=pricing_details_date,
    )

    assert result.updated_current is False
    assert result.current_pricing_details is None
    assert calls == [
        (
            context,
            AssetPricingDetailsStorage,
            {
                "time_index": pricing_details_date,
                "asset_identifier": "example-asset",
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 100},
                "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
                "pricing_package_version": None,
                "source": None,
                "metadata_json": None,
            },
            ("time_index", "asset_identifier"),
        )
    ]


def test_asset_pricing_details_add_many_uses_bulk_upserts_and_updates_current(
    monkeypatch,
) -> None:
    first_asset_uid = uuid.uuid4()
    second_asset_uid = uuid.uuid4()
    now = dt.datetime(2026, 5, 27, 12, 30, tzinfo=dt.UTC)
    historical_date = dt.datetime(2026, 5, 26, tzinfo=dt.UTC)
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.resolve_pricing_runtime",
        lambda **kwargs: calls.append(("runtime", kwargs)) or SimpleNamespace(context=context),
    )
    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.dt",
        SimpleNamespace(datetime=SimpleNamespace(now=lambda _tz: now), UTC=dt.UTC),
    )

    def fake_bulk_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append(("bulk-upsert", active_context, model, values, conflict_columns))
        if model is AssetPricingDetailsStorage:
            return {"rows": values}
        return {"rows": values}

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.bulk_upsert_model",
        fake_bulk_upsert_model,
    )

    result = AssetPricingDetails.add_many(
        [
            {
                "asset_uid": first_asset_uid,
                "asset_identifier": "asset-1",
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 100},
                "source": "unit-test",
            },
            {
                "asset_uid": second_asset_uid,
                "asset_identifier": "asset-2",
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 200},
                "pricing_details_date": historical_date,
                "source": "unit-test",
            },
        ],
        batch_size=1000,
    )

    assert result.updated_current is True
    assert result.updated_current_count == 1
    assert [row.asset_identifier for row in result.pricing_details] == ["asset-1", "asset-2"]
    assert [row.asset_uid for row in result.current_pricing_details] == [first_asset_uid]
    assert calls[1] == (
        "bulk-upsert",
        context,
        AssetPricingDetailsStorage,
        [
            {
                "time_index": now,
                "asset_identifier": "asset-1",
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 100},
                "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
                "pricing_package_version": None,
                "source": "unit-test",
                "metadata_json": None,
            },
            {
                "time_index": historical_date,
                "asset_identifier": "asset-2",
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 200},
                "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
                "pricing_package_version": None,
                "source": "unit-test",
                "metadata_json": None,
            },
        ],
        ("time_index", "asset_identifier"),
    )
    assert calls[3] == (
        "bulk-upsert",
        context,
        AssetCurrentPricingDetailsTable,
        [
            {
                "asset_uid": first_asset_uid,
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": 100},
                "pricing_details_date": now,
                "serialization_format": DEFAULT_INSTRUMENT_SERIALIZATION_FORMAT,
                "pricing_package_version": None,
                "source": "unit-test",
                "metadata_json": None,
            }
        ],
        ("asset_uid",),
    )


def test_asset_pricing_details_add_many_chunks_history_upserts(monkeypatch) -> None:
    pricing_details_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    context = object()
    calls = []

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.resolve_pricing_runtime",
        lambda **_kwargs: SimpleNamespace(context=context),
    )

    def fake_bulk_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append((active_context, model, values, conflict_columns))
        return {"rows": values}

    monkeypatch.setattr(
        "msm_pricing.api.pricing_details.bulk_upsert_model",
        fake_bulk_upsert_model,
    )

    result = AssetPricingDetails.add_many(
        [
            {
                "asset_uid": uuid.uuid4(),
                "asset_identifier": f"asset-{index}",
                "instrument_type": "ExampleInstrument",
                "instrument_dump": {"notional": index},
                "pricing_details_date": pricing_details_date,
            }
            for index in range(3)
        ],
        batch_size=2,
    )

    assert result.updated_current is False
    assert result.current_pricing_details == []
    assert [len(call[2]) for call in calls] == [2, 1]
