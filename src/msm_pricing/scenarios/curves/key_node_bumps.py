"""Generic key-node bump mechanics for transient curve scenarios.

These helpers transform source key-node provenance into copied, bumped runtime
curve observation nodes. They do not own persisted curve storage; that remains
under ``msm_pricing.data_nodes.curves``. They also do not perform
connector-specific curve reconstruction or source quote interpretation such as
clean-price-to-rate conversion.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any

import pandas as pd

from msm_pricing.scenarios.curves.models import CurveBumpSpec

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

_KEY_NODE_QUOTE_PLACEHOLDERS = frozenset({"key_node_quote", "key_node_quote_type"})
_KEY_NODE_UNIT_PLACEHOLDERS = frozenset({"key_node_unit", "key_node_quote_unit"})


def tenor_to_days(tenor: object) -> int | None:
    """Parse a tenor label into approximate days for scenario interpolation.

    Supported labels are ``D``, ``W``, ``M``, and ``Y`` suffixes such as
    ``"28D"``, ``"2W"``, ``"3M"``, and ``"5Y"``. Month and year conversion is
    approximate and exists only for transient key-rate interpolation; it is not
    a persisted curve convention.
    """

    text = str(tenor or "").strip().upper()
    if len(text) < 2:
        return None
    try:
        value = int(text[:-1])
    except ValueError:
        return None
    unit = text[-1]
    if unit == "D":
        return value
    if unit == "W":
        return value * 7
    if unit == "M":
        return value * 30
    if unit == "Y":
        return value * 365
    return None


def key_node_maturity_date(node: Mapping[str, Any]) -> dt.datetime | None:
    """Return ``maturity_date`` or ``pillar_date`` normalized to UTC datetime."""

    value = node.get("maturity_date") or node.get("pillar_date")
    if value in (None, ""):
        return None
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def key_node_days_to_maturity(
    node: Mapping[str, Any],
    *,
    effective_curve_date: object,
) -> int | None:
    """Return key-node days to maturity from explicit days, date, or tenor.

    Precedence is ``days_to_maturity``, then ``maturity_date``/``pillar_date``
    minus the effective curve date, then approximate tenor parsing.
    """

    raw_days = node.get("days_to_maturity")
    if raw_days not in (None, ""):
        days = _finite_float(raw_days, field_name="days_to_maturity")
        return int(days)

    maturity = key_node_maturity_date(node)
    effective = to_utc_datetime(effective_curve_date)
    if maturity is not None and effective is not None:
        return int((pd.Timestamp(maturity).date() - effective.date()).days)

    parsed_tenor = tenor_to_days(node.get("tenor"))
    return int(parsed_tenor) if parsed_tenor is not None else None


def to_utc_datetime(value: object) -> dt.datetime | None:
    """Return a timestamp-like value normalized to UTC datetime."""

    if value in (None, ""):
        return None
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def key_node_decimal_rate(node: Mapping[str, Any]) -> float:
    """Return a supported key-node rate/yield normalized to decimal units.

    Supported fields are ``yield``/``yield_value``, rate-like ``quote`` values
    whose ``quote_type`` is an explicit rate convention, and ``implied_rate``.
    Units must be explicit decimal or percent units. Clean prices, price per
    100, and other source quote forms are rejected because they require
    producer- or connector-owned interpretation.
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
    because scenario math must not infer vendor quote units.
    """

    raw = _finite_float(value, field_name=field_name)
    unit_text = _normalize_rate_unit(unit)
    if unit_text == "decimal":
        return raw
    if unit_text == "percent":
        return raw * 0.01
    raise AssertionError(f"Unhandled normalized unit {unit_text!r}.")


def bumped_raw_rate(value: object, *, unit: object, bump_bp: float) -> float:
    """Return a raw key-node rate after applying a basis-point bump.

    The returned value is in the same unit as the submitted raw value:
    decimal rates add ``bp / 10_000`` and percent rates add ``bp / 100``.
    """

    raw = _finite_float(value, field_name="rate")
    bump = _finite_float(bump_bp, field_name="bump_bp")
    unit_text = _normalize_rate_unit(unit)
    if unit_text == "decimal":
        return raw + bump / 10_000.0
    if unit_text == "percent":
        return raw + bump / 100.0
    raise AssertionError(f"Unhandled normalized unit {unit_text!r}.")


def bump_key_node_rate(node: Mapping[str, Any], *, bump_bp: float) -> dict[str, Any]:
    """Return a copied key node with one supported rate/yield field bumped.

    ``node`` is never mutated. The bump is expressed in basis points and is
    applied to the raw source field using that field's explicit unit.
    """

    out = dict(node)
    if _has_value(out.get("yield")):
        out["yield"] = bumped_raw_rate(
            out.get("yield"),
            unit=_first_present(out, "yield_unit", "quote_unit", "rate_unit"),
            bump_bp=bump_bp,
        )
        return out
    if _has_value(out.get("yield_value")):
        out["yield_value"] = bumped_raw_rate(
            out.get("yield_value"),
            unit=_first_present(out, "yield_unit", "quote_unit", "rate_unit"),
            bump_bp=bump_bp,
        )
        return out

    quote_type = _normalized_token(out.get("quote_type"))
    if quote_type in RATE_QUOTE_TYPES and _has_value(out.get("quote")):
        out["quote"] = bumped_raw_rate(
            out.get("quote"),
            unit=_first_present(out, "quote_unit", "rate_unit"),
            bump_bp=bump_bp,
        )
        return out

    if _has_value(out.get("implied_rate")):
        out["implied_rate"] = bumped_raw_rate(
            out.get("implied_rate"),
            unit=_first_present(out, "implied_rate_unit", "rate_unit", "quote_unit"),
            bump_bp=bump_bp,
        )
        return out

    raise ValueError(f"Cannot bump key node without a supported rate/yield field: {node!r}.")


def bump_key_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
    bump_spec: CurveBumpSpec,
    *,
    effective_curve_date: object,
) -> list[dict[str, Any]]:
    """Return copied key nodes with parallel and key-rate shocks applied.

    The input sequence and its dictionaries are never mutated. Each usable node
    must resolve to a positive days-to-maturity value. Missing maturities,
    unsupported rate fields, unsupported units, and unsupported quote types
    raise explicit errors.
    """

    if bump_spec.is_empty():
        return [dict(node) for node in key_nodes]

    bumped: list[dict[str, Any]] = []
    for node in key_nodes:
        days = key_node_days_to_maturity(node, effective_curve_date=effective_curve_date)
        if days is None or days <= 0:
            raise ValueError(f"Curve key node is missing positive maturity: {node!r}.")
        bumped.append(bump_key_node_rate(node, bump_bp=bump_spec.total_bp_for_days(days)))
    return bumped


def key_nodes_to_curve_observation_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
    *,
    building_details: object,
    effective_curve_date: object,
) -> list[dict[str, float | int]]:
    """Convert bumped key nodes into resolver-compatible runtime nodes.

    The output node quote field follows runtime ``CurveBuildingDetails``:
    ``zero_rate``/``zero`` creates ``zero`` fields and
    ``forward_rate``/``forward`` creates ``forward`` fields. Key-node rates are
    first normalized to decimal rates, then converted into the runtime build
    unit declared by the build details.
    """

    quote_convention = runtime_curve_quote_convention(building_details)
    rate_key = _runtime_rate_key(quote_convention)
    nodes: list[dict[str, float | int]] = []
    for node in key_nodes:
        days = key_node_days_to_maturity(node, effective_curve_date=effective_curve_date)
        if days is None or days <= 0:
            continue
        decimal_rate = key_node_decimal_rate(node)
        nodes.append(
            {
                "days_to_maturity": int(days),
                rate_key: rate_in_build_unit(decimal_rate, building_details=building_details),
            }
        )
    if not nodes:
        raise ValueError("Curve key nodes contain no usable positive-maturity rate nodes.")
    return sorted(nodes, key=lambda item: int(item["days_to_maturity"]))


def runtime_observation_building_details(building_details: object) -> object:
    """Return build details matching already-materialized runtime nodes.

    Some source curves persist placeholders such as
    ``quote_convention="key_node_quote"`` or ``rate_unit="key_node_unit"``
    because source key nodes carry their own raw quote conventions. Runtime
    scenario nodes need one explicit output convention and unit. Those values
    must be present in ``builder_payload`` as output/runtime keys; otherwise the
    function raises instead of guessing.
    """

    runtime_quote = runtime_curve_quote_convention(building_details)
    runtime_unit = runtime_curve_rate_unit(building_details)
    updates: dict[str, object] = {
        "quote_convention": runtime_quote,
        "rate_unit": runtime_unit,
    }
    if runtime_quote in {"zero", "zero_rate"}:
        updates["builder_type"] = "zero_rate_curve"
    elif runtime_quote in {"forward", "forward_rate"}:
        updates["builder_type"] = "forward_rate_curve"

    model_copy = getattr(building_details, "model_copy", None)
    if callable(model_copy):
        return model_copy(update=updates)

    payload = {
        key: getattr(building_details, key)
        for key in dir(building_details)
        if not key.startswith("_") and not callable(getattr(building_details, key))
    }
    payload.update(updates)
    return SimpleNamespace(**payload)


def runtime_curve_quote_convention(building_details: object) -> str:
    """Return the explicit runtime node quote convention for scenario nodes."""

    quote_convention = _normalized_token(getattr(building_details, "quote_convention", None))
    if quote_convention in _KEY_NODE_QUOTE_PLACEHOLDERS:
        payload = _builder_payload(building_details)
        quote_convention = _first_payload_token(
            payload,
            "output_quote_convention",
            "output_quote_type",
            "runtime_quote_convention",
            "runtime_quote_type",
        )
    if quote_convention in {"zero", "zero_rate", "forward", "forward_rate"}:
        return quote_convention
    raise ValueError(
        "Curve scenario runtime nodes require quote_convention zero_rate or "
        f"forward_rate, got {quote_convention!r}."
    )


def runtime_curve_rate_unit(building_details: object) -> str:
    """Return the explicit runtime node rate unit for scenario nodes."""

    rate_unit = _normalized_token(getattr(building_details, "rate_unit", None))
    if rate_unit in _KEY_NODE_UNIT_PLACEHOLDERS:
        payload = _builder_payload(building_details)
        rate_unit = _first_payload_token(
            payload,
            "output_rate_unit",
            "output_quote_unit",
            "runtime_rate_unit",
            "runtime_quote_unit",
        )
    return _normalize_rate_unit(rate_unit)


def rate_in_build_unit(value: float, *, building_details: object) -> float:
    """Return a decimal rate in the runtime curve builder's configured unit."""

    decimal = _finite_float(value, field_name="value")
    rate_unit = runtime_curve_rate_unit(building_details)
    if rate_unit == "decimal":
        return decimal
    if rate_unit == "percent":
        return decimal * 100.0
    raise AssertionError(f"Unhandled normalized unit {rate_unit!r}.")


