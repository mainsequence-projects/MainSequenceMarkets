from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app


def _calendar_row(calendar_uid: uuid.UUID) -> dict[str, object]:
    return {
        "uid": str(calendar_uid),
        "unique_identifier": "XNYS",
        "display_name": "New York Stock Exchange",
        "calendar_type": "TRADING",
        "timezone": "America/New_York",
        "source": "pandas_market_calendars",
        "source_identifier": "NYSE",
        "valid_from": "2026-01-01",
        "valid_to": "2026-12-31",
        "metadata_json": {"source": "test"},
    }


def test_get_calendars_returns_core_rows(monkeypatch) -> None:
    calendar_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_list_calendars(**kwargs):
        captured.update(kwargs)
        return [_calendar_row(calendar_uid)]

    monkeypatch.setattr("apps.v1.routers.calendars.list_calendars", fake_list_calendars)

    client = TestClient(app)
    response = client.get(
        "/api/v1/calendar/",
        params={
            "response_format": "frontend_list",
            "search": "nyse",
            "limit": 10,
            "offset": 2,
            "calendar_type": "TRADING",
            "source": "pandas_market_calendars",
        },
    )

    assert response.status_code == 200
    assert response.json() == [_calendar_row(calendar_uid)]
    assert captured["search"] == "nyse"
    assert captured["limit"] == 10
    assert captured["offset"] == 2
    assert captured["calendar_type"] == "TRADING"
    assert captured["source"] == "pandas_market_calendars"


def test_get_calendars_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/calendar/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 400
    assert "frontend_list" in response.json()["detail"]


def test_post_calendar_returns_record(monkeypatch) -> None:
    calendar_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_create_calendar(*, payload):
        captured.update(payload)
        return _calendar_row(calendar_uid)

    monkeypatch.setattr("apps.v1.routers.calendars.create_calendar", fake_create_calendar)

    client = TestClient(app)
    response = client.post(
        "/api/v1/calendar/",
        json={
            "unique_identifier": "XNYS",
            "display_name": "New York Stock Exchange",
            "calendar_type": "trading",
            "timezone": "America/New_York",
            "source": "pandas_market_calendars",
            "source_identifier": "NYSE",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "metadata_json": {"source": "test"},
        },
    )

    assert response.status_code == 200
    assert response.json() == _calendar_row(calendar_uid)
    assert captured["calendar_type"] == "TRADING"
    assert captured["valid_from"] == dt.date(2026, 1, 1)


def test_get_calendar_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr("apps.v1.routers.calendars.get_calendar", lambda uid: None)

    client = TestClient(app)
    response = client.get("/api/v1/calendar/missing-calendar/")

    assert response.status_code == 404
    assert "missing-calendar" in response.json()["detail"]


