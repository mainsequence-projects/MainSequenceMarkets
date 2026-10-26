"""The remote row backend gives ``msm.api`` row classes the same behaviour over HTTP.

Each test selects the remote backend with an in-process ``TestClient`` of
``apps/v1`` as the transport. The Markets API side runs the row API on its
runtime backend, whose MetaTables calls are replaced by fakes exactly as the
runtime ``msm.api`` tests do, so a test proves the full path: row class method,
client, ``POST /rows/{resource}/{operation}/``, runtime row method, result.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.v1 import policy
from apps.v1.main import app
from msm.api.accounts import Account
from msm.api.assets import Asset, AssetCategory, CurrencySpot
from msm.api.remote import (
    MarketsAccessError,
    is_markets_owned,
    use_remote_backend,
    use_runtime_backend,
)
from msm.client import MarketsClient, tabular_frame_to_pandas


@pytest.fixture
def remote(monkeypatch):
    """Use the remote backend against an in-process Markets API; record runtime calls."""

    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **kwargs: SimpleNamespace(context=SimpleNamespace(timeout=None)),
    )
    client = MarketsClient("http://testserver", session=TestClient(app))
    use_remote_backend(client.backend)
    try:
        yield SimpleNamespace(client=client, calls=calls)
    finally:
        use_runtime_backend()


def _row(**values: Any) -> dict[str, Any]:
    return {"rows": [{"uid": str(uuid.uuid4()), **values}]}


def test_upsert_runs_on_the_markets_runtime_and_returns_the_row(monkeypatch, remote) -> None:
    def upsert_model(context, *, model, values, conflict_columns):
        remote.calls.append(("upsert", {"model": model.__name__, "values": values}))
        return _row(**values)

    monkeypatch.setattr("msm.repositories.crud.upsert_model", upsert_model)

    asset = Asset.upsert(unique_identifier="ACME", asset_type="Equity")

    assert isinstance(asset, Asset)
    assert asset.unique_identifier == "ACME"
    assert asset.asset_type == "equity"
    assert remote.calls == [
        ("upsert", {"model": "AssetTable", "values": {"unique_identifier": "ACME", "asset_type": "equity"}})
    ]


def test_payload_models_keep_exclude_unset_semantics(monkeypatch, remote) -> None:
    from msm.api.assets import AssetUpsert

    seen: dict[str, Any] = {}

    def upsert_model(context, *, model, values, conflict_columns):
        seen.update(values)
        return _row(**values)

    monkeypatch.setattr("msm.repositories.crud.upsert_model", upsert_model)

    Asset.upsert(AssetUpsert(unique_identifier="ACME"))

    assert seen == {"unique_identifier": "ACME"}


def test_get_by_uid_returns_the_row_or_none(monkeypatch, remote) -> None:
    uid = uuid.uuid4()
    rows = {str(uid): {"uid": str(uid), "unique_identifier": "ACME", "asset_type": "equity"}}
    monkeypatch.setattr(
        "msm.repositories.crud.get_model_by_uid",
        lambda context, *, model, uid: {"rows": [rows[str(uid)]] if str(uid) in rows else []},
    )

    assert Asset.get_by_uid(uid) == Asset.model_validate(rows[str(uid)])
    assert Asset.get_by_uid(uuid.uuid4()) is None


def test_filter_values_are_typed_by_the_row_fields(monkeypatch, remote) -> None:
    account_uid = uuid.uuid4()
    seen: dict[str, Any] = {}

    def search_model(context, *, model, filters=None, contains_filters=None, limit=None, **kwargs):
        seen.update({"filters": filters, "contains": contains_filters, "limit": limit})
        return {"rows": [{"uid": str(account_uid), "unique_identifier": "ACC-1", "account_name": "A"}]}

    monkeypatch.setattr("msm.repositories.crud.search_model", search_model)

    accounts = Account.filter(uid=str(account_uid), account_name_contains="A", limit=5)

    assert [account.unique_identifier for account in accounts] == ["ACC-1"]
    assert seen == {"filters": {"uid": account_uid}, "contains": {"account_name": "A"}, "limit": 5}


def test_get_many_by_unique_identifier_returns_a_mapping(monkeypatch, remote) -> None:
    monkeypatch.setattr(
        "msm.repositories.crud.search_model",
        lambda context, *, model, in_filters=None, limit=None, **kwargs: {
            "rows": [
                {"uid": str(uuid.uuid4()), "unique_identifier": value, "asset_type": "equity"}
                for value in in_filters["unique_identifier"]
            ]
        },
    )

    rows = Asset.get_many_by_unique_identifier(["A", "B", "A"])

    assert sorted(rows) == ["A", "B"]
    assert all(isinstance(row, Asset) for row in rows.values())


def test_composite_upsert_runs_remotely(monkeypatch, remote) -> None:
    base, quote = uuid.uuid4(), uuid.uuid4()
    pair_uid = uuid.uuid4()

    def upsert_model(context, *, model, values, conflict_columns):
        name = model.__name__
        remote.calls.append((name, values))
        if name == "AssetTable":
            return {"rows": [{"uid": str(pair_uid), **values}]}
        if name == "CurrencySpotAssetDetailsTable":
            return {"rows": [{"uid": str(uuid.uuid4()), **{k: str(v) for k, v in values.items()}}]}
        return {"rows": [values]}

    monkeypatch.setattr("msm.api.assets.upsert_model", upsert_model)

    spot = CurrencySpot.upsert(
        unique_identifier="EUR/USD", base_currency_uid=base, quote_currency_uid=quote
    )

    assert isinstance(spot, CurrencySpot)
    assert spot.uid == pair_uid
    assert (spot.base_currency_uid, spot.quote_currency_uid) == (base, quote)
    assert [name for name, _ in remote.calls] == [
        "AssetTypeTable",
        "AssetTable",
        "CurrencySpotAssetDetailsTable",
    ]


def test_extra_operations_decode_their_return_type(monkeypatch, remote) -> None:
    from msm.services.indices import RelatedMetaTable

    uid = uuid.uuid4()
    monkeypatch.setattr(
        "msm.repositories.crud.get_model_by_uid",
        lambda context, *, model, uid: {"rows": [{"uid": str(uid), "unique_identifier": "ACME"}]},
    )
    related = RelatedMetaTable(
        key="prices",
        label="Prices",
        owning_package="my-provider",
        storage_kind="related_reference_table",
        identifier="my-provider.PricesTS",
        relationship_type="registered_foreign_key",
        join_kind="unique_identifier",
        join_column="asset_identifier",
        on_delete="RESTRICT",
        authoritative=False,
        discovery_source="inferred",
        exploration_capability="none",
        delete_capability="none",
    )
    monkeypatch.setattr(
        "msm.services.related_meta_tables.list_reference_meta_tables",
        lambda **kwargs: (related,),
    )

    result = Asset.list_related_meta_tables(uid)

    assert isinstance(result, tuple)
    assert result == (related,)


def test_delete_uses_the_service_delete(monkeypatch, remote) -> None:
    uid = str(uuid.uuid4())
    deleted: list[str] = []
    monkeypatch.setattr(
        "apps.v1.services.asset_categories.delete_asset_category",
        lambda *, uid: deleted.append(uid) or True,
    )

    result = AssetCategory.delete(uid)

    assert deleted == [uid]
    assert result["deleted_count"] == 1


def test_delete_without_a_service_route_is_not_offered(remote) -> None:
    from msm.api.remote import MarketsOperationUnsupported

    with pytest.raises(MarketsOperationUnsupported, match="not offered remotely"):
        Account.delete(uuid.uuid4())


def test_validation_errors_come_back_as_value_errors(remote) -> None:
    with pytest.raises(ValueError):
        Asset.upsert(asset_type="equity")


def test_the_write_policy_applies_to_remote_writes(monkeypatch, remote) -> None:
    monkeypatch.setattr(policy, "resolve_identity_type", lambda uid: "workload")
    monkeypatch.setattr(
        "msm.repositories.crud.upsert_model",
        lambda *args, **kwargs: pytest.fail("a refused write must not reach the runtime"),
    )

    with pytest.raises(MarketsAccessError, match="MARKETS_REGISTRY_WRITERS"):
        Asset.upsert(unique_identifier="ACME")
    assert isinstance(MarketsAccessError("x"), PermissionError)


def test_reads_are_not_subject_to_the_write_policy(monkeypatch, remote) -> None:
    monkeypatch.setattr(policy, "resolve_identity_type", lambda uid: "workload")
    monkeypatch.setattr(
        "msm.repositories.crud.get_model_by_uid",
        lambda context, *, model, uid: {"rows": []},
    )

    assert Asset.get_by_uid(uuid.uuid4()) is None


def test_start_engine_attaches_nothing_under_the_remote_backend(monkeypatch, remote) -> None:
    monkeypatch.setattr(
        "msm.bootstrap.start_engine",
        lambda **kwargs: pytest.fail("the remote backend must not attach tables"),
    )

    assert Asset.start_engine() is None


def test_rows_describe_their_remote_operations(remote) -> None:
    described = {item["resource"]: item for item in remote.client.describe_row_operations()}

    assert {"asset", "account", "portfolio", "currency-spot", "index", "calendar"} <= set(described)
    asset_operations = {operation["name"]: operation for operation in described["asset"]["operations"]}
    assert asset_operations["upsert"]["write"] is True
    assert asset_operations["get_by_uid"]["write"] is False
    assert "delete" in asset_operations
    account_operations = {operation["name"] for operation in described["account"]["operations"]}
    assert "delete" not in account_operations


def test_provider_row_classes_keep_the_runtime_backend(remote) -> None:
    provider_table = SimpleNamespace(__table__=SimpleNamespace(info={"namespace": "my-provider"}))
    markets_table = SimpleNamespace(__table__=SimpleNamespace(info={"namespace": "mainsequence.markets"}))

    assert is_markets_owned(type("ProviderRow", (), {"__table__": provider_table})) is False
    assert is_markets_owned(type("CoreRow", (), {"__table__": markets_table})) is True
    assert is_markets_owned(Asset) is True


def test_unknown_resource_and_operation_raise_lookup_errors(remote) -> None:
    with pytest.raises(LookupError, match="Unknown row resource"):
        remote.client.run_row_operation("no-such-resource", "get_by_uid", {})
    with pytest.raises(LookupError, match="no remote operation"):
        remote.client.run_row_operation("asset", "_active_context", {})


def test_portfolio_frames_convert_to_pandas() -> None:
    frame = tabular_frame_to_pandas(
        {
            "columns": ["time_index", "portfolio_identifier", "close"],
            "rows": [{"time_index": dt.datetime(2026, 1, 2).isoformat(), "portfolio_identifier": "P", "close": 1.5}],
        }
    )

    assert list(frame.columns) == ["time_index", "portfolio_identifier", "close"]
    assert frame.iloc[0]["close"] == 1.5


def test_pricing_composites_run_remotely_including_their_own_delete(monkeypatch, remote) -> None:
    from msm_pricing.api.market_data_bindings import PricingMarketDataSet

    set_uid = uuid.uuid4()
    row = {"uid": str(set_uid), "set_key": "default", "display_name": "Default"}
    deleted: list[str] = []
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.search_model",
        lambda context, *, model, filters, limit, **kwargs: {"rows": [row] if filters["set_key"] == "default" else []},
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.delete_model",
        lambda context, *, model, uid: deleted.append(str(uid)) or {"deleted_count": 1},
    )
    monkeypatch.setattr(
        PricingMarketDataSet,
        "_active_context",
        classmethod(lambda cls: SimpleNamespace(timeout=None)),
    )

    found = PricingMarketDataSet.get_by_key("default")

    assert isinstance(found, PricingMarketDataSet)
    assert found.uid == set_uid
    assert PricingMarketDataSet.get_by_key("missing") is None
    assert PricingMarketDataSet.delete(set_uid) == {"deleted_count": 1}
    assert deleted == [str(set_uid)]
