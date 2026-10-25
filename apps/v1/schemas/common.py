from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, Field, model_validator


class RenamedResponseFields(BaseModel):
    """Response that repeats each renamed field under its pre-3.0 name (ADR 0048).

    ``__renamed_fields__`` maps each current field to its pre-3.0 name. Declare the
    pre-3.0 field with :func:`pre_3_0_response_field`; ms-markets 4.0 removes it.
    """

    __renamed_fields__: ClassVar[dict[str, str]] = {}

    @model_validator(mode="before")
    @classmethod
    def _fill_pre_3_0_fields(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        filled = dict(data)
        for current, previous in cls.__renamed_fields__.items():
            if current not in filled and previous in filled:
                filled[current] = filled[previous]
            filled.setdefault(previous, filled.get(current))
        return filled


def pre_3_0_response_field(current: str) -> Any:
    """Declare the deprecated pre-3.0 name of response field ``current``."""

    return Field(
        default=None,
        deprecated=True,
        description=f"Pre-3.0 name of {current}; removed in ms-markets 4.0 (ADR 0048).",
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
