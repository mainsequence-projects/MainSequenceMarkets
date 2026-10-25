from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app


def _portfolio_row(uid: uuid.UUID | None = None) -> dict[str, object]:
    return {
        "uid": str(uid or uuid.uuid4()),
        "unique_identifier": "example-sleeve",
        "calendar_uid": str(uuid.uuid4()),
        "published_index_uid": str(uuid.uuid4()),
        "portfolio_weights_data_node_uid": None,
        "signal_weights_data_node_uid": None,
        "signal_uid": None,
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
            "search": "sleeve",
            "limit": 10,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [portfolio],
        "pageInfo": {
            "pageIndex": 0,
            "pageSize": 10,
            "totalItems": 1,
            "hasNextPage": False,
            "hasPreviousPage": False,
        },
    }
    assert captured == {
        "search": "sleeve",
        "calendar_uid": None,
        "limit": 10,
        "offset": 0,
    }


def test_get_portfolios_does_not_publish_response_format() -> None:
    parameters = app.openapi()["paths"]["/api/v1/portfolio/"]["get"]["parameters"]

    assert "response_format" not in {parameter["name"] for parameter in parameters}


def test_portfolio_service_rejects_null_calendar_uid_in_list(monkeypatch) -> None:
    from apps.v1.services import portfolios as portfolio_service

    invalid_portfolio = {**_portfolio_row(), "calendar_uid": None}
    monkeypatch.setattr(
        portfolio_service,
        "_get_runtime",
        lambda: SimpleNamespace(context=object()),
    )
    monkeypatch.setattr(
        portfolio_service,
        "_list_portfolio_rows_response",
        lambda context, **kwargs: {"count": 1, "results": [invalid_portfolio]},
    )

    with pytest.raises(portfolio_service.PortfolioDataIntegrityError, match="calendar_uid=NULL"):
        portfolio_service.list_portfolios()


def test_get_portfolios_returns_409_for_invalid_stored_calendar(monkeypatch) -> None:
    from apps.v1.services.portfolios import PortfolioDataIntegrityError

    def fake_list_portfolios(**kwargs):
        raise PortfolioDataIntegrityError("Stored Portfolio row has calendar_uid=NULL.")

    monkeypatch.setattr("apps.v1.routers.portfolios.list_portfolios", fake_list_portfolios)

    client = TestClient(app)
    response = client.get("/api/v1/portfolio/")

    assert response.status_code == 409
    assert "calendar_uid=NULL" in response.json()["detail"]


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


def test_portfolio_service_rejects_null_calendar_uid_in_detail(monkeypatch) -> None:
    from apps.v1.services import portfolios as portfolio_service

    invalid_portfolio = {**_portfolio_row(), "calendar_uid": None}
    monkeypatch.setattr(
        portfolio_service,
        "_get_runtime",
        lambda: SimpleNamespace(context=object()),
    )
    monkeypatch.setattr(
        portfolio_service,
        "_get_portfolio_detail_response",
        lambda context, **kwargs: {
            "portfolio": invalid_portfolio,
            "metadata": None,
            "tabs": [],
            "links": {},
        },
    )

    with pytest.raises(portfolio_service.PortfolioDataIntegrityError, match="calendar_uid=NULL"):
        portfolio_service.get_portfolio_detail(uid=str(invalid_portfolio["uid"]))


def test_get_portfolio_detail_returns_409_for_invalid_stored_calendar(monkeypatch) -> None:
    from apps.v1.services.portfolios import PortfolioDataIntegrityError

    def fake_get_portfolio_detail(uid):
        raise PortfolioDataIntegrityError("Stored Portfolio row has calendar_uid=NULL.")

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_detail",
        fake_get_portfolio_detail,
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/portfolio/{uuid.uuid4()}/")

    assert response.status_code == 409
    assert "calendar_uid=NULL" in response.json()["detail"]


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
    portfolio["calendar_uid"] = str(uuid.uuid4())
    portfolio["portfolio_weights_data_node_uid"] = str(uuid.uuid4())
    portfolio["signal_weights_data_node_uid"] = str(uuid.uuid4())
    portfolio["signal_uid"] = "example-signal"
    portfolio["portfolio_data_node_uid"] = str(uuid.uuid4())
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_metadata_row",
        lambda context, unique_identifier: None,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_calendar_row",
        lambda context, uid: {
            "uid": uid,
            "unique_identifier": "EXAMPLE_CALENDAR",
            "display_name": "Example Calendar",
        },
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
    assert {
        "portfolio_weights_data_node_uid",
        "signal_weights_data_node_uid",
        "signal_uid",
        "portfolio_data_node_uid",
    } <= summary_keys
    assert summary["extensions"]["pointers"] == {
        "portfolio_weights_data_node_uid": portfolio["portfolio_weights_data_node_uid"],
        "signal_weights_data_node_uid": portfolio["signal_weights_data_node_uid"],
        "signal_uid": portfolio["signal_uid"],
        "portfolio_data_node_uid": portfolio["portfolio_data_node_uid"],
    }
    assert summary["highlight_fields"][0] == {
        "key": "calendar",
        "label": "Calendar",
        "value": "Example Calendar",
        "kind": "text",
        "icon": "calendar",
        "link_url": f"/api/v1/calendar/{portfolio['calendar_uid']}/",
    }
    inline_fields_by_key = {field["key"]: field for field in summary["inline_fields"]}
    assert inline_fields_by_key["calendar_uid"]["link_url"] == (
        f"/api/v1/calendar/{portfolio['calendar_uid']}/"
    )
    assert inline_fields_by_key["published_index_uid"]["link_url"] == (
        f"/api/v1/index/{portfolio['published_index_uid']}/"
    )
    assert inline_fields_by_key["portfolio_weights_data_node_uid"]["link_url"] == (
        f"/api/v1/portfolio/{portfolio['uid']}/weights/"
        "?order=desc&limit=1&include_asset_detail=true"
    )
    assert inline_fields_by_key["signal_weights_data_node_uid"]["link_url"] == (
        f"/api/v1/portfolio/{portfolio['uid']}/signals_weights/?order=desc&limit=100"
    )
    assert inline_fields_by_key["portfolio_data_node_uid"]["link_url"] == (
        f"/api/v1/portfolio/{portfolio['uid']}/portfolio_values/?order=desc&limit=100"
    )
    assert summary["badges"] == [
        {
            "key": "published_index",
            "label": "Published Index",
            "tone": "info",
            "link_url": f"/api/v1/index/{portfolio['published_index_uid']}/",
        }
    ]
    assert summary["extensions"]["calendar"] == {
        "uid": portfolio["calendar_uid"],
        "label": "Example Calendar",
        "display_name": "Example Calendar",
        "unique_identifier": "EXAMPLE_CALENDAR",
        "detail_url": f"/api/v1/calendar/{portfolio['calendar_uid']}/",
        "dates_url": f"/api/v1/calendar/{portfolio['calendar_uid']}/dates/",
        "sessions_url": f"/api/v1/calendar/{portfolio['calendar_uid']}/sessions/",
        "events_url": f"/api/v1/calendar/{portfolio['calendar_uid']}/events/",
    }
    assert summary["extensions"]["nodes"] == {
        "portfolio_weights": {
            "uid": portfolio["portfolio_weights_data_node_uid"],
            "label": "Portfolio weights",
            "url": (
                f"/api/v1/portfolio/{portfolio['uid']}/weights/"
                "?order=desc&limit=1&include_asset_detail=true"
            ),
        },
        "signal_weights": {
            "uid": portfolio["signal_weights_data_node_uid"],
            "signal_uid": "example-signal",
            "label": "Signal weights",
            "url": f"/api/v1/portfolio/{portfolio['uid']}/signals_weights/?order=desc&limit=100",
        },
        "portfolio_values": {
            "uid": portfolio["portfolio_data_node_uid"],
            "label": "Portfolio values",
            "url": f"/api/v1/portfolio/{portfolio['uid']}/portfolio_values/?order=desc&limit=100",
        },
    }
    assert "links" not in summary


