"""Helpers for curve-observation construction provenance."""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import math
import zlib
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

KEY_NODES_CODEC_PREFIX = "msm_pricing.key_nodes.zlib+base64.v1:"
_LEGACY_SOURCE_REFERENCE_FIELDS = frozenset({"asset_identifier", "index_identifier"})


class CurveKeyNodeSourceReference(BaseModel):
    """Canonical identity of the asset or index that supplied a curve input."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["asset", "index"]
    identifier: str = Field(min_length=1)

    @field_validator("identifier", mode="before")
    @classmethod
    def _normalize_identifier(cls, value: object) -> str:
        identifier = str(value or "").strip()
        if not identifier:
            raise ValueError("source_reference.identifier cannot be empty.")
        return identifier


class CurveKeyNodeBase(BaseModel):
    """Shared source-reference contract for typed curve key nodes."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    source_reference: CurveKeyNodeSourceReference | None = Field(
        default=None,
        description=(
            "Optional canonical AssetTable or IndexTable unique identifier for the "
            "market input represented by this key node."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_source_reference_fields(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            _raise_for_legacy_source_reference_fields(value, path=cls.__name__)
        return value


class CurveKeyNode(CurveKeyNodeBase):
    """Recommended, optional shape for discount-curve construction provenance.

    The base storage contract accepts JSON object/list provenance. Producers
    may use this helper when the standard fields fit their source, and may add
    source-specific fields through Pydantic ``extra="allow"``.
    """

    maturity_date: dt.date | None = Field(
        default=None,
        description="Maturity date for the source input when the input is maturity-based.",
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

    The shared storage contract stays compact: the top-level value is a JSON
    object or list and nested values are JSON-compatible. Financial schemas
    belong in the optional ``CurveKeyNode`` helper or producer validators.
    """

    if value is None:
        raise ValueError(
            "Discount curve builder frames must include key_nodes construction provenance."
        )
    normalized = _normalize_json_value(value, path="key_nodes")
    if not isinstance(normalized, list | dict):
        raise ValueError("Discount curve key_nodes must be a JSON object or list when present.")
    _reject_legacy_source_reference_fields(normalized)
    _normalize_curve_key_node_source_references(normalized)
    return normalized


def normalize_curve_metadata(value: Any) -> dict[str, Any] | None:
    """Normalize optional per-row curve metadata."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Discount curve metadata_json must be a JSON object when provided.")
    return _normalize_json_object(value, path="metadata_json")


def compress_key_nodes_to_string(value: Any) -> str:
    """Serialize key-node provenance into the compressed storage representation."""

    normalized = normalize_curve_key_nodes(value)
    json_bytes = json.dumps(
        normalized,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    compressed_bytes = zlib.compress(json_bytes)
    encoded = base64.b64encode(compressed_bytes).decode("ascii")
    return f"{KEY_NODES_CODEC_PREFIX}{encoded}"


def decompress_key_nodes_from_string(value: str) -> Any:
    """Decode compressed key-node provenance from storage into JSON."""

    if not isinstance(value, str) or not value:
        raise ValueError("Discount curve key_nodes must be a non-empty compressed string.")

    if value.startswith(KEY_NODES_CODEC_PREFIX):
        encoded = value.removeprefix(KEY_NODES_CODEC_PREFIX)
        try:
            compressed_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
            json_bytes = zlib.decompress(compressed_bytes)
            decoded = json.loads(json_bytes.decode("utf-8"))
        except (
            binascii.Error,
            UnicodeDecodeError,
            json.JSONDecodeError,
            zlib.error,
            ValueError,
        ) as exc:
            raise ValueError("Discount curve key_nodes compressed payload is invalid.") from exc
        return normalize_curve_key_nodes(decoded)

    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Discount curve key_nodes must use the compressed key-node codec."
        ) from exc
    return normalize_curve_key_nodes(decoded)


def _normalize_json_value(value: Any, *, path: str) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return _normalize_json_object(value, path=path)
    if isinstance(value, list | tuple):
        return [
            _normalize_json_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)
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


def _reject_legacy_source_reference_fields(value: list[Any] | dict[str, Any]) -> None:
    if isinstance(value, list):
        for index, node in enumerate(value):
            if isinstance(node, Mapping):
                _raise_for_legacy_source_reference_fields(node, path=f"key_nodes[{index}]")
        return
    _raise_for_legacy_source_reference_fields(value, path="key_nodes")


def _normalize_curve_key_node_source_references(value: list[Any] | dict[str, Any]) -> None:
    nodes = value if isinstance(value, list) else [value]
    for node in nodes:
        if not isinstance(node, dict) or "source_reference" not in node:
            continue
        source_reference = node["source_reference"]
        if source_reference is None:
            continue
        node["source_reference"] = CurveKeyNodeSourceReference.model_validate(
            source_reference
        ).model_dump(mode="json")


def _raise_for_legacy_source_reference_fields(
    value: Mapping[str, Any],
    *,
    path: str,
) -> None:
    stale_fields = sorted(_LEGACY_SOURCE_REFERENCE_FIELDS.intersection(value))
    if stale_fields:
        raise ValueError(
            f"{path} uses unsupported top-level source fields "
            f"{', '.join(stale_fields)}; use source_reference with type and identifier."
        )


__all__ = [
    "CurveKeyNode",
    "CurveKeyNodeBase",
    "CurveKeyNodeSourceReference",
    "KEY_NODES_CODEC_PREFIX",
    "compress_key_nodes_to_string",
    "decompress_key_nodes_from_string",
    "normalize_curve_key_nodes",
    "normalize_curve_metadata",
]
