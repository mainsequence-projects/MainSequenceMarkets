"""Adapters from cross-currency helper key nodes to runtime helper specs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from msm_pricing.pricing_engine.curves.cross_currency_helpers import (
    ConstNotionalCrossCurrencyBasisSwapRateHelperSpec,
    CrossCurrencyRateHelperSpec,
    FxSwapRateHelperSpec,
)
from msm_pricing.pricing_engine.curves.helper_resolution import (
    MissingRateHelperDependencyError,
    RateHelperRuntimeResolver,
)
from msm_pricing.pricing_engine.curves.quote_units import (
    key_node_basis_spread,
    key_node_fx_forward_points,
)

FX_SPOT_CONTEXT_TYPE = "fx_spot"
FX_SWAP_RATE_HELPER_TYPE = "fx_swap_rate_helper"
CONST_NOTIONAL_CROSS_CURRENCY_BASIS_SWAP_RATE_HELPER_TYPE = (
    "const_notional_cross_currency_basis_swap_rate_helper"
)
CROSS_CURRENCY_CONTEXT_TYPES = frozenset({FX_SPOT_CONTEXT_TYPE})
CROSS_CURRENCY_HELPER_TYPES = frozenset(
    {
        FX_SWAP_RATE_HELPER_TYPE,
        CONST_NOTIONAL_CROSS_CURRENCY_BASIS_SWAP_RATE_HELPER_TYPE,
    }
)
CROSS_CURRENCY_KEY_NODE_TYPES = frozenset(
    {*CROSS_CURRENCY_CONTEXT_TYPES, *CROSS_CURRENCY_HELPER_TYPES}
)


class FxSpotContextKeyNode(BaseModel):
    """Generic context key-node schema for an FX spot quote."""

    model_config = ConfigDict(extra="allow")

    helper_type: Literal["fx_spot"]
    quote: float
    quote_type: Literal["fx_spot"]
    quote_unit: str
    fx_pair: str
    fx_base_currency: str
    fx_quote_currency: str
    asset_identifier: str | None = None
    maturity_date: str | None = None
    quote_side: str | None = None
    quote_source: str | None = None
    source_quote: float | None = None
    source_quote_unit: str | None = None


class FxSwapRateHelperKeyNode(BaseModel):
    """Generic key-node schema for a QuantLib FX swap helper."""

    model_config = ConfigDict(extra="allow")

    helper_type: Literal["fx_swap_rate_helper"]
    quote: float
    quote_type: Literal["fx_forward_points"]
    quote_unit: str
    tenor: str
    fixing_days: int
    calendar_code: str | dict[str, Any]
    business_day_convention: int | str = Field(default="ModifiedFollowing")
    end_of_month: bool = False
    fx_pair: str
    fx_base_currency: str
    fx_quote_currency: str
    is_fx_base_currency_collateral_currency: bool
    collateral_curve: str
    spot: float | None = None
    spot_context_key: str | None = None
    trading_calendar_code: str | dict[str, Any] | None = None
    source_quote: float | None = None
    source_quote_unit: str | None = None
    point_scale: float | None = None
    market_forward: float | None = None


class ConstNotionalCrossCurrencyBasisSwapRateHelperKeyNode(BaseModel):
    """Generic key-node schema for a constant-notional cross-currency basis helper."""

    model_config = ConfigDict(extra="allow")

    helper_type: Literal["const_notional_cross_currency_basis_swap_rate_helper"]
    quote: float
    quote_type: Literal["basis_spread"]
    quote_unit: str
    tenor: str
    fixing_days: int
    calendar_code: str | dict[str, Any]
    business_day_convention: int | str = Field(default="ModifiedFollowing")
    end_of_month: bool = False
    base_currency_index: str
    quote_currency_index: str
    collateral_curve: str
    is_fx_base_currency_collateral_currency: bool
    is_basis_on_fx_base_currency_leg: bool
    payment_frequency: int | str = Field(default="NoFrequency")
    payment_lag: int = 0
    basis_sign: str | None = None
    basis_side: str | None = None
    notional_style: str | None = None
    source_quote: float | None = None
    source_quote_unit: str | None = None


CrossCurrencyHelperKeyNode = (
    FxSwapRateHelperKeyNode | ConstNotionalCrossCurrencyBasisSwapRateHelperKeyNode
)
CrossCurrencyKeyNode = FxSpotContextKeyNode | CrossCurrencyHelperKeyNode


def normalize_cross_currency_helper_type(value: object) -> str:
    """Normalize a cross-currency helper or context helper-type token."""

    helper_type = str(value or "").strip().lower()
    if helper_type not in CROSS_CURRENCY_KEY_NODE_TYPES:
        raise ValueError(
            f"Unsupported cross-currency helper_type={value!r}. Supported helper types: "
            f"{', '.join(sorted(CROSS_CURRENCY_KEY_NODE_TYPES))}."
        )
    return helper_type


def parse_cross_currency_key_node(node: Mapping[str, Any]) -> CrossCurrencyKeyNode:
    """Validate one cross-currency helper or context key node."""

    helper_type = normalize_cross_currency_helper_type(node.get("helper_type"))
    payload = dict(node)
    payload["helper_type"] = helper_type
    if helper_type == FX_SPOT_CONTEXT_TYPE:
        return FxSpotContextKeyNode.model_validate(payload)
    if helper_type == FX_SWAP_RATE_HELPER_TYPE:
        return FxSwapRateHelperKeyNode.model_validate(payload)
    return ConstNotionalCrossCurrencyBasisSwapRateHelperKeyNode.model_validate(payload)


def cross_currency_context_from_key_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
) -> tuple[FxSpotContextKeyNode, ...]:
    """Return cross-currency context nodes from a mixed helper key-node sequence."""

    contexts: list[FxSpotContextKeyNode] = []
    seen_keys: set[str] = set()
    for raw_node in key_nodes:
        helper_type = str(raw_node.get("helper_type") or "").strip().lower()
        if helper_type != FX_SPOT_CONTEXT_TYPE:
            continue
        context = FxSpotContextKeyNode.model_validate(dict(raw_node, helper_type=helper_type))
        for key in _spot_context_lookup_keys(context):
            if key in seen_keys:
                raise ValueError(f"Duplicate FX spot context key {key!r}.")
            seen_keys.add(key)
        contexts.append(context)
    return tuple(contexts)


def cross_currency_helper_spec_from_key_node(
    node: CrossCurrencyHelperKeyNode,
    *,
    context_nodes: Sequence[FxSpotContextKeyNode],
    helper_runtime_resolver: RateHelperRuntimeResolver | None,
) -> CrossCurrencyRateHelperSpec:
    """Convert one cross-currency helper key node to a runtime helper spec."""

    resolver = _required_runtime_resolver(helper_runtime_resolver)
    if isinstance(node, FxSwapRateHelperKeyNode):
        node_dump = node.model_dump()
        return FxSwapRateHelperSpec(
            forward_points=key_node_fx_forward_points(node_dump),
            spot=_fx_spot_for_node(node, context_nodes),
            tenor=node.tenor,
            fixing_days=node.fixing_days,
            calendar=node.calendar_code,
            convention=node.business_day_convention,
            end_of_month=node.end_of_month,
            is_fx_base_currency_collateral_currency=(
                node.is_fx_base_currency_collateral_currency
            ),
            collateral_curve=resolver.resolve_yield_curve(node.collateral_curve, node_dump),
            trading_calendar=node.trading_calendar_code,
        )
    node_dump = node.model_dump()
    return ConstNotionalCrossCurrencyBasisSwapRateHelperSpec(
        basis=key_node_basis_spread(node_dump),
        tenor=node.tenor,
        fixing_days=node.fixing_days,
        calendar=node.calendar_code,
        convention=node.business_day_convention,
        end_of_month=node.end_of_month,
        base_currency_index=resolver.resolve_index(node.base_currency_index, node_dump),
        quote_currency_index=resolver.resolve_index(node.quote_currency_index, node_dump),
        collateral_curve=resolver.resolve_yield_curve(node.collateral_curve, node_dump),
        is_fx_base_currency_collateral_currency=node.is_fx_base_currency_collateral_currency,
        is_basis_on_fx_base_currency_leg=node.is_basis_on_fx_base_currency_leg,
        payment_frequency=node.payment_frequency,
        payment_lag=node.payment_lag,
    )


def cross_currency_helper_specs_from_key_nodes(
    key_nodes: Sequence[Mapping[str, Any]],
    *,
    helper_runtime_resolver: RateHelperRuntimeResolver | None,
) -> tuple[CrossCurrencyRateHelperSpec, ...]:
    """Convert cross-currency helper key nodes to runtime helper specs."""

    context_nodes = cross_currency_context_from_key_nodes(key_nodes)
    specs: list[CrossCurrencyRateHelperSpec] = []
    for raw_node in key_nodes:
        helper_type = str(raw_node.get("helper_type") or "").strip().lower()
        if helper_type not in CROSS_CURRENCY_HELPER_TYPES:
            continue
        node = parse_cross_currency_key_node(raw_node)
        if not isinstance(
            node,
            FxSwapRateHelperKeyNode
            | ConstNotionalCrossCurrencyBasisSwapRateHelperKeyNode,
        ):
            continue
        specs.append(
            cross_currency_helper_spec_from_key_node(
                node,
                context_nodes=context_nodes,
                helper_runtime_resolver=helper_runtime_resolver,
            )
        )
    return tuple(specs)


def key_nodes_contain_cross_currency_helpers(key_nodes: object) -> bool:
    """Return whether submitted key nodes include cross-currency helpers."""

    if isinstance(key_nodes, str | bytes) or not isinstance(key_nodes, Sequence):
        return False
    return any(
        isinstance(node, Mapping)
        and str(node.get("helper_type") or "").strip().lower()
        in CROSS_CURRENCY_HELPER_TYPES
        for node in key_nodes
    )


def _required_runtime_resolver(
    resolver: RateHelperRuntimeResolver | None,
) -> RateHelperRuntimeResolver:
    if resolver is None:
        raise MissingRateHelperDependencyError(
            "Cross-currency helper key nodes require helper_runtime_resolver."
        )
    return resolver


def _fx_spot_for_node(
    node: FxSwapRateHelperKeyNode,
    context_nodes: Sequence[FxSpotContextKeyNode],
) -> float:
    if node.spot is not None:
        return float(node.spot)
    lookup = _spot_context_lookup(context_nodes)
    for key in (node.spot_context_key, node.fx_pair):
        if key in (None, ""):
            continue
        context = lookup.get(str(key))
        if context is not None:
            return float(context.quote)
    raise MissingRateHelperDependencyError(
        "FX swap helper key node requires inline spot or matching fx_spot context."
    )


def _spot_context_lookup(
    contexts: Sequence[FxSpotContextKeyNode],
) -> dict[str, FxSpotContextKeyNode]:
    lookup: dict[str, FxSpotContextKeyNode] = {}
    for context in contexts:
        for key in _spot_context_lookup_keys(context):
            lookup[key] = context
    return lookup


def _spot_context_lookup_keys(context: FxSpotContextKeyNode) -> tuple[str, ...]:
    keys = [context.fx_pair]
    if context.asset_identifier not in (None, ""):
        keys.append(str(context.asset_identifier))
    return tuple(keys)


__all__ = [
    "CONST_NOTIONAL_CROSS_CURRENCY_BASIS_SWAP_RATE_HELPER_TYPE",
    "CROSS_CURRENCY_CONTEXT_TYPES",
    "CROSS_CURRENCY_HELPER_TYPES",
    "CROSS_CURRENCY_KEY_NODE_TYPES",
    "ConstNotionalCrossCurrencyBasisSwapRateHelperKeyNode",
    "CrossCurrencyHelperKeyNode",
    "CrossCurrencyKeyNode",
    "FX_SPOT_CONTEXT_TYPE",
    "FX_SWAP_RATE_HELPER_TYPE",
    "FxSpotContextKeyNode",
    "FxSwapRateHelperKeyNode",
    "cross_currency_context_from_key_nodes",
    "cross_currency_helper_spec_from_key_node",
    "cross_currency_helper_specs_from_key_nodes",
    "key_nodes_contain_cross_currency_helpers",
    "normalize_cross_currency_helper_type",
    "parse_cross_currency_key_node",
]
