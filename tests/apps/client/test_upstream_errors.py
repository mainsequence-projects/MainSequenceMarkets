"""A MetaTables refusal behind the Markets API reaches a row call typed.

MainSequenceMarkets#84, and #87 for an invalid statement.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.api.assets import Asset
from msm.api.remote import (
    MarketsApiError,
    MarketsInvalidStatementError,
    MarketsUpstreamError,
    raise_for_error,
    use_remote_backend,
    use_runtime_backend,
)
from msm.client import MarketsClient
from tests.support.upstream_errors import STATEMENT_TOO_LONG, sdk_error

ROWS = [{"unique_identifier": "A", "asset_type": "equity"}]


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **kwargs: SimpleNamespace(context=SimpleNamespace(timeout=None)),
    )
    client = MarketsClient("http://testserver", session=TestClient(app))
    use_remote_backend(client.backend)
    try:
        yield client
    finally:
        use_runtime_backend()


def _fail_bulk_upsert(monkeypatch, error: Exception) -> None:
    def bulk_upsert_model(context, *, model, values, conflict_columns):
        raise error

    monkeypatch.setattr("msm.repositories.crud.bulk_upsert_model", bulk_upsert_model)


def test_a_refusal_raises_the_upstream_error_with_its_reason(monkeypatch, remote) -> None:
    _fail_bulk_upsert(monkeypatch, STATEMENT_TOO_LONG)

    with pytest.raises(MarketsUpstreamError) as raised:
        Asset.upsert_many(ROWS)

    assert str(raised.value) == (
        "The upstream API answered 422: "
        "body.statement.sql: String should have at most 1000000 characters"
    )
    assert raised.value.status_code == 502
    assert not raised.value.retryable
    # Not one of the errors the row call raises for the caller's own input.
    assert isinstance(raised.value, MarketsApiError)
    assert not isinstance(raised.value, (ValueError, LookupError, PermissionError))


def test_an_upstream_failure_is_retryable(monkeypatch, remote) -> None:
    _fail_bulk_upsert(monkeypatch, sdk_error(503, {"detail": "DataSource is unavailable."}))

    with pytest.raises(MarketsUpstreamError, match="DataSource is unavailable") as raised:
        Asset.upsert_many(ROWS)

    assert raised.value.status_code == 503
    assert raised.value.retryable


def test_a_502_without_the_error_type_is_not_an_upstream_error() -> None:
    """A proxy in front of the Markets API answers 502 too; only the API names its upstream."""

    with pytest.raises(MarketsApiError, match="Markets API returned 502") as raised:
        raise_for_error(502, "Bad Gateway", None)

    assert not isinstance(raised.value, MarketsUpstreamError)


def test_an_invalid_statement_raises_the_markets_apis_own_error(monkeypatch, remote) -> None:
    """MetaTables rejecting a compiled statement is the Markets API's fault (#87)."""

    _fail_bulk_upsert(
        monkeypatch,
        sdk_error(
            400,
            {
                "detail": {
                    "code": "compiled_sql_database_error",
                    "detail": 'syntax error at or near "WHERE"',
                }
            },
        ),
    )

    with pytest.raises(
        MarketsInvalidStatementError, match='syntax error at or near "WHERE"'
    ) as raised:
        Asset.upsert_many(ROWS)

    assert raised.value.status_code == 500
    assert not raised.value.retryable
    assert isinstance(raised.value, MarketsApiError)
    assert not isinstance(
        raised.value, (MarketsUpstreamError, ValueError, LookupError, PermissionError)
    )


def test_a_500_without_the_error_type_is_not_an_invalid_statement() -> None:
    with pytest.raises(MarketsApiError, match="Markets API returned 500") as raised:
        raise_for_error(500, "Internal Server Error", None)

    assert not isinstance(raised.value, MarketsInvalidStatementError)
