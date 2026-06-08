from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app


def test_get_accounts_returns_count_and_results(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.accounts.list_accounts",
        lambda **kwargs: {
            "count": 1,
            "results": [
                {
                    "uid": str(account_uid),
                    "unique_identifier": "some-account",
                    "account_name": "Some account",
                    "is_paper": False,
                    "account_is_active": True,
                    "account_group_uid": None,
                    "holdings_data_node_uid": None,
                    "metadata_json": None,
                }
            ],
        },
    )

    client = TestClient(app)
    response = client.get("/api/v1/account/", params={"limit": 25, "offset": 0})

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "uid": str(account_uid),
                "unique_identifier": "some-account",
                "account_name": "Some account",
                "is_paper": False,
                "account_is_active": True,
                "account_group_uid": None,
                "holdings_data_node_uid": None,
                "metadata_json": None,
            }
        ],
    }


def test_get_accounts_passes_query_params(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list_accounts(**kwargs):
        captured.update(kwargs)
        return {"count": 0, "results": []}

    monkeypatch.setattr("apps.v1.routers.accounts.list_accounts", fake_list_accounts)

    client = TestClient(app)
    response = client.get(
        "/api/v1/account/",
        params={"search": "some", "limit": 10, "offset": 5},
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 0,
        "next": None,
        "previous": "http://testserver/api/v1/account/?search=some&limit=10&offset=0",
        "results": [],
    }
    assert captured == {"search": "some", "limit": 10, "offset": 5}


def test_account_service_maps_account_rows(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())

    monkeypatch.setattr("apps.v1.services.accounts._get_runtime", lambda: runtime)
    monkeypatch.setattr(
        "apps.v1.services.accounts._list_account_rows_response",
        lambda context, **kwargs: {
            "count": 1,
            "results": [
                {
                    "uid": str(account_uid),
                    "unique_identifier": "some-account",
                    "account_name": "Some account",
                    "is_paper": False,
                    "account_is_active": True,
                    "account_group_uid": None,
                    "holdings_data_node_uid": None,
                    "metadata_json": {"source": "test"},
                }
            ],
        },
    )

    from apps.v1.services.accounts import list_accounts

    response = list_accounts(limit=25, offset=0)

    assert response.model_dump(mode="json") == {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "uid": str(account_uid),
                "unique_identifier": "some-account",
                "account_name": "Some account",
                "is_paper": False,
                "account_is_active": True,
                "account_group_uid": None,
                "holdings_data_node_uid": None,
                "metadata_json": {"source": "test"},
            }
        ],
    }


def test_get_account_summary_returns_frontend_detail_summary(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_summary",
        lambda uid: {
            "entity": {
                "id": str(account_uid),
                "type": "account",
                "title": "Some account",
            },
            "badges": [
                {
                    "key": "account_is_active",
                    "label": "Active",
                    "tone": "success",
                },
                {
                    "key": "is_paper",
                    "label": "Live",
                    "tone": "success",
                },
            ],
            "inline_fields": [
                {
                    "key": "uid",
                    "label": "UID",
                    "value": str(account_uid),
                    "kind": "code",
                }
            ],
            "highlight_fields": [
                {
                    "key": "display_name",
                    "label": "Display name",
                    "value": "Some account",
                    "kind": "text",
                    "icon": "database",
                }
            ],
            "stats": [],
            "label_management": {
                "labels": [],
                "add_label_url": None,
                "remove_label_url": None,
            },
            "summary_warning": None,
            "extensions": {
                "holdings_data_node_uid": None,
                "metadata_json": None,
            },
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/account/{account_uid}/summary/")

    assert response.status_code == 200
    assert response.json() == {
        "entity": {
            "id": str(account_uid),
            "type": "account",
            "title": "Some account",
        },
        "badges": [
            {
                "key": "account_is_active",
                "label": "Active",
                "tone": "success",
            },
            {
                "key": "is_paper",
                "label": "Live",
                "tone": "success",
            },
        ],
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": str(account_uid),
                "kind": "code",
                "icon": None,
            }
        ],
        "highlight_fields": [
            {
                "key": "display_name",
                "label": "Display name",
                "value": "Some account",
                "kind": "text",
                "icon": "database",
            }
        ],
        "stats": [],
        "label_management": {
            "labels": [],
            "add_label_url": None,
            "remove_label_url": None,
        },
        "summary_warning": None,
        "extensions": {
            "holdings_data_node_uid": None,
            "metadata_json": None,
        },
    }


def test_get_account_summary_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_summary",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/account/missing-account/summary/")

    assert response.status_code == 404
    assert "missing-account" in response.json()["detail"]


def test_search_account_target_allocation_targets_returns_candidates(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_search_targets(**kwargs):
        captured.update(kwargs)
        return {
            "count": 2,
            "results": [
                {
                    "target_type": "asset",
                    "target_uid": str(asset_uid),
                    "asset_uid": str(asset_uid),
                    "portfolio_uid": None,
                    "identifier": "example-asset-btc",
                    "display_label": "Bitcoin",
                    "secondary_label": "BTC",
                    "current_snapshot": {
                        "name": "Bitcoin",
                        "ticker": "BTC",
                    },
                    "metadata": {"asset_type": "crypto"},
                },
                {
                    "target_type": "portfolio",
                    "target_uid": str(portfolio_uid),
                    "asset_uid": None,
                    "portfolio_uid": str(portfolio_uid),
                    "identifier": "example-sleeve",
                    "display_label": "example-sleeve",
                    "secondary_label": None,
                    "current_snapshot": None,
                    "metadata": {"portfolio_index_uid": None},
                },
            ],
        }

    monkeypatch.setattr(
        "apps.v1.routers.accounts.search_account_target_allocation_targets",
        fake_search_targets,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/account/target-allocation/targets/",
        params={
            "search": "btc",
            "target_type": "all",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "search": "btc",
        "target_type": "all",
        "limit": 1,
        "offset": 0,
    }
    assert response.json() == {
        "count": 2,
        "next": "http://testserver/api/v1/account/target-allocation/targets/?search=btc&target_type=all&limit=1&offset=1",
        "previous": None,
        "results": [
            {
                "target_type": "asset",
                "target_uid": str(asset_uid),
                "asset_uid": str(asset_uid),
                "portfolio_uid": None,
                "identifier": "example-asset-btc",
                "display_label": "Bitcoin",
                "secondary_label": "BTC",
                "current_snapshot": {
                    "name": "Bitcoin",
                    "ticker": "BTC",
                },
                "metadata": {"asset_type": "crypto"},
            }
        ],
    }


def test_search_account_target_allocation_targets_validates_target_type() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/account/target-allocation/targets/",
        params={"target_type": "bad"},
    )

    assert response.status_code == 422


def test_account_target_allocation_targets_service_maps_candidates(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "apps.v1.services.accounts._get_target_allocation_candidates_runtime",
        lambda: runtime,
    )

    def fake_search_account_target_allocation_candidates(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "count": 1,
            "results": [
                {
                    "target_type": "asset",
                    "target_uid": str(asset_uid),
                    "asset_uid": str(asset_uid),
                    "portfolio_uid": None,
                    "identifier": "example-asset-btc",
                    "display_label": "Bitcoin",
                    "secondary_label": "BTC",
                    "current_snapshot": {
                        "name": "Bitcoin",
                        "ticker": "BTC",
                    },
                    "metadata": {"asset_type": "crypto"},
                }
            ],
        }

    monkeypatch.setattr(
        "apps.v1.services.accounts._search_account_target_allocation_candidates",
        fake_search_account_target_allocation_candidates,
    )

    from apps.v1.services.accounts import search_account_target_allocation_targets

    response = search_account_target_allocation_targets(
        search="btc",
        target_type="asset",
        limit=10,
        offset=5,
    )

    assert captured == {
        "context": runtime.context,
        "search": "btc",
        "target_type": "asset",
        "limit": 10,
        "offset": 5,
    }
    assert response.model_dump(mode="json") == {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "target_type": "asset",
                "target_uid": str(asset_uid),
                "asset_uid": str(asset_uid),
                "portfolio_uid": None,
                "identifier": "example-asset-btc",
                "display_label": "Bitcoin",
                "secondary_label": "BTC",
                "current_snapshot": {
                    "name": "Bitcoin",
                    "ticker": "BTC",
                },
                "metadata": {"asset_type": "crypto"},
            }
        ],
    }


