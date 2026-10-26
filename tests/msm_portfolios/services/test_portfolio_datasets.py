from __future__ import annotations

import datetime as dt
import os
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")

from msm.models import PortfolioDatasetAvailabilityTable, SignalMetadataTable
from msm_portfolios.services import portfolio_datasets
from msm_portfolios.services.portfolio_datasets import (
    PortfolioDatasetRegistration,
    list_portfolio_dataset_states,
    reconcile_portfolio_dataset_availability,
    register_portfolio_datasets,
    register_signal_dataset,
    unregister_portfolio_datasets,
    unregister_signal_dataset,
    verify_contract_instance,
)

NOW = dt.datetime(2026, 1, 31, tzinfo=dt.UTC)
VALUES_COLUMNS = ["time_index", "portfolio_identifier", "close", "return", "calculated_close", "close_time"]


def _meta_table(uid: str, *, physical: str, columns: list[str] | None = None, index_names=None):
    return SimpleNamespace(
        uid=uid,
        physical_table_name=physical,
        physical_schema="public",
        columns=[{"name": name} for name in (columns or VALUES_COLUMNS)],
        table_index_names=index_names if index_names is not None else ["time_index", "portfolio_identifier"],
    )


def _portfolio(identifier: str, *, signal_uid: str | None = None) -> dict[str, Any]:
    return {
        "uid": uuid.uuid4(),
        "unique_identifier": identifier,
        "calendar_uid": uuid.uuid4(),
        "signal_uid": signal_uid,
    }


class _Store:
    """Answer portfolio and catalog selects from memory and record every write."""

    def __init__(self, portfolios: list[dict[str, Any]], catalog: list[dict[str, Any]] | None = None):
        self.portfolios = portfolios
        self.catalog = {uuid.UUID(str(row["portfolio_uid"])): dict(row) for row in (catalog or [])}
        self.upserts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.aggregate_sql: list[str] = []
        self.aggregates: dict[str, list[dict[str, Any]]] = {}
        self.aggregate_errors: dict[str, Exception] = {}

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(portfolio_datasets, "compile_markets_statement", self._compile)
        monkeypatch.setattr(portfolio_datasets, "execute_markets_operation", self._execute)
        monkeypatch.setattr(portfolio_datasets, "search_model", self._search)
        monkeypatch.setattr(portfolio_datasets, "upsert_model", self._upsert)
        monkeypatch.setattr(portfolio_datasets, "update_model", self._update)

    def _compile(self, statement, **_kwargs):
        return statement

    def _execute(self, statement, **_kwargs):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if "ms_markets__portfolio " in sql or sql.startswith("SELECT ms_markets__portfolio."):
            return {"rows": [dict(row) for row in self.portfolios if self._selected(row, sql)]}
        self.aggregate_sql.append(sql)
        table_name = sql.split("FROM ")[1].split()[0]
        if table_name in self.aggregate_errors:
            raise self.aggregate_errors[table_name]
        return {"rows": self.aggregates.get(table_name, [])}

    @staticmethod
    def _selected(row: dict[str, Any], sql: str) -> bool:
        # SQLAlchemy renders Uuid literals as undashed hex.
        return row["uid"].hex in sql or f"'{row['unique_identifier']}'" in sql

    def _search(self, _context, *, model, filters=None, in_filters=None, limit=500, **_kwargs):
        if model is PortfolioDatasetAvailabilityTable:
            wanted = {uuid.UUID(str(item)) for item in (in_filters or {}).get("portfolio_uid", [])}
            return {"rows": [dict(row) for uid, row in self.catalog.items() if uid in wanted]}
        if model is SignalMetadataTable:
            return {"rows": [{"uid": uuid.uuid4(), "signal_uid": filters["signal_uid"]}]}
        raise AssertionError(model)

    def _upsert(self, _context, *, model, values, conflict_columns):
        assert model is PortfolioDatasetAvailabilityTable
        assert tuple(conflict_columns) == ("portfolio_uid",)
        row = dict(values)
        self.upserts.append(row)
        self.catalog[uuid.UUID(str(row["portfolio_uid"]))] = row
        return {"rows": [row]}

    def _update(self, _context, *, model, uid, values, returning=True):
        self.updates.append({"model": model, "uid": uid, **values})
        return {}


