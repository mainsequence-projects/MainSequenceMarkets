from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.v1.main import app


def _virtual_fund_row(uid: uuid.UUID | None = None) -> dict[str, str]:
    return {
        "uid": str(uid or uuid.uuid4()),
        "unique_identifier": "account-alpha__portfolio-sleeve",
        "account_uid": str(uuid.uuid4()),
        "target_portfolio_uid": str(uuid.uuid4()),
    }


def test_get_virtualfund_list_returns_core_rows(monkeypatch) -> None:
    virtual_fund = _virtual_fund_row()
    captured: dict[str, object] = {}

    def fake_list_virtual_funds(**kwargs):
        captured.update(kwargs)
        return {"count": 1, "results": [virtual_fund]}

    monkeypatch.setattr(
        "apps.v1.routers.virtual_funds.list_virtual_funds",
        fake_list_virtual_funds,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/virtualfund/",
        params={
            "response_format": "frontend_list",
            "search": "alpha",
            "account_uid": virtual_fund["account_uid"],
            "portfolio_uid": virtual_fund["target_portfolio_uid"],
            "limit": 25,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [virtual_fund],
    }
    assert captured == {
        "search": "alpha",
        "account_uid": virtual_fund["account_uid"],
        "portfolio_uid": virtual_fund["target_portfolio_uid"],
        "limit": 25,
        "offset": 0,
    }


def test_get_virtualfund_list_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/virtualfund/", params={"response_format": "detail"})

    assert response.status_code == 400
    assert "frontend_list" in response.json()["detail"]


def test_get_virtualfund_detail_returns_composed_payload(monkeypatch) -> None:
    virtual_fund = _virtual_fund_row()

    monkeypatch.setattr(
        "apps.v1.routers.virtual_funds.get_virtual_fund_detail",
        lambda uid: {
            "virtual_fund": virtual_fund,
            "tabs": [
                {
                    "key": "latest_holdings",
                    "label": "Latest Holdings",
                    "url": (
                        f"/api/v1/virtualfund/{virtual_fund['uid']}/holdings/"
                        "?order=desc&limit=1&include_asset_detail=true"
                    ),
                }
            ],
            "links": {
                "summary": f"/api/v1/virtualfund/{virtual_fund['uid']}/summary/",
                "latest_holdings": f"/api/v1/virtualfund/{virtual_fund['uid']}/holdings/",
                "account": f"/api/v1/account/{virtual_fund['account_uid']}/summary/",
                "portfolio": f"/api/v1/portfolio/{virtual_fund['target_portfolio_uid']}/",
            },
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/virtualfund/{virtual_fund['uid']}/")

    assert response.status_code == 200
    body = response.json()
    assert body["virtual_fund"] == virtual_fund
    assert body["tabs"][0]["key"] == "latest_holdings"
    assert body["links"]["portfolio"].endswith(f"{virtual_fund['target_portfolio_uid']}/")


def test_get_virtualfund_detail_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.virtual_funds.get_virtual_fund_detail",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/virtualfund/missing-virtual-fund/")

    assert response.status_code == 404
    assert "missing-virtual-fund" in response.json()["detail"]


def test_get_virtualfund_summary_returns_standard_summary(monkeypatch) -> None:
    virtual_fund = _virtual_fund_row()

    monkeypatch.setattr(
        "apps.v1.routers.virtual_funds.get_virtual_fund_summary",
        lambda uid: {
            "entity": {
                "id": virtual_fund["uid"],
                "type": "virtual_fund",
                "title": virtual_fund["unique_identifier"],
            },
            "badges": [],
            "inline_fields": [],
            "highlight_fields": [],
            "stats": [],
            "label_management": {
                "labels": [],
                "add_label_url": None,
                "remove_label_url": None,
            },
            "summary_warning": None,
            "extensions": {},
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/virtualfund/{virtual_fund['uid']}/summary/")

    assert response.status_code == 200
    assert response.json()["entity"]["id"] == virtual_fund["uid"]


def test_get_virtualfund_holdings_returns_snapshot(monkeypatch) -> None:
    virtual_fund = _virtual_fund_row()
    asset_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_get_virtual_fund_holdings(**kwargs):
        captured.update(kwargs)
        return {
            "virtual_fund_uid": virtual_fund["uid"],
            "virtual_fund_unique_identifier": virtual_fund["unique_identifier"],
            "holdings_set_uid": str(uuid.uuid4()),
            "source_account_holdings_set_uid": str(uuid.uuid4()),
            "holdings_date": "2026-06-08T10:30:00Z",
            "holdings": [
                {
                    "time_index": "2026-06-08T10:30:00Z",
                    "asset_identifier": "example-asset-btc",
                    "virtual_fund_holdings_set_uid": str(uuid.uuid4()),
                    "source_account_holdings_set_uid": str(uuid.uuid4()),
                    "quantity": "5.0",
                    "direction": -1,
                    "signed_quantity": "-5.0",
                    "target_trade_time": None,
                    "extra_details": {},
                    "asset": {
                        "uid": str(asset_uid),
                        "asset_identifier": "example-asset-btc",
                        "current_snapshot": {
                            "name": "Bitcoin",
                            "ticker": "BTC",
                        },
                    },
                }
            ],
        }

    monkeypatch.setattr(
        "apps.v1.routers.virtual_funds.get_virtual_fund_holdings",
        fake_get_virtual_fund_holdings,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/virtualfund/{virtual_fund['uid']}/holdings/",
        params={
            "holdings_date": "2026-06-08T10:30:00Z",
            "include_asset_detail": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["virtual_fund_uid"] == virtual_fund["uid"]
    assert body["holdings"][0]["signed_quantity"] == "-5.0"
    assert body["holdings"][0]["asset"] == {
        "uid": str(asset_uid),
        "asset_identifier": "example-asset-btc",
        "current_snapshot": {
            "name": "Bitcoin",
            "ticker": "BTC",
        },
    }
    assert captured == {
        "uid": virtual_fund["uid"],
        "order": "desc",
        "limit": 1,
        "include_asset_detail": True,
        "holdings_date": dt.datetime(2026, 6, 8, 10, 30, tzinfo=dt.UTC),
    }


def test_get_virtualfund_holdings_returns_empty_snapshot(monkeypatch) -> None:
    virtual_fund = _virtual_fund_row()

    monkeypatch.setattr(
        "apps.v1.routers.virtual_funds.get_virtual_fund_holdings",
        lambda **kwargs: {
            "virtual_fund_uid": virtual_fund["uid"],
            "virtual_fund_unique_identifier": virtual_fund["unique_identifier"],
            "holdings_set_uid": None,
            "source_account_holdings_set_uid": None,
            "holdings_date": None,
            "holdings": [],
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/virtualfund/{virtual_fund['uid']}/holdings/")

    assert response.status_code == 200
    assert response.json()["holdings"] == []


def test_virtualfund_service_maps_source_helpers(monkeypatch) -> None:
    virtual_fund = _virtual_fund_row()
    runtime = SimpleNamespace(context=object())

    monkeypatch.setattr("apps.v1.services.virtual_funds._get_runtime", lambda: runtime)
    monkeypatch.setattr(
        "apps.v1.services.virtual_funds._list_virtual_fund_rows_response",
        lambda context, **kwargs: {"count": 1, "results": [virtual_fund]},
    )

    from apps.v1.services.virtual_funds import list_virtual_funds

    response = list_virtual_funds(account_uid=virtual_fund["account_uid"], limit=25, offset=0)

    assert response.count == 1
    assert response.results[0].model_dump(mode="json") == virtual_fund
