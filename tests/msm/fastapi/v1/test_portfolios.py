from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.v1.main import app


def _portfolio_row(uid: uuid.UUID | None = None) -> dict[str, object]:
    return {
        "uid": str(uid or uuid.uuid4()),
        "unique_identifier": "example-sleeve",
        "calendar_name": "CRYPTO_24_7",
        "calendar_uid": None,
        "portfolio_index_uid": str(uuid.uuid4()),
        "portfolio_weights_data_node_uid": None,
        "signal_weights_data_node_uid": None,
        "portfolio_data_node_uid": None,
        "backtest_table_price_column_name": "close",
    }


def test_get_portfolios_returns_core_portfolio_rows(monkeypatch) -> None:
    portfolio = _portfolio_row()
    captured: dict[str, object] = {}

    def fake_list_portfolios(**kwargs):
        captured.update(kwargs)
        return {"count": 1, "results": [portfolio]}

    monkeypatch.setattr("apps.v1.routers.portfolios.list_portfolios", fake_list_portfolios)

    client = TestClient(app)
    response = client.get(
        "/api/v1/portfolio/",
        params={
            "response_format": "frontend_list",
            "search": "sleeve",
            "calendar_name": "CRYPTO_24_7",
            "limit": 10,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [portfolio],
    }
    assert captured == {
        "search": "sleeve",
        "calendar_uid": None,
        "calendar_name": "CRYPTO_24_7",
        "limit": 10,
        "offset": 0,
    }


def test_get_portfolios_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/portfolio/", params={"response_format": "detail"})

    assert response.status_code == 400
    assert "frontend_list" in response.json()["detail"]


def test_get_portfolio_detail_returns_composed_payload(monkeypatch) -> None:
    portfolio = _portfolio_row()

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_detail",
        lambda uid: {
            "portfolio": portfolio,
            "metadata": {
                "uid": str(uuid.uuid4()),
                "unique_identifier": "example-sleeve",
                "description": "Example sleeve portfolio.",
            },
            "tabs": [
                {
                    "key": "latest_weights",
                    "label": "Latest Weights",
                    "url": f"/api/v1/portfolio/{portfolio['uid']}/weights/?order=desc&limit=1&include_asset_detail=true",
                }
            ],
            "links": {
                "summary": f"/api/v1/portfolio/{portfolio['uid']}/summary/",
                "latest_weights": f"/api/v1/portfolio/{portfolio['uid']}/weights/",
                "delete": f"/api/v1/portfolio/{portfolio['uid']}/",
            },
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/portfolio/{portfolio['uid']}/")

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio"] == portfolio
    assert body["metadata"]["description"] == "Example sleeve portfolio."
    assert body["tabs"][0]["key"] == "latest_weights"


def test_get_portfolio_detail_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr("apps.v1.routers.portfolios.get_portfolio_detail", lambda uid: None)

    client = TestClient(app)
    response = client.get("/api/v1/portfolio/missing-portfolio/")

    assert response.status_code == 404
    assert "missing-portfolio" in response.json()["detail"]


def test_get_portfolio_summary_returns_standard_summary(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_summary",
        lambda uid: {
            "entity": {
                "id": str(portfolio_uid),
                "type": "portfolio",
                "title": "example-sleeve",
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
    response = client.get(f"/api/v1/portfolio/{portfolio_uid}/summary/")

    assert response.status_code == 200
    assert response.json()["entity"]["id"] == str(portfolio_uid)


def test_portfolio_summary_omits_backtest_price_column(monkeypatch) -> None:
    portfolio = _portfolio_row()
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_metadata_row",
        lambda context, unique_identifier: None,
    )

    from msm_portfolios.services.public_api import get_portfolio_frontend_detail_summary

    summary = get_portfolio_frontend_detail_summary(object(), uid=str(portfolio["uid"]))

    assert summary is not None
    summary_keys = {
        field["key"]
        for section in ("inline_fields", "highlight_fields", "stats")
        for field in summary[section]
    }
    assert "backtest_table_price_column_name" not in summary_keys


def test_get_portfolio_weights_returns_snapshot(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_get_portfolio_weights(**kwargs):
        captured.update(kwargs)
        return {
            "portfolio_uid": str(portfolio_uid),
            "portfolio_unique_identifier": "example-sleeve",
            "portfolio_index_uid": str(index_uid),
            "portfolio_index_identifier": "example-sleeve-index",
            "weights_date": "2026-06-07T10:30:00Z",
            "resolution_warning": None,
            "weights": [
                {
                    "time_index": "2026-06-07T10:30:00Z",
                    "portfolio_index_identifier": "example-sleeve-index",
                    "asset_identifier": "example-asset-btc",
                    "weight": "0.6",
                    "weight_before": "0.55",
                    "price_current": "100.0",
                    "price_before": "95.0",
                    "volume_current": None,
                    "volume_before": None,
                    "asset": {
                        "uid": str(asset_uid),
                        "unique_identifier": "example-asset-btc",
                        "current_snapshot": {
                            "name": "Bitcoin",
                            "ticker": "BTC",
                        },
                    },
                }
            ],
        }

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_weights",
        fake_get_portfolio_weights,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/portfolio/{portfolio_uid}/weights/",
        params={
            "weights_date": "2026-06-07T10:30:00Z",
            "include_asset_detail": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_uid"] == str(portfolio_uid)
    assert body["weights_date"] == "2026-06-07T10:30:00Z"
    assert body["weights"][0]["asset"] == {
        "uid": str(asset_uid),
        "unique_identifier": "example-asset-btc",
        "current_snapshot": {
            "name": "Bitcoin",
            "ticker": "BTC",
        },
    }
    assert captured == {
        "uid": str(portfolio_uid),
        "order": "desc",
        "limit": 1,
        "include_asset_detail": True,
        "weights_date": dt.datetime(2026, 6, 7, 10, 30, tzinfo=dt.UTC),
    }


def test_get_portfolio_weights_returns_empty_snapshot(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_weights",
        lambda **kwargs: {
            "portfolio_uid": str(portfolio_uid),
            "portfolio_unique_identifier": "example-sleeve",
            "portfolio_index_uid": None,
            "portfolio_index_identifier": None,
            "weights_date": None,
            "resolution_warning": "Portfolio has no portfolio_index_uid; latest weights cannot be resolved.",
            "weights": [],
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/portfolio/{portfolio_uid}/weights/")

    assert response.status_code == 200
    assert response.json()["weights"] == []
    assert "portfolio_index_uid" in response.json()["resolution_warning"]


def test_delete_portfolio_returns_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.delete_portfolio",
        lambda uid: {"detail": "Portfolio deleted.", "deleted_count": 1},
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/portfolio/{uuid.uuid4()}/")

    assert response.status_code == 200
    assert response.json() == {"detail": "Portfolio deleted.", "deleted_count": 1}


def test_delete_portfolio_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr("apps.v1.routers.portfolios.delete_portfolio", lambda uid: None)

    client = TestClient(app)
    response = client.delete("/api/v1/portfolio/missing-portfolio/")

    assert response.status_code == 404
    assert "missing-portfolio" in response.json()["detail"]


def test_delete_portfolio_returns_409_when_protected(monkeypatch) -> None:
    from msm_portfolios.services import PortfolioDeleteConflictError

    def fake_delete_portfolio(uid):
        raise PortfolioDeleteConflictError("Portfolio is referenced by target positions.")

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.delete_portfolio",
        fake_delete_portfolio,
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/portfolio/{uuid.uuid4()}/")

    assert response.status_code == 409
    assert "referenced" in response.json()["detail"]


def test_bulk_delete_portfolios_reports_failures(monkeypatch) -> None:
    deleted_uid = uuid.uuid4()
    failed_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_bulk_delete_portfolios(**kwargs):
        captured.update(kwargs)
        return {
            "detail": "Deleted 1 portfolio; 1 portfolio could not be deleted.",
            "deleted_count": 1,
            "failed": [
                {
                    "uid": str(failed_uid),
                    "reason": "Portfolio is referenced by target positions.",
                }
            ],
        }

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.bulk_delete_portfolios",
        fake_bulk_delete_portfolios,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/portfolio/bulk-delete/",
        json={"uids": [str(deleted_uid), str(failed_uid)]},
    )

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1
    assert response.json()["failed"] == [
        {
            "uid": str(failed_uid),
            "reason": "Portfolio is referenced by target positions.",
        }
    ]
    assert captured == {"uids": [str(deleted_uid), str(failed_uid)]}


def test_portfolio_service_maps_source_helpers(monkeypatch) -> None:
    portfolio = _portfolio_row()
    runtime = SimpleNamespace(context=object())

    monkeypatch.setattr("apps.v1.services.portfolios._get_runtime", lambda: runtime)
    monkeypatch.setattr(
        "apps.v1.services.portfolios._list_portfolio_rows_response",
        lambda context, **kwargs: {"count": 1, "results": [portfolio]},
    )

    from apps.v1.services.portfolios import list_portfolios

    response = list_portfolios(search="sleeve", limit=25, offset=0)

    assert response["count"] == 1
    assert response["results"][0].model_dump(mode="json") == portfolio


def test_portfolio_weights_service_maps_source_snapshot(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr("apps.v1.services.portfolios._get_runtime", lambda: runtime)

    def fake_weights_snapshot(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "portfolio_uid": str(portfolio_uid),
            "portfolio_unique_identifier": "example-sleeve",
            "portfolio_index_uid": None,
            "portfolio_index_identifier": None,
            "weights_date": None,
            "resolution_warning": None,
            "weights": [],
        }

    monkeypatch.setattr(
        "apps.v1.services.portfolios._get_portfolio_weights_snapshot_response",
        fake_weights_snapshot,
    )

    from apps.v1.services.portfolios import get_portfolio_weights

    response = get_portfolio_weights(uid=str(portfolio_uid), include_asset_detail=False)

    assert response is not None
    assert response.model_dump(mode="json")["portfolio_uid"] == str(portfolio_uid)
    assert captured["context"] is runtime.context
    assert captured["uid"] == str(portfolio_uid)
    assert captured["include_asset_detail"] is False
