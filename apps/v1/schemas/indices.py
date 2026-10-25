from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _contracts():
    prepare_apps_v1_import_namespace()
    from msm.analytics.indices import IndexFormulaDefinition, IndexFormulaInput
    from msm.api.indices import Index, IndexCreate, IndexType, IndexUpdate
    from msm.services.indices.contracts import (
        IndexDatasetDescriptor,
        IndexDatasetState,
        IndexDatasetSummary,
        IndexFormulaDetail,
        IndexFormulaSummary,
        RelatedMetaTable,
    )

    return (
        Index,
        IndexCreate,
        IndexUpdate,
        IndexType,
        IndexFormulaSummary,
        IndexFormulaDetail,
        IndexDatasetDescriptor,
        IndexDatasetState,
        IndexDatasetSummary,
        RelatedMetaTable,
        IndexFormulaDefinition,
        IndexFormulaInput,
    )


(
    Index,
    IndexCreate,
    IndexUpdate,
    IndexType,
    IndexFormulaSummary,
    IndexFormulaDetail,
    IndexDatasetDescriptor,
    IndexDatasetState,
    IndexDatasetSummary,
    RelatedMetaTable,
    IndexFormulaDefinition,
    IndexFormulaInput,
) = _contracts()


class IndexWithIncludes(Index):
    """`Index` plus the provider sidecar rows requested with `include` (ADR 0047)."""

    includes: dict[str, dict[str, Any] | None] = Field(
        default_factory=dict,
        description=(
            "Provider sidecar rows requested with `include`, keyed by sidecar MetaTable uid; "
            "`null` when the sidecar has no row for this uid. Empty when nothing was included."
        ),
    )


class IndexFormulaSaveRequest(BaseModel):
    """A formula version to persist for one formula-calculated Index."""

    model_config = ConfigDict(extra="forbid")

    definition: IndexFormulaDefinition = Field(
        description=(
            "Point-in-time formula definition. `status` may be `draft` (default), `active` "
            "or `retired`; `version` defaults to the next monotonic version."
        )
    )
    inputs: list[IndexFormulaInput] = Field(
        min_length=1,
        description="Exact source bindings: source reference, MetaTable uid and observable.",
    )


class IndexFormulaRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid_to: dt.datetime | None = Field(
        default=None,
        description="Exclusive validity boundary; defaults to now when omitted.",
    )


class IndexFormulaWindowRequest(BaseModel):
    """A bounded, timezone-aware calculation window."""

    model_config = ConfigDict(extra="forbid")

    start: dt.datetime = Field(description="Inclusive timezone-aware start timestamp.")
    end: dt.datetime = Field(description="Exclusive timezone-aware end timestamp.")

    @model_validator(mode="after")
    def _validate_window(self) -> IndexFormulaWindowRequest:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        return self


class IndexFormulaPreviewRequest(IndexFormulaWindowRequest):
    """Calculate an unsaved formula over its pinned sources without persisting anything."""

    definition: IndexFormulaDefinition
    inputs: list[IndexFormulaInput] = Field(min_length=1)
