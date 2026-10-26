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


def test_bulk_count_and_ordering_run_remotely(monkeypatch, remote) -> None:
    from msm.api.accounts import AccountHoldingsSet

    account_uid = uuid.uuid4()
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "msm.repositories.crud.bulk_upsert_model",
        lambda context, *, model, values, conflict_columns: {
            "rows": [{"uid": str(uuid.uuid4()), **value} for value in values]
        },
    )
    monkeypatch.setattr(
        "msm.repositories.crud.count_model",
        lambda context, **kwargs: seen.setdefault("count", kwargs) and {"rows": [{"count": 3}]},
    )
    monkeypatch.setattr(
        "msm.repositories.crud.search_model",
        lambda context, **kwargs: seen.setdefault("search", kwargs) and {"rows": []},
    )

    rows = Asset.upsert_many([{"unique_identifier": "A", "asset_type": "Equity"}])
    total = AccountHoldingsSet.count(account_uid=str(account_uid))
    AccountHoldingsSet.filter(account_uid=str(account_uid), order_by="-time_index", offset=5)

    assert [row.asset_type for row in rows] == ["equity"]
    assert total == 3
    assert seen["count"]["filters"] == {"account_uid": account_uid}
    assert seen["search"]["order_by"] == ["-time_index"] and seen["search"]["offset"] == 5


def test_holdings_and_snapshots_publish_through_markets(monkeypatch, remote) -> None:
    from msm.api.accounts import AccountHoldingsSnapshots
    from msm.api.assets import AssetSnapshots

    account_uid = str(uuid.uuid4())
    published: dict[str, Any] = {}

    def add_snapshot(context, **kwargs):
        published["holdings"] = kwargs
        return {"account_uid": kwargs["account_uid"], "holdings": [{"asset_identifier": "A"}]}

    class FakeSnapshotUpdater:
        def set_snapshots(self, rows):
            published["snapshots"] = rows
            return self

        def run(self):
            return False, None

    monkeypatch.setattr("msm.services.add_account_holdings_snapshot_response", add_snapshot)
    monkeypatch.setattr("msm.time_index.assets.AssetSnapshot", FakeSnapshotUpdater)

    snapshot = AccountHoldingsSnapshots.publish(
        account_uid=account_uid,
        holdings_date=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        positions=[{"asset_identifier": "A", "quantity": "10", "extra_details": {"source": "feed"}}],
    )
    written = AssetSnapshots.publish([{"asset_identifier": "A", "name": "Acme"}])

    assert snapshot["holdings"] == [{"asset_identifier": "A"}]
    assert published["holdings"]["account_uid"] == account_uid
    assert published["holdings"]["positions"][0]["extra_details"] == {"source": "feed"}
    assert published["holdings"]["holdings_date"] == dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    assert written == 1
    assert published["snapshots"] == [{"asset_identifier": "A", "name": "Acme"}]


@pytest.mark.parametrize(
    ("resource", "operation", "arguments"),
    [
        ("asset-snapshots", "publish", {"snapshots": [{"asset_identifier": "A"}]}),
        (
            "account-holdings",
            "publish",
            {"account_uid": str(uuid.uuid4()), "holdings_date": "2026-01-02T00:00:00Z", "positions": []},
        ),
        ("portfolio-datasets", "register", {"registration": {"portfolio_uid": str(uuid.uuid4())}}),
        ("portfolio-datasets", "reconcile", {"portfolio_uids": [str(uuid.uuid4())]}),
        ("asset", "upsert_many", {"payloads": [{"unique_identifier": "A"}]}),
        (
            "portfolio-datasets",
            "register_signal",
            {"registration": {"signal_uid": "s", "signal_meta_table_uid": "t"}},
        ),
        ("formula-index", "activate_definition", {"definition_uid": str(uuid.uuid4())}),
        ("portfolio-datasets", "unregister", {"portfolio_uid": str(uuid.uuid4())}),
        ("portfolio-datasets", "unregister_signal", {"signal_uid": "s"}),
        ("currency-spot", "upsert_many", {"payloads": []}),
        ("future", "upsert_many", {"payloads": []}),
        ("formula-index", "retire_definition", {"definition_uid": str(uuid.uuid4())}),
    ],
)
def test_every_publication_and_catalog_write_is_policy_checked(
    monkeypatch, remote, resource, operation, arguments
) -> None:
    from msm.api.remote import WRITE_OPERATIONS

    monkeypatch.setattr(policy, "resolve_identity_type", lambda uid: "workload")

    assert operation in WRITE_OPERATIONS
    with pytest.raises(MarketsAccessError, match="MARKETS_REGISTRY_WRITERS"):
        remote.client.run_row_operation(resource, operation, arguments)


