from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from msm.api.assets import Asset, AssetType, AssetTypeUpsert, AssetUpsert, _operation_result_rows
from msm.models import AssetTable, AssetTypeTable
from msm.meta_tables import markets_meta_table_fullname


def test_asset_api_declares_table_contract() -> None:
    assert Asset.__table__ is AssetTable
    assert Asset.__required_tables__ == [AssetTable]


def test_asset_type_api_declares_table_contract() -> None:
    assert AssetType.__table__ is AssetTypeTable
    assert AssetType.__required_tables__ == [AssetTypeTable]
    assert AssetType.__upsert_keys__ == ("asset_type",)


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


def test_asset_type_upsert_uses_active_runtime(monkeypatch) -> None:
    asset_type_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(
        context=context,
        target_meta_table_uid_by_fullname={
            markets_meta_table_fullname(AssetTypeTable): str(uuid.uuid4()),
        },
    )
    calls = []

    def fake_resolve_runtime(**kwargs):
        assert kwargs["models"] == AssetType.__required_tables__
        assert kwargs["row_model_name"] == "AssetType"
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append((active_context, model, values, conflict_columns))
        return {
            "row": {
                "uid": str(asset_type_uid),
                "asset_type": "crypto",
                "display_name": "Crypto",
            }
        }

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.api.base.upsert_model", fake_upsert_model)

    asset_type = AssetType.upsert(AssetTypeUpsert(asset_type="crypto", display_name="Crypto"))

    assert asset_type == AssetType(
        uid=asset_type_uid,
        asset_type="crypto",
        display_name="Crypto",
    )
    assert calls == [
        (
            context,
            AssetTypeTable,
            {
                "asset_type": "crypto",
                "display_name": "Crypto",
            },
            ("asset_type",),
        )
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
    context = object()
    runtime = SimpleNamespace(
        context=context,
        target_meta_table_uid_by_fullname={
            markets_meta_table_fullname(AssetTable): str(uuid.uuid4()),
        },
    )
    calls = []

    def fake_resolve_runtime(**kwargs):
        assert kwargs["models"] == Asset.__required_tables__
        assert kwargs["row_model_name"] == "Asset"
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append((active_context, model, values, conflict_columns))
        return {
            "row": {
                "uid": str(asset_uid),
                "unique_identifier": "BTC",
                "asset_type": "crypto",
            }
        }

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.api.base.upsert_model", fake_upsert_model)

    asset = Asset.upsert(AssetUpsert(unique_identifier="BTC", asset_type="crypto"))

    assert asset == Asset(uid=asset_uid, unique_identifier="BTC", asset_type="crypto")
    assert calls == [
        (
            context,
            AssetTable,
            {
                "unique_identifier": "BTC",
                "asset_type": "crypto",
            },
            ("unique_identifier",),
        )
    ]


def test_asset_operation_requires_initialized_runtime(monkeypatch) -> None:
    def fake_resolve_runtime(**kwargs):
        raise RuntimeError(
            "Asset requires registered markets MetaTables for AssetTable. "
            "Set MSM_AUTO_REGISTER_NAMESPACE."
        )

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)

    with pytest.raises(RuntimeError, match="MSM_AUTO_REGISTER_NAMESPACE"):
        Asset.filter(asset_type="crypto")


def test_operation_result_rows_accepts_common_envelopes() -> None:
    row = {"uid": str(uuid.uuid4()), "unique_identifier": "BTC"}

    assert _operation_result_rows({"row": row}) == [row]
    assert _operation_result_rows({"data": {"rows": [row]}}) == [row]
    assert _operation_result_rows({"results": [row]}) == [row]
