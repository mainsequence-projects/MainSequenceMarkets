"""Batch lookups by uid for assets, accounts, portfolios and indexes (ADR 0047)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.services.lookups import normalize_lookup_uids, rows_by_uids


def test_normalize_lookup_uids_accepts_repeated_and_comma_separated_values() -> None:
    first, second = uuid.uuid4(), uuid.uuid4()

    assert normalize_lookup_uids([f"{first},{second}", str(first), " "]) == [first, second]
    with pytest.raises(ValueError, match="at least one"):
        normalize_lookup_uids([""])
    with pytest.raises(ValueError, match="not a UUID"):
        normalize_lookup_uids(["not-a-uuid"])
    with pytest.raises(ValueError, match="at most 500"):
        normalize_lookup_uids([str(uuid.uuid4()) for _ in range(501)])


def test_rows_by_uids_issues_one_in_filter_and_keeps_request_order(monkeypatch) -> None:
    from apps.v1.services import lookups
    from msm.models import AssetTable

    first, second, missing = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_search(_context, *, model, in_filters, limit, **_kwargs):
        captured.update(model=model, in_filters=in_filters, limit=limit)
        return {"rows": [{"uid": str(second)}, {"uid": str(first)}]}

    monkeypatch.setattr(lookups, "search_model", fake_search)

    rows = rows_by_uids(object(), model=AssetTable, uids=[first, missing, second])

    assert captured == {"model": AssetTable, "in_filters": {"uid": [first, missing, second]}, "limit": 3}
    assert [row["uid"] for row in rows] == [str(first), str(second)]


@pytest.mark.parametrize(
    ("route", "service_path", "row"),
    [
        (
            "/api/v1/asset/by-uids/",
            "apps.v1.routers.assets.get_assets_by_uids",
            {"uid": str(uuid.uuid4()), "unique_identifier": "BBG000B9XRY4", "asset_type": "equity"},
        ),
        (
            "/api/v1/account/by-uids/",
            "apps.v1.routers.accounts.get_accounts_by_uids",
            {
                "uid": str(uuid.uuid4()),
                "unique_identifier": "broker-paper-1",
                "account_name": "Broker paper",
                "is_paper": True,
                "account_is_active": True,
                "account_group_uid": None,
                "holdings_storage_table_uid": None,
                "holdings_data_node_uid": None,
                "metadata_json": None,
            },
        ),
        (
            "/api/v1/portfolio/by-uids/",
            "apps.v1.routers.portfolios.get_portfolios_by_uids",
            {
                "uid": str(uuid.uuid4()),
                "unique_identifier": "equity-tracker",
                "calendar_uid": str(uuid.uuid4()),
                "published_index_uid": None,
                "portfolio_weights_table_update_uid": None,
                "portfolio_weights_data_node_uid": None,
                "signal_weights_table_update_uid": None,
                "signal_weights_data_node_uid": None,
                "signal_uid": None,
                "portfolio_table_update_uid": None,
                "portfolio_data_node_uid": None,
                "backtest_table_price_column_name": "close",
            },
        ),
        (
            "/api/v1/index/by-uids/",
            "apps.v1.routers.indices.get_indexes_by_uids",
            {
                "uid": str(uuid.uuid4()),
                "unique_identifier": "SPX",
                "index_type": "equity",
                "display_name": "S&P 500",
                "calculation_method": "custom",
                "value_format": "decimal",
                "value_suffix": None,
                "description": None,
                "metadata_json": None,
            },
        ),
    ],
    ids=["asset", "account", "portfolio", "index"],
)
def test_by_uids_routes_return_rows_in_a_collection_without_paging(monkeypatch, route, service_path, row):
    captured: dict[str, object] = {}

    def fake_lookup(*, uids, include=None):
        captured["uids"] = list(uids)
        captured["include"] = include
        return [{**row, "includes": {}}]

    monkeypatch.setattr(service_path, fake_lookup)
    other = str(uuid.uuid4())

    response = TestClient(app).get(route, params=[("uid__in", row["uid"]), ("uid__in", other)])

    assert response.status_code == 200
    assert captured["uids"] == [row["uid"], other]
    payload = response.json()
    assert payload["items"] == [{**row, "includes": {}}]
    assert captured["include"] is None
    assert payload["pageInfo"]["totalItems"] == 1
    assert payload["pageInfo"]["hasNextPage"] is False
    operation = app.openapi()["paths"][route]["get"]
    assert operation["operationId"].endswith("ByUids")
    assert "x-ui-contract" not in operation
    assert {parameter["name"] for parameter in operation["parameters"]} == {"uid__in", "include"}


def test_by_uids_routes_reject_malformed_uids(monkeypatch) -> None:
    from apps.v1.services import assets as asset_service

    monkeypatch.setattr(asset_service, "_get_runtime", lambda: SimpleNamespace(context=object()))

    response = TestClient(app).get("/api/v1/asset/by-uids/", params={"uid__in": "nope"})

    assert response.status_code == 400
    assert "not a UUID" in response.json()["detail"]
    assert TestClient(app).get("/api/v1/asset/by-uids/").status_code == 422
