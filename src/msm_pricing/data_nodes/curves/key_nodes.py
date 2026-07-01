"""Helpers for curve-observation construction provenance."""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class CurveKeyNode(BaseModel):
    """Recommended, optional shape for discount-curve construction provenance.

    Storage remains permissive JSON. Producers may use this helper when the
    standard fields fit their source, and may add source-specific fields through
    Pydantic ``extra="allow"``.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    maturity_date: dt.date | None = Field(
        default=None,
        description="Maturity date for the source input when the input is maturity-based.",
    )
    asset_identifier: str | None = Field(
        default=None,
        description="Optional registered source-instrument identifier for this key node.",
    )
    instrument_type: str | None = Field(
        default=None,
        description="Optional source instrument type, such as direct_zero_rate or bond.",
    )
    quote: float | None = Field(
        default=None,
        description="Raw source quote used by the producer for this key node.",
    )
    quote_type: str | None = Field(
        default=None,
        description="Meaning of quote, such as zero_rate, yield, clean_price, or par_rate.",
    )
    quote_unit: str | None = Field(
        default=None,
        description="Unit of quote, such as decimal, percent, or price_per_100.",
    )
    quote_side: str | None = Field(
        default="mid",
        description="Optional source quote side, such as bid, mid, or offer.",
    )
    yield_value: float | None = Field(
        default=None,
        validation_alias=AliasChoices("yield", "yield_value"),
        serialization_alias="yield",
        description=(
            "Optional yield-native value for producers whose curve inputs are "
            "naturally represented as yields."
        ),
    )

    @model_validator(mode="after")
    def _validate_recommended_quote(self) -> CurveKeyNode:
        if self.quote is None and self.yield_value is None:
            raise ValueError("CurveKeyNode requires quote or yield.")
        return self


def normalize_curve_key_nodes(value: Any) -> Any:
    """Normalize producer-owned key-node provenance for one curve row.

    ``key_nodes`` is intentionally not a financial schema contract. The only
    storage-level requirements are that the top-level value is a JSON object or
    list and that nested values are JSON-compatible.
    """

    if value is None:
        raise ValueError(
            "Discount curve builder frames must include key_nodes construction provenance."
        )
    normalized = _normalize_json_value(value, path="key_nodes")
    if not isinstance(normalized, list | dict):
        raise ValueError("Discount curve key_nodes must be a JSON object or list when present.")
    return normalized


def normalize_curve_metadata(value: Any) -> dict[str, Any] | None:
    """Normalize optional per-row curve metadata."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Discount curve metadata_json must be a JSON object when provided.")
    return _normalize_json_object(value, path="metadata_json")


def _normalize_json_value(value: Any, *, path: str) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return _normalize_json_object(value, path=path)
    if isinstance(value, list | tuple):
        return [
            _normalize_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str | bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Discount curve {path} must contain finite JSON numbers.")
        return value

    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Discount curve {path} must be JSON serializable.") from exc
    return value


def _normalize_json_object(value: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"Discount curve {path} JSON object keys must be strings.")
        normalized[key] = _normalize_json_value(item, path=f"{path}.{key}")
    return normalized


__all__ = [
    "CurveKeyNode",
    "normalize_curve_key_nodes",
    "normalize_curve_metadata",
]