def test_portfolio_datasets_register_runs_remotely(monkeypatch, remote) -> None:
    from msm_portfolios.api.datasets import PortfolioDatasets
    from msm_portfolios.services.portfolio_datasets import PortfolioDatasetState

    portfolio_uid = uuid.uuid4()
    seen: dict[str, Any] = {}

    def register(context, registration, *, reconcile=True, **kwargs):
        seen.update({"registration": dict(registration), "reconcile": reconcile})
        return PortfolioDatasetState(
            portfolio_uid=portfolio_uid,
            portfolio_identifier="provider-sleeve",
            values_meta_table_uid="values-uid",
            population_state="compatible_empty",
            reconciled_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        )

    monkeypatch.setattr(
        "msm_portfolios.services.portfolio_datasets.register_portfolio_datasets", register
    )

    state = PortfolioDatasets.register(
        {"portfolio_uid": str(portfolio_uid), "values_meta_table_uid": "values-uid"},
        reconcile=False,
    )

    assert isinstance(state, PortfolioDatasetState)
    assert state.portfolio_uid == portfolio_uid
    assert seen == {
        "registration": {"portfolio_uid": str(portfolio_uid), "values_meta_table_uid": "values-uid"},
        "reconcile": False,
    }


class _Recording:
    """Remote backend that records each resource and operation it sends."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self.calls: list[tuple[str, str]] = []

    def call(self, resource: str, operation: str, arguments: Any) -> Any:
        self.calls.append((resource, operation))
        return self.backend.call(resource, operation, arguments)


def test_range_filters_reach_the_runtime_typed(monkeypatch, remote) -> None:
    from msm.api.calendars import CalendarSession

    calendar_uid = uuid.uuid4()
    seen: dict[str, Any] = {}

    def search_model(context, **kwargs):
        seen["search"] = kwargs
        return {
            "rows": [
                {
                    "uid": str(uuid.uuid4()),
                    "calendar_uid": str(calendar_uid),
                    "local_date": "2026-01-05",
                    "session_label": "regular",
                }
            ]
        }

    monkeypatch.setattr("msm.repositories.crud.search_model", search_model)
    monkeypatch.setattr(
        "msm.repositories.crud.count_model",
        lambda context, **kwargs: seen.setdefault("count", kwargs) and {"rows": [{"count": 2}]},
    )

    sessions = CalendarSession.filter(
        calendar_uid=calendar_uid,
        local_date__gte=dt.date(2026, 1, 1),
        local_date__lte=dt.date(2026, 1, 31),
        order_by="local_date",
    )
    total = CalendarSession.count(calendar_uid=calendar_uid, local_date__lt=dt.date(2026, 2, 1))

    assert [session.local_date for session in sessions] == [dt.date(2026, 1, 5)]
    assert seen["search"]["filters"] == {"calendar_uid": calendar_uid}
    assert seen["search"]["range_filters"] == {
        "local_date": {"gte": dt.date(2026, 1, 1), "lte": dt.date(2026, 1, 31)}
    }
    assert seen["count"]["range_filters"] == {"local_date": {"lt": dt.date(2026, 2, 1)}}
    assert total == 2


def test_persisted_calendar_schedule_reads_sessions_through_markets(monkeypatch, remote) -> None:
    import pandas as pd

    from msm_portfolios.services.calendars import PersistedCalendarSchedule

    calendar_uid = uuid.uuid4()
    recording = _Recording(remote.client.backend)
    use_remote_backend(recording)
    monkeypatch.setattr(
        "msm.repositories.crud.search_model",
        lambda context, **kwargs: {
            "rows": [
                {
                    "uid": str(uuid.uuid4()),
                    "calendar_uid": str(calendar_uid),
                    "local_date": "2026-01-05",
                    "session_label": "regular",
                    "opens_at": "2026-01-05T14:30:00Z",
                    "closes_at": "2026-01-05T21:00:00Z",
                }
            ]
        },
    )

    frame = PersistedCalendarSchedule(
        calendar=SimpleNamespace(uid=calendar_uid, unique_identifier="XNYS")
    ).schedule("2026-01-05", "2026-01-06")

    assert recording.calls == [("calendar-session", "filter")]
    assert list(frame.index) == [dt.date(2026, 1, 5)]
    assert frame.loc[dt.date(2026, 1, 5), "market_close"] == pd.Timestamp("2026-01-05T21:00:00Z")


def test_formula_activation_and_retirement_run_remotely(monkeypatch, remote) -> None:
    from msm.analytics.indices import IndexFormulaDefinition
    from msm.api import formula_indices as formula_api

    recording = _Recording(remote.client.backend)
    use_remote_backend(recording)
    definition_uid = uuid.uuid4()
    draft = IndexFormulaDefinition(
        uid=definition_uid,
        index_uid=uuid.uuid4(),
        version=1,
        valid_from=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        formula='asset["BOND"].yield',
    )
    retired_at = dt.datetime(2027, 1, 1, tzinfo=dt.UTC)
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        formula_api,
        "activate_formula_definition",
        lambda context, *, definition_uid: draft.model_copy(update={"status": "active"}),
    )

    def retire(context, *, definition_uid, valid_to):
        seen["retire"] = (definition_uid, valid_to)
        return draft.model_copy(update={"status": "retired", "valid_to": retired_at})

    monkeypatch.setattr(formula_api, "retire_formula_definition", retire)

    active = formula_api.FormulaIndex.activate_definition(definition_uid)
    retired = formula_api.FormulaIndex.retire_definition(definition_uid, valid_to=retired_at)

    assert isinstance(active, IndexFormulaDefinition) and active.status == "active"
    assert retired.status == "retired" and retired.valid_to == retired_at
    assert str(seen["retire"][0]) == str(definition_uid)
    assert recording.calls == [
        ("formula-index", "activate_definition"),
        ("formula-index", "retire_definition"),
    ]


def test_latest_asset_snapshots_read_through_markets(monkeypatch, remote) -> None:
    from msm.api.assets import AssetSnapshotReference, AssetSnapshots

    asset_uid = uuid.uuid4()
    seen: dict[str, Any] = {}

    def by_ticker(tickers, *, repository_context):
        seen["tickers"] = list(tickers)
        return ["FIGI-1"]

    def details(identifiers, *, repository_context):
        seen["identifiers"] = list(identifiers)
        return [
            {
                "asset_uid": str(asset_uid),
                "asset_identifier": "FIGI-1",
                "asset_type": "equity",
                "snapshot_time": "2026-01-02T00:00:00Z",
                "time_index": "2026-01-02T00:00:00Z",
                "name": "Acme",
                "ticker": "ACME",
                "exchange_code": None,
                "asset_ticker_group_id": None,
            }
        ]

    monkeypatch.setattr("msm.services.assets.asset_identifiers_by_ticker", by_ticker)
    monkeypatch.setattr("msm.services.assets.asset_reference_details", details)

    rows = AssetSnapshots.latest(tickers=["ACME"])

    assert rows == [
        AssetSnapshotReference(
            asset_uid=asset_uid,
            asset_identifier="FIGI-1",
            asset_type="equity",
            snapshot_time=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
            name="Acme",
            ticker="ACME",
        )
    ]
    assert seen == {"tickers": ["ACME"], "identifiers": ["FIGI-1"]}
    with pytest.raises(ValueError, match="exactly one"):
        AssetSnapshots.latest()


def test_portfolio_values_page_past_one_request() -> None:
    sent: list[dict[str, Any]] = []

    class Session:
        def request(self, method, url, *, json=None, params=None, headers=None):
            query = dict(params)
            sent.append(query)
            start = query.get("offset", 0)
            available = max(0, 12_000 - start)
            rows = [{"time_index": str(start + i)} for i in range(min(query["limit"], available))]
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"columns": ["time_index"], "rows": rows, "meta": {"page": start}},
            )

    client = MarketsClient("http://markets", session=Session())

    frame = client.portfolio_values(["p"], limit=20_000)

    assert [(query["limit"], query.get("offset", 0)) for query in sent] == [
        (5000, 0),
        (5000, 5000),
        (5000, 10_000),
    ]
    assert len(frame["rows"]) == 12_000 and frame["columns"] == ["time_index"]
    sent.clear()
    client.portfolio_values(["p"], limit=10, offset=30)
    assert sent == [{"portfolio_uid__in": "p", "limit": 10, "offset": 30}]


def test_composite_batches_and_holdings_snapshots_run_remotely(monkeypatch, remote) -> None:
    from msm.api import assets as assets_api
    from msm.api.accounts import AccountHoldingsSnapshots

    recording = _Recording(remote.client.backend)
    use_remote_backend(recording)
    base, quote, pair = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        assets_api,
        "search_model",
        lambda context, *, model, **kwargs: {
            "rows": [
                {"uid": str(pair), "unique_identifier": "EUR/USD", "asset_type": "currency_spot"}
                if model.__name__ == "AssetTable"
                else {"asset_uid": str(pair), "base_currency_uid": str(base), "quote_currency_uid": str(quote)}
            ]
        },
    )
    seen: dict[str, Any] = {}

    def snapshots(context, **kwargs):
        seen.update(kwargs)
        return [{"holdings_set_uid": "s", "holdings_date": "2026-01-02T00:00:00Z", "holdings": []}]

    monkeypatch.setattr("msm.services.get_account_holdings_snapshots_response", snapshots)

    spots = CurrencySpot.filter(asset_uids=[pair])
    history = AccountHoldingsSnapshots.get_many(account_uid=str(uuid.uuid4()), limit=3)

    assert [(spot.uid, spot.base_currency_uid) for spot in spots] == [(pair, base)]
    assert history[0]["holdings_set_uid"] == "s" and seen["limit"] == 3
    assert recording.calls == [("currency-spot", "filter"), ("account-holdings", "get_many")]
