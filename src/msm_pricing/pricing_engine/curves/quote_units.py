"""Curve quote normalization shared by reconstruction and scenarios."""

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
PRICE_QUOTE_TYPES = frozenset(
    {
        "future_price",
        "futures_price",
        "price",
    }
)
FX_FORWARD_POINT_QUOTE_TYPES = frozenset({"fx_forward_points"})
BASIS_SPREAD_QUOTE_TYPES = frozenset({"basis_spread"})


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


def key_node_price(node: Mapping[str, Any]) -> float:
    """Return a supported key-node price quote.

    Futures helpers consume futures prices directly. They must not reuse rate
    normalization because a price such as ``95.25`` is not a percent rate.
    """

    quote_type = _normalized_token(node.get("quote_type"))
    if quote_type in PRICE_QUOTE_TYPES and _has_value(node.get("quote")):
        return normalize_price_value(
            node.get("quote"),
            _first_present(node, "quote_unit", "price_unit"),
            field_name="quote",
        )
    raise ValueError(f"Curve key node has no supported explicit price field: {node!r}.")


def key_node_fx_forward_points(node: Mapping[str, Any]) -> float:
    """Return a supported FX forward-points quote.

    FX forward points are not rates. Direct FX-pair units such as
    ``quote_per_base`` or provider-normalized units are returned unchanged.
    Raw point/pip units require an explicit ``point_scale``.
    """

    quote_type = _normalized_token(node.get("quote_type"))
    if quote_type in FX_FORWARD_POINT_QUOTE_TYPES and _has_value(node.get("quote")):
        return normalize_fx_forward_points_value(
            node.get("quote"),
            _first_present(node, "quote_unit", "fx_forward_points_unit"),
            point_scale=node.get("point_scale"),
        )
    raise ValueError(f"Curve key node has no supported FX forward-points field: {node!r}.")


def key_node_basis_spread(node: Mapping[str, Any]) -> float:
    """Return a supported cross-currency basis spread normalized to decimal units."""

    quote_type = _normalized_token(node.get("quote_type"))
    if quote_type in BASIS_SPREAD_QUOTE_TYPES and _has_value(node.get("quote")):
        return normalize_basis_spread_value(
            node.get("quote"),
            _first_present(node, "quote_unit", "rate_unit"),
        )
    raise ValueError(f"Curve key node has no supported basis-spread field: {node!r}.")


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


def normalize_fx_forward_points_value(
    value: object,
    unit: object,
    *,
    point_scale: object | None = None,
) -> float:
    """Normalize an FX forward-points quote.

    Raw points and pips require an explicit positive ``point_scale`` because
    generic reconstruction must not infer point scale from source names or
    currency pairs.
    """

    raw = _finite_float(value, field_name="fx_forward_points")
    unit_text = _normalized_token(unit)
    if not unit_text:
        raise ValueError("Unsupported or missing FX forward-points unit.")
    if unit_text in {"raw_point", "raw_points", "point", "points", "pip", "pips"}:
        scale = _finite_float(point_scale, field_name="point_scale")
        if scale <= 0:
            raise ValueError("point_scale must be positive.")
        return raw / scale
    return raw


def normalize_basis_spread_value(value: object, unit: object) -> float:
    """Normalize a cross-currency basis spread to decimal units."""

    raw = _finite_float(value, field_name="basis_spread")
    unit_text = _normalized_token(unit)
    if unit_text in {"decimal", "decimals"}:
        return raw
    if unit_text in {"percent", "percentage"}:
        return raw * 0.01
    if unit_text in {"bp", "bps", "basis_point", "basis_points"}:
        return raw * 0.0001
    raise ValueError(
        f"Unsupported or missing key-node basis-spread unit {unit!r}. "
        "Supported units: decimal, percent, basis_points."
    )


def normalize_price_value(value: object, unit: object, *, field_name: str = "price") -> float:
    """Normalize a raw key-node price to price units.

    Only explicit ``price`` units are accepted. Generic curve reconstruction
    must not infer whether a numeric quote is a price, rate, index level, or
    other source-specific convention.
    """

    raw = _finite_float(value, field_name=field_name)
    unit_text = _normalize_price_unit(unit)
    if unit_text == "price":
        return raw
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


def _normalize_price_unit(unit: object) -> str:
    token = _normalized_token(unit)
    if token == "price":
        return "price"
    raise ValueError(
        f"Unsupported or missing key-node price unit {unit!r}. Supported units: price."
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
    "BASIS_SPREAD_QUOTE_TYPES",
    "FX_FORWARD_POINT_QUOTE_TYPES",
    "PRICE_QUOTE_TYPES",
    "RATE_QUOTE_TYPES",
    "key_node_basis_spread",
    "key_node_decimal_rate",
    "key_node_fx_forward_points",
    "key_node_price",
    "normalize_basis_spread_value",
    "normalize_fx_forward_points_value",
    "normalize_price_value",
    "normalize_rate_value",
]
