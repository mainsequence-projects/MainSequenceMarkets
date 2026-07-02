"""Adapters from generic helper-shaped key nodes to QuantLib helper specs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

import QuantLib as ql
from pydantic import BaseModel, ConfigDict, Field

from msm_pricing.pricing_engine.curves.bond_helper_key_nodes import (
    BOND_HELPER_TYPES,
    BondHelperKeyNode,
    FixedRateBondHelperKeyNode,
    ZeroCouponBondHelperKeyNode,
    bond_helper_spec_from_key_node,
    parse_bond_helper_key_node,
)
from msm_pricing.pricing_engine.curves.helpers import (
    InterestRateFutureHelperSpec,
    OISRateHelperSpec,
    OvernightDepositHelperSpec,
    RateHelperSpec,
)
from msm_pricing.pricing_engine.curves.quote_units import key_node_decimal_rate, key_node_price

OIS_HELPER_TYPES = frozenset({"ois_rate_helper", "overnight_indexed_swap_helper"})
OVERNIGHT_DEPOSIT_HELPER_TYPE = "overnight_deposit_helper"
SOFR_FUTURE_HELPER_TYPE = "sofr_future_rate_helper"
INTEREST_RATE_FUTURE_HELPER_TYPES = frozenset(
    {"interest_rate_future_helper", SOFR_FUTURE_HELPER_TYPE}
)
SUPPORTED_RATE_HELPER_TYPES = frozenset(
    {
        *OIS_HELPER_TYPES,
        OVERNIGHT_DEPOSIT_HELPER_TYPE,
        *INTEREST_RATE_FUTURE_HELPER_TYPES,
        *BOND_HELPER_TYPES,
    }
)
OvernightIndexResolver = Callable[[str | None, Mapping[str, Any]], ql.OvernightIndex]


class OvernightDepositHelperKeyNode(BaseModel):
    """Generic key-node schema for a QuantLib overnight deposit helper."""

    model_config = ConfigDict(extra="allow")

    helper_type: Literal["overnight_deposit_helper"]
    quote: float
    quote_type: str
    quote_unit: str
    tenor: str = "1D"
    fixing_days: int = 0
    calendar_code: str = "TARGET"
    business_day_convention: int | str = Field(default="Following")
    end_of_month: bool = False
    day_counter_code: str = "Actual360"


class OISRateHelperKeyNode(BaseModel):
    """Generic key-node schema for a QuantLib overnight-indexed swap helper."""

    model_config = ConfigDict(extra="allow")

    helper_type: Literal["ois_rate_helper", "overnight_indexed_swap_helper"]
    quote: float
    quote_type: str
    quote_unit: str
    tenor: str
    settlement_days: int = 0
    floating_index: str | None = None
    telescopic_value_dates: bool = False
    payment_lag: int = 0
    payment_convention: int | str = Field(default="Following")
    payment_frequency: int | str | None = None
    payment_calendar_code: str | dict[str, Any] | None = None
    forward_start: str = "0D"
    overnight_spread: float = 0.0
    pillar: int | str = Field(default="LastRelevantDate")
    custom_pillar_date: str | None = None
    averaging_method: int | str = Field(default="Compound")
    end_of_month: bool | None = None
    fixed_payment_frequency: int | str | None = None
    fixed_calendar_code: str | dict[str, Any] | None = None
    lookback_days: int | None = None
    lockout_days: int = 0
    apply_observation_shift: bool = False
    rule: int | str = Field(default="Backward")
    overnight_calendar_code: str | dict[str, Any] | None = None
    date_generation_convention: int | str = Field(default="ModifiedFollowing")


class InterestRateFutureHelperKeyNode(BaseModel):
    """Generic key-node schema for a QuantLib interest-rate futures helper."""

    model_config = ConfigDict(extra="allow")

    helper_type: Literal["interest_rate_future_helper", "sofr_future_rate_helper"]
    quote: float
    quote_type: str
    quote_unit: str
    reference_month: int | str
    reference_year: int
    reference_frequency: int | str
    future_family: str | None = None
    convexity_adjustment: float = 0.0
    pillar: int | str = Field(default="LastRelevantDate")
    custom_pillar_date: str | None = None


RateHelperKeyNode = (
    OvernightDepositHelperKeyNode
    | OISRateHelperKeyNode
    | InterestRateFutureHelperKeyNode
    | BondHelperKeyNode
)


def normalize_helper_type(value: object) -> str:
    """Normalize a key-node helper type token."""

    helper_type = str(value or "").strip().lower()
    if helper_type not in SUPPORTED_RATE_HELPER_TYPES:
        raise ValueError(
            f"Unsupported helper_type={value!r}. Supported helper types: "
            f"{', '.join(sorted(SUPPORTED_RATE_HELPER_TYPES))}."
        )
    return helper_type


def parse_rate_helper_key_node(node: Mapping[str, Any]) -> RateHelperKeyNode:
    """Validate one generic helper-shaped key node."""

    helper_type = normalize_helper_type(node.get("helper_type"))
    payload = dict(node)
    payload["helper_type"] = helper_type
    if helper_type in BOND_HELPER_TYPES:
        return parse_bond_helper_key_node(payload)
    if helper_type == OVERNIGHT_DEPOSIT_HELPER_TYPE:
        return OvernightDepositHelperKeyNode.model_validate(payload)
    if helper_type in INTEREST_RATE_FUTURE_HELPER_TYPES:
        return InterestRateFutureHelperKeyNode.model_validate(payload)
    return OISRateHelperKeyNode.model_validate(payload)


def helper_specs_from_key_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
    *,
    overnight_index: ql.OvernightIndex | None = None,
    overnight_index_resolver: OvernightIndexResolver | None = None,
) -> tuple[RateHelperSpec, ...]:
    """Convert helper-shaped key nodes to primitive QuantLib helper specs.

    OIS helpers require an overnight index supplied either directly through
    ``overnight_index`` or through ``overnight_index_resolver``. The resolver
    receives ``(floating_index, original_node)`` and must return a QuantLib
    ``OvernightIndex``. No index is inferred from vendor or product names.
    """

    if isinstance(key_nodes, str | bytes) or not isinstance(key_nodes, Sequence):
        raise TypeError("key_nodes must be a sequence of mapping objects.")
    specs: list[RateHelperSpec] = []
    for raw_node in key_nodes:
        if not isinstance(raw_node, Mapping):
            raise TypeError("Each rate-helper key node must be a mapping.")
        node = parse_rate_helper_key_node(raw_node)
        if isinstance(node, OvernightDepositHelperKeyNode):
            decimal_quote = key_node_decimal_rate(node.model_dump())
            specs.append(
                OvernightDepositHelperSpec(
                    quote=decimal_quote,
                    tenor=node.tenor,
                    fixing_days=node.fixing_days,
                    calendar=node.calendar_code,
                    convention=node.business_day_convention,
                    end_of_month=node.end_of_month,
                    day_counter=node.day_counter_code,
                )
            )
            continue
        if isinstance(node, InterestRateFutureHelperKeyNode):
            price_quote = key_node_price(node.model_dump())
            specs.append(
                InterestRateFutureHelperSpec(
                    quote=price_quote,
                    reference_month=node.reference_month,
                    reference_year=node.reference_year,
                    reference_frequency=node.reference_frequency,
                    future_family=_future_family(node),
                    convexity_adjustment=node.convexity_adjustment,
                    pillar=node.pillar,
                    custom_pillar_date=node.custom_pillar_date,
                )
            )
            continue
        if isinstance(node, ZeroCouponBondHelperKeyNode | FixedRateBondHelperKeyNode):
            specs.append(bond_helper_spec_from_key_node(node))
            continue
        decimal_quote = key_node_decimal_rate(node.model_dump())
        specs.append(
            OISRateHelperSpec(
                quote=decimal_quote,
                tenor=node.tenor,
                settlement_days=node.settlement_days,
                overnight_index=_resolve_overnight_index(
                    node,
                    raw_node=raw_node,
                    overnight_index=overnight_index,
                    overnight_index_resolver=overnight_index_resolver,
                ),
                telescopic_value_dates=node.telescopic_value_dates,
                payment_lag=node.payment_lag,
                payment_convention=node.payment_convention,
                payment_frequency=_payment_frequency(node),
                payment_calendar=_payment_calendar(node),
                forward_start=node.forward_start,
                overnight_spread=node.overnight_spread,
                pillar=node.pillar,
                custom_pillar_date=node.custom_pillar_date,
                averaging_method=node.averaging_method,
                end_of_month=node.end_of_month,
                fixed_payment_frequency=node.fixed_payment_frequency,
                fixed_calendar=node.fixed_calendar_code,
                lookback_days=node.lookback_days,
                lockout_days=node.lockout_days,
                apply_observation_shift=node.apply_observation_shift,
                rule=node.rule,
                overnight_calendar=node.overnight_calendar_code,
                date_generation_convention=node.date_generation_convention,
            )
        )
    if not specs:
        raise ValueError("At least one rate-helper key node is required.")
    return tuple(specs)


def key_nodes_contain_rate_helpers(key_nodes: object) -> bool:
    """Return whether every submitted key node declares a supported helper type."""

    if isinstance(key_nodes, str | bytes) or not isinstance(key_nodes, Sequence):
        return False
    if not key_nodes:
        return False
    for node in key_nodes:
        if not isinstance(node, Mapping):
            return False
        try:
            normalize_helper_type(node.get("helper_type"))
        except ValueError:
            return False
    return True


def _resolve_overnight_index(
    node: OISRateHelperKeyNode,
    *,
    raw_node: Mapping[str, Any],
    overnight_index: ql.OvernightIndex | None,
    overnight_index_resolver: OvernightIndexResolver | None,
) -> ql.OvernightIndex:
    if overnight_index is not None:
        return overnight_index
    if overnight_index_resolver is not None:
        resolved = overnight_index_resolver(node.floating_index, raw_node)
        if not isinstance(resolved, ql.OvernightIndex):
            raise TypeError("overnight_index_resolver must return a QuantLib OvernightIndex.")
        return resolved
    raise ValueError(
        "OIS rate-helper key nodes require overnight_index or overnight_index_resolver; "
        "msm_pricing does not infer indexes from curve or provider names."
    )


def _payment_frequency(node: OISRateHelperKeyNode) -> int | str:
    if node.payment_frequency not in (None, ""):
        return node.payment_frequency
    if node.fixed_payment_frequency not in (None, ""):
        return node.fixed_payment_frequency
    return "Annual"


def _payment_calendar(node: OISRateHelperKeyNode) -> str | dict[str, Any] | None:
    if node.payment_calendar_code not in (None, ""):
        return node.payment_calendar_code
    return node.fixed_calendar_code


def _future_family(node: InterestRateFutureHelperKeyNode) -> str:
    if node.future_family not in (None, ""):
        return str(node.future_family)
    if node.helper_type == SOFR_FUTURE_HELPER_TYPE:
        return "sofr"
    raise ValueError("interest_rate_future_helper key nodes require future_family.")


__all__ = [
    "BOND_HELPER_TYPES",
    "BondHelperKeyNode",
    "FixedRateBondHelperKeyNode",
    "INTEREST_RATE_FUTURE_HELPER_TYPES",
    "InterestRateFutureHelperKeyNode",
    "OIS_HELPER_TYPES",
    "OISRateHelperKeyNode",
    "OVERNIGHT_DEPOSIT_HELPER_TYPE",
    "OvernightDepositHelperKeyNode",
    "OvernightIndexResolver",
    "RateHelperKeyNode",
    "SOFR_FUTURE_HELPER_TYPE",
    "SUPPORTED_RATE_HELPER_TYPES",
    "ZeroCouponBondHelperKeyNode",
    "helper_specs_from_key_nodes",
    "key_nodes_contain_rate_helpers",
    "normalize_helper_type",
    "parse_rate_helper_key_node",
]
