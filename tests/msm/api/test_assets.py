from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from msm.api.assets import (
    Asset,
    AssetType,
    AssetTypeUpsert,
    AssetUpsert,
    CurrencySpot,
    CurrencySpotUpsert,
    OpenFigiDetails,
    _operation_result_rows,
    normalize_asset_type,
)
from msm.models import (
    AssetTable,
    AssetTypeTable,
    CurrencySpotAssetDetailsTable,
    OpenFigiAssetDetailsTable,
)


def test_asset_api_declares_table_contract() -> None:
    assert Asset.__table__ is AssetTable
    assert Asset.__required_tables__ == [AssetTable]


def test_asset_type_api_declares_table_contract() -> None:
    assert AssetType.__table__ is AssetTypeTable
    assert AssetType.__required_tables__ == [AssetTypeTable]
    assert AssetType.__upsert_keys__ == ("asset_type",)


def test_currency_spot_api_declares_required_table_contract() -> None:
    assert CurrencySpot.__required_tables__ == [
        AssetTypeTable,
        AssetTable,
        CurrencySpotAssetDetailsTable,
    ]


def test_asset_type_normalization_for_typed_payloads() -> None:
    assert normalize_asset_type(" Asset Future ") == "asset_future"
    assert normalize_asset_type("Currency Pair") == "currency_pair"
    assert AssetUpsert(unique_identifier="BTC", asset_type="Crypto Asset").asset_type == (
        "crypto_asset"
    )
    assert AssetTypeUpsert(asset_type="Currency Pair").asset_type == "currency_pair"


def test_asset_type_normalization_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="asset_type"):
        normalize_asset_type(" ")


def test_openfigi_details_api_uses_asset_uid_as_row_identity() -> None:
    asset_uid = uuid.uuid4()

    details = OpenFigiDetails.model_validate(
        {
            "asset_uid": str(asset_uid),
            "figi": "BBG00FNFPQH4",
        }
    )

    assert OpenFigiDetails.__table__ is OpenFigiAssetDetailsTable
    assert details.uid == asset_uid
    assert details.asset_uid == asset_uid


def test_asset_start_engine_delegates_to_required_table(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_start_engine(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr("msm.bootstrap.start_engine", fake_start_engine)

    assert Asset.start_engine(namespace="mainsequence.examples") is runtime
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
    monkeypatch.setattr("msm.repositories.crud.upsert_model", fake_upsert_model)

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


def test_asset_type_upsert_normalizes_keyword_payload(monkeypatch) -> None:
    asset_type_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
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
                "asset_type": values["asset_type"],
                "display_name": values["display_name"],
            }
        }

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.repositories.crud.upsert_model", fake_upsert_model)

    asset_type = AssetType.upsert(asset_type="Asset Future", display_name="Asset Future")

    assert asset_type.asset_type == "asset_future"
    assert calls[0][2]["asset_type"] == "asset_future"


