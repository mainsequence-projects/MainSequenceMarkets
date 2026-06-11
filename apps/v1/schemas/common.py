from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

ResultT = TypeVar("ResultT")


class ErrorResponse(BaseModel):
    detail: str


class PaginatedResponse(BaseModel, Generic[ResultT]):
    """Reusable FastAPI v1 limit-offset pagination envelope."""

    model_config = ConfigDict(extra="ignore")

    count: int = Field(ge=0, description="Total number of rows matching the request filters.")
    next: str | None = Field(default=None, description="URL for the next page, if one exists.")
    previous: str | None = Field(
        default=None,
        description="URL for the previous page, if one exists.",
    )
    results: list[ResultT]


def build_paginated_response(
    *,
    request_url: str,
    results: Sequence[ResultT],
    limit: int,
    offset: int,
    count: int | None = None,
) -> PaginatedResponse[ResultT]:
    """Build a Django REST Framework-style limit-offset response."""

    page_results = list(results[:limit])
    resolved_count = count
    if resolved_count is None:
        resolved_count = offset + len(page_results)
        if len(results) > limit:
            resolved_count += 1
    return PaginatedResponse[ResultT](
        count=resolved_count,
        next=_pagination_url(
            request_url=request_url,
            limit=limit,
            offset=offset + limit,
        )
        if offset + limit < resolved_count
        else None,
        previous=_pagination_url(
            request_url=request_url,
            limit=limit,
            offset=max(offset - limit, 0),
        )
        if offset > 0
        else None,
        results=page_results,
    )


def _pagination_url(*, request_url: str, limit: int, offset: int) -> str:
    split = urlsplit(request_url)
    params = dict(parse_qsl(split.query, keep_blank_values=True))
    params["limit"] = str(limit)
    params["offset"] = str(offset)
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            split.path,
            urlencode(params),
            split.fragment,
        )
    )


class FrontEndDetailSummaryEntity(BaseModel):
    id: str | int | float
    type: str
    title: str


class FrontEndDetailSummaryBadge(BaseModel):
    key: str
    label: str
    tone: str
    link_url: str | None = None


class FrontEndDetailSummaryField(BaseModel):
    key: str
    label: str
    value: str | int | float | bool | None
    kind: str
    icon: str | None = None
    link_url: str | None = None


class FrontEndDetailSummaryStat(BaseModel):
    key: str
    label: str
    display: str
    value: str | int | float | bool | None
    kind: str
    link_url: str | None = None


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
