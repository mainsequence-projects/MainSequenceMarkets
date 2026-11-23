"""Typed ``MarketsClient`` methods for portfolio retirement and its account targets."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.api.accounts import PortfolioAccountTarget
from msm.api.portfolios import Portfolio
from msm.api.remote import MarketsConflictError
from msm.client import MarketsClient
from msm.services.portfolio_lifecycle import PortfolioRetirementConflictError

RETIRED_AT = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def client() -> MarketsClient:
    return MarketsClient("http://testserver", session=TestClient(app))


def _portfolio(uid: str, retired_at: dt.datetime | None) -> dict[str, object]:
    return {
        "uid": uid,
        "unique_identifier": "example-sleeve",
        "calendar_uid": str(uuid.uuid4()),
        "retired_at": retired_at,
    }


def test_reads_the_accounts_targeting_a_portfolio(monkeypatch, client) -> None:
    portfolio_uid = str(uuid.uuid4())
    account_uid = str(uuid.uuid4())
    received: dict[str, object] = {}

    def fake_list(*, uid, limit, offset):
        received.update(uid=uid, limit=limit, offset=offset)
        return {
            "count": 1,
            "results": [
                {
                    "account_uid": account_uid,
                    "account_target_allocation_uid": str(uuid.uuid4()),
                    "position_set_uid": str(uuid.uuid4()),
                    "target_positions_date": RETIRED_AT,
                    "weight_notional_exposure": "0.5",
                }
            ],
        }

    monkeypatch.setattr("apps.v1.routers.portfolios.list_portfolio_account_targets", fake_list)

    page = client.portfolio_account_targets(portfolio_uid, limit=50, offset=0)

    assert received == {"uid": portfolio_uid, "limit": 50, "offset": 0}
    assert isinstance(page.items[0], PortfolioAccountTarget)
    assert page.items[0].account_uid == account_uid
    assert page.items[0].weight_notional_exposure == "0.5"
    assert page.page_info.total_items == 1


def test_retires_and_reinstates_a_portfolio(monkeypatch, client) -> None:
    portfolio_uid = str(uuid.uuid4())
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.retire_portfolio",
        lambda *, uid: _portfolio(uid, RETIRED_AT),
    )
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.reinstate_portfolio",
        lambda *, uid: _portfolio(uid, None),
    )

    retired = client.retire_portfolio(portfolio_uid)
    reinstated = client.reinstate_portfolio(portfolio_uid)

    assert isinstance(retired, Portfolio)
    assert retired.retired_at == RETIRED_AT
    assert reinstated.retired_at is None


def test_a_refused_retirement_raises_a_conflict(monkeypatch, client) -> None:
    def refused(*, uid):
        raise PortfolioRetirementConflictError(portfolio_uid=uid, account_count=1)

    monkeypatch.setattr("apps.v1.routers.portfolios.retire_portfolio", refused)

    with pytest.raises(MarketsConflictError, match="1 account's current target names it"):
        client.retire_portfolio(uuid.uuid4())


def test_bulk_retires_and_answers_what_it_did_not_retire(monkeypatch, client) -> None:
    # Issue 124: one call; a refused portfolio never stops the others.
    from msm.api.portfolios import PortfolioBulkRetireResponse

    retired_uid, refused_uid = str(uuid.uuid4()), str(uuid.uuid4())
    refusal = str(PortfolioRetirementConflictError(portfolio_uid=refused_uid, account_count=1))
    received: list[list[str]] = []

    def fake_bulk_retire(*, uids):
        received.append(uids)
        return PortfolioBulkRetireResponse(
            retired=[_portfolio(retired_uid, RETIRED_AT)],
            failed=[{"uid": refused_uid, "detail": refusal}],
        )

    monkeypatch.setattr("apps.v1.routers.portfolios.bulk_retire_portfolios", fake_bulk_retire)

    response = client.bulk_retire_portfolios([uuid.UUID(retired_uid), refused_uid])

    assert received == [[retired_uid, refused_uid]]
    assert isinstance(response.retired[0], Portfolio)
    assert response.retired[0].retired_at == RETIRED_AT
    assert [(item.uid, item.detail) for item in response.failed] == [(refused_uid, refusal)]