def test_asset_start_engine_merges_additional_models(monkeypatch) -> None:
    calls = []

    def fake_start_engine(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("msm.bootstrap.start_engine", fake_start_engine)

    Asset.start_engine(models=["OpenFigiAssetDetails"])

    assert calls == [{"models": [AssetTable, "OpenFigiAssetDetails"]}]


def test_asset_create_schemas_warns_and_delegates(monkeypatch) -> None:
    calls = []

    def fake_start_engine(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("msm.bootstrap.start_engine", fake_start_engine)

    with pytest.warns(DeprecationWarning, match="Asset.create_schemas"):
        Asset.create_schemas(models=["OpenFigiAssetDetails"])

    assert calls == [{"models": [AssetTable, "OpenFigiAssetDetails"]}]


def test_asset_upsert_uses_active_runtime(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(
        context=context,
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
    monkeypatch.setattr("msm.repositories.crud.upsert_model", fake_upsert_model)

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


def test_asset_related_meta_tables_forwards_optional_filters(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    asset = Asset(uid=asset_uid, unique_identifier="BOND-1", asset_type="bond")
    calls = []

    monkeypatch.setattr(Asset, "get_by_uid", classmethod(lambda _cls, _uid: asset))

    def fake_list_reference_meta_tables(*, reference_type, numeric, timestamped):
        calls.append((reference_type, numeric, timestamped))
        return ()

    monkeypatch.setattr(
        "msm.services.related_meta_tables.list_reference_meta_tables",
        fake_list_reference_meta_tables,
    )

    assert Asset.list_related_meta_tables(asset_uid) == ()
    assert Asset.list_related_meta_tables(
        asset_uid,
        numeric=False,
        timestamped=False,
    ) == ()
    assert calls == [
        ("asset", True, True),
        ("asset", False, False),
    ]


def test_currency_spot_upsert_owns_multitable_workflow(monkeypatch) -> None:
    pair_uid = uuid.uuid4()
    base_uid = uuid.uuid4()
    quote_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    def fake_resolve_runtime(**kwargs):
        assert kwargs["models"] == CurrencySpot.__required_tables__
        assert kwargs["row_model_name"] == "CurrencySpot"
        return runtime

    def fake_upsert_model(active_context, *, model, values, conflict_columns):
        calls.append((active_context, model, values, conflict_columns))
        if model is AssetTypeTable:
            return {"row": {"uid": str(uuid.uuid4()), **values}}
        if model is AssetTable:
            return {"row": {"uid": str(pair_uid), **values}}
        if model is CurrencySpotAssetDetailsTable:
            return {"row": {**values}}
        raise AssertionError(model)

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.api.assets.upsert_model", fake_upsert_model)

    currency_spot = CurrencySpot.upsert(
        CurrencySpotUpsert(
            unique_identifier="BTC/USDT",
            base_currency_uid=base_uid,
            quote_currency_uid=quote_uid,
        )
    )

    assert currency_spot == CurrencySpot(
        uid=pair_uid,
        asset_uid=pair_uid,
        unique_identifier="BTC/USDT",
        asset_type="currency_spot",
        base_currency_uid=base_uid,
        quote_currency_uid=quote_uid,
    )
    assert calls == [
        (
            context,
            AssetTypeTable,
            {
                "asset_type": "currency_spot",
                "display_name": "Currency Spot",
                "description": "Tradable currency spot pair asset.",
            },
            ("asset_type",),
        ),
        (
            context,
            AssetTable,
            {
                "unique_identifier": "BTC/USDT",
                "asset_type": "currency_spot",
            },
            ("unique_identifier",),
        ),
        (
            context,
            CurrencySpotAssetDetailsTable,
            {
                "asset_uid": pair_uid,
                "base_currency_uid": base_uid,
                "quote_currency_uid": quote_uid,
            },
            ("asset_uid",),
        ),
    ]


def test_currency_spot_payload_rejects_same_base_and_quote_asset() -> None:
    asset_uid = uuid.uuid4()

    with pytest.raises(ValueError, match="must differ"):
        CurrencySpotUpsert(
            unique_identifier="BTC/BTC",
            base_currency_uid=asset_uid,
            quote_currency_uid=asset_uid,
        )


def test_asset_operation_requires_initialized_runtime(monkeypatch) -> None:
    def fake_resolve_runtime(**kwargs):
        raise RuntimeError(
            "Asset requires an initialized markets runtime for AssetTable. "
            "Run msm.start_engine(models=[...]) during application initialization."
        )

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)

    with pytest.raises(RuntimeError, match="initialized markets runtime"):
        Asset.filter(asset_type="crypto")


def test_asset_get_many_by_unique_identifier_uses_single_in_lookup(monkeypatch) -> None:
    btc_uid = uuid.uuid4()
    context = object()
    runtime = SimpleNamespace(context=context)
    calls = []

    def fake_resolve_runtime(**kwargs):
        assert kwargs["models"] == Asset.__required_tables__
        assert kwargs["row_model_name"] == "Asset"
        return runtime

    def fake_search_model(active_context, **kwargs):
        calls.append((active_context, kwargs))
        return {
            "rows": [
                {
                    "uid": str(btc_uid),
                    "unique_identifier": "BTC",
                    "asset_type": "crypto",
                }
            ]
        }

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.repositories.crud.search_model", fake_search_model)

    assets = Asset.get_many_by_unique_identifier(["BTC", "ETH", "BTC", " "])

    assert assets == {
        "BTC": Asset(uid=btc_uid, unique_identifier="BTC", asset_type="crypto")
    }
    assert calls == [
        (
            context,
            {
                "model": AssetTable,
                "in_filters": {"unique_identifier": ["BTC", "ETH"]},
                "limit": 2,
            },
        )
    ]


def test_asset_get_many_by_unique_identifier_empty_input_skips_runtime(monkeypatch) -> None:
    def fail_resolve_runtime(**_kwargs):
        raise AssertionError("empty lookup should not resolve runtime")

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fail_resolve_runtime)

    assert Asset.get_many_by_unique_identifier([]) == {}


def test_operation_result_rows_accepts_common_envelopes() -> None:
    row = {"uid": str(uuid.uuid4()), "unique_identifier": "BTC"}
    detail_row = {"asset_uid": str(uuid.uuid4()), "base_currency_uid": str(uuid.uuid4())}

    assert _operation_result_rows({"row": row}) == [row]
    assert _operation_result_rows({"row": detail_row}) == [detail_row]
    assert _operation_result_rows({"data": {"rows": [row]}}) == [row]
    assert _operation_result_rows({"results": [row]}) == [row]
