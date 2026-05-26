from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from msm.api.assets import Asset, AssetUpsert, _operation_result_rows
from msm.models import AssetTable


def test_asset_api_declares_table_contract() -> None:
    assert Asset.__table__ is AssetTable
    assert Asset.__required_tables__ == [AssetTable]


def test_asset_create_schemas_delegates_to_required_table(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_create_schemas(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr("msm.bootstrap.create_schemas", fake_create_schemas)

    assert Asset.create_schemas(namespace="mainsequence.examples") is runtime
    assert calls == [
        {
            "models": [AssetTable],
            "namespace": "mainsequence.examples",
        }
    ]


def test_asset_create_schemas_merges_additional_models(monkeypatch) -> None:
    calls = []

    def fake_create_schemas(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("msm.bootstrap.create_schemas", fake_create_schemas)

    Asset.create_schemas(models=["OpenFigiDetails"])

    assert calls == [{"models": [AssetTable, "OpenFigiDetails"]}]


def test_asset_upsert_uses_active_runtime(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    table_handle = object()
    runtime = SimpleNamespace(table=lambda model: table_handle)
    calls = []

    def fake_get_runtime():
        return runtime

    def fake_repository_upsert(asset_table, **kwargs):
        calls.append((asset_table, kwargs))
        return {
            "row": {
                "uid": str(asset_uid),
                "unique_identifier": "BTC",
                "asset_type": "crypto",
            }
        }

    monkeypatch.setattr("msm.bootstrap.get_runtime", fake_get_runtime)
    monkeypatch.setattr("msm.api.assets.repository_upsert_asset", fake_repository_upsert)

    asset = Asset.upsert(AssetUpsert(unique_identifier="BTC", asset_type="crypto"))

    assert asset == Asset(uid=asset_uid, unique_identifier="BTC", asset_type="crypto")
    assert calls == [
        (
            table_handle,
            {
                "unique_identifier": "BTC",
                "asset_type": "crypto",
            },
        )
    ]


def test_asset_operation_requires_initialized_runtime(monkeypatch) -> None:
    def fake_get_runtime():
        raise RuntimeError("Markets schemas are not initialized.")

    monkeypatch.setattr("msm.bootstrap.get_runtime", fake_get_runtime)

    with pytest.raises(RuntimeError, match="not initialized"):
        Asset.filter(asset_type="crypto")


def test_operation_result_rows_accepts_common_envelopes() -> None:
    row = {"uid": str(uuid.uuid4()), "unique_identifier": "BTC"}

    assert _operation_result_rows({"row": row}) == [row]
    assert _operation_result_rows({"data": {"rows": [row]}}) == [row]
    assert _operation_result_rows({"results": [row]}) == [row]
