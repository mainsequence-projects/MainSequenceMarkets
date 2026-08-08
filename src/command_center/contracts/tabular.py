"""Project-owned models for the ``core.tabular_frame@v1`` wire contract.

The language-neutral contract is owned by ``@dev-mainsequence/command-center-sdk``.
These Pydantic models implement that contract without depending on the removed
Main Sequence SDK compatibility package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CORE_TABULAR_FRAME_CONTRACT = "core.tabular_frame@v1"

TabularFrameStatus = Literal["idle", "loading", "ready", "error"]
TabularFrameFieldType = Literal[
    "string",
    "number",
    "integer",
    "boolean",
    "datetime",
    "date",
    "time",
    "json",
    "unknown",
]
TabularFrameFieldProvenance = Literal["backend", "manual", "inferred", "derived"]


class ContractBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TabularFrameFieldResponse(ContractBaseModel):
    key: str
    type: TabularFrameFieldType
    label: str | None = None
    description: str | None = None
    nullable: bool | None = None
    nativeType: str | None = None
    provenance: TabularFrameFieldProvenance | None = None
    reason: str | None = None
    derivedFrom: list[str] | None = None
    warnings: list[str] | None = None


class TabularFrameSourceResponse(ContractBaseModel):
    kind: str
    id: str | int | float | None = None
    label: str | None = None
    updatedAtMs: int | None = None
    context: dict[str, Any] | None = None


class TabularTimeSeriesMetaResponse(ContractBaseModel):
    shape: Literal["long", "wide"]
    timeField: str
    timeUnit: Literal["ms"] = "ms"
    timezone: Literal["UTC"] = "UTC"
    sorted: bool
    valueField: str | None = None
    seriesField: str | None = None
    seriesLabelFields: list[str] | None = None
    valueFields: list[str] | None = None
    frequency: str | None = None
    calendar: str | None = None
    gapPolicy: Literal["preserve_nulls", "drop_nulls"] | None = None
    duplicatePolicy: Literal["error", "first", "latest", "aggregate", "preserve"] | None = None
    unitByField: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_shape_fields(self) -> TabularTimeSeriesMetaResponse:
        if self.shape == "long":
            if self.valueField is None or self.valueFields is not None:
                raise ValueError("Long time-series metadata requires valueField and forbids valueFields.")
        elif not self.valueFields or self.valueField is not None:
            raise ValueError("Wide time-series metadata requires valueFields and forbids valueField.")
        return self


class TableVisualThreshold(ContractBaseModel):
    operator: Literal["gt", "gte", "lt", "lte", "eq"]
    value: float
    backgroundColor: str | None = None
    id: str | None = None
    textColor: str | None = None
    tone: Literal["neutral", "primary", "success", "warning", "danger"] | None = None


class TableVisualColorScale(ContractBaseModel):
    negative: str | None = None
    neutral: str | None = None
    positive: str | None = None


class TableVisualRange(ContractBaseModel):
    min: float | None = None
    max: float | None = None
    midpoint: float | None = None
    clamp: bool | None = None


class TableVisualColumn(ContractBaseModel):
    label: str | None = None
    format: Literal[
        "number",
        "price",
        "percent",
        "volume",
        "currency",
        "datetime",
        "formula",
    ] | None = None
    formulaExpression: str | None = None
    formulaResultFormat: Literal[
        "text",
        "datetime",
        "number",
        "currency",
        "percent",
        "bps",
    ] | None = None
    dateTimeInputFormat: str | None = None
    dateTimeOutputFormat: str | None = None
    decimals: int | None = Field(default=None, ge=0, le=6)
    visible: bool | None = None
    colorScale: TableVisualColorScale | None = None
    range: TableVisualRange | None = None
    thresholds: list[TableVisualThreshold] | None = None
    heatmap: bool | None = None
    barMode: Literal["none", "fill"] | None = None
    gradientMode: Literal["none", "fill"] | None = None
    heatmapPalette: Literal[
        "auto",
        "viridis",
        "plasma",
        "inferno",
        "magma",
        "turbo",
        "jet",
        "blue-white-red",
        "red-yellow-green",
    ] | None = None
    gaugeMode: Literal["none", "ring"] | None = None
    visualRangeMode: Literal["auto", "fixed"] | None = None
    visualMin: float | None = None
    visualMax: float | None = None
    kind: Literal["sparkline", "bar", "heatmap"] | None = None
    encoding: Literal["csv-number", "json-number-array", "number-array"] | None = None
    order: Literal["oldest-to-newest", "newest-to-oldest"] | None = None
    width: float | None = Field(default=None, gt=0)


class TableFrameVisualsMetadata(ContractBaseModel):
    columns: dict[str, TableVisualColumn] | None = None


class TabularFrameMetaResponse(ContractBaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    timeSeries: TabularTimeSeriesMetaResponse | None = None
    tableVisuals: TableFrameVisualsMetadata | None = None


class TabularFrameResponse(ContractBaseModel):
    status: TabularFrameStatus
    columns: list[str]
    rows: list[dict[str, Any]]
    error: str | None = None
    fields: list[TabularFrameFieldResponse] | None = None
    meta: TabularFrameMetaResponse | None = None
    source: TabularFrameSourceResponse | None = None

    @field_validator("columns")
    @classmethod
    def validate_unique_columns(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Tabular frame columns must be unique.")
        if any(not column.strip() for column in value):
            raise ValueError("Tabular frame columns must be non-empty strings.")
        return value

    @model_validator(mode="after")
    def validate_unique_fields(self) -> TabularFrameResponse:
        if self.fields is not None:
            keys = [field.key for field in self.fields]
            if len(keys) != len(set(keys)):
                raise ValueError("Tabular frame field keys must be unique.")
        return self


def build_tabular_field(
    key: str,
    *,
    label: str | None = None,
    field_type: TabularFrameFieldType = "string",
    description: str | None = None,
    nullable: bool | None = True,
    native_type: str | None = None,
    provenance: TabularFrameFieldProvenance | None = None,
    derived_from: Sequence[str] | None = None,
) -> TabularFrameFieldResponse:
    return TabularFrameFieldResponse(
        key=key,
        label=label,
        description=description,
        type=field_type,
        nullable=nullable,
        nativeType=native_type,
        provenance=provenance,
        derivedFrom=list(derived_from) if derived_from is not None else None,
    )


def build_tabular_frame(
    *,
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str] | None = None,
    fields: Sequence[TabularFrameFieldResponse | Mapping[str, Any]] | None = None,
    status: TabularFrameStatus = "ready",
    error: str | None = None,
    meta: TabularFrameMetaResponse | Mapping[str, Any] | None = None,
    source: TabularFrameSourceResponse | Mapping[str, Any] | None = None,
) -> TabularFrameResponse:
    normalized_rows = [dict(row) for row in rows]
    normalized_columns = list(columns) if columns is not None else _columns_from_rows(normalized_rows)
    return TabularFrameResponse(
        status=status,
        error=error,
        columns=normalized_columns,
        rows=normalized_rows,
        fields=list(fields) if fields is not None else None,
        meta=meta,
        source=source,
    )


def infer_tabular_field_type(value: Any) -> TabularFrameFieldType:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, (dict, list, tuple)):
        return "json"
    return "string"


def _columns_from_rows(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


__all__ = [
    "CORE_TABULAR_FRAME_CONTRACT",
    "ContractBaseModel",
    "TabularFrameFieldProvenance",
    "TabularFrameFieldResponse",
    "TabularFrameFieldType",
    "TabularFrameMetaResponse",
    "TabularFrameResponse",
    "TabularFrameSourceResponse",
    "TabularFrameStatus",
    "TabularTimeSeriesMetaResponse",
    "build_tabular_field",
    "build_tabular_frame",
    "infer_tabular_field_type",
]
