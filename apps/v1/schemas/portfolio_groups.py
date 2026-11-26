from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from msm.api.http import BulkDeletedRow, BulkDeleteFailure


def _portfolio_contract():
    from msm.api.portfolios import Portfolio

    return Portfolio


def _portfolio_group_contract():
    from msm.api.portfolios import PortfolioGroup

    return PortfolioGroup


def _portfolio_group_membership_contract():
    from msm.api.portfolios import PortfolioGroupMembership

    return PortfolioGroupMembership


Portfolio = _portfolio_contract()
PortfolioGroup = _portfolio_group_contract()
PortfolioGroupMembership = _portfolio_group_membership_contract()


class PortfolioGroupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class PortfolioGroupUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class PortfolioGroupDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int = 0


class PortfolioGroupBulkDeleteResponse(BaseModel):
    """What a bulk delete of portfolio groups did: the groups it deleted, in one
    statement, and each selected group it did not delete, with the reason."""

    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int = 0
    deleted: list[BulkDeletedRow] = Field(default_factory=list)
    failed: list[BulkDeleteFailure] = Field(default_factory=list)


class PortfolioGroupMembershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_uid: UUID | None = None
    portfolio_unique_identifier: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _require_one_portfolio_reference(self) -> PortfolioGroupMembershipRequest:
        if self.portfolio_uid is not None and self.portfolio_unique_identifier is not None:
            raise ValueError("Pass either portfolio_uid or portfolio_unique_identifier, not both.")
        if self.portfolio_uid is None and self.portfolio_unique_identifier is None:
            raise ValueError("portfolio_uid or portfolio_unique_identifier is required.")
        return self


class PortfolioGroupMembershipBulkDeleteResponse(BaseModel):
    """What a bulk delete of portfolio-group memberships did: the memberships it deleted,
    in one statement, and each selected membership uid it did not delete, with the
    reason (issue 152)."""

    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int = 0
    deleted: list[BulkDeletedRow] = Field(default_factory=list)
    failed: list[BulkDeleteFailure] = Field(default_factory=list)


class PortfolioGroupMembershipBulkDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uids: list[UUID] = Field(default_factory=list)
    portfolio_group_uids: list[UUID] = Field(default_factory=list)
    portfolio_uids: list[UUID] = Field(default_factory=list)