def test_register_verifies_contract_tables_and_reconciles(monkeypatch) -> None:
    growth = _portfolio("growth", signal_uid="growth-signal")
    store = _Store([growth])
    store.install(monkeypatch)
    store.aggregates["my_provider__portfoliosts__main"] = [
        {"portfolio_identifier": "growth", "row_count": 7, "earliest_time_index": NOW - dt.timedelta(days=6),
         "latest_time_index": NOW}
    ]
    tables = {
        "values-uid": _meta_table("values-uid", physical="my_provider__portfoliosts__main"),
        "weights-uid": _meta_table(
            "weights-uid",
            physical="my_provider__portfolioweightsts__main",
            columns=["time_index", "portfolio_identifier", "asset_identifier", "weight", "weight_before",
                     "price_current", "price_before", "volume_current", "volume_before", "extra"],
            index_names=["time_index", "portfolio_identifier", "asset_identifier"],
        ),
        "signal-uid": _meta_table(
            "signal-uid",
            physical="my_provider__signalweightsts__main",
            columns=["time_index", "signal_uid", "asset_identifier", "signal_weight"],
            index_names=["time_index", "signal_uid", "asset_identifier"],
        ),
    }
    looked_up: list[list[str]] = []

    def lookup(uids):
        looked_up.append(list(uids))
        return [tables[uid] for uid in uids if uid in tables]

    state = register_portfolio_datasets(
        object(),
        PortfolioDatasetRegistration(
            portfolio_uid=growth["uid"],
            values_meta_table_uid="values-uid",
            weights_meta_table_uid="weights-uid",
            signal_meta_table_uid="signal-uid",
        ),
        meta_table_lookup=lookup,
    )

    assert looked_up[0] == ["values-uid", "weights-uid", "signal-uid"]
    assert state.portfolio_identifier == "growth"
    assert state.values_meta_table_uid == "values-uid"
    assert state.weights_meta_table_uid == "weights-uid"
    assert state.signal_meta_table_uid == "signal-uid"
    assert state.population_state == "populated"
    assert state.row_count == 7
    assert state.latest_time_index == NOW
    assert state.error is None
    # Registration writes the row once as not reconciled, then the reconcile overwrites it.
    assert [row["population_state"] for row in store.upserts] == ["unavailable", "populated"]
    assert store.upserts[0]["error_code"] == "not_reconciled"
    assert store.upserts[1]["uid"] == store.upserts[0]["uid"]
    # The signal's metadata row points at the same instance.
    assert store.updates == [
        {"model": SignalMetadataTable, "uid": store.updates[0]["uid"], "meta_table_uid": "signal-uid"}
    ]
    assert "GROUP BY" in store.aggregate_sql[0]
    assert "my_provider__portfoliosts__main" in store.aggregate_sql[0]


def test_register_rejects_missing_or_incompatible_tables(monkeypatch) -> None:
    growth = _portfolio("growth")
    store = _Store([growth])
    store.install(monkeypatch)
    registration = PortfolioDatasetRegistration(
        portfolio_uid=growth["uid"], values_meta_table_uid="values-uid"
    )

    with pytest.raises(LookupError, match="not a visible TimeIndexMetaTable"):
        register_portfolio_datasets(object(), registration, meta_table_lookup=lambda _uids: [])

    incompatible = _meta_table("values-uid", physical="x", columns=["time_index", "portfolio_identifier"])
    with pytest.raises(ValueError, match="missing contract columns"):
        register_portfolio_datasets(object(), registration, meta_table_lookup=lambda _uids: [incompatible])

    with pytest.raises(LookupError, match="was not found"):
        register_portfolio_datasets(
            object(),
            {"portfolio_uid": uuid.uuid4(), "values_meta_table_uid": "values-uid"},
            meta_table_lookup=lambda _uids: [],
        )
    assert store.upserts == []


def test_register_signal_binds_any_signal_to_a_verified_instance(monkeypatch) -> None:
    store = _Store([])
    store.install(monkeypatch)
    signal_table = _meta_table(
        "signal-uid",
        physical="my_provider__signalweightsts__main",
        columns=["time_index", "signal_uid", "asset_identifier", "signal_weight"],
        index_names=["time_index", "signal_uid", "asset_identifier"],
    )

    registration = register_signal_dataset(
        object(),
        {"signal_uid": "last-week-signal", "signal_meta_table_uid": "signal-uid"},
        meta_table_lookup=lambda uids: [signal_table] if list(uids) == ["signal-uid"] else [],
    )

    assert registration.signal_uid == "last-week-signal"
    assert store.updates == [
        {"model": SignalMetadataTable, "uid": store.updates[0]["uid"], "meta_table_uid": "signal-uid"}
    ]
    with pytest.raises(LookupError, match="not a visible TimeIndexMetaTable"):
        register_signal_dataset(
            object(),
            {"signal_uid": "last-week-signal", "signal_meta_table_uid": "missing"},
            meta_table_lookup=lambda _uids: [],
        )
    values_table = _meta_table("values-uid", physical="x")
    with pytest.raises(ValueError, match="missing contract columns"):
        register_signal_dataset(
            object(),
            {"signal_uid": "last-week-signal", "signal_meta_table_uid": "values-uid"},
            meta_table_lookup=lambda _uids: [values_table],
        )


