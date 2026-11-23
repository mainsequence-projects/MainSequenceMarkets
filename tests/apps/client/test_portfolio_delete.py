"""Typed ``MarketsClient`` methods for the two portfolio delete routes (ADR 0049)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.api.portfolios import PortfolioBulkDeleteResponse, PortfolioDeleteResponse
from msm.api.remote import MarketsConflictError
from msm.client import MarketsClient
from msm_portfolios.services.portfolio_deletion import PortfolioDeleteConflictError

DELETED_ROWS = {
    "weights": 3,
    "values": 2,
    "rebalance_state": 1,
    "analytics": 0,
    "event_ledger": 4,
    "state": 2,
    "cash_flows": 1,
}
REFUSAL = (
    "Portfolio 'example-sleeve' cannot be deleted; nothing was deleted. 1 virtual fund "
    "targets it (VirtualFundTable.target_portfolio_uid, ON DELETE RESTRICT)."
)


@pytest.fixture
def client() -> MarketsClient:
    return MarketsClient("http://testserver", session=TestClient(app))


def _deleted(uid: str) -> dict[str, object]:
    return {
        "detail": "Portfolio 'example-sleeve' deleted with its datasets.",
        "uid": uid,
        "unique_identifier": "example-sleeve",
        "deleted_count": 1,
        "deleted_rows": DELETED_ROWS,
    }


def _allowed_preflight(**kwargs) -> dict[str, object]:
    return {
        "allowed": True,
        "matched_count": len(kwargs["uids"]),
        "blockers": [],
        "warnings": [],
    }


def _no_delete(**_kwargs):
    pytest.fail("The bulk delete must not run.")


class _Plan:
    """The bulk route's checks, run once; its deletes reuse them (issue 96)."""

    def __init__(self, answer: dict[str, object]) -> None:
        self.answer = answer

    def preflight(self) -> dict[str, object]:
        return self.answer


def test_deletes_one_portfolio_with_its_datasets(monkeypatch, client) -> None:
    portfolio_uid = uuid.uuid4()
    received: list[str] = []

    def fake_delete(*, uid):
        received.append(uid)
        return _deleted(uid)

    monkeypatch.setattr("apps.v1.routers.portfolios.delete_portfolio", fake_delete)

    deleted = client.delete_portfolio(portfolio_uid)

    assert received == [str(portfolio_uid)]
    assert isinstance(deleted, PortfolioDeleteResponse)
    assert deleted.uid == str(portfolio_uid)
    assert deleted.deleted_rows == DELETED_ROWS


def test_deleting_a_missing_portfolio_raises_lookup_error(monkeypatch, client) -> None:
    monkeypatch.setattr("apps.v1.routers.portfolios.delete_portfolio", lambda *, uid: None)
    portfolio_uid = uuid.uuid4()

    with pytest.raises(LookupError, match=f"Portfolio '{portfolio_uid}' was not found."):
        client.delete_portfolio(portfolio_uid)


def test_a_refused_delete_raises_a_conflict(monkeypatch, client) -> None:
    def refused(*, uid):
        raise PortfolioDeleteConflictError(REFUSAL)

    monkeypatch.setattr("apps.v1.routers.portfolios.delete_portfolio", refused)

    with pytest.raises(MarketsConflictError) as conflict:
        client.delete_portfolio(uuid.uuid4())

    assert str(conflict.value) == REFUSAL


def test_bulk_delete_sends_an_explicit_selection(monkeypatch, client) -> None:
    first, second = uuid.uuid4(), str(uuid.uuid4())
    calls: list[tuple[str, list[str]]] = []

    def fake_plan(**kwargs):
        calls.append(("plan", kwargs["uids"]))
        return _Plan(_allowed_preflight(**kwargs))

    def fake_bulk_delete(*, uids, plan):
        assert isinstance(plan, _Plan)
        calls.append(("delete", uids))
        return PortfolioBulkDeleteResponse.model_validate(
            {
                "detail": "Deleted 2 portfolios with their datasets.",
                "deleted_count": 2,
                "deleted": [_deleted(uid) for uid in uids],
                "failed": [],
            }
        )

    monkeypatch.setattr("apps.v1.routers.portfolios.plan_bulk_delete_portfolios", fake_plan)
    monkeypatch.setattr("apps.v1.routers.portfolios.bulk_delete_portfolios", fake_bulk_delete)

    response = client.bulk_delete_portfolios([first, second])

    assert calls == [("plan", [str(first), second]), ("delete", [str(first), second])]
    assert isinstance(response, PortfolioBulkDeleteResponse)
    assert response.deleted_count == 2
    assert all(isinstance(item, PortfolioDeleteResponse) for item in response.deleted)
    assert [item.uid for item in response.deleted] == [str(first), second]
    assert response.failed == []


def test_a_partly_refused_bulk_delete_answers_what_it_did_not_delete(monkeypatch, client) -> None:
    # Issue 127: a refused portfolio never stops the others, and nothing is raised.
    deleted_uid, failed_uid = str(uuid.uuid4()), str(uuid.uuid4())
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.plan_bulk_delete_portfolios",
        lambda **kwargs: _Plan(_allowed_preflight(**kwargs)),
    )
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.bulk_delete_portfolios",
        lambda *, uids, plan: PortfolioBulkDeleteResponse.model_validate(
            {
                "detail": "Deleted 1 portfolio with its datasets. 1 could not be deleted.",
                "deleted_count": 1,
                "deleted": [_deleted(deleted_uid)],
                "failed": [{"uid": failed_uid, "detail": REFUSAL}],
            }
        ),
    )

    response = client.bulk_delete_portfolios([deleted_uid, failed_uid])

    assert [item.uid for item in response.deleted] == [deleted_uid]
    assert [(item.uid, item.detail) for item in response.failed] == [(failed_uid, REFUSAL)]


def test_bulk_delete_needs_a_portfolio_before_sending(monkeypatch, client) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.plan_bulk_delete_portfolios",
        lambda **_kwargs: pytest.fail("An empty selection must not reach the Markets API."),
    )
    monkeypatch.setattr("apps.v1.routers.portfolios.bulk_delete_portfolios", _no_delete)

    with pytest.raises(ValueError, match="at least 1 item"):
        client.bulk_delete_portfolios([])
