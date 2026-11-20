"""A refused or failed MetaTables call answers with its reason, not a bare 500 (MainSequenceMarkets#84).

The SDK errors are built the way the MetaTables client builds them: from an HTTP
response, by ``mainsequence.client.exceptions.raise_for_response``, with the request
payload attached.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mainsequence.client.exceptions import TransportError
from metatables import MetaTableTransactionGuardError
from metatables.endpoint import ApiResolutionError

from apps.v1.main import app
from apps.v1.upstream_errors import MAX_REASON_CHARACTERS
from tests.support.upstream_errors import STATEMENT_TOO_LONG, sdk_error

ROWS_ROUTE = "/api/v1/rows/asset/upsert_many/"
ROWS_BODY = {"arguments": {"payloads": [{"unique_identifier": "A", "asset_type": "equity"}]}}


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **kwargs: SimpleNamespace(context=SimpleNamespace(timeout=None)),
    )
    return TestClient(app)


def _fail_bulk_upsert(monkeypatch, error: Exception) -> None:
    def bulk_upsert_model(context, *, model, values, conflict_columns):
        raise error

    monkeypatch.setattr("msm.repositories.crud.bulk_upsert_model", bulk_upsert_model)


def test_a_refused_statement_answers_502_with_the_reason(client, monkeypatch) -> None:
    _fail_bulk_upsert(monkeypatch, STATEMENT_TOO_LONG)

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 502
    assert response.json() == {
        "detail": (
            "The upstream API answered 422: "
            "body.statement.sql: String should have at most 1000000 characters"
        ),
        "error_type": "UpstreamApiError",
        "upstream_status": 422,
    }
    # Neither the value the validation error echoes nor the request the SDK keeps.
    assert "INSERT" not in response.text
    assert "secret_value" not in response.text


def test_a_database_error_answers_502_with_its_code_and_statement(client, monkeypatch) -> None:
    _fail_bulk_upsert(
        monkeypatch,
        sdk_error(
            400,
            {
                "detail": {
                    "code": "compiled_sql_database_error",
                    "detail": 'duplicate key value violates unique constraint "uq_asset"',
                    "statement_index": 2,
                    "label": None,
                }
            },
        ),
    )

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The upstream API answered 400: compiled_sql_database_error: "
        'duplicate key value violates unique constraint "uq_asset" (statement 2)'
    )
    assert response.json()["upstream_status"] == 400


def test_an_unhandled_guard_refusal_answers_502(client, monkeypatch) -> None:
    _fail_bulk_upsert(
        monkeypatch,
        MetaTableTransactionGuardError(
            "Statement 0 returned 1 rows; expected 0.",
            statement_index=0,
            label="upsert_status",
            expect_rows=0,
            row_count=1,
            response=sdk_error(409, {"detail": "Statement 0 returned 1 rows; expected 0."}).response,
        ),
    )

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 502
    assert response.json()["upstream_status"] == 409
    assert response.json()["detail"].endswith("Statement 0 returned 1 rows; expected 0.")


@pytest.mark.parametrize("upstream_status", [500, 503, 429])
def test_an_upstream_failure_answers_503_and_keeps_retry_after(
    client, monkeypatch, upstream_status
) -> None:
    _fail_bulk_upsert(
        monkeypatch,
        sdk_error(upstream_status, {"detail": "DataSource is unavailable."}, headers={"Retry-After": "1"}),
    )

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json() == {
        "detail": f"The upstream API answered {upstream_status}: DataSource is unavailable.",
        "error_type": "UpstreamApiError",
        "upstream_status": upstream_status,
    }


def test_no_upstream_answer_is_a_503(client, monkeypatch) -> None:
    _fail_bulk_upsert(monkeypatch, TransportError("Request failed after retries (expired)"))

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The upstream API did not answer: Request failed after retries (expired)",
        "error_type": "UpstreamApiError",
        "upstream_status": None,
    }


def test_an_unreachable_metatables_api_is_a_503(client, monkeypatch) -> None:
    _fail_bulk_upsert(
        monkeypatch,
        ApiResolutionError("MetaTables deployment is unavailable; check its deployment status."),
    )

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 503
    assert response.json() == {
        "detail": (
            "The MetaTables API could not be reached: "
            "MetaTables deployment is unavailable; check its deployment status."
        ),
        "error_type": "UpstreamApiError",
        "upstream_status": None,
    }


def test_credentials_in_a_url_and_long_reasons_do_not_reach_the_caller(client, monkeypatch) -> None:
    _fail_bulk_upsert(
        monkeypatch,
        sdk_error(
            400,
            {
                "detail": {
                    "code": "compiled_sql_database_error",
                    "detail": "connection to postgresql://markets:hunter2@db.internal:5432/markets "
                    "failed " + "x" * 5000,
                }
            },
        ),
    )

    detail = client.post(ROWS_ROUTE, json=ROWS_BODY).json()["detail"]

    assert "hunter2" not in detail and "markets:" not in detail
    assert "postgresql://***@db.internal:5432/markets" in detail
    assert len(detail) < MAX_REASON_CHARACTERS + 100


def test_an_answer_that_is_not_json_is_reported_by_its_text(client, monkeypatch) -> None:
    _fail_bulk_upsert(monkeypatch, sdk_error(502, "<html>Bad Gateway</html>"))

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 503
    assert response.json()["detail"] == "The upstream API answered 502: <html>Bad Gateway</html>"


def test_every_router_answers_the_same_way(client, monkeypatch) -> None:
    """The handler is the application's, so a typed route answers as the rows route does."""

    def bulk_upsert_calendar_session_rules(*, calendar_uid, rows):
        raise STATEMENT_TOO_LONG

    monkeypatch.setattr(
        "apps.v1.routers.calendars.bulk_upsert_calendar_session_rules",
        bulk_upsert_calendar_session_rules,
    )

    response = client.post(
        f"/api/v1/calendar/{uuid.uuid4()}/rules/bulk-upsert/",
        json={"rows": [{"effective_from": "2026-01-01", "weekdays": "1111100"}]},
    )

    assert response.status_code == 502
    assert response.json()["error_type"] == "UpstreamApiError"
    assert response.json()["upstream_status"] == 422


def test_errors_a_row_operation_raises_itself_keep_their_answers(client, monkeypatch) -> None:
    _fail_bulk_upsert(monkeypatch, ValueError("Asset upsert received the conflict key twice."))

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 400
    assert response.json()["error_type"] == "ValueError"