def test_register_signal_requires_a_signal_metadata_row(monkeypatch) -> None:
    store = _Store([])
    store.install(monkeypatch)
    monkeypatch.setattr(portfolio_datasets, "search_model", lambda *_args, **_kwargs: {"rows": []})

    with pytest.raises(LookupError, match="has no SignalMetadata row"):
        register_signal_dataset(
            object(),
            {"signal_uid": "unknown", "signal_meta_table_uid": "signal-uid"},
            verify_tables=False,
        )
    assert store.updates == []


def test_unregister_removes_the_catalog_row_and_its_signal_binding(monkeypatch) -> None:
    growth = _portfolio("growth", signal_uid="growth-signal")
    catalog_row = {
        "uid": uuid.uuid4(),
        "portfolio_uid": growth["uid"],
        "values_meta_table_uid": "values-uid",
        "weights_meta_table_uid": None,
        "signal_meta_table_uid": "signal-uid",
        "population_state": "populated",
        "row_count": 3,
        "reconciled_at": NOW,
    }
    store = _Store([growth], catalog=[catalog_row])
    store.install(monkeypatch)
    deleted: list[Any] = []
    monkeypatch.setattr(
        portfolio_datasets,
        "delete_model",
        lambda _context, *, model, uid: deleted.append((model, uid)) or {},
    )
    signal_row_uid = uuid.uuid4()
    original_search = store._search

    def search(_context, *, model, filters=None, **kwargs):
        if model is SignalMetadataTable:
            return {"rows": [{"uid": signal_row_uid, "signal_uid": filters["signal_uid"], "meta_table_uid": "signal-uid"}]}
        return original_search(_context, model=model, filters=filters, **kwargs)

    monkeypatch.setattr(portfolio_datasets, "search_model", search)

    state = unregister_portfolio_datasets(object(), portfolio_uid=str(growth["uid"]))

    assert state is not None and state.values_meta_table_uid == "values-uid"
    assert deleted == [(PortfolioDatasetAvailabilityTable, catalog_row["uid"])]
    assert store.updates == [{"model": SignalMetadataTable, "uid": signal_row_uid, "meta_table_uid": None}]

    store.updates.clear()
    store.catalog[growth["uid"]] = dict(catalog_row)
    kept = unregister_portfolio_datasets(object(), portfolio_uid=growth["uid"], unbind_signal=False)
    assert kept is not None and store.updates == []

    store.catalog.clear()
    assert unregister_portfolio_datasets(object(), portfolio_uid=growth["uid"]) is None
    with pytest.raises(LookupError, match="was not found"):
        unregister_portfolio_datasets(object(), portfolio_uid=uuid.uuid4())


def test_unregister_signal_clears_only_a_bound_signal(monkeypatch) -> None:
    store = _Store([])
    store.install(monkeypatch)
    signal_row_uid = uuid.uuid4()
    bound: dict[str, Any] = {"meta_table_uid": "signal-uid"}
    monkeypatch.setattr(
        portfolio_datasets,
        "search_model",
        lambda _context, *, model, filters=None, **kwargs: {
            "rows": [] if filters["signal_uid"] == "unknown"
            else [{"uid": signal_row_uid, "signal_uid": filters["signal_uid"], **bound}]
        },
    )

    removed = unregister_signal_dataset(object(), signal_uid="last-week-signal")

    assert removed is not None and removed.signal_meta_table_uid == "signal-uid"
    assert store.updates == [{"model": SignalMetadataTable, "uid": signal_row_uid, "meta_table_uid": None}]
    bound["meta_table_uid"] = None
    assert unregister_signal_dataset(object(), signal_uid="last-week-signal") is None
    assert len(store.updates) == 1
    with pytest.raises(LookupError, match="has no SignalMetadata row"):
        unregister_signal_dataset(object(), signal_uid="unknown")


