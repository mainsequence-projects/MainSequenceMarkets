from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.schemas.portfolio_signals import (
    PortfolioSignalDeleteResponse,
    PortfolioSignalListResponse,
    PortfolioSignalWeightsDeleteResponse,
    SignalMetadata,
)


def _signal_row(
    *,
    uid: uuid.UUID | None = None,
    signal_uid: str = "example-signal",
) -> SignalMetadata:
    return SignalMetadata(
        uid=uid or uuid.uuid4(),
        signal_uid=signal_uid,
        signal_description="Example signal",
    )


def test_list_portfolio_signals_returns_paginated_metadata(monkeypatch) -> None:
    row = _signal_row()
    captured: dict[str, object] = {}

    def fake_list_portfolio_signals(**kwargs):
        captured.update(kwargs)
        return PortfolioSignalListResponse(count=2, results=[row])

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_signals.list_portfolio_signals",
        fake_list_portfolio_signals,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/portfolio-signal/",
        params={
            "search": "example",
            "signal_uid": "example-signal",
            "limit": 1,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 2,
        "next": (
            "http://testserver/api/v1/portfolio-signal/?search=example"
            "&signal_uid=example-signal&limit=1&offset=1"
        ),
        "previous": None,
        "results": [
            {
                "uid": str(row.uid),
                "signal_uid": "example-signal",
                "signal_description": "Example signal",
            }
        ],
    }
    assert captured == {
        "search": "example",
        "signal_uid": "example-signal",
        "limit": 1,
        "offset": 0,
    }


def test_get_portfolio_signal_returns_metadata(monkeypatch) -> None:
    row = _signal_row()
    monkeypatch.setattr(
        "apps.v1.routers.portfolio_signals.get_portfolio_signal",
        lambda uid: row,
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/portfolio-signal/{row.uid}/")

    assert response.status_code == 200
    assert response.json() == {
        "uid": str(row.uid),
        "signal_uid": "example-signal",
        "signal_description": "Example signal",
    }


def test_get_portfolio_signal_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.portfolio_signals.get_portfolio_signal",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/portfolio-signal/{uuid.uuid4()}/")

    assert response.status_code == 404


def test_create_portfolio_signal_returns_metadata(monkeypatch) -> None:
    row = _signal_row()
    captured: dict[str, object] = {}

    def fake_create_portfolio_signal(*, payload):
        captured["payload"] = payload
        return row

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_signals.create_portfolio_signal",
        fake_create_portfolio_signal,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/portfolio-signal/",
        json={
            "signal_uid": "example-signal",
            "signal_description": "Example signal",
        },
    )

    assert response.status_code == 200
    assert response.json()["signal_uid"] == "example-signal"
    assert captured["payload"].signal_uid == "example-signal"


def test_update_portfolio_signal_returns_metadata(monkeypatch) -> None:
    row = _signal_row()
    captured: dict[str, object] = {}

    def fake_update_portfolio_signal(**kwargs):
        captured.update(kwargs)
        return row

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_signals.update_portfolio_signal",
        fake_update_portfolio_signal,
    )

    client = TestClient(app)
    response = client.patch(
        f"/api/v1/portfolio-signal/{row.uid}/",
        json={"signal_description": "Updated signal"},
    )

    assert response.status_code == 200
    assert response.json()["uid"] == str(row.uid)
    assert captured["uid"] == str(row.uid)
    assert captured["payload"].signal_description == "Updated signal"


def test_delete_portfolio_signal_deletes_metadata_and_weights(monkeypatch) -> None:
    signal_uid = uuid.uuid4()

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_signals.delete_portfolio_signal",
        lambda uid: PortfolioSignalDeleteResponse(
            detail="Signal metadata deleted.",
            signal_metadata_uid=uid,
            signal_uid="example-signal",
            deleted_count=1,
            deleted_weights_count=3,
        ),
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/portfolio-signal/{signal_uid}/")

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Signal metadata deleted.",
        "signal_metadata_uid": str(signal_uid),
        "signal_uid": "example-signal",
        "deleted_count": 1,
        "deleted_weights_count": 3,
    }


def test_delete_portfolio_signal_returns_409_on_conflict(monkeypatch) -> None:
    from apps.v1.services.portfolio_signals import PortfolioSignalDeleteConflictError

    def fake_delete_portfolio_signal(**_kwargs):
        raise PortfolioSignalDeleteConflictError("blocked signal delete")

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_signals.delete_portfolio_signal",
        fake_delete_portfolio_signal,
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/portfolio-signal/{uuid.uuid4()}/")

    assert response.status_code == 409
    assert response.json() == {"detail": "blocked signal delete"}


