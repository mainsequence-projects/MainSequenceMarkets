from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.schemas.portfolio_groups import (
    Portfolio,
    PortfolioGroup,
    PortfolioGroupDeleteResponse,
    PortfolioGroupMembership,
)


def _portfolio_group_row(
    *,
    uid: uuid.UUID | None = None,
    unique_identifier: str = "core-portfolios",
) -> PortfolioGroup:
    return PortfolioGroup(
        uid=uid or uuid.uuid4(),
        unique_identifier=unique_identifier,
        display_name="Core Portfolios",
        description="Core portfolio group",
    )


def _portfolio_row(
    *,
    uid: uuid.UUID | None = None,
    unique_identifier: str = "portfolio-alpha",
) -> Portfolio:
    return Portfolio(
        uid=uid or uuid.uuid4(),
        unique_identifier=unique_identifier,
        calendar_uid=uuid.uuid4(),
    )


def test_list_portfolio_groups_returns_paginated_groups(monkeypatch) -> None:
    group = _portfolio_group_row()
    captured: dict[str, object] = {}

    def fake_list_portfolio_groups(**kwargs):
        captured.update(kwargs)
        return [group]

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_groups.list_portfolio_groups",
        fake_list_portfolio_groups,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/portfolio-group/",
        params={"search": "core", "limit": 50, "offset": 0},
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "uid": str(group.uid),
            "unique_identifier": "core-portfolios",
            "display_name": "Core Portfolios",
            "description": "Core portfolio group",
            "metadata_json": None,
        }
    ]
    assert captured["search"] == "core"


def test_create_portfolio_group_returns_group(monkeypatch) -> None:
    group = _portfolio_group_row()
    captured: dict[str, object] = {}

    def fake_create_portfolio_group(*, payload):
        captured["payload"] = payload
        return group

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_groups.create_portfolio_group",
        fake_create_portfolio_group,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/portfolio-group/",
        json={
            "unique_identifier": "core-portfolios",
            "display_name": "Core Portfolios",
        },
    )

    assert response.status_code == 200
    assert response.json()["uid"] == str(group.uid)
    assert captured["payload"] == {
        "unique_identifier": "core-portfolios",
        "display_name": "Core Portfolios",
    }


def test_add_portfolio_to_group_returns_membership(monkeypatch) -> None:
    group_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    membership = PortfolioGroupMembership(
        uid=uuid.uuid4(),
        portfolio_group_uid=group_uid,
        portfolio_uid=portfolio_uid,
    )
    captured: dict[str, object] = {}

    def fake_add_portfolio_to_group(**kwargs):
        captured.update(kwargs)
        return membership

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_groups.add_portfolio_to_group",
        fake_add_portfolio_to_group,
    )

    client = TestClient(app)
    response = client.post(
        f"/api/v1/portfolio-group/{group_uid}/portfolios/",
        json={"portfolio_uid": str(portfolio_uid)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "uid": str(membership.uid),
        "portfolio_group_uid": str(group_uid),
        "portfolio_uid": str(portfolio_uid),
    }
    assert captured == {
        "portfolio_group_uid": str(group_uid),
        "payload": {"portfolio_uid": portfolio_uid},
    }


def test_list_portfolios_in_group_returns_paginated_portfolios(monkeypatch) -> None:
    portfolio = _portfolio_row()
    captured: dict[str, object] = {}

    def fake_list_portfolios_in_group(**kwargs):
        captured.update(kwargs)
        return [portfolio]

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_groups.list_portfolios_in_group",
        fake_list_portfolios_in_group,
    )

    client = TestClient(app)
    group_uid = uuid.uuid4()
    response = client.get(f"/api/v1/portfolio-group/{group_uid}/portfolios/")

    assert response.status_code == 200
    assert response.json()["results"][0]["unique_identifier"] == "portfolio-alpha"
    assert captured["portfolio_group_uid"] == str(group_uid)


def test_list_groups_for_portfolio_returns_paginated_groups(monkeypatch) -> None:
    group = _portfolio_group_row()
    captured: dict[str, object] = {}

    def fake_list_groups_for_portfolio(**kwargs):
        captured.update(kwargs)
        return [group]

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_groups.list_groups_for_portfolio",
        fake_list_groups_for_portfolio,
    )

    client = TestClient(app)
    portfolio_uid = uuid.uuid4()
    response = client.get(f"/api/v1/portfolio-group/by-portfolio/{portfolio_uid}/")

    assert response.status_code == 200
    assert response.json()["results"][0]["unique_identifier"] == "core-portfolios"
    assert captured["portfolio_uid"] == str(portfolio_uid)


def test_bulk_delete_portfolio_groups_returns_deleted_count(monkeypatch) -> None:
    group_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_bulk_delete_portfolio_groups(*, payload):
        captured["payload"] = payload
        return PortfolioGroupDeleteResponse(
            detail="Deleted 1 portfolio group.",
            deleted_count=1,
        )

    monkeypatch.setattr(
        "apps.v1.routers.portfolio_groups.bulk_delete_portfolio_groups",
        fake_bulk_delete_portfolio_groups,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/portfolio-group/bulk-delete/",
        json={"uids": [str(group_uid)]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Deleted 1 portfolio group.",
        "deleted_count": 1,
    }
    assert captured["payload"]["uids"] == [str(group_uid)]
