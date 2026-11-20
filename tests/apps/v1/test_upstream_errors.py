"""A refused or failed MetaTables call answers with its reason, not a bare 500 (MainSequenceMarkets#84).

A statement MetaTables rejects as invalid is the Markets API's own fault and answers
``500`` (MainSequenceMarkets#87); any other refusal answers ``502``.

The SDK errors are built the way the MetaTables client builds them: from an HTTP
response, by ``mainsequence.client.exceptions.raise_for_response``, with the request
payload attached.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from mainsequence.client.exceptions import TransportError
from metatables import MetaTableTransactionGuardError
from metatables.endpoint import ApiResolutionError

from apps.v1.main import app
from apps.v1.upstream_errors import (
    INVALID_STATEMENT_CODES,
    MAX_REASON_CHARACTERS,
    install_upstream_error_handlers,
)
from tests.support.upstream_errors import STATEMENT_TOO_LONG, sdk_error
from tests.support.markets_runtime import serve_runtime

ROWS_ROUTE = "/api/v1/rows/asset/upsert_many/"
ROWS_BODY = {"arguments": {"payloads": [{"unique_identifier": "A", "asset_type": "equity"}]}}


@pytest.fixture
def client(monkeypatch) -> TestClient:
    serve_runtime(
        monkeypatch, lambda **_kwargs: SimpleNamespace(context=SimpleNamespace(timeout=None))
    )
    return TestClient(app)


@pytest.fixture
def handler_client() -> TestClient:
    """An application with only the upstream error handlers, raising what a test gives it."""

    handled = FastAPI()
    install_upstream_error_handlers(handled)

    @handled.post("/raise/")
    def _raise(request: Request) -> None:
        raise request.app.state.error

    return TestClient(handled)


def _status_for(handler_client: TestClient, error: Exception) -> int:
    handler_client.app.state.error = error
    return handler_client.post("/raise/").status_code


@pytest.mark.parametrize("code", sorted(INVALID_STATEMENT_CODES))
@pytest.mark.parametrize("upstream_status", [400, 422])
def test_every_invalid_statement_code_answers_500(handler_client, code, upstream_status) -> None:
    error = sdk_error(upstream_status, {"detail": {"code": code, "detail": "rejected"}})

    assert _status_for(handler_client, error) == 500


def test_a_code_metatables_sends_as_the_whole_detail_is_read(handler_client) -> None:
    # check_wire_contract answers HTTPException(422, exc.code).
    error = sdk_error(422, {"detail": "compiled_sql_dialect_mismatch"})

    assert _status_for(handler_client, error) == 500


@pytest.mark.parametrize(
    ("upstream_status", "body"),
    [
        # Permissions.
        (400, {"detail": {"code": "sql_scope_denied", "detail": "sql_scope_denied"}}),
        (400, {"detail": {"code": "relation_read_denied", "detail": "relation_read_denied"}}),
        (403, {"detail": "Caller assertion is not accepted locally."}),
        # A missing table.
        (404, {"detail": "MetaTable not found."}),
        # Conflicts.
        (409, {"detail": {"code": "compiled_sql_guard_failed", "detail": "Statement 0 missed."}}),
        (409, {"detail": "MetaTable is reserved."}),
        # A request MetaTables' schema refuses.
        (422, {"detail": [{"loc": ["body", "statement", "sql"], "msg": "too long"}]}),
    ],
)
def test_other_refusals_answer_502(handler_client, upstream_status, body) -> None:
    assert _status_for(handler_client, sdk_error(upstream_status, body)) == 502


@pytest.mark.parametrize("upstream_status", [500, 503, 429])
def test_an_invalid_statement_code_on_a_failure_answers_503(handler_client, upstream_status):
    body = {"detail": {"code": "compiled_sql_database_error", "detail": "x"}}
    error = sdk_error(upstream_status, body)

    assert _status_for(handler_client, error) == 503


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


def test_an_invalid_statement_answers_500_as_markets_own_error(client, monkeypatch) -> None:
    """A statement the database rejects fails the same way on every retry (#87)."""

    _fail_bulk_upsert(
        monkeypatch,
        sdk_error(
            400,
            {
                "detail": {
                    "code": "compiled_sql_database_error",
                    "detail": 'syntax error at or near "WHERE"',
                    "statement_index": 2,
                    "label": None,
                }
            },
        ),
    )

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 500
    assert response.json() == {
        "detail": (
            "The Markets API sent a statement the upstream API rejects as invalid. "
            "This is a fault of the Markets API; a retry fails the same way. "
            "The upstream API answered 400: compiled_sql_database_error: "
            'syntax error at or near "WHERE" (statement 2)'
        ),
        "error_type": "InvalidStatementError",
        "upstream_status": 400,
    }
    assert "Retry-After" not in response.headers
    assert "INSERT" not in response.text


def test_a_refusal_of_the_caller_answers_502(client, monkeypatch) -> None:
    _fail_bulk_upsert(
        monkeypatch,
        sdk_error(400, {"detail": {"code": "sql_scope_denied", "detail": "sql_scope_denied"}}),
    )

    response = client.post(ROWS_ROUTE, json=ROWS_BODY)

    assert response.status_code == 502
    assert response.json() == {
        "detail": "The upstream API answered 400: sql_scope_denied: sql_scope_denied",
        "error_type": "UpstreamApiError",
        "upstream_status": 400,
    }


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
    # The reason is cut; what the answer says around it is not.
    assert len(detail) < MAX_REASON_CHARACTERS + 200


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
