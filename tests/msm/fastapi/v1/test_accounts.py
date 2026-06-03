from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

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
    assert response.json() == {"count": 0, "results": []}
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


def test_get_account_holdings_returns_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()

    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_holdings",
        lambda **kwargs: {
            "id": None,
            "snapshot_uid": None,
            "holdings_set_uid": "holdings-set-uid",
            "holdings_date": "2026-06-01T10:30:00Z",
            "nav": None,
            "related_account_uid": str(account_uid),
            "is_trade_snapshot": False,
            "target_trade_time": None,
            "related_expected_asset_exposure_df": [],
            "holdings": [
                {
                    "time_index": "2026-06-01T10:30:00Z",
                    "unique_identifier": "btc_spot",
                    "asset_id": None,
                    "asset": {
                        "uid": str(asset_uid),
                        "figi": "BBG000BTC",
                        "current_snapshot": {
                            "name": "Bitcoin spot",
                            "ticker": "BTC",
                        },
                    },
                    "position_type": "units",
                    "price": None,
                    "quantity": "12.0",
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
    assert body["id"] is None
    assert body["related_account_uid"] == str(account_uid)
    assert body["holdings_set_uid"] == "holdings-set-uid"
    assert body["holdings"][0]["asset_id"] is None
    assert body["holdings"][0]["asset"]["uid"] == str(asset_uid)
    assert body["holdings"][0]["asset"]["current_snapshot"] == {
        "name": "Bitcoin spot",
        "ticker": "BTC",
    }


def test_get_account_holdings_passes_query_params(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_get_account_holdings(**kwargs):
        captured.update(kwargs)
        return {
            "id": None,
            "snapshot_uid": None,
            "holdings_set_uid": None,
            "holdings_date": None,
            "nav": None,
            "related_account_uid": str(account_uid),
            "is_trade_snapshot": False,
            "target_trade_time": None,
            "related_expected_asset_exposure_df": [],
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


def test_get_account_target_positions_returns_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()

    monkeypatch.setattr(
        "apps.v1.routers.accounts.get_account_target_positions",
        lambda **kwargs: {
            "related_account_uid": str(account_uid),
            "target_positions_date": "2026-06-02T10:30:00Z",
            "position_set_uid": "position-set-uid",
            "positions": [
                {
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
                }
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


def test_account_holdings_service_maps_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())

    monkeypatch.setattr("apps.v1.services.accounts._get_holdings_runtime", lambda: runtime)
    monkeypatch.setattr(
        "apps.v1.services.accounts._get_account_holdings_snapshot_response",
        lambda context, **kwargs: {
            "id": None,
            "snapshot_uid": None,
            "holdings_set_uid": "holdings-set-uid",
            "holdings_date": "2026-06-01T10:30:00Z",
            "nav": None,
            "related_account_uid": str(account_uid),
            "is_trade_snapshot": False,
            "target_trade_time": None,
            "related_expected_asset_exposure_df": [],
            "holdings": [
                {
                    "time_index": "2026-06-01T10:30:00Z",
                    "unique_identifier": "btc_spot",
                    "asset_id": None,
                    "asset": None,
                    "position_type": "units",
                    "price": None,
                    "quantity": "12.0",
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
    assert payload["related_account_uid"] == str(account_uid)
    assert payload["holdings"][0]["unique_identifier"] == "btc_spot"
    assert payload["holdings"][0]["asset"] is None


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
                    "unique_identifier": "btc_spot",
                    "weight_notional_exposure": "0.55",
                    "constant_notional_exposure": None,
                    "single_asset_quantity": None,
                    "asset": None,
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
                "direction": 1,
                "target_trade_time": None,
                "extra_details": {"source": "test"},
            },
        ],
    )
    monkeypatch.setattr(
        account_services,
        "_asset_references_by_unique_identifier",
        lambda context, rows: {
            "btc_spot": {
                "uid": str(asset_uid),
                "figi": "BBG000BTC",
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
        "id": None,
        "snapshot_uid": None,
        "holdings_set_uid": "latest-set",
        "holdings_date": latest_time,
        "nav": None,
        "related_account_uid": str(account_uid),
        "is_trade_snapshot": False,
        "target_trade_time": None,
        "related_expected_asset_exposure_df": [],
        "holdings": [
            {
                "time_index": latest_time,
                "unique_identifier": "btc_spot",
                "asset_id": None,
                "asset": {
                    "uid": str(asset_uid),
                    "figi": "BBG000BTC",
                    "current_snapshot": {
                        "name": "Bitcoin spot",
                        "ticker": "BTC",
                    },
                },
                "position_type": "units",
                "price": None,
                "quantity": "12.0",
                "direction": 1,
                "missing_price": True,
                "target_trade_time": None,
                "extra_details": {"source": "test"},
            }
        ],
    }


def test_core_account_target_positions_snapshot_selects_latest(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    target_portfolio_uid = uuid.uuid4()
    older_position_set_uid = uuid.uuid4()
    latest_position_set_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    older_time = dt.datetime(2026, 6, 1, 10, 30, tzinfo=dt.UTC)
    latest_time = dt.datetime(2026, 6, 2, 10, 30, tzinfo=dt.UTC)

    from msm.services import accounts as account_services

    monkeypatch.setattr(
        account_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        account_services,
        "_search_active_account_target_portfolio_rows",
        lambda context, account_uid: [{"uid": str(target_portfolio_uid)}],
    )
    monkeypatch.setattr(
        account_services,
        "_search_position_set_rows_for_target_portfolios",
        lambda context, target_portfolio_uids, position_set_time: [
            {
                "uid": str(older_position_set_uid),
                "account_target_portfolio_uid": str(target_portfolio_uid),
                "position_set_time": older_time,
            },
            {
                "uid": str(latest_position_set_uid),
                "account_target_portfolio_uid": str(target_portfolio_uid),
                "position_set_time": latest_time,
            },
        ],
    )
    monkeypatch.setattr(
        account_services,
        "_search_target_position_rows",
        lambda context, position_set_uid, target_positions_date, limit: [
            {
                "time_index": latest_time,
                "position_set_uid": position_set_uid,
                "asset_identifier": "btc_spot",
                "weight_notional_exposure": 0.55,
                "constant_notional_exposure": None,
                "single_asset_quantity": None,
            }
        ],
    )
    monkeypatch.setattr(
        account_services,
        "_asset_snapshot_references_by_unique_identifier",
        lambda context, rows: {
            "btc_spot": {
                "uid": str(asset_uid),
                "unique_identifier": "btc_spot",
                "current_snapshot": {
                    "name": "Bitcoin spot",
                    "ticker": "BTC",
                },
            }
        },
    )

    snapshot = account_services.get_account_target_positions_snapshot_response(
        object(),
        account_uid=str(account_uid),
    )

    assert snapshot == {
        "related_account_uid": str(account_uid),
        "target_positions_date": latest_time,
        "position_set_uid": str(latest_position_set_uid),
        "positions": [
            {
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
            }
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
        "id": None,
        "snapshot_uid": None,
        "holdings_set_uid": None,
        "holdings_date": None,
        "nav": None,
        "related_account_uid": str(account_uid),
        "is_trade_snapshot": False,
        "target_trade_time": None,
        "related_expected_asset_exposure_df": [],
        "holdings": [],
    }


def test_core_account_target_positions_snapshot_returns_empty_for_no_data(monkeypatch) -> None:
    account_uid = uuid.uuid4()

    from msm.services import accounts as account_services

    monkeypatch.setattr(
        account_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        account_services,
        "_search_active_account_target_portfolio_rows",
        lambda context, account_uid: [],
    )

    snapshot = account_services.get_account_target_positions_snapshot_response(
        object(),
        account_uid=str(account_uid),
    )

    assert snapshot == {
        "related_account_uid": str(account_uid),
        "target_positions_date": None,
        "position_set_uid": None,
        "positions": [],
    }