def test_get_account_holdings_returns_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()

    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_holdings",
        lambda **kwargs: {
            "holdings_set_uid": "holdings-set-uid",
            "holdings_date": "2026-06-01T10:30:00Z",
            "holdings": [
                {
                    "time_index": "2026-06-01T10:30:00Z",
                    "asset_identifier": "btc_spot",
                    "asset": {
                        "uid": str(asset_uid),
                        "asset_identifier": "btc_spot",
                        "current_snapshot": {
                            "name": "Bitcoin spot",
                            "ticker": "BTC",
                        },
                    },
                    "position_type": "units",
                    "price": None,
                    "quantity": "12.0",
                    "direction": -1,
                    "signed_quantity": "-12.0",
                    "missing_price": True,
                    "target_trade_time": None,
                    "extra_details": {"source": "test"},
                }
            ],
        },
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/account/{account_uid}/holdings/",
        params={"order": "desc", "limit": 1, "include_asset_detail": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["holdings_set_uid"] == "holdings-set-uid"
    assert body["holdings"][0]["asset_identifier"] == "btc_spot"
    assert body["holdings"][0]["asset"]["uid"] == str(asset_uid)
    assert body["holdings"][0]["asset"]["asset_identifier"] == "btc_spot"
    assert body["holdings"][0]["asset"]["current_snapshot"] == {
        "name": "Bitcoin spot",
        "ticker": "BTC",
    }
    assert body["holdings"][0]["quantity"] == "12.0"
    assert body["holdings"][0]["direction"] == -1
    assert body["holdings"][0]["signed_quantity"] == "-12.0"


def test_get_account_holdings_passes_query_params(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_get_account_holdings(**kwargs):
        captured.update(kwargs)
        return {
            "holdings_set_uid": None,
            "holdings_date": None,
            "holdings": [],
        }

    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_holdings",
        fake_get_account_holdings,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/account/{account_uid}/holdings/",
        params={
            "order": "asc",
            "limit": 1,
            "include_asset_detail": False,
            "holdings_date": "2026-06-01T10:30:00Z",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "account_uid": str(account_uid),
        "order": "asc",
        "limit": 1,
        "include_asset_detail": False,
        "holdings_date": dt.datetime(2026, 6, 1, 10, 30, tzinfo=dt.UTC),
    }


def test_get_account_holdings_returns_404_when_account_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_holdings",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/account/missing-account/holdings/")

    assert response.status_code == 404
    assert "missing-account" in response.json()["detail"]


def test_get_account_holdings_by_fund_returns_grouped_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    virtual_fund_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_get_account_holdings_by_fund(**kwargs):
        captured.update(kwargs)
        return {
            "account_uid": str(account_uid),
            "source_account_holdings_set_uid": "source-holdings-set-uid",
            "holdings_date": "2026-06-08T10:30:00Z",
            "funds": [
                {
                    "virtual_fund_uid": str(virtual_fund_uid),
                    "virtual_fund_unique_identifier": "account-alpha__sleeve",
                    "target_portfolio_uid": str(portfolio_uid),
                    "holdings_set_uid": "virtual-fund-holdings-set-uid",
                    "holdings": [
                        {
                            "time_index": "2026-06-08T10:30:00Z",
                            "asset_identifier": "example-asset-btc",
                            "asset": {
                                "uid": str(asset_uid),
                                "asset_identifier": "example-asset-btc",
                                "current_snapshot": {
                                    "name": "Bitcoin",
                                    "ticker": "BTC",
                                },
                            },
                            "quantity": "10.0",
                            "direction": 1,
                            "signed_quantity": "10.0",
                            "target_trade_time": None,
                            "extra_details": {
                                "position_set_uid": "position-set-uid",
                                "target_row_key": "row-key",
                                "target_gap_signed_quantity": "0.0",
                                "scale": "1.0",
                            },
                            "allocation": {
                                "target_gap_signed_quantity": "0.0",
                                "scale": "1.0",
                                "target_row_key": "row-key",
                                "position_set_uid": "position-set-uid",
                            },
                        }
                    ],
                }
            ],
            "residuals": [
                {
                    "asset_identifier": "example-asset-eth",
                    "source_signed_quantity": "25.0",
                    "allocated_signed_quantity": "20.0",
                    "residual_signed_quantity": "5.0",
                    "asset": None,
                }
            ],
            "allocation_warnings": [],
        }

    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_holdings_by_fund",
        fake_get_account_holdings_by_fund,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/account/{account_uid}/holdings/by-fund/",
        params={
            "order": "asc",
            "limit": 1,
            "include_asset_detail": True,
            "holdings_date": "2026-06-08T10:30:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["account_uid"] == str(account_uid)
    assert body["source_account_holdings_set_uid"] == "source-holdings-set-uid"
    assert body["funds"][0]["virtual_fund_uid"] == str(virtual_fund_uid)
    assert body["funds"][0]["holdings"][0]["asset"]["uid"] == str(asset_uid)
    assert body["funds"][0]["holdings"][0]["signed_quantity"] == "10.0"
    assert body["funds"][0]["holdings"][0]["allocation"] == {
        "target_gap_signed_quantity": "0.0",
        "scale": "1.0",
        "target_row_key": "row-key",
        "position_set_uid": "position-set-uid",
    }
    assert body["residuals"][0]["residual_signed_quantity"] == "5.0"
    assert "id" not in body["funds"][0]["holdings"][0]["asset"]
    assert captured == {
        "account_uid": str(account_uid),
        "order": "asc",
        "limit": 1,
        "include_asset_detail": True,
        "holdings_date": dt.datetime(2026, 6, 8, 10, 30, tzinfo=dt.UTC),
    }


def test_get_account_holdings_by_fund_returns_404_when_account_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_holdings_by_fund",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/account/missing-account/holdings/by-fund/")

    assert response.status_code == 404
    assert "missing-account" in response.json()["detail"]


def test_add_account_holdings_returns_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()

    def fake_add_account_holdings(*, account_uid, payload):
        assert payload.holdings_date == dt.datetime(2026, 6, 5, 8, tzinfo=dt.UTC)
        assert payload.overwrite is True
        assert payload.positions[0].asset_identifier == "example-asset-btc"
        assert payload.positions[0].asset_uid == str(asset_uid)
        assert payload.positions[0].direction == -1
        return {
            "holdings_set_uid": "holdings-set-uid",
            "holdings_date": "2026-06-05T08:00:00Z",
            "holdings": [
                {
                    "time_index": "2026-06-05T08:00:00Z",
                    "asset_identifier": "example-asset-btc",
                    "asset": {
                        "uid": str(asset_uid),
                        "asset_identifier": "example-asset-btc",
                        "current_snapshot": {
                            "name": "Bitcoin",
                            "ticker": "BTC",
                        },
                    },
                    "position_type": "units",
                    "price": None,
                    "quantity": "10.0",
                    "direction": -1,
                    "signed_quantity": "-10.0",
                    "missing_price": True,
                    "target_trade_time": "2026-06-05T08:00:00Z",
                    "extra_details": {},
                }
            ],
        }

    monkeypatch.setattr(
        "apps.v1.routers.accounts.add_account_holdings",
        fake_add_account_holdings,
    )

    client = TestClient(app)
    response = client.post(
        f"/api/v1/account/{account_uid}/add-holdings/",
        json={
            "holdings_date": "2026-06-05T08:00:00.000Z",
            "overwrite": True,
            "positions": [
                {
                    "asset_identifier": "example-asset-btc",
                    "asset_uid": str(asset_uid),
                    "position_type": "units",
                    "quantity": "10",
                    "direction": -1,
                    "target_trade_time": "2026-06-05T08:00:00.000Z",
                    "extra_details": {},
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["holdings_set_uid"] == "holdings-set-uid"
    assert body["holdings"][0]["asset_identifier"] == "example-asset-btc"
    assert body["holdings"][0]["quantity"] == "10.0"
    assert body["holdings"][0]["direction"] == -1
    assert body["holdings"][0]["signed_quantity"] == "-10.0"


def test_add_account_holdings_returns_404_when_account_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.accounts.add_account_holdings",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/account/missing-account/add-holdings/",
        json={
            "holdings_date": "2026-06-05T08:00:00.000Z",
            "overwrite": True,
            "positions": [
                {
                    "asset_identifier": "example-asset-btc",
                    "quantity": "10",
                }
            ],
        },
    )

    assert response.status_code == 404
    assert "missing-account" in response.json()["detail"]


def test_add_account_holdings_returns_409_when_snapshot_exists(monkeypatch) -> None:
    from msm.services import accounts as account_services

    def fake_add_account_holdings(**kwargs):
        raise account_services.AccountHoldingsSnapshotExistsError("snapshot exists")

    monkeypatch.setattr(
        "apps.v1.routers.accounts.add_account_holdings",
        fake_add_account_holdings,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/account/some-account/add-holdings/",
        json={
            "holdings_date": "2026-06-05T08:00:00.000Z",
            "overwrite": False,
            "positions": [
                {
                    "asset_identifier": "example-asset-btc",
                    "quantity": "10",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert "snapshot exists" in response.json()["detail"]


def test_get_account_target_positions_returns_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()

    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_target_positions",
        lambda **kwargs: {
            "related_account_uid": str(account_uid),
            "target_positions_date": "2026-06-02T10:30:00Z",
            "position_set_uid": "position-set-uid",
            "positions": [
                {
                    "target_type": "asset",
                    "target_uid": str(asset_uid),
                    "asset_uid": str(asset_uid),
                    "portfolio_uid": None,
                    "unique_identifier": "btc_spot",
                    "weight_notional_exposure": "0.55",
                    "constant_notional_exposure": None,
                    "single_asset_quantity": None,
                    "asset": {
                        "uid": str(asset_uid),
                        "unique_identifier": "btc_spot",
                        "current_snapshot": {
                            "name": "Bitcoin spot",
                            "ticker": "BTC",
                        },
                    },
                    "portfolio": None,
                },
                {
                    "target_type": "portfolio",
                    "target_uid": str(portfolio_uid),
                    "asset_uid": None,
                    "portfolio_uid": str(portfolio_uid),
                    "unique_identifier": "example-sleeve",
                    "weight_notional_exposure": "0.45",
                    "constant_notional_exposure": None,
                    "single_asset_quantity": None,
                    "asset": None,
                    "portfolio": {
                        "uid": str(portfolio_uid),
                        "unique_identifier": "example-sleeve",
                        "portfolio_index_uid": None,
                    },
                },
            ],
        },
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/account/{account_uid}/target-positions/",
        params={"order": "desc", "limit": 1, "include_asset_detail": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["related_account_uid"] == str(account_uid)
    assert body["position_set_uid"] == "position-set-uid"
    assert body["positions"][0]["asset"] == {
        "uid": str(asset_uid),
        "unique_identifier": "btc_spot",
        "current_snapshot": {
            "name": "Bitcoin spot",
            "ticker": "BTC",
        },
    }
    assert body["positions"][1]["portfolio"] == {
        "uid": str(portfolio_uid),
        "unique_identifier": "example-sleeve",
        "portfolio_index_uid": None,
    }
    assert "figi" not in body["positions"][0]["asset"]
    assert "id" not in body["positions"][0]["asset"]


def test_get_account_target_positions_passes_query_params(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_get_account_target_positions(**kwargs):
        captured.update(kwargs)
        return {
            "related_account_uid": str(account_uid),
            "target_positions_date": None,
            "position_set_uid": None,
            "positions": [],
        }

    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_target_positions",
        fake_get_account_target_positions,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/account/{account_uid}/target-positions/",
        params={
            "order": "asc",
            "limit": 1,
            "include_asset_detail": False,
            "target_positions_date": "2026-06-02T10:30:00Z",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "account_uid": str(account_uid),
        "order": "asc",
        "limit": 1,
        "include_asset_detail": False,
        "target_positions_date": dt.datetime(2026, 6, 2, 10, 30, tzinfo=dt.UTC),
    }


def test_get_account_target_positions_returns_404_when_account_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_target_positions",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/account/missing-account/target-positions/")

    assert response.status_code == 404
    assert "missing-account" in response.json()["detail"]


def test_add_account_target_positions_returns_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_add_account_target_positions(*, account_uid, payload):
        captured["account_uid"] = account_uid
        captured["target_positions_date"] = payload.target_positions_date
        captured["overwrite"] = payload.overwrite
        captured["positions"] = [position.model_dump() for position in payload.positions]
        return {
            "related_account_uid": account_uid,
            "target_positions_date": "2026-06-08T10:30:00Z",
            "position_set_uid": "position-set-uid",
            "positions": [
                {
                    "target_type": "asset",
                    "target_uid": str(asset_uid),
                    "asset_uid": str(asset_uid),
                    "portfolio_uid": None,
                    "unique_identifier": "btc_spot",
                    "weight_notional_exposure": "0.6",
                    "constant_notional_exposure": None,
                    "single_asset_quantity": None,
                    "asset": None,
                    "portfolio": None,
                },
                {
                    "target_type": "portfolio",
                    "target_uid": str(portfolio_uid),
                    "asset_uid": None,
                    "portfolio_uid": str(portfolio_uid),
                    "unique_identifier": "example-sleeve",
                    "weight_notional_exposure": "0.4",
                    "constant_notional_exposure": None,
                    "single_asset_quantity": None,
                    "asset": None,
                    "portfolio": None,
                },
            ],
        }

    monkeypatch.setattr(
        "apps.v1.routers.accounts.add_account_target_positions",
        fake_add_account_target_positions,
    )

    client = TestClient(app)
    response = client.post(
        f"/api/v1/account/{account_uid}/add-target-positions/",
        json={
            "target_positions_date": "2026-06-08T10:30:00.000Z",
            "overwrite": True,
            "positions": [
                {
                    "target_type": "asset",
                    "target_uid": str(asset_uid),
                    "asset_uid": str(asset_uid),
                    "weight_notional_exposure": "0.60",
                    "metadata_json": {},
                },
                {
                    "target_type": "portfolio",
                    "target_uid": str(portfolio_uid),
                    "portfolio_uid": str(portfolio_uid),
                    "weight_notional_exposure": "0.40",
                    "metadata_json": {"portfolio_role": "satellite_sleeve"},
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["related_account_uid"] == str(account_uid)
    assert body["position_set_uid"] == "position-set-uid"
    assert captured["account_uid"] == str(account_uid)
    assert captured["target_positions_date"] == dt.datetime(
        2026,
        6,
        8,
        10,
        30,
        tzinfo=dt.UTC,
    )
    assert captured["overwrite"] is True
    assert captured["positions"] == [
        {
            "target_uid": str(asset_uid),
            "weight_notional_exposure": "0.60",
            "constant_notional_exposure": None,
            "single_asset_quantity": None,
            "metadata_json": {},
            "target_type": "asset",
            "asset_uid": str(asset_uid),
            "portfolio_uid": None,
        },
        {
            "target_uid": str(portfolio_uid),
            "weight_notional_exposure": "0.40",
            "constant_notional_exposure": None,
            "single_asset_quantity": None,
            "metadata_json": {"portfolio_role": "satellite_sleeve"},
            "target_type": "portfolio",
            "asset_uid": None,
            "portfolio_uid": str(portfolio_uid),
        },
    ]


def test_add_account_target_positions_rejects_parent_fields() -> None:
    client = TestClient(app)
    response = client.post(
        f"/api/v1/account/{uuid.uuid4()}/add-target-positions/",
        json={
            "account_allocation_model_uid": str(uuid.uuid4()),
            "target_positions_date": "2026-06-08T10:30:00Z",
            "overwrite": True,
            "positions": [],
        },
    )

    assert response.status_code == 422
    assert "account_allocation_model_uid" in response.text


def test_add_account_target_positions_rejects_portfolio_units() -> None:
    portfolio_uid = uuid.uuid4()

    client = TestClient(app)
    response = client.post(
        f"/api/v1/account/{uuid.uuid4()}/add-target-positions/",
        json={
            "target_positions_date": "2026-06-08T10:30:00Z",
            "overwrite": True,
            "positions": [
                {
                    "target_type": "portfolio",
                    "target_uid": str(portfolio_uid),
                    "portfolio_uid": str(portfolio_uid),
                    "single_asset_quantity": "1",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert "cannot use single_asset_quantity" in response.text


def test_add_account_target_positions_returns_404_when_account_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.accounts.add_account_target_positions",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/account/missing-account/add-target-positions/",
        json={
            "target_positions_date": "2026-06-08T10:30:00Z",
            "overwrite": True,
            "positions": [
                {
                    "target_type": "asset",
                    "target_uid": str(uuid.uuid4()),
                    "asset_uid": str(uuid.uuid4()),
                    "weight_notional_exposure": "1.0",
                }
            ],
        },
    )

    assert response.status_code == 404
    assert "missing-account" in response.json()["detail"]


def test_add_account_target_positions_returns_409_when_snapshot_exists(monkeypatch) -> None:
    from msm.services import target_positions as target_position_services

    def fake_add_account_target_positions(**kwargs):
        raise target_position_services.AccountTargetPositionsSnapshotExistsError(
            "target snapshot exists"
        )

    monkeypatch.setattr(
        "apps.v1.routers.accounts.add_account_target_positions",
        fake_add_account_target_positions,
    )

    client = TestClient(app)
    target_uid = uuid.uuid4()
    response = client.post(
        "/api/v1/account/some-account/add-target-positions/",
        json={
            "target_positions_date": "2026-06-08T10:30:00Z",
            "overwrite": False,
            "positions": [
                {
                    "target_type": "asset",
                    "target_uid": str(target_uid),
                    "asset_uid": str(target_uid),
                    "weight_notional_exposure": "1.0",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert "target snapshot exists" in response.json()["detail"]


def test_account_holdings_service_maps_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())

    monkeypatch.setattr("apps.v1.services.accounts._get_holdings_runtime", lambda: runtime)
    monkeypatch.setattr(
        "apps.v1.services.accounts._get_account_holdings_snapshot_response",
        lambda context, **kwargs: {
            "holdings_set_uid": "holdings-set-uid",
            "holdings_date": "2026-06-01T10:30:00Z",
            "holdings": [
                {
                    "time_index": "2026-06-01T10:30:00Z",
                    "asset_identifier": "btc_spot",
                    "asset": None,
                    "position_type": "units",
                    "price": None,
                    "quantity": "12.0",
                    "direction": 1,
                    "signed_quantity": "12.0",
                    "missing_price": True,
                    "target_trade_time": None,
                    "extra_details": {},
                }
            ],
        },
    )

    from apps.v1.services.accounts import get_account_holdings

    response = get_account_holdings(
        account_uid=str(account_uid),
        order="desc",
        limit=1,
        include_asset_detail=False,
    )

    assert response is not None
    payload = response.model_dump(mode="json")
    assert payload["holdings_set_uid"] == "holdings-set-uid"
    assert payload["holdings"][0]["asset_identifier"] == "btc_spot"
    assert payload["holdings"][0]["asset"] is None


def test_account_holdings_by_fund_service_maps_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    virtual_fund_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "apps.v1.services.accounts._get_holdings_by_fund_runtime",
        lambda: runtime,
    )

    def fake_get_account_holdings_by_fund_response(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "account_uid": str(account_uid),
            "source_account_holdings_set_uid": "source-holdings-set-uid",
            "holdings_date": "2026-06-08T10:30:00Z",
            "funds": [
                {
                    "virtual_fund_uid": str(virtual_fund_uid),
                    "virtual_fund_unique_identifier": "fund-key",
                    "target_portfolio_uid": str(uuid.uuid4()),
                    "holdings_set_uid": "fund-set",
                    "holdings": [],
                }
            ],
            "residuals": [],
            "allocation_warnings": [],
        }

    monkeypatch.setattr(
        "apps.v1.services.accounts._get_account_holdings_by_fund_response",
        fake_get_account_holdings_by_fund_response,
    )

    from apps.v1.services.accounts import get_account_holdings_by_fund

    response = get_account_holdings_by_fund(
        account_uid=str(account_uid),
        order="desc",
        limit=1,
        include_asset_detail=False,
    )

    assert captured == {
        "context": runtime.context,
        "account_uid": str(account_uid),
        "order": "desc",
        "limit": 1,
        "include_asset_detail": False,
        "holdings_date": None,
    }
    assert response is not None
    payload = response.model_dump(mode="json")
    assert payload["account_uid"] == str(account_uid)
    assert payload["funds"][0]["virtual_fund_uid"] == str(virtual_fund_uid)


def test_add_account_holdings_service_maps_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr("apps.v1.services.accounts._get_holdings_runtime", lambda: runtime)

    def fake_add_account_holdings_snapshot_response(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "holdings_set_uid": "holdings-set-uid",
            "holdings_date": "2026-06-05T08:00:00Z",
            "holdings": [],
        }

    monkeypatch.setattr(
        "apps.v1.services.accounts._add_account_holdings_snapshot_response",
        fake_add_account_holdings_snapshot_response,
    )

    from apps.v1.schemas.accounts import AccountAddHoldingsRequest
    from apps.v1.services.accounts import add_account_holdings

    payload = AccountAddHoldingsRequest.model_validate(
        {
            "holdings_date": "2026-06-05T08:00:00Z",
            "overwrite": True,
            "positions": [
                {
                    "asset_identifier": "example-asset-btc",
                    "quantity": "10",
                    "direction": -1,
                    "target_trade_time": "2026-06-05T08:00:00Z",
                }
            ],
        }
    )
    response = add_account_holdings(account_uid=str(account_uid), payload=payload)

    assert captured["context"] is runtime.context
    assert captured["account_uid"] == str(account_uid)
    assert captured["holdings_date"] == dt.datetime(2026, 6, 5, 8, tzinfo=dt.UTC)
    assert captured["overwrite"] is True
    assert captured["include_asset_detail"] is True
    assert response is not None
    assert response.model_dump(mode="json")["holdings_set_uid"] == "holdings-set-uid"


def test_account_target_positions_service_maps_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())

    monkeypatch.setattr(
        "apps.v1.services.accounts._get_target_positions_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(
        "apps.v1.services.accounts._get_account_target_positions_snapshot_response",
        lambda context, **kwargs: {
            "related_account_uid": str(account_uid),
            "target_positions_date": "2026-06-02T10:30:00Z",
            "position_set_uid": "position-set-uid",
            "positions": [
                {
                    "target_type": "asset",
                    "target_uid": "asset-target-uid",
                    "asset_uid": "asset-target-uid",
                    "portfolio_uid": None,
                    "unique_identifier": "btc_spot",
                    "weight_notional_exposure": "0.55",
                    "constant_notional_exposure": None,
                    "single_asset_quantity": None,
                    "asset": None,
                    "portfolio": None,
                }
            ],
        },
    )

    from apps.v1.services.accounts import get_account_target_positions

    response = get_account_target_positions(
        account_uid=str(account_uid),
        order="desc",
        limit=1,
        include_asset_detail=False,
    )

    assert response is not None
    payload = response.model_dump(mode="json")
    assert payload["related_account_uid"] == str(account_uid)
    assert payload["position_set_uid"] == "position-set-uid"
    assert payload["positions"][0]["asset"] is None


def test_add_account_target_positions_service_maps_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    target_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "apps.v1.services.accounts._get_target_positions_runtime",
        lambda: runtime,
    )

    def fake_add_account_target_positions_snapshot_response(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "related_account_uid": str(account_uid),
            "target_positions_date": "2026-06-08T10:30:00Z",
            "position_set_uid": "position-set-uid",
            "positions": [
                {
                    "target_type": "asset",
                    "target_uid": str(target_uid),
                    "asset_uid": str(target_uid),
                    "portfolio_uid": None,
                    "unique_identifier": "btc_spot",
                    "weight_notional_exposure": "1.0",
                    "constant_notional_exposure": None,
                    "single_asset_quantity": None,
                    "asset": None,
                    "portfolio": None,
                }
            ],
        }

    monkeypatch.setattr(
        "apps.v1.services.accounts._add_account_target_positions_snapshot_response",
        fake_add_account_target_positions_snapshot_response,
    )

    from apps.v1.schemas.accounts import AccountAddTargetPositionsRequest
    from apps.v1.services.accounts import add_account_target_positions

    payload = AccountAddTargetPositionsRequest.model_validate(
        {
            "target_positions_date": "2026-06-08T10:30:00Z",
            "overwrite": True,
            "positions": [
                {
                    "target_type": "asset",
                    "target_uid": str(target_uid),
                    "asset_uid": str(target_uid),
                    "weight_notional_exposure": "1.0",
                }
            ],
        }
    )
    response = add_account_target_positions(account_uid=str(account_uid), payload=payload)

    assert captured["context"] is runtime.context
    assert captured["account_uid"] == str(account_uid)
    assert captured["target_positions_date"] == dt.datetime(
        2026,
        6,
        8,
        10,
        30,
        tzinfo=dt.UTC,
    )
    assert captured["overwrite"] is True
    assert captured["include_asset_detail"] is True
    assert captured["positions"] == [
        {
            "target_uid": str(target_uid),
            "weight_notional_exposure": "1.0",
            "constant_notional_exposure": None,
            "single_asset_quantity": None,
            "metadata_json": {},
            "target_type": "asset",
            "asset_uid": str(target_uid),
            "portfolio_uid": None,
        }
    ]
    assert response is not None
    assert response.model_dump(mode="json")["position_set_uid"] == "position-set-uid"


def test_core_account_holdings_snapshot_selects_latest(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    older_time = dt.datetime(2026, 5, 31, 10, 30, tzinfo=dt.UTC)
    latest_time = dt.datetime(2026, 6, 1, 10, 30, tzinfo=dt.UTC)

    from msm.services import accounts as account_services

    monkeypatch.setattr(
        account_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        account_services,
        "_search_account_holdings_rows",
        lambda context, account_uid, limit: [
            {
                "time_index": older_time,
                "account_uid": str(account_uid),
                "asset_identifier": "eth_spot",
                "holdings_set_uid": "older-set",
                "is_trade_snapshot": False,
                "quantity": 2.0,
                "direction": 1,
                "target_trade_time": None,
                "extra_details": {},
            },
            {
                "time_index": latest_time,
                "account_uid": str(account_uid),
                "asset_identifier": "btc_spot",
                "holdings_set_uid": "latest-set",
                "is_trade_snapshot": False,
                "quantity": 12.0,
                "direction": -1,
                "target_trade_time": None,
                "extra_details": {"source": "test"},
            },
        ],
    )
    monkeypatch.setattr(
        account_services,
        "_asset_snapshot_references_by_unique_identifier",
        lambda context, rows: {
            "btc_spot": {
                "uid": str(asset_uid),
                "asset_identifier": "btc_spot",
                "current_snapshot": {
                    "name": "Bitcoin spot",
                    "ticker": "BTC",
                },
            }
        },
    )

    snapshot = account_services.get_account_holdings_snapshot_response(
        object(),
        account_uid=str(account_uid),
    )

    assert snapshot == {
        "holdings_set_uid": "latest-set",
        "holdings_date": latest_time,
        "holdings": [
            {
                "time_index": latest_time,
                "asset_identifier": "btc_spot",
                "asset": {
                    "uid": str(asset_uid),
                    "asset_identifier": "btc_spot",
                    "current_snapshot": {
                        "name": "Bitcoin spot",
                        "ticker": "BTC",
                    },
                },
                "position_type": "units",
                "price": None,
                "quantity": "12.0",
                "direction": -1,
                "signed_quantity": "-12.0",
                "missing_price": True,
                "target_trade_time": None,
                "extra_details": {"source": "test"},
            }
        ],
    }


def test_core_account_holdings_by_fund_groups_allocations_and_residuals(
    monkeypatch,
) -> None:
    account_uid = uuid.uuid4()
    source_holdings_set_uid = uuid.uuid4()
    virtual_fund_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    btc_uid = uuid.uuid4()
    eth_uid = uuid.uuid4()
    holdings_date = dt.datetime(2026, 6, 8, 10, 30, tzinfo=dt.UTC)
    context = object()

    from msm.services.accounts import virtual_funds_public_api as virtual_fund_services

    def fake_get_model_by_uid(context, model, uid):
        assert model.__name__ == "AccountTable"
        assert uid == str(account_uid)
        return {"row": {"uid": str(account_uid)}}

    def fake_search_model(context, model, filters=None, in_filters=None, limit=None):
        model_name = model.__name__
        if model_name == "AccountHoldingsSetTable":
            assert filters == {"account_uid": str(account_uid)}
            return {
                "rows": [
                    {
                        "uid": str(source_holdings_set_uid),
                        "account_uid": str(account_uid),
                        "time_index": holdings_date,
                    }
                ]
            }
        if model_name == "AccountHoldingsStorage":
            assert filters == {
                "account_uid": str(account_uid),
                "holdings_set_uid": str(source_holdings_set_uid),
            }
            return {
                "rows": [
                    {
                        "time_index": holdings_date,
                        "account_uid": str(account_uid),
                        "asset_identifier": "example-asset-btc",
                        "holdings_set_uid": str(source_holdings_set_uid),
                        "quantity": 10.0,
                        "direction": 1,
                        "target_trade_time": None,
                        "extra_details": {},
                    },
                    {
                        "time_index": holdings_date,
                        "account_uid": str(account_uid),
                        "asset_identifier": "example-asset-eth",
                        "holdings_set_uid": str(source_holdings_set_uid),
                        "quantity": 25.0,
                        "direction": 1,
                        "target_trade_time": None,
                        "extra_details": {},
                    },
                ]
            }
        if model_name == "VirtualFundTable":
            assert filters == {"account_uid": str(account_uid)}
            return {
                "rows": [
                    {
                        "uid": str(virtual_fund_uid),
                        "unique_identifier": "fund-key",
                        "account_uid": str(account_uid),
                        "target_portfolio_uid": str(portfolio_uid),
                    }
                ]
            }
        if model_name == "VirtualFundHoldingsSetTable":
            assert filters == {"source_account_holdings_set_uid": str(source_holdings_set_uid)}
            assert in_filters == {"virtual_fund_uid": [str(virtual_fund_uid)]}
            return {
                "rows": [
                    {
                        "uid": "virtual-fund-holdings-set-uid",
                        "virtual_fund_uid": str(virtual_fund_uid),
                        "source_account_holdings_set_uid": str(source_holdings_set_uid),
                        "time_index": holdings_date,
                    }
                ]
            }
        if model_name == "VirtualFundHoldingsStorage":
            assert filters == {"source_account_holdings_set_uid": str(source_holdings_set_uid)}
            assert in_filters == {"virtual_fund_uid": [str(virtual_fund_uid)]}
            return {
                "rows": [
                    {
                        "time_index": holdings_date,
                        "virtual_fund_uid": str(virtual_fund_uid),
                        "asset_identifier": "example-asset-btc",
                        "virtual_fund_holdings_set_uid": "virtual-fund-holdings-set-uid",
                        "source_account_holdings_set_uid": str(source_holdings_set_uid),
                        "allocated_quantity": 6.0,
                        "direction": 1,
                        "target_trade_time": None,
                        "extra_details": {
                            "position_set_uid": "position-set-uid",
                            "target_row_key": "btc-row",
                            "target_gap_signed_quantity": "0.0",
                            "scale": "1.0",
                        },
                    },
                    {
                        "time_index": holdings_date,
                        "virtual_fund_uid": str(virtual_fund_uid),
                        "asset_identifier": "example-asset-eth",
                        "virtual_fund_holdings_set_uid": "virtual-fund-holdings-set-uid",
                        "source_account_holdings_set_uid": str(source_holdings_set_uid),
                        "allocated_quantity": 20.0,
                        "direction": 1,
                        "target_trade_time": None,
                        "extra_details": {
                            "position_set_uid": "position-set-uid",
                            "target_row_key": "eth-row",
                            "target_gap_signed_quantity": "5.0",
                            "scale": "0.8",
                        },
                    },
                ]
            }
        raise AssertionError(f"Unexpected model {model_name}")

    monkeypatch.setattr(virtual_fund_services, "get_model_by_uid", fake_get_model_by_uid)
    monkeypatch.setattr(virtual_fund_services, "search_model", fake_search_model)
    monkeypatch.setattr(
        virtual_fund_services,
        "_asset_references_by_unique_identifier",
        lambda context, rows: {
            "example-asset-btc": {
                "uid": str(btc_uid),
                "asset_identifier": "example-asset-btc",
                "current_snapshot": {
                    "name": "Bitcoin",
                    "ticker": "BTC",
                },
            },
            "example-asset-eth": {
                "uid": str(eth_uid),
                "asset_identifier": "example-asset-eth",
                "current_snapshot": {
                    "name": "Ethereum",
                    "ticker": "ETH",
                },
            },
        },
    )

    response = virtual_fund_services.get_account_holdings_by_fund_response(
        context,
        account_uid=str(account_uid),
        order="desc",
        limit=1,
        include_asset_detail=True,
    )

    assert response is not None
    assert response["account_uid"] == str(account_uid)
    assert response["source_account_holdings_set_uid"] == str(source_holdings_set_uid)
    assert response["holdings_date"] == holdings_date
    assert response["allocation_warnings"] == []
    assert response["funds"] == [
        {
            "virtual_fund_uid": str(virtual_fund_uid),
            "virtual_fund_unique_identifier": "fund-key",
            "target_portfolio_uid": str(portfolio_uid),
            "holdings_set_uid": "virtual-fund-holdings-set-uid",
            "holdings": [
                {
                    "time_index": holdings_date,
                    "asset_identifier": "example-asset-btc",
                    "asset": {
                        "uid": str(btc_uid),
                        "asset_identifier": "example-asset-btc",
                        "current_snapshot": {
                            "name": "Bitcoin",
                            "ticker": "BTC",
                        },
                    },
                    "quantity": "6.0",
                    "direction": 1,
                    "signed_quantity": "6.0",
                    "target_trade_time": None,
                    "extra_details": {
                        "position_set_uid": "position-set-uid",
                        "target_row_key": "btc-row",
                        "target_gap_signed_quantity": "0.0",
                        "scale": "1.0",
                    },
                    "allocation": {
                        "target_gap_signed_quantity": "0.0",
                        "scale": "1.0",
                        "target_row_key": "btc-row",
                        "position_set_uid": "position-set-uid",
                    },
                },
                {
                    "time_index": holdings_date,
                    "asset_identifier": "example-asset-eth",
                    "asset": {
                        "uid": str(eth_uid),
                        "asset_identifier": "example-asset-eth",
                        "current_snapshot": {
                            "name": "Ethereum",
                            "ticker": "ETH",
                        },
                    },
                    "quantity": "20.0",
                    "direction": 1,
                    "signed_quantity": "20.0",
                    "target_trade_time": None,
                    "extra_details": {
                        "position_set_uid": "position-set-uid",
                        "target_row_key": "eth-row",
                        "target_gap_signed_quantity": "5.0",
                        "scale": "0.8",
                    },
                    "allocation": {
                        "target_gap_signed_quantity": "5.0",
                        "scale": "0.8",
                        "target_row_key": "eth-row",
                        "position_set_uid": "position-set-uid",
                    },
                },
            ],
        }
    ]
    assert response["residuals"] == [
        {
            "asset_identifier": "example-asset-btc",
            "source_signed_quantity": "10.0",
            "allocated_signed_quantity": "6.0",
            "residual_signed_quantity": "4.0",
            "asset": {
                "uid": str(btc_uid),
                "asset_identifier": "example-asset-btc",
                "current_snapshot": {
                    "name": "Bitcoin",
                    "ticker": "BTC",
                },
            },
        },
        {
            "asset_identifier": "example-asset-eth",
            "source_signed_quantity": "25.0",
            "allocated_signed_quantity": "20.0",
            "residual_signed_quantity": "5.0",
            "asset": {
                "uid": str(eth_uid),
                "asset_identifier": "example-asset-eth",
                "current_snapshot": {
                    "name": "Ethereum",
                    "ticker": "ETH",
                },
            },
        },
    ]


def test_core_add_account_holdings_snapshot_writes_frame_and_returns_snapshot(
    monkeypatch,
) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    holdings_set_uid = uuid.uuid4()
    holdings_date = dt.datetime(2026, 6, 5, 8, tzinfo=dt.UTC)
    context = object()
    captured: dict[str, object] = {}

    from msm.services import accounts as account_services

    monkeypatch.setattr(
        account_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        account_services,
        "_asset_row_by_unique_identifier",
        lambda context, unique_identifier: {
            "uid": str(asset_uid),
            "unique_identifier": unique_identifier,
        },
    )
    monkeypatch.setattr(
        account_services,
        "uuid",
        SimpleNamespace(uuid4=lambda: holdings_set_uid),
    )

    def fake_build_account_holdings_frame(**kwargs):
        captured["frame_kwargs"] = kwargs
        return SimpleNamespace(
            reset_index=lambda: SimpleNamespace(
                to_dict=lambda orient: [
                    {
                        "asset_identifier": "example-asset-btc",
                        "quantity": 10.0,
                        "direction": -1,
                        "target_trade_time": holdings_date,
                        "extra_details": {"source": "test"},
                    }
                ]
            )
        )

    def fake_replace_account_holdings_snapshot(context, **kwargs):
        captured["write_context"] = context
        captured["write_kwargs"] = kwargs
        return {
            "rows": [
                {
                    "asset_identifier": "example-asset-btc",
                    "quantity": 10.0,
                    "direction": -1,
                }
            ]
        }

    def fake_get_account_holdings_snapshot_response(context, **kwargs):
        captured["response_context"] = context
        captured["response_kwargs"] = kwargs
        return {
            "holdings_set_uid": str(holdings_set_uid),
            "holdings_date": holdings_date,
            "holdings": [],
        }

    monkeypatch.setattr(
        account_services,
        "_build_account_holdings_frame",
        fake_build_account_holdings_frame,
    )
    monkeypatch.setattr(
        account_services.account_repository,
        "replace_account_holdings_snapshot",
        fake_replace_account_holdings_snapshot,
    )
    monkeypatch.setattr(
        account_services,
        "get_account_holdings_snapshot_response",
        fake_get_account_holdings_snapshot_response,
    )

    snapshot = account_services.add_account_holdings_snapshot_response(
        context,
        account_uid=str(account_uid),
        holdings_date=holdings_date,
        overwrite=True,
        positions=[
            {
                "asset_identifier": "example-asset-btc",
                "asset_uid": str(asset_uid),
                "position_type": "units",
                "quantity": "10",
                "direction": -1,
                "target_trade_time": holdings_date,
                "extra_details": {"source": "test"},
            }
        ],
    )

    assert captured["frame_kwargs"] == {
        "holdings_date": holdings_date,
        "account_uid": str(account_uid),
        "holdings_set_uid": str(holdings_set_uid),
        "positions": [
            {
                "asset_identifier": "example-asset-btc",
                "quantity": "10",
                "direction": -1,
                "target_trade_time": holdings_date,
                "extra_details": {"source": "test"},
            }
        ],
    }
    assert captured["write_context"] is context
    assert captured["write_kwargs"] == {
        "holdings_set_uid": str(holdings_set_uid),
        "account_uid": str(account_uid),
        "holdings_date": holdings_date,
        "positions": [
            {
                "asset_identifier": "example-asset-btc",
                "quantity": 10.0,
                "direction": -1,
                "target_trade_time": holdings_date,
                "extra_details": {"source": "test"},
            }
        ],
        "overwrite": True,
    }
    assert captured["response_context"] is context
    assert captured["response_kwargs"] == {
        "account_uid": str(account_uid),
        "order": "desc",
        "limit": 1,
        "include_asset_detail": True,
        "holdings_date": holdings_date,
    }
    assert snapshot is not None
    assert snapshot["holdings_set_uid"] == str(holdings_set_uid)


def test_core_add_account_holdings_snapshot_rejects_existing_without_overwrite(
    monkeypatch,
) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    holdings_date = dt.datetime(2026, 6, 5, 8, tzinfo=dt.UTC)
    captured: dict[str, object] = {}

    from msm.services import accounts as account_services

    monkeypatch.setattr(
        account_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        account_services,
        "_asset_row_by_unique_identifier",
        lambda context, unique_identifier: {
            "uid": str(asset_uid),
            "unique_identifier": unique_identifier,
        },
    )

    def fake_build_account_holdings_frame(**kwargs):
        captured["frame_kwargs"] = kwargs
        return SimpleNamespace(
            reset_index=lambda: SimpleNamespace(
                to_dict=lambda orient: [
                    {
                        "asset_identifier": "example-asset-btc",
                        "quantity": 10.0,
                        "direction": 1,
                        "target_trade_time": holdings_date,
                        "extra_details": {},
                    }
                ]
            )
        )

    monkeypatch.setattr(
        account_services,
        "_build_account_holdings_frame",
        fake_build_account_holdings_frame,
    )
    monkeypatch.setattr(
        account_services.account_repository,
        "replace_account_holdings_snapshot",
        lambda context, **kwargs: {"rows": []},
    )

    with pytest.raises(account_services.AccountHoldingsSnapshotExistsError):
        account_services.add_account_holdings_snapshot_response(
            object(),
            account_uid=str(account_uid),
            holdings_date=holdings_date,
            overwrite=False,
            positions=[
                {
                    "asset_identifier": "example-asset-btc",
                    "asset_uid": str(asset_uid),
                    "quantity": "10",
                }
            ],
        )
    assert captured["frame_kwargs"]["account_uid"] == str(account_uid)


def test_account_repository_builds_atomic_holdings_replacement_operation() -> None:
    from mainsequence.client.metatables import MetaTableOperationScopeTable

    from msm.data_nodes.accounts.storage import AccountHoldingsStorage
    from msm.models import AccountHoldingsSetTable
    from msm.repositories import accounts as account_repository

    class FakeContext:
        data_source_uid = "test-data-source"
        limits = None

        def scope_table(self, model, *, access="read", alias=None):
            return MetaTableOperationScopeTable(
                meta_table_uid=f"{model.__name__}-uid",
                access=access,
                alias=alias,
            )

    holdings_set_uid = uuid.uuid4()
    account_uid = uuid.uuid4()
    holdings_date = dt.datetime(2026, 6, 5, 8, tzinfo=dt.UTC)

    operation = account_repository.build_replace_account_holdings_snapshot_operation(
        FakeContext(),
        holdings_set_uid=holdings_set_uid,
        account_uid=account_uid,
        holdings_date=holdings_date,
        overwrite=True,
        positions=[
            {
                "asset_identifier": "example-asset-btc",
                "quantity": "10",
                "direction": -1,
                "target_trade_time": holdings_date,
                "extra_details": {"source": "test"},
            }
        ],
    )

    sql = operation.statement.sql
    assert operation.operation == "upsert"
    assert "WITH holdings_set AS" in sql
    assert "ON CONFLICT (account_uid, time_index)" in sql
    assert "WHERE %(overwrite)s" in sql
    assert "DELETE FROM" in sql
    assert "deleted_gate AS" in sql
    assert "INSERT INTO" in sql
    assert "WITH inserted AS" not in sql
    assert "FROM inserted" not in sql
    assert "JOIN holdings_set ON true" in sql
    assert "JOIN deleted_gate ON true" in sql
    assert "CAST(%(quantity_0)s AS FLOAT)" in sql
    assert "CAST(%(direction_0)s AS SMALLINT)" in sql
    assert operation.statement.parameters["holdings_set_uid"] == holdings_set_uid
    assert operation.statement.parameters["account_uid"] == account_uid
    assert operation.statement.parameters["overwrite"] is True
    assert operation.statement.parameters["asset_identifier_0"] == "example-asset-btc"
    assert operation.statement.parameter_types == {
        "holdings_date": "timestamp with time zone",
        "target_trade_time_0": "timestamp with time zone",
    }
    assert [(table.meta_table_uid, table.access) for table in operation.scope.tables] == [
        (f"{AccountHoldingsSetTable.__name__}-uid", "write"),
        (f"{AccountHoldingsStorage.__name__}-uid", "write"),
    ]


def test_core_add_account_holdings_snapshot_rejects_asset_uid_mismatch(
    monkeypatch,
) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    wrong_asset_uid = uuid.uuid4()
    holdings_date = dt.datetime(2026, 6, 5, 8, tzinfo=dt.UTC)

    from msm.services import accounts as account_services

    monkeypatch.setattr(
        account_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        account_services,
        "_asset_row_by_unique_identifier",
        lambda context, unique_identifier: {
            "uid": str(asset_uid),
            "unique_identifier": unique_identifier,
        },
    )

    with pytest.raises(ValueError, match="does not match"):
        account_services.add_account_holdings_snapshot_response(
            object(),
            account_uid=str(account_uid),
            holdings_date=holdings_date,
            overwrite=True,
            positions=[
                {
                    "asset_identifier": "example-asset-btc",
                    "asset_uid": str(wrong_asset_uid),
                    "quantity": "10",
                }
            ],
        )


def test_core_search_account_target_allocation_candidates_maps_rows(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    from msm.services import target_positions as target_position_services

    def fake_repository_search_candidates(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "rows": [
                {
                    "row_kind": "__count__",
                    "total_count": 2,
                },
                {
                    "row_kind": "data",
                    "target_type": "asset",
                    "target_uid": str(asset_uid),
                    "asset_uid": str(asset_uid),
                    "portfolio_uid": None,
                    "identifier": "example-asset-btc",
                    "display_label": "Bitcoin",
                    "secondary_label": "BTC",
                    "snapshot_name": "Bitcoin",
                    "snapshot_ticker": "BTC",
                    "asset_type": "crypto",
                    "portfolio_index_uid": None,
                },
                {
                    "row_kind": "data",
                    "target_type": "portfolio",
                    "target_uid": str(portfolio_uid),
                    "asset_uid": None,
                    "portfolio_uid": str(portfolio_uid),
                    "identifier": "example-sleeve",
                    "display_label": "example-sleeve",
                    "secondary_label": None,
                    "snapshot_name": None,
                    "snapshot_ticker": None,
                    "asset_type": None,
                    "portfolio_index_uid": None,
                },
            ],
        }

    monkeypatch.setattr(
        "msm.repositories.accounts.search_account_target_allocation_candidates",
        fake_repository_search_candidates,
    )

    context = object()
    response = target_position_services.search_account_target_allocation_candidates(
        context,
        search="btc",
        target_type="all",
        limit=25,
        offset=0,
    )

    assert captured == {
        "context": context,
        "search": "btc",
        "target_type": "all",
        "limit": 25,
        "offset": 0,
    }
    assert response == {
        "count": 2,
        "results": [
            {
                "target_type": "asset",
                "target_uid": str(asset_uid),
                "asset_uid": str(asset_uid),
                "portfolio_uid": None,
                "identifier": "example-asset-btc",
                "display_label": "Bitcoin",
                "secondary_label": "BTC",
                "current_snapshot": {
                    "name": "Bitcoin",
                    "ticker": "BTC",
                },
                "metadata": {"asset_type": "crypto"},
            },
            {
                "target_type": "portfolio",
                "target_uid": str(portfolio_uid),
                "asset_uid": None,
                "portfolio_uid": str(portfolio_uid),
                "identifier": "example-sleeve",
                "display_label": "example-sleeve",
                "secondary_label": None,
                "current_snapshot": None,
                "metadata": {"portfolio_index_uid": None},
            },
        ],
    }


def test_account_repository_builds_single_target_candidate_search_operation() -> None:
    from mainsequence.client.metatables import MetaTableOperationScopeTable

    from msm.data_nodes.assets.storage import AssetSnapshotsStorage
    from msm.models import AssetTable, PortfolioTable
    from msm.repositories import accounts as account_repository

    class FakeContext:
        data_source_uid = "test-data-source"
        limits = None

        def scope_table(self, model, *, access="read", alias=None):
            return MetaTableOperationScopeTable(
                meta_table_uid=f"{model.__name__}-uid",
                access=access,
                alias=alias,
            )

    operation = account_repository.build_search_account_target_allocation_candidates_operation(
        FakeContext(),
        search="btc",
        target_type="all",
        limit=25,
        offset=5,
    )

    sql = operation.statement.sql
    assert operation.operation == "select"
    assert "UNION ALL" in sql
    assert "account_target_allocation_candidates" in sql
    assert "ranked_asset_snapshots" in sql
    assert "paged_account_target_allocation_candidates" in sql
    assert "row_number()" in sql.lower()
    assert "LIMIT" in sql
    assert "OFFSET" in sql
    assert [(table.meta_table_uid, table.access) for table in operation.scope.tables] == [
        (f"{AssetTable.__name__}-uid", "read"),
        (f"{AssetSnapshotsStorage.__name__}-uid", "read"),
        (f"{PortfolioTable.__name__}-uid", "read"),
    ]


def test_account_target_positions_snapshot_selects_latest(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    target_allocation_uid = uuid.uuid4()
    older_position_set_uid = uuid.uuid4()
    latest_position_set_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    older_time = dt.datetime(2026, 6, 1, 10, 30, tzinfo=dt.UTC)
    latest_time = dt.datetime(2026, 6, 2, 10, 30, tzinfo=dt.UTC)

    from msm.services import target_positions as target_position_services

    monkeypatch.setattr(
        target_position_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        target_position_services,
        "_search_active_account_target_allocation_rows",
        lambda context, account_uid: [{"uid": str(target_allocation_uid)}],
    )
    monkeypatch.setattr(
        target_position_services,
        "_search_position_set_rows_for_target_allocations",
        lambda context, target_allocation_uids, position_set_time: [
            {
                "uid": str(older_position_set_uid),
                "account_target_allocation_uid": str(target_allocation_uid),
                "position_set_time": older_time,
            },
            {
                "uid": str(latest_position_set_uid),
                "account_target_allocation_uid": str(target_allocation_uid),
                "position_set_time": latest_time,
            },
        ],
    )
    monkeypatch.setattr(
        target_position_services,
        "_search_target_position_rows",
        lambda context, position_set_uid, target_positions_date, limit: [
            {
                "time_index": latest_time,
                "position_set_uid": position_set_uid,
                "target_type": "asset",
                "target_uid": str(asset_uid),
                "asset_uid": str(asset_uid),
                "portfolio_uid": None,
                "weight_notional_exposure": 0.55,
                "constant_notional_exposure": None,
                "single_asset_quantity": None,
                "metadata_json": {},
            },
            {
                "time_index": latest_time,
                "position_set_uid": position_set_uid,
                "target_type": "portfolio",
                "target_uid": str(portfolio_uid),
                "asset_uid": None,
                "portfolio_uid": str(portfolio_uid),
                "weight_notional_exposure": 0.45,
                "constant_notional_exposure": None,
                "single_asset_quantity": None,
                "metadata_json": {},
            },
        ],
    )
    monkeypatch.setattr(
        target_position_services,
        "_asset_references_by_uid",
        lambda context, rows: {
            str(asset_uid): {
                "uid": str(asset_uid),
                "unique_identifier": "btc_spot",
                "current_snapshot": {
                    "name": "Bitcoin spot",
                    "ticker": "BTC",
                },
            }
        },
    )
    monkeypatch.setattr(
        target_position_services,
        "_portfolio_references_by_uid",
        lambda context, rows: {
            str(portfolio_uid): {
                "uid": str(portfolio_uid),
                "unique_identifier": "example-sleeve",
                "portfolio_index_uid": None,
            }
        },
    )

    snapshot = target_position_services.get_account_target_positions_snapshot_response(
        object(),
        account_uid=str(account_uid),
    )

    assert snapshot == {
        "related_account_uid": str(account_uid),
        "target_positions_date": latest_time,
        "position_set_uid": str(latest_position_set_uid),
        "positions": [
            {
                "target_type": "asset",
                "target_uid": str(asset_uid),
                "asset_uid": str(asset_uid),
                "portfolio_uid": None,
                "unique_identifier": "btc_spot",
                "weight_notional_exposure": "0.55",
                "constant_notional_exposure": None,
                "single_asset_quantity": None,
                "asset": {
                    "uid": str(asset_uid),
                    "unique_identifier": "btc_spot",
                    "current_snapshot": {
                        "name": "Bitcoin spot",
                        "ticker": "BTC",
                    },
                },
                "portfolio": None,
            },
            {
                "target_type": "portfolio",
                "target_uid": str(portfolio_uid),
                "asset_uid": None,
                "portfolio_uid": str(portfolio_uid),
                "unique_identifier": "example-sleeve",
                "weight_notional_exposure": "0.45",
                "constant_notional_exposure": None,
                "single_asset_quantity": None,
                "asset": None,
                "portfolio": {
                    "uid": str(portfolio_uid),
                    "unique_identifier": "example-sleeve",
                    "portfolio_index_uid": None,
                },
            },
        ],
    }


def test_core_account_holdings_snapshot_returns_empty_for_no_data(monkeypatch) -> None:
    account_uid = uuid.uuid4()

    from msm.services import accounts as account_services

    monkeypatch.setattr(
        account_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        account_services,
        "_search_account_holdings_rows",
        lambda context, account_uid, limit: [],
    )

    snapshot = account_services.get_account_holdings_snapshot_response(
        object(),
        account_uid=str(account_uid),
    )

    assert snapshot == {
        "holdings_set_uid": None,
        "holdings_date": None,
        "holdings": [],
    }


def test_account_target_positions_snapshot_returns_empty_for_no_data(monkeypatch) -> None:
    account_uid = uuid.uuid4()

    from msm.services import target_positions as target_position_services

    monkeypatch.setattr(
        target_position_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        target_position_services,
        "_search_active_account_target_allocation_rows",
        lambda context, account_uid: [],
    )

    snapshot = target_position_services.get_account_target_positions_snapshot_response(
        object(),
        account_uid=str(account_uid),
    )

    assert snapshot == {
        "related_account_uid": str(account_uid),
        "target_positions_date": None,
        "position_set_uid": None,
        "positions": [],
    }


def test_core_add_account_target_positions_snapshot_derives_parent_rows(
    monkeypatch,
) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    target_positions_date = dt.datetime(2026, 6, 8, 10, 30, tzinfo=dt.UTC)
    captured: dict[str, object] = {}

    from msm.services import target_positions as target_position_services

    monkeypatch.setattr(
        target_position_services,
        "get_account_by_uid",
        lambda context, uid: {
            "row": {
                "uid": str(account_uid),
                "account_name": "Some account",
            }
        },
    )

    def fake_replace_account_target_positions_snapshot(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {"rows": [{"target_uid": str(asset_uid)}]}

    monkeypatch.setattr(
        "msm.repositories.accounts.replace_account_target_positions_snapshot",
        fake_replace_account_target_positions_snapshot,
    )
    monkeypatch.setattr(
        target_position_services,
        "get_account_target_positions_snapshot_response",
        lambda context, **kwargs: {
            "related_account_uid": str(account_uid),
            "target_positions_date": target_positions_date,
            "position_set_uid": "position-set-uid",
            "positions": [],
        },
    )

    snapshot = target_position_services.add_account_target_positions_snapshot_response(
        object(),
        account_uid=str(account_uid),
        target_positions_date=target_positions_date,
        overwrite=True,
        positions=[
            {
                "target_type": "asset",
                "target_uid": str(asset_uid),
                "asset_uid": str(asset_uid),
                "weight_notional_exposure": "1.0",
            }
        ],
    )

    assert snapshot is not None
    assert snapshot["position_set_uid"] == "position-set-uid"
    assert uuid.UUID(str(captured["account_allocation_model_uid"]))
    assert uuid.UUID(str(captured["account_target_allocation_uid"]))
    assert uuid.UUID(str(captured["position_set_uid"]))
    assert captured["account_uid"] == str(account_uid)
    assert captured["account_name"] == "Some account"
    assert captured["target_positions_date"] == target_positions_date
    assert captured["overwrite"] is True
    assert captured["positions"] == [
        {
            "target_type": "asset",
            "target_uid": str(asset_uid),
            "asset_uid": str(asset_uid),
            "portfolio_uid": None,
            "weight_notional_exposure": 1.0,
            "constant_notional_exposure": None,
            "single_asset_quantity": None,
            "metadata_json": {},
        }
    ]


def test_core_add_account_target_positions_returns_none_for_missing_account(
    monkeypatch,
) -> None:
    from msm.services import target_positions as target_position_services

    monkeypatch.setattr(
        target_position_services,
        "get_account_by_uid",
        lambda context, uid: {"rows": []},
    )

    snapshot = target_position_services.add_account_target_positions_snapshot_response(
        object(),
        account_uid=str(uuid.uuid4()),
        target_positions_date=dt.datetime(2026, 6, 8, 10, 30, tzinfo=dt.UTC),
        positions=[],
    )

    assert snapshot is None


def test_core_add_account_target_positions_raises_conflict_when_snapshot_exists(
    monkeypatch,
) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()

    from msm.services import target_positions as target_position_services

    monkeypatch.setattr(
        target_position_services,
        "get_account_by_uid",
        lambda context, uid: {
            "row": {
                "uid": str(account_uid),
                "account_name": "Some account",
            }
        },
    )
    monkeypatch.setattr(
        "msm.repositories.accounts.replace_account_target_positions_snapshot",
        lambda context, **kwargs: {"rows": []},
    )

    with pytest.raises(target_position_services.AccountTargetPositionsSnapshotExistsError):
        target_position_services.add_account_target_positions_snapshot_response(
            object(),
            account_uid=str(account_uid),
            target_positions_date=dt.datetime(2026, 6, 8, 10, 30, tzinfo=dt.UTC),
            overwrite=False,
            positions=[
                {
                    "target_type": "asset",
                    "target_uid": str(asset_uid),
                    "asset_uid": str(asset_uid),
                    "weight_notional_exposure": "1.0",
                }
            ],
        )


def test_account_repository_builds_atomic_target_positions_replacement_operation() -> None:
    from mainsequence.client.metatables import MetaTableOperationScopeTable

    from msm.data_nodes.accounts.storage import TargetPositionsStorage
    from msm.models import (
        AccountAllocationModelTable,
        AccountTargetAllocationTable,
        PositionSetTable,
    )
    from msm.repositories import accounts as account_repository

    class FakeContext:
        data_source_uid = "test-data-source"
        limits = None

        def scope_table(self, model, *, access="read", alias=None):
            return MetaTableOperationScopeTable(
                meta_table_uid=f"{model.__name__}-uid",
                access=access,
                alias=alias,
            )

    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    target_positions_date = dt.datetime(2026, 6, 8, 10, 30, tzinfo=dt.UTC)

    operation = account_repository.build_replace_account_target_positions_snapshot_operation(
        FakeContext(),
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        account_uid=account_uid,
        account_name="Some account",
        target_positions_date=target_positions_date,
        overwrite=True,
        positions=[
            {
                "target_type": "asset",
                "target_uid": str(asset_uid),
                "asset_uid": str(asset_uid),
                "portfolio_uid": None,
                "weight_notional_exposure": "1.0",
                "constant_notional_exposure": None,
                "single_asset_quantity": None,
                "metadata_json": {"source": "test"},
            }
        ],
    )

    sql = operation.statement.sql
    assert operation.operation == "upsert"
    assert "WITH account_allocation_model AS" in sql
    assert "account_target_allocation AS" in sql
    assert "position_set AS" in sql
    assert "ON CONFLICT (allocation_model_name)" in sql
    assert "ON CONFLICT (unique_identifier)" in sql
    assert "ON CONFLICT (account_target_allocation_uid, position_set_time)" in sql
    assert "FROM account_allocation_model ON CONFLICT" in sql
    assert "FROM account_target_allocation ON CONFLICT" in sql
    assert "WHERE %(overwrite)s" in sql
    assert "DELETE FROM" in sql
    assert "deleted_gate AS" in sql
    assert "INSERT INTO" in sql
    assert "WITH inserted AS" not in sql
    assert "FROM inserted" not in sql
    assert "JOIN position_set ON true" in sql
    assert "JOIN deleted_gate ON true" in sql
    assert operation.statement.parameters["account_uid"] == account_uid
    assert operation.statement.parameters["account_name"] == "Some account"
    assert operation.statement.parameters["target_positions_date"] == "2026-06-08T10:30:00Z"
    assert operation.statement.parameters["target_type_0"] == "asset"
    assert operation.statement.parameters["target_uid_0"] == asset_uid
    assert operation.statement.parameters["asset_uid_0"] == asset_uid
    assert operation.statement.parameters["portfolio_uid_0"] is None
    assert operation.statement.parameters["weight_notional_exposure_0"] == "1.0"
    assert operation.statement.parameters["metadata_json_0"] == {"source": "test"}
    assert operation.statement.parameter_types == {
        "target_positions_date": "timestamp with time zone",
    }
    assert [(table.meta_table_uid, table.access) for table in operation.scope.tables] == [
        (f"{AccountAllocationModelTable.__name__}-uid", "write"),
        (f"{AccountTargetAllocationTable.__name__}-uid", "write"),
        (f"{PositionSetTable.__name__}-uid", "write"),
        (f"{TargetPositionsStorage.__name__}-uid", "write"),
    ]
