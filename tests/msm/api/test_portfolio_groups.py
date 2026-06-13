from __future__ import annotations

import uuid

import pytest

from msm.api.portfolios import Portfolio, PortfolioGroup, PortfolioGroupMembership


def test_portfolio_group_add_portfolio_resolves_unique_identifiers(monkeypatch) -> None:
    portfolio_group_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    captured: dict[str, object] = {}
    membership = PortfolioGroupMembership(
        uid=uuid.uuid4(),
        portfolio_group_uid=portfolio_group_uid,
        portfolio_uid=portfolio_uid,
    )

    monkeypatch.setattr(
        PortfolioGroup,
        "get_by_unique_identifier",
        classmethod(
            lambda cls, unique_identifier: PortfolioGroup(
                uid=portfolio_group_uid,
                unique_identifier=unique_identifier,
                display_name="Core",
            )
        ),
    )
    monkeypatch.setattr(
        Portfolio,
        "get_by_unique_identifier",
        classmethod(
            lambda cls, unique_identifier: Portfolio(
                uid=portfolio_uid,
                unique_identifier=unique_identifier,
                calendar_uid=uuid.uuid4(),
            )
        ),
    )

    def fake_add(**kwargs):
        captured.update(kwargs)
        return membership

    monkeypatch.setattr(
        PortfolioGroupMembership,
        "add",
        classmethod(lambda cls, **kw: fake_add(**kw)),
    )

    result = PortfolioGroup.add_portfolio(
        portfolio_group_unique_identifier="core",
        portfolio_unique_identifier="portfolio-alpha",
    )

    assert result is membership
    assert captured == {
        "portfolio_group_uid": str(portfolio_group_uid),
        "portfolio_uid": str(portfolio_uid),
    }


def test_portfolio_group_add_portfolio_rejects_ambiguous_references() -> None:
    with pytest.raises(ValueError, match="portfolio_group_uid"):
        PortfolioGroup.add_portfolio(
            portfolio_group_uid=uuid.uuid4(),
            portfolio_group_unique_identifier="core",
            portfolio_uid=uuid.uuid4(),
        )

    with pytest.raises(ValueError, match="portfolio_uid"):
        PortfolioGroup.add_portfolio(
            portfolio_group_uid=uuid.uuid4(),
            portfolio_uid=uuid.uuid4(),
            portfolio_unique_identifier="portfolio-alpha",
        )


def test_portfolio_group_membership_bulk_delete_delegates_to_service(monkeypatch) -> None:
    captured: dict[str, object] = {}
    result = {"detail": "Deleted 1 portfolio group membership.", "deleted_count": 1}

    monkeypatch.setattr(
        PortfolioGroupMembership, "_active_context", classmethod(lambda cls: object())
    )

    def fake_bulk_delete(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return result

    monkeypatch.setattr(
        "msm.services.portfolios.bulk_delete_portfolio_group_memberships",
        fake_bulk_delete,
    )
    monkeypatch.setattr(
        "msm.services.bulk_delete_portfolio_group_memberships",
        fake_bulk_delete,
        raising=False,
    )

    membership_uid = uuid.uuid4()
    response = PortfolioGroupMembership.bulk_delete(uids=[membership_uid])

    assert response == result
    assert captured["uids"] == [str(membership_uid)]
