"""Validation helpers for curve-observation construction provenance."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from typing import Any

ALLOWED_KEY_NODE_FIELDS = frozenset({"maturity_date", "asset_identifier", "quote"})


def normalize_curve_key_nodes(value: Any) -> list[dict[str, Any]]:
    """Normalize and validate curve key-node provenance for one curve row."""

    if value is None:
        raise ValueError(
            "Discount curve builder frames must include key_nodes with at least "
            "one item containing maturity_date and quote."
        )
    if not isinstance(value, list | tuple):
        raise ValueError("Discount curve key_nodes must be a list of JSON objects.")
    if not value:
        raise ValueError("Discount curve key_nodes must contain at least one node.")

    return [_normalize_key_node(node, index=index) for index, node in enumerate(value)]


def normalize_curve_metadata(value: Any) -> dict[str, Any] | None:
    """Normalize optional per-row curve metadata."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Discount curve metadata_json must be a JSON object when provided.")
    return dict(value)


def _normalize_key_node(node: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise ValueError(f"Discount curve key_nodes[{index}] must be a JSON object.")

    unexpected_fields = set(node) - ALLOWED_KEY_NODE_FIELDS
    if unexpected_fields:
        raise ValueError(
            "Discount curve key_nodes only supports maturity_date, asset_identifier, "
            f"and quote. Unsupported fields at index {index}: {sorted(unexpected_fields)!r}."
        )

    normalized = {
        "maturity_date": _normalize_maturity_date(node.get("maturity_date"), index=index),
        "quote": _normalize_quote(node.get("quote"), index=index),
    }
    asset_identifier = node.get("asset_identifier")
    if asset_identifier is not None:
        normalized["asset_identifier"] = _normalize_asset_identifier(
            asset_identifier,
            index=index,
        )
    return normalized


def _normalize_maturity_date(value: Any, *, index: int) -> str:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"Discount curve key_nodes[{index}].maturity_date is required.")
        try:
            if "T" in cleaned:
                return dt.datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date().isoformat()
            return dt.date.fromisoformat(cleaned).isoformat()
        except ValueError as exc:
            raise ValueError(
                f"Discount curve key_nodes[{index}].maturity_date must be an ISO date."
            ) from exc
    raise ValueError(f"Discount curve key_nodes[{index}].maturity_date is required.")


def _normalize_quote(value: Any, *, index: int) -> float:
    if value is None:
        raise ValueError(f"Discount curve key_nodes[{index}].quote is required.")
    try:
        quote = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Discount curve key_nodes[{index}].quote must be numeric.") from exc
    if not math.isfinite(quote):
        raise ValueError(f"Discount curve key_nodes[{index}].quote must be finite.")
    return quote


def _normalize_asset_identifier(value: Any, *, index: int) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"Discount curve key_nodes[{index}].asset_identifier must be a string when provided."
        )
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(
            f"Discount curve key_nodes[{index}].asset_identifier cannot be empty."
        )
    return cleaned


__all__ = [
    "ALLOWED_KEY_NODE_FIELDS",
    "normalize_curve_key_nodes",
    "normalize_curve_metadata",
]
