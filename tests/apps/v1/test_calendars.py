from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from apps.v1.main import app
from apps.v1.services import calendars as calendar_service
from msm.services.calendars import CalendarRangeError


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
        return {"count": 11, "results": [_calendar_row(calendar_uid)]}

    monkeypatch.setattr("apps.v1.routers.calendars.list_calendars", fake_list_calendars)

    client = TestClient(app)
    response = client.get(
        "/api/v1/calendar/",
        params={
            "search": "nyse",
            "limit": 10,
            "offset": 10,
            "calendar_type": "TRADING",
            "source": "pandas_market_calendars",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [_calendar_row(calendar_uid)],
        "pageInfo": {
            "pageIndex": 1,
            "pageSize": 10,
            "totalItems": 11,
            "hasNextPage": False,
            "hasPreviousPage": True,
        },
    }
    assert captured["search"] == "nyse"
    assert captured["limit"] == 10
    assert captured["offset"] == 10
    assert captured["calendar_type"] == "TRADING"
    assert captured["source"] == "pandas_market_calendars"


def test_get_calendars_does_not_expose_legacy_response_format() -> None:
    client = TestClient(app)
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/calendar/"]["get"]
    assert "response_format" not in {parameter["name"] for parameter in operation["parameters"]}


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


def test_calendar_range_is_optional(monkeypatch) -> None:
    calendar_uid = uuid.uuid4()
    row = {**_calendar_row(calendar_uid), "valid_from": None, "valid_to": None}
    captured: dict[str, object] = {}

    def fake_create_calendar(*, payload):
        captured.update(payload)
        return row

    monkeypatch.setattr("apps.v1.routers.calendars.create_calendar", fake_create_calendar)

    client = TestClient(app)
    response = client.post(
        "/api/v1/calendar/",
        json={
            "unique_identifier": "ALWAYS_OPEN",
            "display_name": "Always open",
            "calendar_type": "trading",
        },
    )

    assert response.status_code == 200
    assert response.json()["valid_from"] is None
    assert response.json()["valid_to"] is None
    assert "valid_from" not in captured
    assert "valid_to" not in captured


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
                    "rules_url": f"/api/v1/calendar/{calendar_uid}/rules/",
                    "exceptions_url": f"/api/v1/calendar/{calendar_uid}/exceptions/",
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
        "link_url": None,
    }
    assert response.json()["stats"] == [
        {
            "key": "horizon_days",
            "label": "Horizon days",
            "display": "365",
            "value": 365,
            "kind": "number",
            "link_url": None,
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


def test_delete_of_a_calendar_in_use_answers_409(monkeypatch) -> None:
    """ADR 0057: a calendar an asset or a portfolio references is not deleted."""

    from msm.services.calendars import CalendarInUseConflictError

    def refuse(uid):
        raise CalendarInUseConflictError(
            "Calendar 'NYSE' is the trading calendar of 2 asset(s) and cannot be deleted. "
            "Move them to another calendar first."
        )

    monkeypatch.setattr("apps.v1.routers.calendars.delete_calendar", refuse)
    client = TestClient(app)

    response = client.delete(f"/api/v1/calendar/{uuid.uuid4()}/")

    assert response.status_code == 409
    assert "trading calendar of 2 asset(s)" in response.json()["detail"]


def test_delete_calendar_returns_null(monkeypatch) -> None:
    monkeypatch.setattr("apps.v1.routers.calendars.delete_calendar", lambda uid: True)

    client = TestClient(app)
    response = client.delete(f"/api/v1/calendar/{uuid.uuid4()}/")

    assert response.status_code == 200
    assert response.json() is None


def _stub_runtime(monkeypatch) -> object:
    """Let the real apps/v1 calendar services run against a fake runtime."""

    context = object()
    monkeypatch.setattr(calendar_service, "_get_runtime", lambda: SimpleNamespace(context=context))
    return context


_WINDOW = {"start_date": "2024-11-25", "end_date": "2024-12-31"}
_WINDOW_ROUTES = pytest.mark.parametrize(
    ("segment", "hook"),
    [
        ("dates", "_list_calendar_date_records_page"),
        ("sessions", "_list_calendar_session_records_page"),
    ],
)


def test_calendar_dates_returns_the_computed_window(monkeypatch) -> None:
    context = _stub_runtime(monkeypatch)
    calendar_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_list_dates(received_context, **kwargs):
        captured["context"] = received_context
        captured["kwargs"] = kwargs
        return {
            "count": 3,
            "results": [
                {
                    "calendar_uid": str(calendar_uid),
                    "local_date": dt.date(2024, 11, 28),
                    "is_business_day": False,
                    "is_holiday": True,
                    "is_weekend": False,
                    "is_early_close": False,
                    "holiday_name": "Thanksgiving Day",
                }
            ],
        }

    monkeypatch.setattr(calendar_service, "_list_calendar_date_records_page", fake_list_dates)

    client = TestClient(app)
    response = client.get(
        f"/api/v1/calendar/{calendar_uid}/dates/",
        params={**_WINDOW, "is_holiday": "true", "limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "calendar_uid": str(calendar_uid),
                "local_date": "2024-11-28",
                "is_business_day": False,
                "is_holiday": True,
                "is_weekend": False,
                "is_early_close": False,
                "holiday_name": "Thanksgiving Day",
            }
        ],
        "pageInfo": {
            "pageIndex": 1,
            "pageSize": 1,
            "totalItems": 3,
            "hasNextPage": True,
            "hasPreviousPage": True,
        },
    }
    assert captured["context"] is context
    assert captured["kwargs"] == {
        "calendar_uid": str(calendar_uid),
        "start_date": dt.date(2024, 11, 25),
        "end_date": dt.date(2024, 12, 31),
        "is_business_day": None,
        "is_holiday": True,
        "is_weekend": None,
        "is_early_close": None,
        "limit": 1,
        "offset": 1,
    }


def test_calendar_sessions_returns_the_computed_window(monkeypatch) -> None:
    context = _stub_runtime(monkeypatch)
    calendar_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_list_sessions(received_context, **kwargs):
        captured["context"] = received_context
        captured["kwargs"] = kwargs
        return {
            "count": 1,
            "results": [
                {
                    "calendar_uid": str(calendar_uid),
                    "local_date": dt.date(2024, 11, 29),
                    "session_label": "regular",
                    "opens_at": dt.datetime(2024, 11, 29, 14, 30, tzinfo=dt.UTC),
                    "closes_at": dt.datetime(2024, 11, 29, 18, 0, tzinfo=dt.UTC),
                    "timezone": "America/New_York",
                    "is_primary": True,
                    "is_early_close": True,
                    "is_late_open": False,
                }
            ],
        }

    monkeypatch.setattr(calendar_service, "_list_calendar_session_records_page", fake_list_sessions)

    client = TestClient(app)
    response = client.get(
        f"/api/v1/calendar/{calendar_uid}/sessions/",
        params={**_WINDOW, "session_label": "regular", "is_primary": "true"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "calendar_uid": str(calendar_uid),
            "local_date": "2024-11-29",
            "session_label": "regular",
            "opens_at": "2024-11-29T14:30:00Z",
            "closes_at": "2024-11-29T18:00:00Z",
            "timezone": "America/New_York",
            "is_primary": True,
            "is_early_close": True,
            "is_late_open": False,
        }
    ]
    assert response.json()["pageInfo"]["totalItems"] == 1
    assert captured["context"] is context
    assert captured["kwargs"] == {
        "calendar_uid": str(calendar_uid),
        "start_date": dt.date(2024, 11, 25),
        "end_date": dt.date(2024, 12, 31),
        "session_label": "regular",
        "is_primary": True,
        "limit": 500,
        "offset": 0,
    }


@_WINDOW_ROUTES
@pytest.mark.parametrize(
    "params",
    [{}, {"start_date": "2024-11-25"}, {"end_date": "2024-12-31"}],
    ids=["no-window", "no-end-date", "no-start-date"],
)
def test_calendar_window_requires_start_and_end_date(monkeypatch, segment, hook, params) -> None:
    _stub_runtime(monkeypatch)

    def fail_if_computed(context, **kwargs):
        raise AssertionError("A window without both dates must not be computed.")

    monkeypatch.setattr(calendar_service, hook, fail_if_computed)

    client = TestClient(app)
    response = client.get(f"/api/v1/calendar/{uuid.uuid4()}/{segment}/", params=params)

    assert response.status_code == 422
    missing = {error["loc"][-1] for error in response.json()["detail"]}
    assert missing == {"start_date", "end_date"} - set(params)


@_WINDOW_ROUTES
def test_calendar_window_outside_the_calendar_range_is_refused(monkeypatch, segment, hook) -> None:
    _stub_runtime(monkeypatch)
    message = (
        "Calendar 'XNYS' is complete from 2026-01-01 to 2026-12-31; "
        "2024-11-25 to 2024-12-31 is outside that range."
    )

    def refuse_window(context, **kwargs):
        raise CalendarRangeError(message)

    monkeypatch.setattr(calendar_service, hook, refuse_window)

    client = TestClient(app)
    response = client.get(f"/api/v1/calendar/{uuid.uuid4()}/{segment}/", params=_WINDOW)

    assert response.status_code == 400
    assert response.json() == {"detail": message}


@_WINDOW_ROUTES
def test_calendar_window_that_ends_before_it_starts_is_refused(monkeypatch, segment, hook) -> None:
    _stub_runtime(monkeypatch)

    def refuse_window(context, **kwargs):
        raise ValueError("end_date must be greater than or equal to start_date.")

    monkeypatch.setattr(calendar_service, hook, refuse_window)

    client = TestClient(app)
    response = client.get(
        f"/api/v1/calendar/{uuid.uuid4()}/{segment}/",
        params={"start_date": "2024-12-31", "end_date": "2024-11-25"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "end_date must be greater than or equal to start_date."}


@_WINDOW_ROUTES
def test_calendar_window_returns_404_for_an_unknown_calendar(monkeypatch, segment, hook) -> None:
    _stub_runtime(monkeypatch)
    monkeypatch.setattr(calendar_service, hook, lambda context, **kwargs: None)

    client = TestClient(app)
    response = client.get("/api/v1/calendar/missing-calendar/" + f"{segment}/", params=_WINDOW)

    assert response.status_code == 404
    assert "missing-calendar" in response.json()["detail"]


def test_remote_row_operation_refuses_a_window_outside_the_calendar_range(monkeypatch) -> None:
    from msm.api.calendars import Calendar
    from msm.services.calendars import CalendarDefinition

    definition = CalendarDefinition.from_rows(
        timezone="America/New_York",
        rules=[],
        exceptions=[],
        valid_from=dt.date(2026, 1, 1),
        valid_to=dt.date(2026, 12, 31),
        unique_identifier="XNYS",
    )
    monkeypatch.setattr(
        Calendar,
        "_definition",
        classmethod(lambda cls, calendar_uid, start_date, end_date: definition),
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/rows/calendar/sessions/",
        json={"arguments": {"calendar_uid": str(uuid.uuid4()), **_WINDOW}},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "Calendar 'XNYS' is complete from 2026-01-01 to 2026-12-31; "
            "2024-11-25 to 2024-12-31 is outside that range."
        ),
        "error_type": "CalendarRangeError",
    }


def test_computed_dates_and_sessions_are_read_only() -> None:
    paths = app.openapi()["paths"]
    calendar_uid = uuid.uuid4()
    client = TestClient(app)

    for segment in ("dates", "sessions"):
        collection = f"/api/v1/calendar/{{calendar_uid}}/{segment}/"
        assert set(paths[collection]) == {"get"}
        assert {path for path in paths if path.startswith(collection)} == {
            collection,
            f"{collection}discovery/",
        }
        assert (
            client.post(f"/api/v1/calendar/{calendar_uid}/{segment}/", json={}).status_code == 405
        )
        assert (
            client.post(
                f"/api/v1/calendar/{calendar_uid}/{segment}/bulk-upsert/", json={"rows": []}
            ).status_code
            == 404
        )
        assert (
            client.get(f"/api/v1/calendar/{calendar_uid}/{segment}/{uuid.uuid4()}/").status_code
            == 404
        )

    for item_schema in ("ComputedCalendarDate", "ComputedCalendarSession"):
        properties = app.openapi()["components"]["schemas"][item_schema]["properties"]
        assert "uid" not in properties
        assert "metadata_json" not in properties


def test_calendar_child_routes_are_dates_sessions_rules_and_exceptions() -> None:
    prefix = "/api/v1/calendar/{calendar_uid}/"
    paths = {path for path in app.openapi()["paths"] if path.startswith(prefix)}

    assert paths == {
        f"{prefix}dates/",
        f"{prefix}dates/discovery/",
        f"{prefix}sessions/",
        f"{prefix}sessions/discovery/",
        f"{prefix}rules/",
        f"{prefix}rules/discovery/",
        f"{prefix}rules/bulk-upsert/",
        f"{prefix}rules/{{rule_uid}}/",
        f"{prefix}exceptions/",
        f"{prefix}exceptions/discovery/",
        f"{prefix}exceptions/bulk-upsert/",
        f"{prefix}exceptions/{{exception_uid}}/",
    }


def _rule_row(calendar_uid: uuid.UUID, rule_uid: uuid.UUID) -> dict[str, object]:
    return {
        "uid": str(rule_uid),
        "calendar_uid": str(calendar_uid),
        "session_label": "regular",
        "effective_from": "1985-01-01",
        "effective_to": None,
        "weekdays": "1111100",
        "opens_at_local": "09:30:00",
        "closes_at_local": "16:00:00",
        "open_day_offset": 0,
        "close_day_offset": 0,
        "is_primary": True,
    }


def test_calendar_session_rule_routes(monkeypatch) -> None:
    context = _stub_runtime(monkeypatch)
    calendar_uid = uuid.uuid4()
    rule_uid = uuid.uuid4()
    row = _rule_row(calendar_uid, rule_uid)
    captured: dict[str, dict[str, object]] = {}

    def hook(name: str, result):
        def fake(received_context, **kwargs):
            assert received_context is context
            captured[name] = kwargs
            return result

        return fake

    monkeypatch.setattr(
        calendar_service,
        "_list_calendar_session_rule_records_page",
        hook("listed", {"count": 1, "results": [row]}),
    )
    monkeypatch.setattr(calendar_service, "_get_calendar_session_rule_record", hook("read", row))
    monkeypatch.setattr(
        calendar_service, "_create_calendar_session_rule_record", hook("created", row)
    )
    monkeypatch.setattr(
        calendar_service, "_bulk_upsert_calendar_session_rule_records", hook("bulk", [row])
    )
    monkeypatch.setattr(
        calendar_service,
        "_update_calendar_session_rule_record",
        hook("patched", {**row, "effective_to": "2030-12-31"}),
    )
    monkeypatch.setattr(
        calendar_service, "_delete_calendar_session_rule_record", hook("deleted", True)
    )

    body = {
        "effective_from": "1985-01-01",
        "weekdays": "1111100",
        "opens_at_local": "09:30",
        "closes_at_local": "16:00",
    }
    client = TestClient(app)
    base = f"/api/v1/calendar/{calendar_uid}/rules/"
    list_response = client.get(base, params={"session_label": "regular", "limit": 10})
    post_response = client.post(base, json=body)
    bulk_response = client.post(f"{base}bulk-upsert/", json={"rows": [body]})
    get_response = client.get(f"{base}{rule_uid}/")
    patch_response = client.patch(f"{base}{rule_uid}/", json={"effective_to": "2030-12-31"})
    delete_response = client.delete(f"{base}{rule_uid}/")

    assert list_response.status_code == 200
    assert list_response.json() == {
        "items": [row],
        "pageInfo": {
            "pageIndex": 0,
            "pageSize": 10,
            "totalItems": 1,
            "hasNextPage": False,
            "hasPreviousPage": False,
        },
    }
    assert post_response.status_code == 200
    assert post_response.json() == row
    assert bulk_response.status_code == 200
    assert bulk_response.json() == [row]
    assert get_response.status_code == 200
    assert get_response.json() == row
    assert patch_response.status_code == 200
    assert patch_response.json()["effective_to"] == "2030-12-31"
    assert delete_response.status_code == 200
    assert delete_response.json() is None

    created_values = {
        "session_label": "regular",
        "effective_from": dt.date(1985, 1, 1),
        "weekdays": "1111100",
        "opens_at_local": "09:30:00",
        "closes_at_local": "16:00:00",
        "open_day_offset": 0,
        "close_day_offset": 0,
        "is_primary": True,
    }
    assert captured["listed"] == {
        "calendar_uid": str(calendar_uid),
        "session_label": "regular",
        "limit": 10,
        "offset": 0,
    }
    assert captured["created"] == {"calendar_uid": str(calendar_uid), **created_values}
    assert captured["bulk"] == {"calendar_uid": str(calendar_uid), "rows": [created_values]}
    assert captured["read"] == {"calendar_uid": str(calendar_uid), "uid": str(rule_uid)}
    assert captured["patched"] == {
        "calendar_uid": str(calendar_uid),
        "uid": str(rule_uid),
        "effective_to": dt.date(2030, 12, 31),
    }
    assert captured["deleted"] == {"calendar_uid": str(calendar_uid), "uid": str(rule_uid)}


def test_calendar_session_rule_that_the_service_refuses_returns_400(monkeypatch) -> None:
    _stub_runtime(monkeypatch)
    message = "effective_to must be greater than or equal to effective_from."

    def refuse(context, **kwargs):
        raise ValueError(message)

    monkeypatch.setattr(calendar_service, "_create_calendar_session_rule_record", refuse)
    monkeypatch.setattr(calendar_service, "_bulk_upsert_calendar_session_rule_records", refuse)

    body = {"effective_from": "1985-01-01", "effective_to": "1984-12-31", "weekdays": "1111100"}
    client = TestClient(app)
    base = f"/api/v1/calendar/{uuid.uuid4()}/rules/"
    responses = [
        client.post(base, json=body),
        client.post(f"{base}bulk-upsert/", json={"rows": [body]}),
    ]

    for response in responses:
        assert response.status_code == 400
        assert response.json() == {"detail": message}


@pytest.mark.parametrize(
    ("field", "value"),
    [("weekdays", "11111xx"), ("weekdays", "11111"), ("opens_at_local", "half past nine")],
)
def test_calendar_session_rule_body_is_validated_before_it_is_written(
    monkeypatch, field, value
) -> None:
    _stub_runtime(monkeypatch)

    def fail_if_written(context, **kwargs):
        raise AssertionError("A malformed rule must not be written.")

    monkeypatch.setattr(calendar_service, "_create_calendar_session_rule_record", fail_if_written)
    monkeypatch.setattr(
        calendar_service, "_bulk_upsert_calendar_session_rule_records", fail_if_written
    )
    monkeypatch.setattr(calendar_service, "_update_calendar_session_rule_record", fail_if_written)

    body = {"effective_from": "1985-01-01", "weekdays": "1111100", field: value}
    client = TestClient(app)
    base = f"/api/v1/calendar/{uuid.uuid4()}/rules/"
    responses = [
        client.post(base, json=body),
        client.post(f"{base}bulk-upsert/", json={"rows": [body]}),
        client.patch(f"{base}{uuid.uuid4()}/", json={field: value}),
    ]

    for response in responses:
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"][-1] == field


def test_calendar_session_rule_returns_404_when_missing(monkeypatch) -> None:
    _stub_runtime(monkeypatch)
    for hook in (
        "_get_calendar_session_rule_record",
        "_update_calendar_session_rule_record",
    ):
        monkeypatch.setattr(calendar_service, hook, lambda context, **kwargs: None)
    monkeypatch.setattr(
        calendar_service, "_delete_calendar_session_rule_record", lambda context, **kwargs: False
    )

    rule_uid = uuid.uuid4()
    client = TestClient(app)
    url = f"/api/v1/calendar/{uuid.uuid4()}/rules/{rule_uid}/"
    responses = [client.get(url), client.patch(url, json={"is_primary": False}), client.delete(url)]

    for response in responses:
        assert response.status_code == 404
        assert str(rule_uid) in response.json()["detail"]


def _exception_row(calendar_uid: uuid.UUID, exception_uid: uuid.UUID) -> dict[str, object]:
    return {
        "uid": str(exception_uid),
        "calendar_uid": str(calendar_uid),
        "local_date": "2024-12-31",
        "session_label": "",
        "exception_type": "CLOSED",
        "opens_at_local": None,
        "closes_at_local": None,
        "name": "Desk closed",
        "source": "user",
        "metadata_json": None,
    }


def test_calendar_exception_routes(monkeypatch) -> None:
    context = _stub_runtime(monkeypatch)
    calendar_uid = uuid.uuid4()
    exception_uid = uuid.uuid4()
    row = _exception_row(calendar_uid, exception_uid)
    captured: dict[str, dict[str, object]] = {}

    def hook(name: str, result):
        def fake(received_context, **kwargs):
            assert received_context is context
            captured[name] = kwargs
            return result

        return fake

    monkeypatch.setattr(
        calendar_service,
        "_list_calendar_exception_records_page",
        hook("listed", {"count": 1, "results": [row]}),
    )
    monkeypatch.setattr(calendar_service, "_get_calendar_exception_record", hook("read", row))
    monkeypatch.setattr(calendar_service, "_create_calendar_exception_record", hook("created", row))
    monkeypatch.setattr(
        calendar_service, "_bulk_upsert_calendar_exception_records", hook("bulk", [row])
    )
    monkeypatch.setattr(
        calendar_service,
        "_update_calendar_exception_record",
        hook("patched", {**row, "name": None}),
    )
    monkeypatch.setattr(
        calendar_service, "_delete_calendar_exception_record", hook("deleted", True)
    )

    body = {"local_date": "2024-12-31", "exception_type": "closed", "name": "Desk closed"}
    client = TestClient(app)
    base = f"/api/v1/calendar/{calendar_uid}/exceptions/"
    list_response = client.get(
        base,
        params={
            "start_date": "2024-12-01",
            "end_date": "2024-12-31",
            "exception_type": "CLOSED",
            "source": "user",
        },
    )
    post_response = client.post(base, json=body)
    bulk_response = client.post(f"{base}bulk-upsert/", json={"rows": [body]})
    get_response = client.get(f"{base}{exception_uid}/")
    patch_response = client.patch(f"{base}{exception_uid}/", json={"name": None})
    delete_response = client.delete(f"{base}{exception_uid}/")

    assert list_response.status_code == 200
    assert list_response.json()["items"] == [row]
    assert list_response.json()["pageInfo"]["totalItems"] == 1
    assert post_response.status_code == 200
    assert post_response.json() == row
    assert post_response.json()["source"] == "user"
    assert bulk_response.status_code == 200
    assert bulk_response.json() == [row]
    assert get_response.status_code == 200
    assert get_response.json() == row
    assert patch_response.status_code == 200
    assert patch_response.json()["name"] is None
    assert delete_response.status_code == 200
    assert delete_response.json() is None

    created_values = {
        "local_date": dt.date(2024, 12, 31),
        "session_label": "",
        "exception_type": "CLOSED",
        "name": "Desk closed",
    }
    assert captured["listed"] == {
        "calendar_uid": str(calendar_uid),
        "start_date": dt.date(2024, 12, 1),
        "end_date": dt.date(2024, 12, 31),
        "session_label": None,
        "exception_type": "CLOSED",
        "source": "user",
        "limit": 500,
        "offset": 0,
    }
    # The routes send no source: the record service writes `source="user"`.
    assert captured["created"] == {"calendar_uid": str(calendar_uid), **created_values}
    assert captured["bulk"] == {"calendar_uid": str(calendar_uid), "rows": [created_values]}
    assert captured["read"] == {"calendar_uid": str(calendar_uid), "uid": str(exception_uid)}
    assert captured["patched"] == {
        "calendar_uid": str(calendar_uid),
        "uid": str(exception_uid),
        "name": None,
    }
    assert captured["deleted"] == {"calendar_uid": str(calendar_uid), "uid": str(exception_uid)}


def test_calendar_exception_bodies_do_not_accept_a_source(monkeypatch) -> None:
    _stub_runtime(monkeypatch)

    def fail_if_written(context, **kwargs):
        raise AssertionError("A body that names a source must not be written.")

    monkeypatch.setattr(calendar_service, "_create_calendar_exception_record", fail_if_written)
    monkeypatch.setattr(
        calendar_service, "_bulk_upsert_calendar_exception_records", fail_if_written
    )
    monkeypatch.setattr(calendar_service, "_update_calendar_exception_record", fail_if_written)

    body = {
        "local_date": "2024-12-31",
        "exception_type": "CLOSED",
        "source": "pandas_market_calendars",
    }
    client = TestClient(app)
    base = f"/api/v1/calendar/{uuid.uuid4()}/exceptions/"
    responses = [
        client.post(base, json=body),
        client.post(f"{base}bulk-upsert/", json={"rows": [body]}),
        client.patch(f"{base}{uuid.uuid4()}/", json={"source": "pandas_market_calendars"}),
    ]

    for response in responses:
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"][-1] == "source"

    schemas = app.openapi()["components"]["schemas"]
    assert "source" in schemas["CalendarException"]["properties"]
    for body_schema in ("CalendarExceptionCreateRequest", "CalendarExceptionUpdate"):
        assert "source" not in schemas[body_schema]["properties"]


def test_calendar_exception_type_must_be_known(monkeypatch) -> None:
    _stub_runtime(monkeypatch)

    def fail_if_written(context, **kwargs):
        raise AssertionError("An unknown exception type must not be written.")

    monkeypatch.setattr(calendar_service, "_create_calendar_exception_record", fail_if_written)

    client = TestClient(app)
    response = client.post(
        f"/api/v1/calendar/{uuid.uuid4()}/exceptions/",
        json={"local_date": "2024-12-31", "exception_type": "HALF_DAY"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "exception_type"


def test_closed_exception_next_to_another_user_exception_is_refused(monkeypatch) -> None:
    _stub_runtime(monkeypatch)
    message = (
        "2024-12-24 would have a CLOSED exception next to OPEN for the whole day. "
        "A closed session cannot also open or close at another time."
    )

    def refuse(context, **kwargs):
        raise ValueError(message)

    monkeypatch.setattr(calendar_service, "_create_calendar_exception_record", refuse)
    monkeypatch.setattr(calendar_service, "_bulk_upsert_calendar_exception_records", refuse)

    closed = {"local_date": "2024-12-24", "exception_type": "CLOSED"}
    opened = {"local_date": "2024-12-24", "exception_type": "OPEN"}
    client = TestClient(app)
    base = f"/api/v1/calendar/{uuid.uuid4()}/exceptions/"
    responses = [
        client.post(base, json=closed),
        client.post(f"{base}bulk-upsert/", json={"rows": [closed, opened]}),
    ]

    for response in responses:
        assert response.status_code == 400
        assert response.json() == {"detail": message}


def test_calendar_exception_returns_404_when_missing(monkeypatch) -> None:
    _stub_runtime(monkeypatch)
    for hook in ("_get_calendar_exception_record", "_update_calendar_exception_record"):
        monkeypatch.setattr(calendar_service, hook, lambda context, **kwargs: None)
    monkeypatch.setattr(
        calendar_service, "_delete_calendar_exception_record", lambda context, **kwargs: False
    )

    exception_uid = uuid.uuid4()
    client = TestClient(app)
    url = f"/api/v1/calendar/{uuid.uuid4()}/exceptions/{exception_uid}/"
    responses = [client.get(url), client.patch(url, json={"name": "Renamed"}), client.delete(url)]

    for response in responses:
        assert response.status_code == 404
        assert str(exception_uid) in response.json()["detail"]


def _resource_discovery_validator() -> Draft202012Validator:
    """The vendored Command Center SDK schema of `command-center.resource_discovery@v1`."""

    contracts = Path(__file__).parents[2] / "contracts" / "command-center-sdk-v0.1.13"
    schemas = [json.loads(path.read_text()) for path in (contracts / "schemas").glob("*.json")]
    manifest = json.loads((contracts / "manifest.json").read_text())
    entry = next(
        item
        for item in manifest["schemas"]
        if item["contract"] == "command-center.resource_discovery@v1"
    )
    return Draft202012Validator(
        json.loads((contracts / entry["file"]).read_text()),
        registry=Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas
        ),
    )


def test_calendar_child_discovery_describes_the_collections() -> None:
    calendar_uid = uuid.uuid4()
    client = TestClient(app)
    validator = _resource_discovery_validator()

    def discover(segment: str) -> dict:
        response = client.get(f"/api/v1/calendar/{calendar_uid}/{segment}/discovery/")
        assert response.status_code == 200
        validator.validate(response.json())
        return response.json()

    for segment, identity in (
        ("dates", ["local_date"]),
        ("sessions", ["local_date", "session_label"]),
    ):
        discovery = discover(segment)
        assert discovery["resource"]["identity"]["fields"] == identity
        assert discovery["bulk_actions"] == []
        assert discovery["extensions"] == {
            "computed": True,
            "read_only": True,
            "required_filters": ["start_date", "end_date"],
        }
        assert {"start_date", "end_date"} <= {
            item["key"] for item in discovery["list"]["controls"]["filters"]
        }

    rules = discover("rules")
    assert rules["resource"]["id"] == "calendar-session-rules"
    assert rules["resource"]["identity"]["fields"] == ["uid"]
    assert "extensions" not in rules

    exceptions = discover("exceptions")
    assert exceptions["resource"]["id"] == "calendar-exceptions"
    assert exceptions["resource"]["identity"]["fields"] == ["uid"]
    filters = {item["key"]: item for item in exceptions["list"]["controls"]["filters"]}
    assert set(filters) == {"start_date", "end_date", "session_label", "exception_type", "source"}
    assert [option["value"] for option in filters["exception_type"]["options"]] == [
        "CLOSED",
        "EARLY_CLOSE",
        "LATE_OPEN",
        "OPEN",
    ]


def test_calendar_routes_run_on_the_record_services(sqlite_markets, monkeypatch) -> None:
    """The routes against the real `msm.services` calendar records, on a migrated SQLite file.

    The worked example of ADR 0055: one rule and two exceptions give the dates and
    sessions of a Thanksgiving week.
    """

    monkeypatch.setattr(
        calendar_service, "_get_runtime", lambda: SimpleNamespace(context=sqlite_markets.context)
    )
    client = TestClient(app)

    def path_uid(response) -> str:
        # SQLite stores a uid as 32 hex characters; the row models answer with dashes.
        return uuid.UUID(response.json()["uid"]).hex

    calendar = client.post(
        "/api/v1/calendar/",
        json={
            "unique_identifier": "XNYS",
            "display_name": "New York Stock Exchange",
            "calendar_type": "trading",
            "timezone": "America/New_York",
            "valid_from": "2024-01-01",
            "valid_to": "2024-12-31",
        },
    )
    assert calendar.status_code == 200
    base = f"/api/v1/calendar/{path_uid(calendar)}"

    rule_body = {
        "effective_from": "1985-01-01",
        "weekdays": "1111100",
        "opens_at_local": "09:30",
        "closes_at_local": "16:00",
    }
    rule = client.post(f"{base}/rules/", json=rule_body)
    assert rule.status_code == 200
    assert rule.json()["opens_at_local"] == "09:30:00"
    upserted_rule = client.post(f"{base}/rules/bulk-upsert/", json={"rows": [rule_body]})
    assert upserted_rule.status_code == 200
    assert [row["uid"] for row in upserted_rule.json()] == [rule.json()["uid"]]
    assert client.get(f"{base}/rules/").json()["pageInfo"]["totalItems"] == 1
    assert client.get(f"{base}/rules/{path_uid(rule)}/").json() == rule.json()

    closed = client.post(
        f"{base}/exceptions/",
        json={"local_date": "2024-11-28", "exception_type": "CLOSED", "name": "Thanksgiving Day"},
    )
    assert closed.status_code == 200
    assert closed.json()["source"] == "user"
    early_close = client.post(
        f"{base}/exceptions/bulk-upsert/",
        json={
            "rows": [
                {
                    "local_date": "2024-11-29",
                    "exception_type": "EARLY_CLOSE",
                    "closes_at_local": "13:00",
                }
            ]
        },
    )
    assert early_close.status_code == 200
    assert [row["source"] for row in early_close.json()] == ["user"]

    # A closed date cannot also open: the stored row and the written row are checked together.
    conflict = client.post(
        f"{base}/exceptions/", json={"local_date": "2024-11-28", "exception_type": "OPEN"}
    )
    assert conflict.status_code == 400
    assert "CLOSED exception next to OPEN" in conflict.json()["detail"]
    bulk_conflict = client.post(
        f"{base}/exceptions/bulk-upsert/",
        json={
            "rows": [
                {"local_date": "2024-12-24", "exception_type": "CLOSED"},
                {"local_date": "2024-12-24", "exception_type": "OPEN"},
            ]
        },
    )
    assert bulk_conflict.status_code == 400
    listed = client.get(f"{base}/exceptions/", params={"source": "user"})
    assert [(row["local_date"], row["exception_type"]) for row in listed.json()["items"]] == [
        ("2024-11-28", "CLOSED"),
        ("2024-11-29", "EARLY_CLOSE"),
    ]

    window = {"start_date": "2024-11-27", "end_date": "2024-11-30"}
    dates = client.get(f"{base}/dates/", params=window)
    assert dates.status_code == 200
    assert [
        (item["local_date"], item["is_business_day"], item["is_holiday"], item["is_early_close"])
        for item in dates.json()["items"]
    ] == [
        ("2024-11-27", True, False, False),
        ("2024-11-28", False, True, False),
        ("2024-11-29", True, False, True),
        ("2024-11-30", False, False, False),
    ]
    assert dates.json()["items"][1]["holiday_name"] == "Thanksgiving Day"
    assert dates.json()["items"][3]["is_weekend"] is True
    holidays = client.get(f"{base}/dates/", params={**window, "is_holiday": "true"})
    assert [item["local_date"] for item in holidays.json()["items"]] == ["2024-11-28"]

    sessions = client.get(f"{base}/sessions/", params=window)
    assert sessions.status_code == 200
    assert [
        (item["local_date"], item["opens_at"], item["closes_at"], item["is_early_close"])
        for item in sessions.json()["items"]
    ] == [
        ("2024-11-27", "2024-11-27T14:30:00Z", "2024-11-27T21:00:00Z", False),
        ("2024-11-29", "2024-11-29T14:30:00Z", "2024-11-29T18:00:00Z", True),
    ]

    outside = client.get(
        f"{base}/sessions/", params={"start_date": "2024-12-30", "end_date": "2025-01-03"}
    )
    assert outside.status_code == 400
    assert outside.json() == {
        "detail": (
            "Calendar 'XNYS' is complete from 2024-01-01 to 2024-12-31; "
            "2024-12-30 to 2025-01-03 is outside that range."
        )
    }
    unknown = client.get(f"/api/v1/calendar/{uuid.uuid4().hex}/dates/", params=window)
    assert unknown.status_code == 404

    # Deleting the user's closure restores the rule's answer for that date.
    assert client.delete(f"{base}/exceptions/{path_uid(closed)}/").status_code == 200
    restored = client.get(
        f"{base}/dates/", params={"start_date": "2024-11-28", "end_date": "2024-11-28"}
    )
    assert restored.json()["items"][0]["is_business_day"] is True
