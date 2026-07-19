"""Adapters from bond-helper key nodes to QuantLib bond-helper specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field

from msm_pricing.pricing_engine.curves.bond_helpers import (
    BondHelperSpec,
    FixedRateBondHelperSpec,
    ZeroCouponBondHelperSpec,
)
from msm_pricing.pricing_engine.curves.fixed_income_key_nodes import FixedIncomeCurveKeyNode

ZERO_COUPON_BOND_HELPER_TYPE = "zero_coupon_bond_helper"
FIXED_RATE_BOND_HELPER_TYPE = "fixed_rate_bond_helper"
BOND_HELPER_TYPES = frozenset({ZERO_COUPON_BOND_HELPER_TYPE, FIXED_RATE_BOND_HELPER_TYPE})


class ZeroCouponBondHelperKeyNode(FixedIncomeCurveKeyNode):
    """Generic key-node schema for a QuantLib zero-coupon bond helper."""

    helper_type: Literal["zero_coupon_bond_helper"]
    quote_type: Literal["clean_price", "dirty_price"]
    quote_unit: Literal["price", "price_per_face", "price_per_100"]
    maturity_date: str
    settlement_days: int = 0
    calendar_code: str | dict[str, Any] = "TARGET"
    face_value: float = 100.0
    payment_convention: int | str = Field(default="Following")
    redemption: float | None = None
    issue_date: str | None = None


class FixedRateBondHelperKeyNode(FixedIncomeCurveKeyNode):
    """Generic key-node schema for a QuantLib fixed-rate bond helper."""

    helper_type: Literal["fixed_rate_bond_helper"]
    quote_type: Literal["clean_price", "dirty_price"]
    quote_unit: Literal["price", "price_per_face", "price_per_100"]
    coupon_rate: float
    issue_date: str
    maturity_date: str
    settlement_days: int = 0
    face_value: float = 100.0
    calendar_code: str | dict[str, Any] = "TARGET"
    tenor: str | None = None
    coupon_period_days: int | None = None
    coupon_frequency: int | str | None = None
    schedule: dict[str, Any] | list[str] | None = None
    schedule_dates: list[str] | None = None
    day_counter_code: str = "Actual360"
    payment_convention: int | str = Field(default="Following")
    business_day_convention: int | str = Field(default="Following")
    termination_business_day_convention: int | str | None = None
    redemption: float | None = None
    payment_calendar_code: str | dict[str, Any] | None = None
    end_of_month: bool = False
    date_generation_rule: int | str = Field(default="Backward")
    first_date: str | None = None
    next_to_last_date: str | None = None
    ex_coupon_period: str | None = None
    ex_coupon_calendar_code: str | dict[str, Any] | None = None
    ex_coupon_convention: int | str = Field(default="Unadjusted")
    ex_coupon_end_of_month: bool = False


BondHelperKeyNode = ZeroCouponBondHelperKeyNode | FixedRateBondHelperKeyNode


def normalize_bond_helper_type(value: object) -> str:
    """Normalize a bond-helper key-node type token."""

    helper_type = str(value or "").strip().lower()
    if helper_type not in BOND_HELPER_TYPES:
        raise ValueError(
            f"Unsupported bond helper_type={value!r}. Supported helper types: "
            f"{', '.join(sorted(BOND_HELPER_TYPES))}."
        )
    return helper_type


def parse_bond_helper_key_node(node: Mapping[str, Any]) -> BondHelperKeyNode:
    """Validate one generic bond-helper-shaped key node."""

    helper_type = normalize_bond_helper_type(node.get("helper_type"))
    payload = dict(node)
    payload["helper_type"] = helper_type
    if helper_type == ZERO_COUPON_BOND_HELPER_TYPE:
        return ZeroCouponBondHelperKeyNode.model_validate(payload)
    return FixedRateBondHelperKeyNode.model_validate(payload)


def bond_helper_spec_from_key_node(node: BondHelperKeyNode) -> BondHelperSpec:
    """Convert one validated bond-helper key node into a runtime helper spec."""

    if isinstance(node, ZeroCouponBondHelperKeyNode):
        return ZeroCouponBondHelperSpec(
            quote=node.quote,
            maturity_date=node.maturity_date,
            quote_type=node.quote_type,
            quote_unit=node.quote_unit,
            settlement_days=node.settlement_days,
            calendar=node.calendar_code,
            face_value=node.face_value,
            payment_convention=node.payment_convention,
            redemption=node.redemption,
            issue_date=node.issue_date,
        )
    return FixedRateBondHelperSpec(
        quote=node.quote,
        coupon_rate=node.coupon_rate,
        issue_date=node.issue_date,
        maturity_date=node.maturity_date,
        quote_type=node.quote_type,
        quote_unit=node.quote_unit,
        settlement_days=node.settlement_days,
        face_value=node.face_value,
        calendar=node.calendar_code,
        tenor=node.tenor,
        coupon_period_days=node.coupon_period_days,
        coupon_frequency=node.coupon_frequency,
        schedule=node.schedule,
        schedule_dates=node.schedule_dates,
        day_counter=node.day_counter_code,
        payment_convention=node.payment_convention,
        business_day_convention=node.business_day_convention,
        termination_business_day_convention=node.termination_business_day_convention,
        redemption=node.redemption,
        payment_calendar=node.payment_calendar_code,
        end_of_month=node.end_of_month,
        date_generation_rule=node.date_generation_rule,
        first_date=node.first_date,
        next_to_last_date=node.next_to_last_date,
        ex_coupon_period=node.ex_coupon_period,
        ex_coupon_calendar=node.ex_coupon_calendar_code,
        ex_coupon_convention=node.ex_coupon_convention,
        ex_coupon_end_of_month=node.ex_coupon_end_of_month,
    )


def bond_helper_specs_from_key_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
) -> tuple[BondHelperSpec, ...]:
    """Convert bond-helper-shaped key nodes to primitive QuantLib helper specs."""

    if isinstance(key_nodes, str | bytes) or not isinstance(key_nodes, Sequence):
        raise TypeError("key_nodes must be a sequence of mapping objects.")
    specs: list[BondHelperSpec] = []
    for node in key_nodes:
        if not isinstance(node, Mapping):
            raise TypeError("Each bond-helper key node must be a mapping.")
        specs.append(bond_helper_spec_from_key_node(parse_bond_helper_key_node(node)))
    if not specs:
        raise ValueError("At least one bond-helper key node is required.")
    return tuple(specs)


def key_nodes_contain_bond_helpers(key_nodes: object) -> bool:
    """Return whether every submitted key node declares a supported bond helper."""

    if isinstance(key_nodes, str | bytes) or not isinstance(key_nodes, Sequence):
        return False
    if not key_nodes:
        return False
    for node in key_nodes:
        if not isinstance(node, Mapping):
            return False
        try:
            normalize_bond_helper_type(node.get("helper_type"))
        except ValueError:
            return False
    return True


__all__ = [
    "BOND_HELPER_TYPES",
    "BondHelperKeyNode",
    "FIXED_RATE_BOND_HELPER_TYPE",
    "FixedRateBondHelperKeyNode",
    "ZERO_COUPON_BOND_HELPER_TYPE",
    "ZeroCouponBondHelperKeyNode",
    "bond_helper_spec_from_key_node",
    "bond_helper_specs_from_key_nodes",
    "key_nodes_contain_bond_helpers",
    "normalize_bond_helper_type",
    "parse_bond_helper_key_node",
]
