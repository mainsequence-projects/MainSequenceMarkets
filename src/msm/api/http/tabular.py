"""Provider-neutral Command Center ``core.tabular_frame@v1`` contract and helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from ._base import HttpContractModel

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


def _omit_unset(**constraints: Any) -> Any:
    """Declare an optional field that the payload omits while it is unset.

    The ``core.tabular_frame@v1`` schema rejects ``null`` for these fields, so a frame
    stays valid without ``response_model_exclude_none``.
    """

    return Field(default=None, exclude_if=lambda value: value is None, **constraints)


class TabularFrameFieldResponse(HttpContractModel):
    key: str
    type: TabularFrameFieldType
    label: str | None = _omit_unset()
    description: str | None = _omit_unset()
    nullable: bool | None = _omit_unset()
    nativeType: str | None = _omit_unset()
    provenance: TabularFrameFieldProvenance | None = _omit_unset()
    reason: str | None = _omit_unset()
    derivedFrom: list[str] | None = _omit_unset()
    warnings: list[str] | None = _omit_unset()


class TabularFrameSourceResponse(HttpContractModel):
    kind: str
    id: str | int | float | None = _omit_unset()
    label: str | None = _omit_unset()
    updatedAtMs: int | None = _omit_unset()
    context: dict[str, Any] | None = _omit_unset()


class TabularTimeSeriesMetaResponse(HttpContractModel):
    shape: Literal["long", "wide"]
    timeField: str
    timeUnit: Literal["ms"] = "ms"
    timezone: Literal["UTC"] = "UTC"
    sorted: bool
    valueField: str | None = _omit_unset()
    seriesField: str | None = _omit_unset()
    seriesLabelFields: list[str] | None = _omit_unset()
    valueFields: list[str] | None = _omit_unset()
    frequency: str | None = _omit_unset()
    calendar: str | None = _omit_unset()
    gapPolicy: Literal["preserve_nulls", "drop_nulls"] | None = _omit_unset()
    duplicatePolicy: (
        Literal["error", "first", "latest", "aggregate", "preserve"] | None
    ) = _omit_unset()
    unitByField: dict[str, str] | None = _omit_unset()

    @model_validator(mode="after")
    def validate_shape_fields(self) -> TabularTimeSeriesMetaResponse:
        if self.shape == "long":
            if self.valueField is None or self.valueFields is not None:
                raise ValueError("Long time-series metadata requires valueField and forbids valueFields.")
        elif not self.valueFields or self.valueField is not None:
            raise ValueError("Wide time-series metadata requires valueFields and forbids valueField.")
        return self


class TableVisualThreshold(HttpContractModel):
    operator: Literal["gt", "gte", "lt", "lte", "eq"]
    value: float
    backgroundColor: str | None = _omit_unset()
    id: str | None = _omit_unset()
    textColor: str | None = _omit_unset()
    tone: Literal["neutral", "primary", "success", "warning", "danger"] | None = _omit_unset()


class TableVisualColorScale(HttpContractModel):
    negative: str | None = _omit_unset()
    neutral: str | None = _omit_unset()
    positive: str | None = _omit_unset()


class TableVisualRange(HttpContractModel):
    min: float | None = _omit_unset()
    max: float | None = _omit_unset()
    midpoint: float | None = _omit_unset()
    clamp: bool | None = _omit_unset()


class TableVisualColumn(HttpContractModel):
    label: str | None = _omit_unset()
    format: Literal[
        "number",
        "price",
        "percent",
        "volume",
        "currency",
        "datetime",
        "formula",
    ] | None = _omit_unset()
    formulaExpression: str | None = _omit_unset()
    formulaResultFormat: Literal[
        "text",
        "datetime",
        "number",
        "currency",
        "percent",
        "bps",
    ] | None = _omit_unset()
    dateTimeInputFormat: str | None = _omit_unset()
    dateTimeOutputFormat: str | None = _omit_unset()
    decimals: int | None = _omit_unset(ge=0, le=6)
    visible: bool | None = _omit_unset()
    colorScale: TableVisualColorScale | None = _omit_unset()
    range: TableVisualRange | None = _omit_unset()
    thresholds: list[TableVisualThreshold] | None = _omit_unset()
    heatmap: bool | None = _omit_unset()
    barMode: Literal["none", "fill"] | None = _omit_unset()
    gradientMode: Literal["none", "fill"] | None = _omit_unset()
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
    ] | None = _omit_unset()
    gaugeMode: Literal["none", "ring"] | None = _omit_unset()
    visualRangeMode: Literal["auto", "fixed"] | None = _omit_unset()
    visualMin: float | None = _omit_unset()
    visualMax: float | None = _omit_unset()
    kind: Literal["sparkline", "bar", "heatmap"] | None = _omit_unset()
    encoding: Literal["csv-number", "json-number-array", "number-array"] | None = _omit_unset()
    order: Literal["oldest-to-newest", "newest-to-oldest"] | None = _omit_unset()
    width: float | None = _omit_unset(gt=0)


class TableFrameVisualsMetadata(HttpContractModel):
    columns: dict[str, TableVisualColumn] | None = _omit_unset()


class TabularFrameMetaResponse(HttpContractModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    timeSeries: TabularTimeSeriesMetaResponse | None = _omit_unset()
    tableVisuals: TableFrameVisualsMetadata | None = _omit_unset()


class TabularFrameResponse(HttpContractModel):
    status: TabularFrameStatus
    columns: list[str]
    rows: list[dict[str, Any]]
    error: str | None = _omit_unset()
    fields: list[TabularFrameFieldResponse] | None = _omit_unset()
    meta: TabularFrameMetaResponse | None = _omit_unset()
    source: TabularFrameSourceResponse | None = _omit_unset()

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
]
