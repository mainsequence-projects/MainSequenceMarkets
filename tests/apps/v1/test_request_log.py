"""Each API request logs how many MetaTables operations it sent (issue 94)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1 import request_log
from apps.v1.main import app
from metatables import MetaTable
from msm.repositories.operation_count import count_operation, counting_operations
from tests.support.account_snapshots import seed_account_snapshots


@pytest.fixture
def lines(monkeypatch):
    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        request_log,
        "logger",
        SimpleNamespace(info=lambda message, **fields: logged.append((message, fields))),
    )
    return logged


@pytest.fixture
def account(sqlite_markets, monkeypatch):
    for runtime in ("_get_target_positions_runtime", "_get_holdings_by_fund_runtime"):
        monkeypatch.setattr(
            f"apps.v1.services.accounts.{runtime}",
            lambda: SimpleNamespace(context=sqlite_markets.context),
        )
    return seed_account_snapshots(sqlite_markets.engine, held=2)


def test_a_request_logs_its_operations_by_route_and_not_by_uid(account, lines) -> None:
    client = TestClient(app)

    assert client.get(f"/api/v1/account/{account}/target-positions/").status_code == 200
    assert client.get(f"/api/v1/account/{account}/holdings/by-fund/").status_code == 200

    assert [fields["metatables_operations"] for _message, fields in lines] == [1, 2]
    message, fields = lines[0]
    # The hosted log keeps a line's message and drops its fields, so the count is in both.
    assert message.startswith("MetaTables operations=1 GET ")
    assert "/account/{account_uid}/target-positions/ status=200 duration_ms=" in message
    assert str(account) not in message
    assert fields["status_code"] == 200


def test_a_request_without_operations_logs_no_line(lines) -> None:
    TestClient(app).get("/openapi.json")

    assert lines == []


def test_a_failed_request_logs_what_it_sent(account, lines, monkeypatch) -> None:
    def refused(cls, operation, *, timeout=None):
        raise RuntimeError("refused")

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(refused))

    response = TestClient(app, raise_server_exceptions=False).get(
        f"/api/v1/account/{account}/target-positions/"
    )

    assert response.status_code == 500
    assert [(f["metatables_operations"], f["status_code"]) for _m, f in lines] == [(1, 500)]


def test_the_platforms_completion_line_gets_the_count(account, lines) -> None:
    scopes: list[dict] = []

    async def launcher(scope, receive, send):
        await app(scope, receive, send)
        scopes.append(scope)

    TestClient(launcher).get(f"/api/v1/account/{account}/target-positions/")

    assert scopes[-1]["state"]["platform_log_fields"]["metatables_operations"] == 1


def test_operations_outside_a_count_are_not_counted() -> None:
    count_operation()
    with counting_operations() as counted:
        count_operation()
    count_operation()

    assert counted.operations == 1