def _runtime_rate_key(quote_convention: str) -> str:
    if quote_convention in {"zero", "zero_rate"}:
        return "zero"
    if quote_convention in {"forward", "forward_rate"}:
        return "forward"
    raise ValueError(f"Unsupported runtime quote_convention={quote_convention!r}.")


def _builder_payload(building_details: object) -> Mapping[str, Any]:
    payload = getattr(building_details, "builder_payload", None)
    if not isinstance(payload, Mapping):
        raise ValueError(
            "CurveBuildingDetails.builder_payload must provide explicit runtime "
            "output convention/unit when source placeholders are used."
        )
    return payload


def _first_payload_token(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        token = _normalized_token(payload.get(key))
        if token:
            return token
    raise ValueError(f"builder_payload is missing one of: {', '.join(keys)}.")


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
    "bump_key_node_rate",
    "bump_key_nodes",
    "bumped_raw_rate",
    "key_node_days_to_maturity",
    "key_node_decimal_rate",
    "key_node_maturity_date",
    "key_nodes_to_curve_observation_nodes",
    "normalize_rate_value",
    "rate_in_build_unit",
    "runtime_curve_quote_convention",
    "runtime_curve_rate_unit",
    "runtime_observation_building_details",
    "tenor_to_days",
    "to_utc_datetime",
]
