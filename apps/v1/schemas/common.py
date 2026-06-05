from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

ResultT = TypeVar("ResultT")


class ErrorResponse(BaseModel):
    detail: str


class PaginatedResponse(BaseModel, Generic[ResultT]):
    """Reusable FastAPI v1 pagination envelope for list endpoints."""

    model_config = ConfigDict(extra="ignore")

    count: int = Field(ge=0, description="Total number of rows matching the request filters.")
    limit: int = Field(ge=0, description="Maximum number of rows requested for this page.")
    offset: int = Field(ge=0, description="Zero-based offset into the filtered row set.")
    results: list[ResultT]


def build_paginated_response(
    *,
    results: Sequence[ResultT],
    count: int,
    limit: int,
    offset: int,
) -> PaginatedResponse[ResultT]:
    """Build the shared FastAPI v1 pagination envelope."""

    return PaginatedResponse[ResultT](
        count=count,
        limit=limit,
        offset=offset,
        results=list(results),
    )


class FrontEndDetailSummaryEntity(BaseModel):
    id: str | int | float
    type: str
    title: str


class FrontEndDetailSummaryBadge(BaseModel):
    key: str
    label: str
    tone: str


class FrontEndDetailSummaryField(BaseModel):
    key: str
    label: str
    value: str | int | float | bool | None
    kind: str
    icon: str | None = None


class FrontEndDetailSummaryStat(BaseModel):
    key: str
    label: str
    display: str
    value: str | int | float | bool | None
    kind: str


class FrontEndDetailSummaryLabelManagement(BaseModel):
    labels: list[str]
    add_label_url: str | None = None
    remove_label_url: str | None = None


class FrontEndDetailSummary(BaseModel):
    entity: FrontEndDetailSummaryEntity
    badges: list[FrontEndDetailSummaryBadge]
    inline_fields: list[FrontEndDetailSummaryField]
    highlight_fields: list[FrontEndDetailSummaryField]
    stats: list[FrontEndDetailSummaryStat]
    label_management: FrontEndDetailSummaryLabelManagement | None = None
    summary_warning: str | None = None
    extensions: dict[str, Any]
