from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str


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