def test_get_portfolio_weights_returns_snapshot(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_get_portfolio_weights(**kwargs):
        captured.update(kwargs)
        return {
            "portfolio_uid": str(portfolio_uid),
            "portfolio_unique_identifier": "example-sleeve",
            "published_index_uid": None,
            "portfolio_identifier": "example-sleeve",
            "weights_date": "2026-06-07T10:30:00Z",
            "resolution_warning": None,
            "weights": [
                {
                    "time_index": "2026-06-07T10:30:00Z",
                    "portfolio_identifier": "example-sleeve",
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
            "published_index_uid": None,
            "portfolio_identifier": "example-sleeve",
            "weights_date": None,
            "resolution_warning": None,
            "weights": [],
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/portfolio/{portfolio_uid}/weights/")

    assert response.status_code == 200
    assert response.json()["weights"] == []
    assert response.json()["portfolio_identifier"] == "example-sleeve"


def test_get_portfolio_signal_weights_frame_returns_tabular_response(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_signal_weights_frame(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ready",
            "columns": ["time_index", "signal_uid", "asset_identifier", "signal_weight"],
            "rows": [
                {
                    "time_index": "2026-06-10T10:30:00Z",
                    "signal_uid": "signal-hash",
                    "asset_identifier": "example-asset-btc",
                    "signal_weight": 0.6,
                }
            ],
            "fields": [
                {
                    "key": "signal_weight",
                    "label": "Signal Weight",
                    "type": "number",
                    "provenance": "backend",
                }
            ],
            "source": {
                "kind": "api",
                "label": "Portfolio signal weights",
                "context": {"portfolio_uid": str(portfolio_uid)},
            },
        }

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_signal_weights_frame",
        fake_signal_weights_frame,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/portfolio/{portfolio_uid}/signals_weights/",
        params={
            "start_date": "2026-06-01T00:00:00Z",
            "end_date": "2026-06-10T23:59:59Z",
            "order": "asc",
            "limit": 25,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["columns"] == ["time_index", "signal_uid", "asset_identifier", "signal_weight"]
    assert body["rows"][0]["signal_weight"] == 0.6
    assert captured == {
        "uid": str(portfolio_uid),
        "start_date": dt.datetime(2026, 6, 1, 0, 0, tzinfo=dt.UTC),
        "end_date": dt.datetime(2026, 6, 10, 23, 59, 59, tzinfo=dt.UTC),
        "order": "asc",
        "limit": 25,
    }


def test_get_portfolio_signal_weights_frame_returns_400_when_unconfigured(monkeypatch) -> None:
    def fake_signal_weights_frame(**kwargs):
        raise ValueError("Portfolio has no signal_weights_data_node_uid configured.")

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_signal_weights_frame",
        fake_signal_weights_frame,
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/portfolio/{uuid.uuid4()}/signals_weights/")

    assert response.status_code == 400
    assert "signal_weights_data_node_uid" in response.json()["detail"]


def test_get_portfolio_values_frame_returns_tabular_response(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_values_frame(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ready",
            "columns": [
                "time_index",
                "portfolio_identifier",
                "close",
                "return",
                "calculated_close",
                "close_time",
            ],
            "rows": [
                {
                    "time_index": "2026-06-10T10:30:00Z",
                    "portfolio_identifier": "example-sleeve",
                    "close": 101.0,
                    "return": 0.01,
                    "calculated_close": 101.0,
                    "close_time": "2026-06-10T10:30:00Z",
                }
            ],
            "fields": [
                {
                    "key": "close",
                    "label": "Close",
                    "type": "number",
                    "provenance": "backend",
                }
            ],
            "source": {
                "kind": "api",
                "label": "Portfolio values",
                "context": {"portfolio_uid": str(portfolio_uid)},
            },
        }

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_values_frame",
        fake_values_frame,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/portfolio/{portfolio_uid}/portfolio_values/",
        params={"limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["rows"][0]["portfolio_identifier"] == "example-sleeve"
    assert body["rows"][0]["close"] == 101.0
    assert captured == {
        "uid": str(portfolio_uid),
        "start_date": None,
        "end_date": None,
        "order": "desc",
        "limit": 10,
    }


def test_get_portfolio_values_frame_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_values_frame",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/portfolio/missing-portfolio/portfolio_values/")

    assert response.status_code == 404
    assert "missing-portfolio" in response.json()["detail"]


def test_delete_portfolio_returns_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.delete_portfolio",
        lambda uid: {
            "detail": "Portfolio deleted.",
            "deleted_count": 1,
            "deleted_weights_count": 3,
            "deleted_values_count": 2,
        },
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/portfolio/{uuid.uuid4()}/")

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Portfolio deleted.",
        "deleted_count": 1,
        "deleted_weights_count": 3,
        "deleted_values_count": 2,
    }


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


def test_delete_portfolio_weights_returns_success(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_delete_portfolio_weights(**kwargs):
        captured.update(kwargs)
        return {
            "detail": "Portfolio weights deleted.",
            "portfolio_uid": str(portfolio_uid),
            "portfolio_identifier": "example-sleeve",
            "weights_date": "2026-06-07T10:30:00Z",
            "deleted_count": 4,
        }

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.delete_portfolio_weights",
        fake_delete_portfolio_weights,
    )

    client = TestClient(app)
    response = client.delete(
        f"/api/v1/portfolio/{portfolio_uid}/weights/",
        params={"weights_date": "2026-06-07T10:30:00Z"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Portfolio weights deleted.",
        "portfolio_uid": str(portfolio_uid),
        "portfolio_identifier": "example-sleeve",
        "weights_date": "2026-06-07T10:30:00Z",
        "deleted_count": 4,
    }
    assert captured == {
        "uid": str(portfolio_uid),
        "weights_date": dt.datetime(2026, 6, 7, 10, 30, tzinfo=dt.UTC),
    }


def test_delete_portfolio_weights_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.delete_portfolio_weights",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.delete("/api/v1/portfolio/missing-portfolio/weights/")

    assert response.status_code == 404
    assert "missing-portfolio" in response.json()["detail"]


def test_bulk_delete_portfolios_reports_failures(monkeypatch) -> None:
    deleted_uid = uuid.uuid4()
    failed_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_bulk_delete_portfolios(**kwargs):
        from apps.v1.schemas.portfolios import PortfolioBulkDeleteResponse

        captured.update(kwargs)
        return PortfolioBulkDeleteResponse.model_validate(
            {
                "detail": "Deleted 1 portfolio; 1 portfolio could not be deleted.",
                "deleted_count": 1,
                "deleted_weights_count": 3,
                "deleted_values_count": 2,
                "failed": [
                    {
                        "uid": str(failed_uid),
                        "reason": "Portfolio is referenced by target positions.",
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.bulk_delete_portfolios",
        fake_bulk_delete_portfolios,
    )
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.preflight_bulk_delete_portfolios",
        lambda **kwargs: {
            "allowed": True,
            "matched_count": len(kwargs["uids"]),
            "blockers": [],
            "warnings": [],
        },
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/portfolio/bulk-delete/",
        json={
            "selection": {
                "mode": "explicit",
                "uids": [str(deleted_uid), str(failed_uid)],
            },
            "options": {},
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "Deleted 1 portfolio; 1 portfolio could not be deleted. "
            f"Failed: {failed_uid}: Portfolio is referenced by target positions."
        )
    }
    assert captured == {"uids": [str(deleted_uid), str(failed_uid)]}


def test_bulk_delete_portfolios_returns_success_when_all_deleted(monkeypatch) -> None:
    deleted_uid = uuid.uuid4()

    def fake_bulk_delete_portfolios(**kwargs):
        from apps.v1.schemas.portfolios import PortfolioBulkDeleteResponse

        return PortfolioBulkDeleteResponse.model_validate(
            {
                "detail": "Deleted 1 portfolio.",
                "deleted_count": 1,
                "deleted_weights_count": 3,
                "deleted_values_count": 2,
                "failed": [],
            }
        )

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.bulk_delete_portfolios",
        fake_bulk_delete_portfolios,
    )
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.preflight_bulk_delete_portfolios",
        lambda **kwargs: {
            "allowed": True,
            "matched_count": len(kwargs["uids"]),
            "blockers": [],
            "warnings": [],
        },
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/portfolio/bulk-delete/",
        json={
            "selection": {"mode": "explicit", "uids": [str(deleted_uid)]},
            "options": {},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Deleted 1 portfolio.",
        "deleted_count": 1,
        "deleted_weights_count": 3,
        "deleted_values_count": 2,
        "failed": [],
    }


def test_bulk_cascade_delete_portfolios_returns_success(monkeypatch) -> None:
    deleted_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_bulk_cascade_delete_portfolios(**kwargs):
        from apps.v1.schemas.portfolios import PortfolioBulkCascadeDeleteResponse

        captured.update(kwargs)
        return PortfolioBulkCascadeDeleteResponse.model_validate(
            {
                "detail": "Cascade deleted 1 portfolio.",
                "deleted_count": 1,
                "deleted_weights_count": 3,
                "deleted_values_count": 2,
                "deleted_target_positions_count": 4,
                "deleted_virtual_funds_count": 1,
                "deleted_virtual_fund_holdings_sets_count": 1,
                "deleted_virtual_fund_holdings_count": 5,
                "failed": [],
            }
        )

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.bulk_cascade_delete_portfolios",
        fake_bulk_cascade_delete_portfolios,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/portfolio/bulk-cascade-delete/",
        json={"uids": [str(deleted_uid)]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Cascade deleted 1 portfolio.",
        "deleted_count": 1,
        "deleted_weights_count": 3,
        "deleted_values_count": 2,
        "deleted_target_positions_count": 4,
        "deleted_virtual_funds_count": 1,
        "deleted_virtual_fund_holdings_sets_count": 1,
        "deleted_virtual_fund_holdings_count": 5,
        "failed": [],
    }
    assert captured == {"uids": [str(deleted_uid)]}


def test_bulk_cascade_delete_portfolios_reports_failures(monkeypatch) -> None:
    failed_uid = uuid.uuid4()

    def fake_bulk_cascade_delete_portfolios(**kwargs):
        from apps.v1.schemas.portfolios import PortfolioBulkCascadeDeleteResponse

        return PortfolioBulkCascadeDeleteResponse.model_validate(
            {
                "detail": "No portfolios were cascade deleted; 1 portfolio deletion failed.",
                "deleted_count": 0,
                "deleted_weights_count": 0,
                "deleted_values_count": 0,
                "deleted_target_positions_count": 0,
                "deleted_virtual_funds_count": 0,
                "deleted_virtual_fund_holdings_sets_count": 0,
                "deleted_virtual_fund_holdings_count": 0,
                "failed": [
                    {
                        "uid": str(failed_uid),
                        "reason": "Portfolio was not found.",
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.bulk_cascade_delete_portfolios",
        fake_bulk_cascade_delete_portfolios,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/portfolio/bulk-cascade-delete/",
        json={"uids": [str(failed_uid)]},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "No portfolios were cascade deleted; 1 portfolio deletion failed. "
            f"Failed: {failed_uid}: Portfolio was not found."
        )
    }


def test_bulk_delete_portfolios_returns_409_with_not_found_reason(monkeypatch) -> None:
    failed_uid = uuid.uuid4()

    def fake_bulk_delete_portfolios(**kwargs):
        from apps.v1.schemas.portfolios import PortfolioBulkDeleteResponse

        return PortfolioBulkDeleteResponse.model_validate(
            {
                "detail": "No portfolios were deleted; 1 portfolio deletion failed.",
                "deleted_count": 0,
                "deleted_weights_count": 0,
                "deleted_values_count": 0,
                "failed": [
                    {
                        "uid": str(failed_uid),
                        "reason": "Portfolio was not found.",
                    }
                ],
            }
        )

    monkeypatch.setattr(
        "apps.v1.routers.portfolios.bulk_delete_portfolios",
        fake_bulk_delete_portfolios,
    )
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.preflight_bulk_delete_portfolios",
        lambda **kwargs: {
            "allowed": True,
            "matched_count": len(kwargs["uids"]),
            "blockers": [],
            "warnings": [],
        },
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/portfolio/bulk-delete/",
        json={
            "selection": {"mode": "explicit", "uids": [str(failed_uid)]},
            "options": {},
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "No portfolios were deleted; 1 portfolio deletion failed. "
            f"Failed: {failed_uid}: Portfolio was not found."
        )
    }


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
            "published_index_uid": None,
            "portfolio_identifier": "example-sleeve",
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


def test_portfolio_signal_weights_frame_service_maps_source_frame(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr("apps.v1.services.portfolios._get_runtime", lambda: runtime)

    def fake_signal_weights_frame(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "status": "ready",
            "columns": ["time_index", "signal_uid", "asset_identifier", "signal_weight"],
            "rows": [],
            "fields": [],
            "source": {
                "kind": "api",
                "label": "Portfolio signal weights",
                "context": {"portfolio_uid": str(portfolio_uid)},
            },
        }

    monkeypatch.setattr(
        "apps.v1.services.portfolios._get_portfolio_signal_weights_frame_response",
        fake_signal_weights_frame,
    )

    from apps.v1.services.portfolios import get_portfolio_signal_weights_frame

    response = get_portfolio_signal_weights_frame(uid=str(portfolio_uid), limit=12)

    assert response is not None
    assert response.model_dump(mode="json")["status"] == "ready"
    assert captured["context"] is runtime.context
    assert captured["uid"] == str(portfolio_uid)
    assert captured["limit"] == 12


def test_portfolio_values_frame_service_maps_source_frame(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr("apps.v1.services.portfolios._get_runtime", lambda: runtime)

    def fake_values_frame(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "status": "ready",
            "columns": ["time_index", "portfolio_identifier", "close"],
            "rows": [],
            "fields": [],
            "source": {
                "kind": "api",
                "label": "Portfolio values",
                "context": {"portfolio_uid": str(portfolio_uid)},
            },
        }

    monkeypatch.setattr(
        "apps.v1.services.portfolios._get_portfolio_values_frame_response",
        fake_values_frame,
    )

    from apps.v1.services.portfolios import get_portfolio_values_frame

    response = get_portfolio_values_frame(uid=str(portfolio_uid), limit=8)

    assert response is not None
    assert response.model_dump(mode="json")["status"] == "ready"
    assert captured["context"] is runtime.context
    assert captured["uid"] == str(portfolio_uid)
    assert captured["limit"] == 8


def test_delete_portfolio_service_maps_source_response(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr("apps.v1.services.portfolios._get_runtime", lambda: runtime)

    def fake_delete_portfolio_record(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "detail": "Portfolio deleted.",
            "deleted_count": 1,
            "deleted_weights_count": 5,
            "deleted_values_count": 6,
        }

    monkeypatch.setattr(
        "apps.v1.services.portfolios._delete_portfolio_record",
        fake_delete_portfolio_record,
    )

    from apps.v1.services.portfolios import delete_portfolio

    response = delete_portfolio(uid=str(portfolio_uid))

    assert response is not None
    assert response.model_dump() == {
        "detail": "Portfolio deleted.",
        "deleted_count": 1,
        "deleted_weights_count": 5,
        "deleted_values_count": 6,
    }
    assert captured["context"] is runtime.context
    assert captured["uid"] == str(portfolio_uid)


def test_cascade_delete_portfolio_service_maps_source_response(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr("apps.v1.services.portfolios._get_runtime", lambda: runtime)

    def fake_cascade_delete_portfolio_record(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "detail": "Portfolio cascade deleted.",
            "deleted_count": 1,
            "deleted_weights_count": 5,
            "deleted_values_count": 6,
            "deleted_target_positions_count": 7,
            "deleted_virtual_funds_count": 2,
            "deleted_virtual_fund_holdings_sets_count": 3,
            "deleted_virtual_fund_holdings_count": 8,
        }

    monkeypatch.setattr(
        "apps.v1.services.portfolios._cascade_delete_portfolio_record",
        fake_cascade_delete_portfolio_record,
    )

    from apps.v1.services.portfolios import cascade_delete_portfolio

    response = cascade_delete_portfolio(uid=str(portfolio_uid))

    assert response is not None
    assert response.model_dump() == {
        "detail": "Portfolio cascade deleted.",
        "deleted_count": 1,
        "deleted_weights_count": 5,
        "deleted_values_count": 6,
        "deleted_target_positions_count": 7,
        "deleted_virtual_funds_count": 2,
        "deleted_virtual_fund_holdings_sets_count": 3,
        "deleted_virtual_fund_holdings_count": 8,
    }
    assert captured["context"] is runtime.context
    assert captured["uid"] == str(portfolio_uid)


def test_delete_portfolio_weights_service_maps_source_response(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    weights_date = dt.datetime(2026, 6, 7, 10, 30, tzinfo=dt.UTC)
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr("apps.v1.services.portfolios._get_runtime", lambda: runtime)

    def fake_delete_portfolio_weights(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "detail": "Portfolio weights deleted.",
            "portfolio_uid": str(portfolio_uid),
            "portfolio_identifier": "example-sleeve",
            "weights_date": weights_date,
            "deleted_count": 2,
        }

    monkeypatch.setattr(
        "apps.v1.services.portfolios._delete_portfolio_weights",
        fake_delete_portfolio_weights,
    )

    from apps.v1.services.portfolios import delete_portfolio_weights

    response = delete_portfolio_weights(uid=str(portfolio_uid), weights_date=weights_date)

    assert response is not None
    assert response.model_dump(mode="json") == {
        "detail": "Portfolio weights deleted.",
        "portfolio_uid": str(portfolio_uid),
        "portfolio_identifier": "example-sleeve",
        "weights_date": "2026-06-07T10:30:00Z",
        "deleted_count": 2,
    }
    assert captured["context"] is runtime.context
    assert captured["uid"] == str(portfolio_uid)
    assert captured["weights_date"] == weights_date


def test_public_delete_portfolio_blocks_virtual_fund_references(monkeypatch) -> None:
    portfolio = _portfolio_row()
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._virtual_fund_reference_count",
        lambda context, portfolio_uid: 1,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._target_position_reference_count",
        lambda context, portfolio_uid: 0,
    )

    from msm_portfolios.services.public_api import (
        PortfolioDeleteConflictError,
        delete_portfolio_record,
    )

    with pytest.raises(PortfolioDeleteConflictError, match="virtual funds"):
        delete_portfolio_record(object(), uid=str(portfolio["uid"]))


def test_public_delete_portfolio_blocks_target_position_references(monkeypatch) -> None:
    portfolio = _portfolio_row()
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._virtual_fund_reference_count",
        lambda context, portfolio_uid: 0,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._target_position_reference_count",
        lambda context, portfolio_uid: 3,
    )

    from msm_portfolios.services.public_api import (
        PortfolioDeleteConflictError,
        delete_portfolio_record,
    )

    with pytest.raises(
        PortfolioDeleteConflictError,
        match="TargetPositionsStorage\\.portfolio_uid",
    ):
        delete_portfolio_record(object(), uid=str(portfolio["uid"]))


def test_public_delete_portfolio_reports_deleted_weights(monkeypatch) -> None:
    portfolio = _portfolio_row()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._raise_if_portfolio_delete_is_blocked",
        lambda context, **kwargs: captured.update({"blocked_check": kwargs}),
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._delete_portfolio_weight_rows",
        lambda context, **kwargs: captured.update({"delete_weights": kwargs}) or 4,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._delete_portfolio_value_rows",
        lambda context, **kwargs: captured.update({"delete_values": kwargs}) or 5,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._compile_delete_portfolio_operation",
        lambda context, **kwargs: captured.update({"compile": kwargs}) or "delete-op",
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api.execute_markets_operation",
        lambda operation, context: {
            "rows": [
                {
                    "uid": portfolio["uid"],
                }
            ]
        },
    )

    from msm_portfolios.services.public_api import delete_portfolio_record

    response = delete_portfolio_record(object(), uid=str(portfolio["uid"]))

    assert response == {
        "detail": "Portfolio deleted.",
        "deleted_count": 1,
        "deleted_weights_count": 4,
        "deleted_values_count": 5,
    }
    assert captured["compile"]["portfolio_uid"] == uuid.UUID(str(portfolio["uid"]))
    assert captured["delete_weights"] == {
        "portfolio_identifier": "example-sleeve",
        "after_date": None,
    }
    assert captured["delete_values"] == {
        "portfolio_identifier": "example-sleeve",
        "after_date": None,
    }


def test_public_portfolio_values_frame_queries_storage_by_portfolio_identifier(monkeypatch) -> None:
    portfolio = _portfolio_row()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )

    def fake_compile(statement, **kwargs):
        captured["statement"] = statement
        captured.update(kwargs)
        return statement

    def fake_execute(operation, context):
        # ADR 0047: the read first resolves the portfolio's dataset instance from the
        # Markets catalog; no row means the core PortfoliosStorage table.
        if "portfoliodatasetavailability" in str(operation):
            return {"rows": []}
        return {
            "rows": [
                {
                    "time_index": dt.datetime(2026, 6, 10, 10, 30, tzinfo=dt.UTC),
                    "portfolio_identifier": "example-sleeve",
                    "close": 101.0,
                    "return_": 0.01,
                    "calculated_close": 101.0,
                    "close_time": dt.datetime(2026, 6, 10, 10, 30, tzinfo=dt.UTC),
                }
            ]
        }

    monkeypatch.setattr(
        "msm_portfolios.services.portfolio_reads.compile_markets_statement",
        fake_compile,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.portfolio_reads.execute_markets_operation",
        fake_execute,
    )

    from msm_portfolios.services.public_api import get_portfolio_values_frame_response

    response = get_portfolio_values_frame_response(
        object(),
        uid=str(portfolio["uid"]),
        limit=1,
    )

    assert response is not None
    assert response["columns"] == [
        "time_index",
        "portfolio_identifier",
        "close",
        "return",
        "calculated_close",
        "close_time",
    ]
    assert response["rows"][0]["return"] == 0.01
    assert response["source"]["context"]["portfolio_identifier"] == "example-sleeve"
    assert captured["operation"] == "select"


def test_public_signal_weights_frame_uses_portfolio_signal_uid(monkeypatch) -> None:
    portfolio = _portfolio_row()
    portfolio["signal_weights_data_node_uid"] = str(uuid.uuid4())
    portfolio["signal_uid"] = "portfolio-signal"
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )

    def fake_compile(statement, **kwargs):
        captured["statement"] = statement
        captured.update(kwargs)
        return statement

    def fake_execute(operation, context):
        # No catalog row and no SignalMetadata.meta_table_uid: the core table is read.
        sql = str(operation)
        if "portfoliodatasetavailability" in sql:
            return {"rows": []}
        if "signalweightsts" not in sql:
            return {"rows": [{"meta_table_uid": None}]}
        return {
            "rows": [
                {
                    "time_index": dt.datetime(2026, 6, 10, 10, 30, tzinfo=dt.UTC),
                    "signal_uid": "portfolio-signal",
                    "asset_identifier": "example-asset-btc",
                    "signal_weight": 0.6,
                }
            ]
        }

    monkeypatch.setattr(
        "msm_portfolios.services.portfolio_reads.compile_markets_statement",
        fake_compile,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.portfolio_reads.execute_markets_operation",
        fake_execute,
    )

    from msm_portfolios.services.public_api import get_portfolio_signal_weights_frame_response

    response = get_portfolio_signal_weights_frame_response(
        object(),
        uid=str(portfolio["uid"]),
        limit=1,
    )

    assert response is not None
    assert response["rows"][0] == {
        "time_index": dt.datetime(2026, 6, 10, 10, 30, tzinfo=dt.UTC),
        "signal_uid": "portfolio-signal",
        "asset_identifier": "example-asset-btc",
        "signal_weight": 0.6,
    }
    assert response["source"]["context"]["signal_uid"] == "portfolio-signal"
    assert captured["operation"] == "select"


def test_public_signal_weights_frame_requires_portfolio_signal_uid(monkeypatch) -> None:
    portfolio = _portfolio_row()
    portfolio["signal_weights_data_node_uid"] = str(uuid.uuid4())

    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )

    from msm_portfolios.services.public_api import get_portfolio_signal_weights_frame_response

    with pytest.raises(ValueError, match="Portfolio has no signal_uid configured"):
        get_portfolio_signal_weights_frame_response(object(), uid=str(portfolio["uid"]))


def test_public_signal_weights_frame_requires_signal_data_node(monkeypatch) -> None:
    portfolio = _portfolio_row()
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )

    from msm_portfolios.services.public_api import get_portfolio_signal_weights_frame_response

    with pytest.raises(ValueError, match="signal_weights_data_node_uid"):
        get_portfolio_signal_weights_frame_response(object(), uid=str(portfolio["uid"]))


def test_public_delete_portfolio_operation_deletes_identity_only(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_compile(statement, **kwargs):
        captured["statement"] = statement
        captured.update(kwargs)
        return "compiled-delete-op"

    monkeypatch.setattr(
        "msm_portfolios.services.public_api.compile_markets_statement",
        fake_compile,
    )

    from msm_portfolios.services.public_api import _compile_delete_portfolio_operation

    operation = _compile_delete_portfolio_operation(
        object(),
        portfolio_uid=portfolio_uid,
    )

    statement_text = str(captured["statement"]).lower()
    assert operation == "compiled-delete-op"
    assert captured["operation"] == "delete"
    assert "portfolio_scope" in statement_text
    assert "deleted_weights" not in statement_text
    assert "deleted_values" not in statement_text
    assert "delete from" in statement_text


def test_public_cascade_delete_portfolio_operation_deletes_dependents(monkeypatch) -> None:
    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_compile(statement, **kwargs):
        captured["statement"] = statement
        captured.update(kwargs)
        return "compiled-cascade-delete-op"

    monkeypatch.setattr(
        "msm_portfolios.services.public_api.compile_markets_statement",
        fake_compile,
    )

    from msm_portfolios.services.public_api import _compile_cascade_delete_portfolio_operation

    operation = _compile_cascade_delete_portfolio_operation(
        object(),
        portfolio_uid=portfolio_uid,
    )

    statement_text = str(captured["statement"]).lower()
    assert operation == "compiled-cascade-delete-op"
    assert captured["operation"] == "delete"
    assert "deleted_virtual_funds" in statement_text
    assert "deleted_virtual_fund_holdings_sets" in statement_text
    assert "deleted_target_positions" not in statement_text
    assert "deleted_virtual_fund_holdings as" not in statement_text
    assert "deleted_weights" not in statement_text
    assert "deleted_values" not in statement_text


def test_public_delete_portfolio_weights_uses_portfolio_identifier(monkeypatch) -> None:
    portfolio = _portfolio_row()
    weights_date = dt.datetime(2026, 6, 7, 10, 30, tzinfo=dt.UTC)
    captured: dict[str, object] = {}

    class FakeTimeIndexMetaTable:
        def delete_after_date(self, after_date, *, dimension_filters, timeout=None):
            captured["delete_after_date"] = {
                "after_date": after_date,
                "dimension_filters": dimension_filters,
                "timeout": timeout,
            }
            return {"deleted_count": 2}

    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: portfolio,
    )
    monkeypatch.setattr(
        "msm_portfolios.data_nodes.portfolios.storage.PortfolioWeightsStorage.get_time_index_meta_table",
        classmethod(lambda cls: FakeTimeIndexMetaTable()),
    )

    from msm_portfolios.services.public_api import delete_portfolio_weights

    response = delete_portfolio_weights(
        SimpleNamespace(timeout=30),
        uid=str(portfolio["uid"]),
        weights_date=weights_date,
    )

    assert response == {
        "detail": "Portfolio weights deleted.",
        "portfolio_uid": str(portfolio["uid"]),
        "portfolio_identifier": "example-sleeve",
        "weights_date": weights_date,
        "deleted_count": 2,
    }
    assert captured["delete_after_date"] == {
        "after_date": weights_date,
        "dimension_filters": {"portfolio_identifier": ["example-sleeve"]},
        "timeout": 30,
    }


# --- ADR 0047: multi-portfolio frames and the dataset catalog ---------------------------------


def _catalog_state(portfolio_uid: uuid.UUID) -> dict[str, object]:
    return {
        "portfolio_uid": str(portfolio_uid),
        "portfolio_identifier": "equity-tracker",
        "values_meta_table_uid": "provider-values",
        "weights_meta_table_uid": "provider-weights",
        "signal_meta_table_uid": None,
        "population_state": "populated",
        "row_count": 12,
        "earliest_time_index": "2026-01-01T00:00:00Z",
        "latest_time_index": "2026-01-12T00:00:00Z",
        "reconciled_at": "2026-01-12T01:00:00Z",
        "error": None,
    }


def test_multi_portfolio_values_frame_route_groups_uids_into_one_frame(monkeypatch) -> None:
    from msm.api.http import build_tabular_frame

    captured: dict[str, object] = {}
    first, second = uuid.uuid4(), uuid.uuid4()

    def fake_frame(**kwargs):
        captured.update(kwargs)
        return build_tabular_frame(
            rows=[{"time_index": "2026-01-02T00:00:00+00:00", "portfolio_identifier": "a", "close": 1.0}]
        )

    monkeypatch.setattr("apps.v1.routers.portfolios.get_portfolios_values_frame", fake_frame)

    response = TestClient(app).get(
        "/api/v1/portfolio/values/",
        params=[("portfolio_uid__in", f"{first},{second}"), ("order", "asc"), ("limit", 10)],
    )

    assert response.status_code == 200
    assert response.json()["rows"][0]["portfolio_identifier"] == "a"
    assert captured == {
        "uids": [f"{first},{second}"],
        "start_date": None,
        "end_date": None,
        "order": "asc",
        "limit": 10,
    }
    operation = app.openapi()["paths"]["/api/v1/portfolio/values/"]["get"]
    assert operation["operationId"] == "getPortfoliosValuesFrame"
    assert operation["x-ui-contract"] == "core.tabular_frame@v1"

    def unknown(**_kwargs):
        raise LookupError("Portfolios were not found: ['x']")

    monkeypatch.setattr("apps.v1.routers.portfolios.get_portfolios_values_frame", unknown)
    assert TestClient(app).get("/api/v1/portfolio/values/", params={"portfolio_uid__in": str(first)}).status_code == 404


def test_multi_portfolio_weights_frame_route_passes_snapshot_selection(monkeypatch) -> None:
    from msm.api.http import build_tabular_frame

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolios_weights_frame",
        lambda **kwargs: captured.update(kwargs) or build_tabular_frame(rows=[]),
    )
    portfolio_uid = uuid.uuid4()

    response = TestClient(app).get(
        "/api/v1/portfolio/weights/",
        params={
            "portfolio_uid__in": str(portfolio_uid),
            "weights_date": "2026-01-05T00:00:00Z",
            "as_of": "false",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "uids": [str(portfolio_uid)],
        "weights_date": dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        "as_of": False,
    }


def test_multi_portfolio_frame_services_read_through_the_catalog_aware_reads(monkeypatch) -> None:
    from apps.v1.services import portfolios as portfolio_service

    first, second = _portfolio_row(), {**_portfolio_row(), "unique_identifier": "income-fund"}
    monkeypatch.setattr(portfolio_service, "_get_runtime", lambda: SimpleNamespace(context="ctx"))
    monkeypatch.setattr(
        portfolio_service,
        "get_portfolios_by_uids",
        lambda *, uids: [portfolio_service._validate_portfolio_row(row) for row in (first, second) if row["uid"] in uids],
    )
    values_calls: list[tuple] = []
    weights_calls: list[tuple] = []
    now = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)

    def fake_values(identifiers, **kwargs):
        values_calls.append((identifiers, kwargs))
        return [
            {"portfolio_uid": uuid.UUID(first["uid"]), "portfolio_identifier": "example-sleeve",
             "time_index": now - dt.timedelta(days=1), "close": 1.0, "return": 0.0},
            {"portfolio_uid": uuid.UUID(second["uid"]), "portfolio_identifier": "income-fund",
             "time_index": now, "close": 2.0, "return": 0.1},
        ]

    def fake_weights(identifiers, **kwargs):
        weights_calls.append((identifiers, kwargs))
        return [{"portfolio_uid": first["uid"], "portfolio_identifier": "example-sleeve",
                 "time_index": now, "asset_identifier": "a", "weight": 1.0}]

    monkeypatch.setattr(portfolio_service, "_portfolio_values", fake_values)
    monkeypatch.setattr(portfolio_service, "_latest_portfolio_weights", fake_weights)

    values = portfolio_service.get_portfolios_values_frame(
        uids=[first["uid"], second["uid"]], order="desc", limit=1
    )
    weights = portfolio_service.get_portfolios_weights_frame(uids=[first["uid"]], weights_date=now)

    # One read for both portfolios, through the catalog-aware service with the API runtime context.
    assert values_calls == [(["example-sleeve", "income-fund"], {"start": None, "end": None, "repository_context": "ctx"})]
    assert [row["portfolio_identifier"] for row in values.rows] == ["income-fund"]
    assert values.rows[0]["portfolio_uid"] == second["uid"]
    assert values.rows[0]["time_index"] == now.isoformat()
    assert values.source.context["portfolio_uids"] == [first["uid"], second["uid"]]
    assert weights_calls == [(["example-sleeve"], {"weights_date": now, "as_of": True, "repository_context": "ctx"})]
    assert weights.rows[0]["asset_identifier"] == "a"
    with pytest.raises(LookupError, match="not found"):
        portfolio_service.get_portfolios_values_frame(uids=[str(uuid.uuid4())])


def test_register_portfolio_datasets_route_returns_catalog_state(monkeypatch) -> None:
    from apps.v1.schemas.portfolios import PortfolioDatasetRegistrationRequest, PortfolioDatasetState

    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_register(*, uid, payload):
        captured.update(uid=uid, payload=payload)
        return PortfolioDatasetState.model_validate(_catalog_state(portfolio_uid))

    monkeypatch.setattr("apps.v1.routers.portfolios.register_portfolio_dataset_catalog", fake_register)

    response = TestClient(app).post(
        f"/api/v1/portfolio/{portfolio_uid}/datasets/",
        json={"values_meta_table_uid": "provider-values", "weights_meta_table_uid": "provider-weights"},
    )

    assert response.status_code == 201
    assert response.json()["population_state"] == "populated"
    assert response.json()["values_meta_table_uid"] == "provider-values"
    assert captured["uid"] == str(portfolio_uid)
    assert isinstance(captured["payload"], PortfolioDatasetRegistrationRequest)
    assert captured["payload"].reconcile is True
    assert captured["payload"].signal_meta_table_uid is None

    def not_visible(**_kwargs):
        raise LookupError("PortfoliosTS instance 'x' is not a visible TimeIndexMetaTable")

    monkeypatch.setattr("apps.v1.routers.portfolios.register_portfolio_dataset_catalog", not_visible)
    assert TestClient(app).post(
        f"/api/v1/portfolio/{portfolio_uid}/datasets/", json={"values_meta_table_uid": "x"}
    ).status_code == 404

    def incompatible(**_kwargs):
        raise ValueError("missing contract columns ['close']")

    monkeypatch.setattr("apps.v1.routers.portfolios.register_portfolio_dataset_catalog", incompatible)
    assert TestClient(app).post(
        f"/api/v1/portfolio/{portfolio_uid}/datasets/", json={"values_meta_table_uid": "x"}
    ).status_code == 400


def test_get_portfolio_datasets_route_returns_row_or_null(monkeypatch) -> None:
    from apps.v1.schemas.portfolios import PortfolioDatasetState

    portfolio_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.get_portfolio_dataset_state",
        lambda *, uid: PortfolioDatasetState.model_validate(_catalog_state(portfolio_uid)),
    )
    assert TestClient(app).get(f"/api/v1/portfolio/{portfolio_uid}/datasets/").json()["row_count"] == 12

    monkeypatch.setattr("apps.v1.routers.portfolios.get_portfolio_dataset_state", lambda *, uid: None)
    response = TestClient(app).get(f"/api/v1/portfolio/{portfolio_uid}/datasets/")
    assert response.status_code == 200 and response.json() is None

    def missing(*, uid):
        raise LookupError(f"Portfolio {uid!r} was not found.")

    monkeypatch.setattr("apps.v1.routers.portfolios.get_portfolio_dataset_state", missing)
    assert TestClient(app).get(f"/api/v1/portfolio/{portfolio_uid}/datasets/").status_code == 404


def test_reconcile_portfolio_datasets_route_returns_states_and_skipped(monkeypatch) -> None:
    from apps.v1.schemas.portfolios import (
        PortfolioDatasetReconcileRequest,
        PortfolioDatasetReconciliationResult,
        PortfolioDatasetState,
    )

    portfolio_uid, skipped_uid = uuid.uuid4(), uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_reconcile(*, payload):
        captured["payload"] = payload
        return PortfolioDatasetReconciliationResult(
            portfolio_uids=(portfolio_uid, skipped_uid),
            states=(PortfolioDatasetState.model_validate(_catalog_state(portfolio_uid)),),
            skipped_portfolio_uids=(skipped_uid,),
        )

    monkeypatch.setattr("apps.v1.routers.portfolios.reconcile_portfolio_dataset_catalog", fake_reconcile)

    response = TestClient(app).post(
        "/api/v1/portfolio/datasets/reconcile/",
        json={"portfolio_uids": [str(portfolio_uid)], "portfolio_identifiers": ["legacy"]},
    )

    assert response.status_code == 200
    assert response.json()["skipped_portfolio_uids"] == [str(skipped_uid)]
    assert response.json()["states"][0]["population_state"] == "populated"
    assert isinstance(captured["payload"], PortfolioDatasetReconcileRequest)
    assert captured["payload"].portfolio_identifiers == ["legacy"]

    def no_selectors(**_kwargs):
        raise ValueError("requires explicit portfolio UIDs or identifiers")

    monkeypatch.setattr("apps.v1.routers.portfolios.reconcile_portfolio_dataset_catalog", no_selectors)
    assert TestClient(app).post("/api/v1/portfolio/datasets/reconcile/", json={}).status_code == 400


def test_portfolio_dataset_services_delegate_to_the_catalog_services(monkeypatch) -> None:
    from apps.v1.schemas.portfolios import (
        PortfolioDatasetReconcileRequest,
        PortfolioDatasetRegistrationRequest,
        PortfolioDatasetState,
    )
    from apps.v1.services import portfolios as portfolio_service
    from msm_portfolios.services import portfolio_datasets

    portfolio_uid = uuid.uuid4()
    state = PortfolioDatasetState.model_validate(_catalog_state(portfolio_uid))
    calls: dict[str, object] = {}
    monkeypatch.setattr(portfolio_service, "_get_runtime", lambda: SimpleNamespace(context="ctx"))
    monkeypatch.setattr(
        portfolio_datasets,
        "register_portfolio_datasets",
        lambda context, registration, *, reconcile=True, **_kwargs: calls.update(register=(context, registration, reconcile)) or state,
    )
    monkeypatch.setattr(
        portfolio_datasets,
        "reconcile_portfolio_dataset_availability",
        lambda context, *, portfolio_uids, portfolio_identifiers: calls.update(reconcile=(context, portfolio_uids, portfolio_identifiers)) or "result",
    )
    monkeypatch.setattr(
        portfolio_datasets,
        "list_portfolio_dataset_states",
        lambda context, *, portfolio_uids: calls.update(list=(context, portfolio_uids)) or (state,),
    )
    monkeypatch.setattr(portfolio_service, "get_portfolio_detail", lambda *, uid: object() if uid == str(portfolio_uid) else None)
    import msm_portfolios.services as services_package

    for name in ("register_portfolio_datasets", "reconcile_portfolio_dataset_availability", "list_portfolio_dataset_states"):
        monkeypatch.setattr(services_package, name, getattr(portfolio_datasets, name), raising=False)

    registered = portfolio_service.register_portfolio_dataset_catalog(
        uid=str(portfolio_uid),
        payload=PortfolioDatasetRegistrationRequest(values_meta_table_uid="v", reconcile=False),
    )
    reconciled = portfolio_service.reconcile_portfolio_dataset_catalog(
        payload=PortfolioDatasetReconcileRequest(portfolio_uids=[str(portfolio_uid)])
    )
    listed = portfolio_service.get_portfolio_dataset_state(uid=str(portfolio_uid))

    assert registered is state and listed is state and reconciled == "result"
    assert calls["register"] == (
        "ctx",
        {"portfolio_uid": portfolio_uid, "values_meta_table_uid": "v", "weights_meta_table_uid": None, "signal_meta_table_uid": None},
        False,
    )
    assert calls["reconcile"] == ("ctx", [str(portfolio_uid)], [])
    assert calls["list"] == ("ctx", [str(portfolio_uid)])
    with pytest.raises(LookupError):
        portfolio_service.get_portfolio_dataset_state(uid=str(uuid.uuid4()))
    assert portfolio_service.register_portfolio_dataset_catalog.__registry_write__ == ("portfolio", "register:datasets")
