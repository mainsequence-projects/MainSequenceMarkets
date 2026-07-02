"""Rate quote normalization shared by curve reconstruction and scenarios."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

RATE_QUOTE_TYPES = frozenset(
    {
        "deposit_rate",
        "forward",
        "forward_rate",
        "overnight_rate",
        "par_rate",
        "par_swap_rate",
        "rate",
        "swap_rate",
        "yield",
        "yield_to_maturity",
        "zero",
        "zero_rate",
    }
)


def key_node_decimal_rate(node: Mapping[str, Any]) -> float:
    """Return a supported key-node rate/yield normalized to decimal units.

    Supported fields are ``yield``/``yield_value``, rate-like ``quote`` values
    whose ``quote_type`` is an explicit rate convention, and ``implied_rate``.
    Units must be explicit decimal or percent units. Price-like quotes are
    rejected because converting them to rates is source-specific.
    """

    if _has_value(node.get("yield")):
        return normalize_rate_value(
            node.get("yield"),
            _first_present(node, "yield_unit", "quote_unit", "rate_unit"),
            field_name="yield",
        )
    if _has_value(node.get("yield_value")):
        return normalize_rate_value(
            node.get("yield_value"),
            _first_present(node, "yield_unit", "quote_unit", "rate_unit"),
            field_name="yield_value",
        )

    quote_type = _normalized_token(node.get("quote_type"))
    if quote_type in RATE_QUOTE_TYPES and _has_value(node.get("quote")):
        return normalize_rate_value(
            node.get("quote"),
            _first_present(node, "quote_unit", "rate_unit"),
            field_name="quote",
        )

    if _has_value(node.get("implied_rate")):
        return normalize_rate_value(
            node.get("implied_rate"),
            _first_present(node, "implied_rate_unit", "rate_unit", "quote_unit"),
            field_name="implied_rate",
        )

    raise ValueError(f"Curve key node has no supported explicit rate/yield field: {node!r}.")


def normalize_rate_value(value: object, unit: object, *, field_name: str = "rate") -> float:
    """Normalize a raw key-node rate/yield to decimal units.

    ``decimal``/``decimals`` values are returned unchanged. ``percent`` and
    ``percentage`` values are divided by 100. Missing or unsupported units raise
    because generic curve math must not infer provider quote units.
    """

    raw = _finite_float(value, field_name=field_name)
    unit_text = _normalize_rate_unit(unit)
    if unit_text == "decimal":
        return raw
    if unit_text == "percent":
        return raw * 0.01
    raise AssertionError(f"Unhandled normalized unit {unit_text!r}.")


def _first_present(node: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        value = node.get(key)
        if value not in (None, ""):
            return value
    return None


def _has_value(value: object) -> bool:
    return value not in (None, "")


def _normalized_token(value: object) -> str:
    return str(value or "").strip().lower()


def _normalize_rate_unit(unit: object) -> str:
    token = _normalized_token(unit)
    if token in {"decimal", "decimals"}:
        return "decimal"
    if token in {"percent", "percentage"}:
        return "percent"
    raise ValueError(
        f"Unsupported or missing key-node rate unit {unit!r}. "
        "Supported units: decimal, percent."
    )


def _finite_float(value: object, *, field_name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(out):
        raise ValueError(f"{field_name} must be a finite number.")
    return out


__all__ = [
    "RATE_QUOTE_TYPES",
    "key_node_decimal_rate",
    "normalize_rate_value",
]