def test_get_calendar_summary_returns_frontend_detail_summary(monkeypatch) -> None:
    calendar_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.calendars.get_calendar_summary",
        lambda uid: {
            "entity": {
                "id": str(calendar_uid),
                "type": "calendar",
                "title": "New York Stock Exchange",
            },
            "badges": [
                {
                    "key": "calendar_type",
                    "label": "TRADING",
                    "tone": "success",
                },
                {
                    "key": "timezone",
                    "label": "America/New_York",
                    "tone": "neutral",
                },
            ],
            "inline_fields": [
                {
                    "key": "uid",
                    "label": "UID",
                    "value": str(calendar_uid),
                    "kind": "code",
                }
            ],
            "highlight_fields": [
                {
                    "key": "display_name",
                    "label": "Display name",
                    "value": "New York Stock Exchange",
                    "kind": "text",
                    "icon": "calendar",
                }
            ],
            "stats": [
                {
                    "key": "horizon_days",
                    "label": "Horizon days",
                    "display": "365",
                    "value": 365,
                    "kind": "number",
                }
            ],
            "label_management": {
                "labels": [],
                "add_label_url": None,
                "remove_label_url": None,
            },
            "summary_warning": None,
            "extensions": {
                "relationships": {
                    "dates_url": f"/api/v1/calendar/{calendar_uid}/dates/",
                    "sessions_url": f"/api/v1/calendar/{calendar_uid}/sessions/",
                    "events_url": f"/api/v1/calendar/{calendar_uid}/events/",
                }
            },
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/calendar/{calendar_uid}/summary/")

    assert response.status_code == 200
    assert response.json()["entity"] == {
        "id": str(calendar_uid),
        "type": "calendar",
        "title": "New York Stock Exchange",
    }
    assert response.json()["badges"][0] == {
        "key": "calendar_type",
        "label": "TRADING",
        "tone": "success",
    }
    assert response.json()["stats"] == [
        {
            "key": "horizon_days",
            "label": "Horizon days",
            "display": "365",
            "value": 365,
            "kind": "number",
        }
    ]


def test_get_calendar_summary_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr("apps.v1.routers.calendars.get_calendar_summary", lambda uid: None)

    client = TestClient(app)
    response = client.get("/api/v1/calendar/missing-calendar/summary/")

    assert response.status_code == 404
    assert "missing-calendar" in response.json()["detail"]


def test_patch_calendar_returns_record(monkeypatch) -> None:
    calendar_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_update_calendar(*, uid: str, payload: dict[str, object]):
        captured["uid"] = uid
        captured["payload"] = payload
        row = _calendar_row(calendar_uid)
        row["display_name"] = "NYSE Updated"
        return row

    monkeypatch.setattr("apps.v1.routers.calendars.update_calendar", fake_update_calendar)

    client = TestClient(app)
    response = client.patch(
        f"/api/v1/calendar/{calendar_uid}/",
        json={"display_name": "NYSE Updated"},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "NYSE Updated"
    assert captured == {
        "uid": str(calendar_uid),
        "payload": {"display_name": "NYSE Updated"},
    }


def test_delete_calendar_returns_null(monkeypatch) -> None:
    monkeypatch.setattr("apps.v1.routers.calendars.delete_calendar", lambda uid: True)

    client = TestClient(app)
    response = client.delete(f"/api/v1/calendar/{uuid.uuid4()}/")

    assert response.status_code == 200
    assert response.json() is None


def test_calendar_dates_routes(monkeypatch) -> None:
    calendar_uid = uuid.uuid4()
    date_uid = uuid.uuid4()
    row = {
        "uid": str(date_uid),
        "calendar_uid": str(calendar_uid),
        "local_date": "2026-01-02",
        "is_business_day": True,
        "is_holiday": False,
        "is_weekend": False,
        "is_early_close": False,
        "holiday_name": None,
        "metadata_json": None,
    }
    captured: dict[str, object] = {}

    def fake_create_calendar_date(**kwargs):
        captured["created"] = kwargs
        return row

    def fake_bulk_upsert_calendar_dates(**kwargs):
        captured["bulk"] = kwargs
        return [row]

    def fake_update_calendar_date(**kwargs):
        captured["patched"] = kwargs
        return row

    monkeypatch.setattr("apps.v1.routers.calendars.list_calendar_dates", lambda **kwargs: [row])
    monkeypatch.setattr(
        "apps.v1.routers.calendars.create_calendar_date",
        fake_create_calendar_date,
    )
    monkeypatch.setattr(
        "apps.v1.routers.calendars.bulk_upsert_calendar_dates",
        fake_bulk_upsert_calendar_dates,
    )
    monkeypatch.setattr(
        "apps.v1.routers.calendars.update_calendar_date",
        fake_update_calendar_date,
    )
    monkeypatch.setattr("apps.v1.routers.calendars.delete_calendar_date", lambda **kwargs: True)

    client = TestClient(app)
    list_response = client.get(
        f"/api/v1/calendar/{calendar_uid}/dates/",
        params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
    )
    post_response = client.post(
        f"/api/v1/calendar/{calendar_uid}/dates/",
        json={"local_date": "2026-01-02", "is_business_day": True},
    )
    bulk_response = client.post(
        f"/api/v1/calendar/{calendar_uid}/dates/bulk-upsert/",
        json={"rows": [{"local_date": "2026-01-02", "is_business_day": True}]},
    )
    patch_response = client.patch(
        f"/api/v1/calendar/{calendar_uid}/dates/{date_uid}/",
        json={"is_early_close": True},
    )
    delete_response = client.delete(f"/api/v1/calendar/{calendar_uid}/dates/{date_uid}/")

    assert list_response.status_code == 200
    assert post_response.status_code == 200
    assert bulk_response.status_code == 200
    assert patch_response.status_code == 200
    assert delete_response.status_code == 200
    assert captured["created"]["calendar_uid"] == str(calendar_uid)
    assert captured["created"]["payload"]["local_date"] == dt.date(2026, 1, 2)
    assert captured["bulk"]["rows"][0]["local_date"] == dt.date(2026, 1, 2)
    assert captured["patched"]["payload"] == {"is_early_close": True}


def test_calendar_sessions_routes(monkeypatch) -> None:
    calendar_uid = uuid.uuid4()
    session_uid = uuid.uuid4()
    row = {
        "uid": str(session_uid),
        "calendar_uid": str(calendar_uid),
        "local_date": "2026-01-02",
        "session_label": "regular",
        "opens_at": None,
        "closes_at": None,
        "timezone": "UTC",
        "is_primary": True,
        "metadata_json": None,
    }
    captured: dict[str, object] = {}

    def fake_create_calendar_session(**kwargs):
        captured["created"] = kwargs
        return row

    def fake_bulk_upsert_calendar_sessions(**kwargs):
        captured["bulk"] = kwargs
        return [row]

    monkeypatch.setattr("apps.v1.routers.calendars.list_calendar_sessions", lambda **kwargs: [row])
    monkeypatch.setattr(
        "apps.v1.routers.calendars.create_calendar_session",
        fake_create_calendar_session,
    )
    monkeypatch.setattr(
        "apps.v1.routers.calendars.bulk_upsert_calendar_sessions",
        fake_bulk_upsert_calendar_sessions,
    )
    monkeypatch.setattr("apps.v1.routers.calendars.get_calendar_session", lambda **kwargs: row)
    monkeypatch.setattr("apps.v1.routers.calendars.delete_calendar_session", lambda **kwargs: True)

    client = TestClient(app)
    list_response = client.get(f"/api/v1/calendar/{calendar_uid}/sessions/")
    post_response = client.post(
        f"/api/v1/calendar/{calendar_uid}/sessions/",
        json={"local_date": "2026-01-02", "session_label": "regular"},
    )
    bulk_response = client.post(
        f"/api/v1/calendar/{calendar_uid}/sessions/bulk-upsert/",
        json={"rows": [{"local_date": "2026-01-02", "session_label": "regular"}]},
    )
    get_response = client.get(f"/api/v1/calendar/{calendar_uid}/sessions/{session_uid}/")
    delete_response = client.delete(f"/api/v1/calendar/{calendar_uid}/sessions/{session_uid}/")

    assert list_response.status_code == 200
    assert post_response.status_code == 200
    assert bulk_response.status_code == 200
    assert get_response.status_code == 200
    assert delete_response.status_code == 200
    assert captured["created"]["payload"]["session_label"] == "regular"
    assert captured["bulk"]["rows"][0]["session_label"] == "regular"


def test_calendar_events_routes(monkeypatch) -> None:
    calendar_uid = uuid.uuid4()
    event_uid = uuid.uuid4()
    row = {
        "uid": str(event_uid),
        "calendar_uid": str(calendar_uid),
        "event_date": "2026-03-20",
        "event_time": None,
        "event_type": "EXPIRY",
        "event_label": "",
        "target_type": "",
        "target_uid": None,
        "target_identifier": "",
        "metadata_json": None,
    }
    captured: dict[str, object] = {}

    def fake_create_calendar_event(**kwargs):
        captured["created"] = kwargs
        return row

    def fake_bulk_upsert_calendar_events(**kwargs):
        captured["bulk"] = kwargs
        return [row]

    def fake_update_calendar_event(**kwargs):
        captured["patched"] = kwargs
        return row

    monkeypatch.setattr("apps.v1.routers.calendars.list_calendar_events", lambda **kwargs: [row])
    monkeypatch.setattr(
        "apps.v1.routers.calendars.create_calendar_event",
        fake_create_calendar_event,
    )
    monkeypatch.setattr(
        "apps.v1.routers.calendars.bulk_upsert_calendar_events",
        fake_bulk_upsert_calendar_events,
    )
    monkeypatch.setattr(
        "apps.v1.routers.calendars.update_calendar_event",
        fake_update_calendar_event,
    )
    monkeypatch.setattr("apps.v1.routers.calendars.delete_calendar_event", lambda **kwargs: True)

    client = TestClient(app)
    list_response = client.get(
        f"/api/v1/calendar/{calendar_uid}/events/",
        params={"event_type": "EXPIRY"},
    )
    post_response = client.post(
        f"/api/v1/calendar/{calendar_uid}/events/",
        json={"event_date": "2026-03-20", "event_type": "expiry"},
    )
    bulk_response = client.post(
        f"/api/v1/calendar/{calendar_uid}/events/bulk-upsert/",
        json={"rows": [{"event_date": "2026-03-20", "event_type": "expiry"}]},
    )
    patch_response = client.patch(
        f"/api/v1/calendar/{calendar_uid}/events/{event_uid}/",
        json={"metadata_json": {"reviewed": True}},
    )
    delete_response = client.delete(f"/api/v1/calendar/{calendar_uid}/events/{event_uid}/")

    assert list_response.status_code == 200
    assert post_response.status_code == 200
    assert bulk_response.status_code == 200
    assert patch_response.status_code == 200
    assert delete_response.status_code == 200
    assert captured["created"]["payload"]["event_type"] == "expiry"
    assert captured["bulk"]["rows"][0]["event_date"] == dt.date(2026, 3, 20)
    assert captured["patched"]["payload"] == {"metadata_json": {"reviewed": True}}


def test_calendar_child_detail_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr("apps.v1.routers.calendars.get_calendar_event", lambda **kwargs: None)

    calendar_uid = uuid.uuid4()
    event_uid = uuid.uuid4()
    client = TestClient(app)
    response = client.get(f"/api/v1/calendar/{calendar_uid}/events/{event_uid}/")

    assert response.status_code == 404
    assert str(event_uid) in response.json()["detail"]
