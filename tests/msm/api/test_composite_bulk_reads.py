"""Composite rows and holdings snapshots read and write in batches (ADR 0047 remote parity)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from msm.api import assets as assets_api
from msm.api import derivatives as derivatives_api
from msm.api.assets import CurrencySpot
from msm.api.derivatives import Future


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **kwargs: SimpleNamespace(context=SimpleNamespace(timeout=None)),
    )


class _Tables:
    """Answer composite statements from memory and record each one."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, str]] = []
        self.assets: dict[str, dict[str, Any]] = {}
        self.details: dict[str, dict[str, Any]] = {}

    def upsert(self, context, *, model, values, conflict_columns):
        self.statements.append(("upsert", model.__name__))
        return {"rows": [dict(values)]}

    def bulk_upsert(self, context, *, model, values, conflict_columns):
        self.statements.append(("bulk_upsert", model.__name__))
        rows = []
        for value in values:
            if model.__name__ == "AssetTable":
                row = self.assets.setdefault(
                    value["unique_identifier"], {"uid": str(uuid.uuid4()), **value}
                )
            else:
                row = {**value, "asset_uid": str(value["asset_uid"])}
                self.details[row["asset_uid"]] = row
            rows.append(dict(row))
        return {"rows": rows}

    def search(self, context, *, model, in_filters=None, limit=500, offset=0, order_by=None, **kwargs):
        self.statements.append(("search", model.__name__))
        filters = in_filters or {}
        if model.__name__ == "AssetTable":
            wanted = {str(uid) for uid in filters.get("uid", [])}
            return {"rows": [row for row in self.assets.values() if row["uid"] in wanted]}
        rows = [
            row
            for row in self.details.values()
            if all(str(row.get(column)) in {str(item) for item in items} for column, items in filters.items())
        ]
        return {"rows": sorted(rows, key=lambda row: row["asset_uid"])[offset : offset + limit]}

    def install(self, monkeypatch, module) -> None:
        monkeypatch.setattr(module, "upsert_model", self.upsert)
        monkeypatch.setattr(module, "bulk_upsert_model", self.bulk_upsert)
        monkeypatch.setattr(assets_api, "bulk_upsert_model", self.bulk_upsert)
        monkeypatch.setattr(assets_api, "search_model", self.search)


def test_currency_spot_upsert_many_and_filter_use_one_statement_per_table(monkeypatch, runtime) -> None:
    tables = _Tables()
    tables.install(monkeypatch, assets_api)
    usd, eur, gbp = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    spots = CurrencySpot.upsert_many(
        [
            {"unique_identifier": "EUR/USD", "base_currency_uid": eur, "quote_currency_uid": usd},
            {"unique_identifier": "GBP/USD", "base_currency_uid": gbp, "quote_currency_uid": usd},
            {"unique_identifier": "GBP/USD", "base_currency_uid": gbp, "quote_currency_uid": usd},
        ]
    )

    assert sorted(spot.unique_identifier for spot in spots) == ["EUR/USD", "GBP/USD"]
    assert tables.statements == [
        ("upsert", "AssetTypeTable"),
        ("bulk_upsert", "AssetTable"),
        ("bulk_upsert", "CurrencySpotAssetDetailsTable"),
    ]
    assert CurrencySpot.upsert_many([]) == []

    tables.statements.clear()
    found = CurrencySpot.filter(base_currency_uids=[str(gbp)])

    assert [spot.unique_identifier for spot in found] == ["GBP/USD"]
    assert found[0].quote_currency_uid == usd
    assert tables.statements == [
        ("search", "CurrencySpotAssetDetailsTable"),
        ("search", "AssetTable"),
    ]


def test_future_upsert_many_and_filter(monkeypatch, runtime) -> None:
    tables = _Tables()
    tables.install(monkeypatch, derivatives_api)
    index_uid, usdt = uuid.uuid4(), uuid.uuid4()
    terms = {
        "kind": "perpetual",
        "underlying_index_uid": index_uid,
        "quote_unit": "usdt",
        "settlement_asset": usdt,
        "margin_asset": usdt,
        "settlement_model": "linear",
        "settlement_method": "cash",
        "contract_size": "1",
        "contract_unit": "btc",
    }

    futures = Future.upsert_many([{"unique_identifier": "BTCUSDT-PERP", **terms}])

    assert [future.unique_identifier for future in futures] == ["BTCUSDT-PERP"]
    assert futures[0].kind == "PERPETUAL" and futures[0].contract_size == Decimal("1")
    assert tables.statements == [
        ("upsert", "AssetTypeTable"),
        ("bulk_upsert", "AssetTable"),
        ("bulk_upsert", "FutureAssetDetailsTable"),
    ]

    assert [future.unique_identifier for future in Future.filter(kinds=["perpetual"])] == ["BTCUSDT-PERP"]
    assert Future.filter(underlying_index_uids=[uuid.uuid4()]) == []


def test_holdings_snapshots_scan_ordered_pages(monkeypatch) -> None:
    from msm.services.accounts import core

    account_uid = str(uuid.uuid4())
    times = [dt.datetime(2026, 1, day, tzinfo=dt.UTC) for day in (3, 2, 1)]
    rows = [
        {"time_index": time, "account_uid": account_uid, "asset_identifier": f"A{index}",
         "holdings_set_uid": f"set-{time.day}", "quantity": 1, "direction": 1}
        for time in times
        for index in range(300)
    ]
    calls: list[dict[str, Any]] = []

    def search_model(context, *, model, filters, in_filters=None, limit, offset=0, order_by=None):
        calls.append({"in_filters": in_filters, "offset": offset, "order_by": order_by})
        selected = rows if not in_filters else [r for r in rows if r["time_index"] in in_filters["time_index"]]
        selected = sorted(selected, key=lambda r: r["time_index"], reverse=order_by == ["-time_index"])
        return {"rows": selected[offset : offset + limit]}

    monkeypatch.setattr("msm.repositories.crud.search_model", search_model)
    monkeypatch.setattr(core, "get_account_by_uid", lambda context, uid: {"row": {"uid": account_uid}})

    latest_two = core.get_account_holdings_snapshots_response(object(), account_uid=account_uid, limit=2)

    assert [snapshot["holdings_date"] for snapshot in latest_two] == times[:2]
    assert [len(snapshot["holdings"]) for snapshot in latest_two] == [300, 300]
    assert [call["offset"] for call in calls] == [0, 500]
    assert calls[0]["order_by"] == ["-time_index"]

    calls.clear()
    chosen = core.get_account_holdings_snapshots_response(
        object(), account_uid=account_uid, holdings_dates=[times[2], dt.datetime(2020, 1, 1, tzinfo=dt.UTC)]
    )
    assert [snapshot["holdings_date"] for snapshot in chosen] == [times[2]]
    assert calls[0]["in_filters"]["time_index"][0] == times[2]

    earliest = core.get_account_holdings_snapshot_response(
        object(), account_uid=account_uid, order="asc", include_asset_detail=False
    )
    assert earliest["holdings_date"] == times[2]
    latest = core.get_account_holdings_snapshot_response(
        object(), account_uid=account_uid, include_asset_detail=False
    )
    assert latest["holdings_date"] == times[0]