def test_delete_portfolio_signal_weights_returns_deleted_count(monkeypatch) -> None:
    signal_uid = uuid.uuid4()
    weights_date = dt.datetime(2026, 6, 10, 10, 30, tzinfo=dt.UTC)
    captured: dict[str, object] = {}

    def fake_delete_portfolio_signal_weights(**kwargs):
        captured.update(kwargs)
        return PortfolioSignalWeightsDeleteResponse(
            detail="Signal weights deleted.",
            signal_metadata_uid=kwargs["uid"],
            signal_uid="example-signal",
            weights_date=kwargs["weights_date"],
            deleted_count=2,
        )

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_signals.delete_portfolio_signal_weights",
        fake_delete_portfolio_signal_weights,
    )

    client = TestClient(app)
    response = client.delete(
        f"/api/v1/portfolio-signal/{signal_uid}/weights/",
        params={"weights_date": weights_date.isoformat()},
    )

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Signal weights deleted.",
        "signal_metadata_uid": str(signal_uid),
        "signal_uid": "example-signal",
        "weights_date": "2026-06-10T10:30:00Z",
        "deleted_count": 2,
    }
    assert captured == {
        "uid": str(signal_uid),
        "weights_date": weights_date,
    }


def test_public_delete_signal_metadata_reports_deleted_weights(monkeypatch) -> None:
    signal_uid = uuid.uuid4()
    signal = {
        "uid": signal_uid,
        "signal_uid": "example-signal",
        "signal_description": "Example signal",
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_signal_metadata_row",
        lambda context, uid: signal,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._compile_delete_signal_metadata_with_weights_operation",
        lambda context, **kwargs: captured.update({"compile": kwargs}) or "delete-signal-op",
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api.execute_markets_operation",
        lambda operation, context: {"rows": [{"deleted_weights_count": 4}]},
    )

    from msm_portfolios.services.public_api import delete_signal_metadata_record

    response = delete_signal_metadata_record(object(), uid=str(signal_uid))

    assert response == {
        "detail": "Signal metadata deleted.",
        "signal_metadata_uid": str(signal_uid),
        "signal_uid": "example-signal",
        "deleted_count": 1,
        "deleted_weights_count": 4,
    }
    assert captured["compile"] == {"signal_metadata_uid": signal_uid}


def test_public_delete_signal_weights_uses_signal_uid(monkeypatch) -> None:
    signal_uid = uuid.uuid4()
    weights_date = dt.datetime(2026, 6, 10, 10, 30, tzinfo=dt.UTC)
    signal = {
        "uid": signal_uid,
        "signal_uid": "example-signal",
        "signal_description": "Example signal",
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_signal_metadata_row",
        lambda context, uid: signal,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._compile_delete_signal_weights_operation",
        lambda context, **kwargs: captured.update({"compile": kwargs}) or "delete-weights-op",
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api.execute_markets_operation",
        lambda operation, context: {"rows": [{"deleted": 1}, {"deleted": 1}]},
    )

    from msm_portfolios.services.public_api import delete_signal_weights

    response = delete_signal_weights(
        object(),
        uid=str(signal_uid),
        weights_date=weights_date,
    )

    assert response == {
        "detail": "Signal weights deleted.",
        "signal_metadata_uid": str(signal_uid),
        "signal_uid": "example-signal",
        "weights_date": weights_date,
        "deleted_count": 2,
    }
    assert captured["compile"] == {
        "signal_uid": "example-signal",
        "weights_date": weights_date,
    }


def test_public_delete_signal_metadata_operation_uses_weights_cleanup_cte(monkeypatch) -> None:
    signal_metadata_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_compile(statement, **kwargs):
        captured["statement"] = statement
        captured.update(kwargs)
        return "compiled-delete-signal-op"

    monkeypatch.setattr(
        "msm_portfolios.services.public_api.compile_markets_statement",
        fake_compile,
    )

    from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage
    from msm_portfolios.models import SignalMetadataTable
    from msm_portfolios.services.public_api import (
        _compile_delete_signal_metadata_with_weights_operation,
    )

    operation = _compile_delete_signal_metadata_with_weights_operation(
        object(),
        signal_metadata_uid=signal_metadata_uid,
    )

    statement_text = str(captured["statement"]).lower()
    assert operation == "compiled-delete-signal-op"
    assert captured["operation"] == "delete"
    assert captured["access"] == "write"
    assert captured["models"] == [SignalMetadataTable, SignalWeightsStorage]
    assert "signal_scope" in statement_text
    assert "deleted_signal_weights" in statement_text
    assert "delete from" in statement_text