def test_verify_contract_instance_allows_extra_columns_but_requires_grain() -> None:
    verify_contract_instance(
        "PortfoliosTS", _meta_table("u", physical="p", columns=[*VALUES_COLUMNS, "provider_extra"])
    )
    with pytest.raises(ValueError, match="index names"):
        verify_contract_instance(
            "PortfoliosTS", _meta_table("u", physical="p", index_names=["time_index"])
        )


def test_reconcile_groups_portfolios_by_values_table_and_skips_uncatalogued(monkeypatch) -> None:
    growth, balanced, income, legacy = (
        _portfolio("growth"), _portfolio("balanced"), _portfolio("income"), _portfolio("legacy")
    )
    catalog = [
        {"uid": uuid.uuid4(), "portfolio_uid": growth["uid"], "values_meta_table_uid": "provider-a",
         "weights_meta_table_uid": "provider-a-w", "signal_meta_table_uid": None},
        {"uid": uuid.uuid4(), "portfolio_uid": balanced["uid"], "values_meta_table_uid": "provider-a",
         "weights_meta_table_uid": None, "signal_meta_table_uid": None},
        {"uid": uuid.uuid4(), "portfolio_uid": income["uid"], "values_meta_table_uid": "provider-b",
         "weights_meta_table_uid": None, "signal_meta_table_uid": None},
    ]
    store = _Store([growth, balanced, income, legacy], catalog)
    store.install(monkeypatch)
    store.aggregates["provider_a__portfoliosts"] = [
        {"portfolio_identifier": "growth", "row_count": 3, "earliest_time_index": NOW, "latest_time_index": NOW},
    ]
    store.aggregate_errors["provider_b__portfoliosts"] = PermissionError("no data_viewer role")
    tables = {
        "provider-a": _meta_table("provider-a", physical="provider_a__portfoliosts"),
        "provider-b": _meta_table("provider-b", physical="provider_b__portfoliosts"),
    }

    result = reconcile_portfolio_dataset_availability(
        object(),
        portfolio_uids=[growth["uid"], balanced["uid"]],
        portfolio_identifiers=["income", "legacy"],
        meta_table_lookup=lambda uids: [tables[uid] for uid in uids],
    )

    # One aggregate per instance, not per portfolio; both provider A portfolios share one statement.
    assert len(store.aggregate_sql) == 2
    provider_a_sql = next(sql for sql in store.aggregate_sql if "provider_a__portfoliosts" in sql)
    assert "'growth'" in provider_a_sql and "'balanced'" in provider_a_sql
    states = {state.portfolio_identifier: state for state in result.states}
    assert states["growth"].population_state == "populated"
    assert states["growth"].row_count == 3
    assert states["growth"].weights_meta_table_uid == "provider-a-w"
    assert states["balanced"].population_state == "compatible_empty"
    assert states["balanced"].row_count == 0
    assert states["income"].population_state == "unavailable"
    assert states["income"].error == "PermissionError: no data_viewer role"
    assert result.skipped_portfolio_uids == (legacy["uid"],)
    assert set(result.portfolio_uids) == {growth["uid"], balanced["uid"], income["uid"], legacy["uid"]}
    assert all(row["uid"] in {item["uid"] for item in catalog} for row in store.upserts)


def test_reconcile_requires_selectors_and_reports_unknown_portfolios(monkeypatch) -> None:
    store = _Store([_portfolio("growth")])
    store.install(monkeypatch)

    with pytest.raises(ValueError, match="explicit portfolio UIDs"):
        reconcile_portfolio_dataset_availability(object())
    with pytest.raises(LookupError, match="identifiers=\\['missing'\\]"):
        reconcile_portfolio_dataset_availability(object(), portfolio_identifiers=["missing"])


def test_list_states_returns_catalog_rows_without_reconciling(monkeypatch) -> None:
    growth = _portfolio("growth")
    store = _Store(
        [growth],
        [{"uid": uuid.uuid4(), "portfolio_uid": growth["uid"], "values_meta_table_uid": "provider-a",
          "weights_meta_table_uid": None, "signal_meta_table_uid": None,
          "population_state": "unavailable", "row_count": None, "earliest_time_index": None,
          "latest_time_index": None, "reconciled_at": NOW, "error_code": "not_reconciled",
          "error_message": "Registered"}],
    )
    store.install(monkeypatch)

    states = list_portfolio_dataset_states(object(), portfolio_uids=[growth["uid"], uuid.uuid4()])

    assert len(states) == 1
    assert states[0].population_state == "unavailable"
    assert states[0].error == "not_reconciled: Registered"
    assert store.aggregate_sql == []
    assert store.upserts == []
