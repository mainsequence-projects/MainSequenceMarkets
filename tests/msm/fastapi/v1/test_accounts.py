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
                    "quantity": "-12.0",
                    "direction": -1,
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
    assert body["holdings"][0]["quantity"] == "-12.0"
    assert body["holdings"][0]["direction"] == -1


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


def test_add_account_holdings_returns_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()

    def fake_add_account_holdings(*, account_uid, payload):
        assert payload.holdings_date == dt.datetime(2026, 6, 5, 8, tzinfo=dt.UTC)
        assert payload.overwrite is True
        assert payload.positions[0].unique_identifier == "example-asset-btc"
        assert payload.positions[0].asset_uid == str(asset_uid)
        assert payload.positions[0].direction == -1
        return {
            "id": None,
            "snapshot_uid": None,
            "holdings_set_uid": "holdings-set-uid",
            "holdings_date": "2026-06-05T08:00:00Z",
            "nav": None,
            "related_account_uid": account_uid,
            "is_trade_snapshot": False,
            "target_trade_time": "2026-06-05T08:00:00Z",
            "related_expected_asset_exposure_df": [],
            "holdings": [
                {
                    "time_index": "2026-06-05T08:00:00Z",
                    "unique_identifier": "example-asset-btc",
                    "asset_id": None,
                    "asset": {
                        "uid": str(asset_uid),
                        "figi": None,
                        "current_snapshot": {
                            "name": "Bitcoin",
                            "ticker": "BTC",
                        },
                    },
                    "position_type": "units",
                    "price": None,
                    "quantity": "-10.0",
                    "direction": -1,
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
                    "unique_identifier": "example-asset-btc",
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
    assert body["related_account_uid"] == str(account_uid)
    assert body["holdings_set_uid"] == "holdings-set-uid"
    assert body["holdings"][0]["quantity"] == "-10.0"
    assert body["holdings"][0]["direction"] == -1


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
                    "unique_identifier": "example-asset-btc",
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
                    "unique_identifier": "example-asset-btc",
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
                    "direction": 1,
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


def test_add_account_holdings_service_maps_snapshot(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr("apps.v1.services.accounts._get_holdings_runtime", lambda: runtime)

    def fake_add_account_holdings_snapshot_response(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "id": None,
            "snapshot_uid": None,
            "holdings_set_uid": "holdings-set-uid",
            "holdings_date": "2026-06-05T08:00:00Z",
            "nav": None,
            "related_account_uid": str(account_uid),
            "is_trade_snapshot": False,
            "target_trade_time": "2026-06-05T08:00:00Z",
            "related_expected_asset_exposure_df": [],
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
                    "unique_identifier": "example-asset-btc",
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
                "unique_identifier": "btc_spot",
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
                    "unique_identifier": "btc_spot",
                    "current_snapshot": {
                        "name": "Bitcoin spot",
                        "ticker": "BTC",
                    },
                },
                "position_type": "units",
                "price": None,
                "quantity": "-12.0",
                "direction": -1,
                "missing_price": True,
                "target_trade_time": None,
                "extra_details": {"source": "test"},
            }
        ],
    }


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
            "id": None,
            "snapshot_uid": None,
            "holdings_set_uid": str(holdings_set_uid),
            "holdings_date": holdings_date,
            "nav": None,
            "related_account_uid": str(account_uid),
            "is_trade_snapshot": False,
            "target_trade_time": holdings_date,
            "related_expected_asset_exposure_df": [],
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
                "unique_identifier": "example-asset-btc",
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
                    "unique_identifier": "example-asset-btc",
                    "asset_uid": str(asset_uid),
                    "quantity": "10",
                }
            ],
        )
    assert captured["frame_kwargs"]["account_uid"] == str(account_uid)


def test_account_repository_builds_atomic_holdings_replacement_operation() -> None:
    from mainsequence.client.metatables import MetaTableOperationScopeTable

    from msm.data_nodes.storage import AccountHoldingsStorage
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
    assert [
        (table.meta_table_uid, table.access)
        for table in operation.scope.tables
    ] == [
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
                    "unique_identifier": "example-asset-btc",
                    "asset_uid": str(wrong_asset_uid),
                    "quantity": "10",
                }
            ],
        )


def test_portfolio_account_target_positions_snapshot_selects_latest(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    target_portfolio_uid = uuid.uuid4()
    older_position_set_uid = uuid.uuid4()
    latest_position_set_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    older_time = dt.datetime(2026, 6, 1, 10, 30, tzinfo=dt.UTC)
    latest_time = dt.datetime(2026, 6, 2, 10, 30, tzinfo=dt.UTC)

    from msm_portfolios.services import target_positions as target_position_services

    monkeypatch.setattr(
        target_position_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        target_position_services,
        "_search_active_account_target_portfolio_rows",
        lambda context, account_uid: [{"uid": str(target_portfolio_uid)}],
    )
    monkeypatch.setattr(
        target_position_services,
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
            }
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


def test_portfolio_account_target_positions_snapshot_returns_empty_for_no_data(monkeypatch) -> None:
    account_uid = uuid.uuid4()

    from msm_portfolios.services import target_positions as target_position_services

    monkeypatch.setattr(
        target_position_services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": str(account_uid)}},
    )
    monkeypatch.setattr(
        target_position_services,
        "_search_active_account_target_portfolio_rows",
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
