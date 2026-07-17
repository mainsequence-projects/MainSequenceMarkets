"""Curve reconstruction primitives for QuantLib-backed pricing."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "BOND_HELPER_TYPES": ".bond_helper_key_nodes",
    "BASIS_SPREAD_QUOTE_TYPES": ".quote_units",
    "BondHelperKeyNode": ".bond_helper_key_nodes",
    "BondHelperSpec": ".bond_helpers",
    "BondQuoteType": ".bond_helpers",
    "BondQuoteUnit": ".bond_helpers",
    "CONST_NOTIONAL_CROSS_CURRENCY_BASIS_SWAP_RATE_HELPER_TYPE": ".cross_currency_key_nodes",
    "CROSS_CURRENCY_CONTEXT_TYPES": ".cross_currency_key_nodes",
    "CROSS_CURRENCY_HELPER_TYPES": ".cross_currency_key_nodes",
    "CROSS_CURRENCY_KEY_NODE_TYPES": ".cross_currency_key_nodes",
    "ConstNotionalCrossCurrencyBasisSwapRateHelperKeyNode": ".cross_currency_key_nodes",
    "ConstNotionalCrossCurrencyBasisSwapRateHelperSpec": ".cross_currency_helpers",
    "CurveObservationExportConfig": ".observations",
    "CurveObservationNode": ".observations",
    "CurveReconstructionConfig": ".reconstruction",
    "CurveReconstructionResult": ".reconstruction",
    "CrossCurrencyHelperKeyNode": ".cross_currency_key_nodes",
    "CrossCurrencyKeyNode": ".cross_currency_key_nodes",
    "CrossCurrencyRateHelperSpec": ".cross_currency_helpers",
    "FIXED_RATE_BOND_HELPER_TYPE": ".bond_helper_key_nodes",
    "FX_FORWARD_POINT_QUOTE_TYPES": ".quote_units",
    "FX_SPOT_CONTEXT_TYPE": ".cross_currency_key_nodes",
    "FX_SWAP_RATE_HELPER_TYPE": ".cross_currency_key_nodes",
    "FixedRateBondHelperKeyNode": ".bond_helper_key_nodes",
    "FixedRateBondHelperSpec": ".bond_helpers",
    "FxSpotContextKeyNode": ".cross_currency_key_nodes",
    "FxSwapRateHelperKeyNode": ".cross_currency_key_nodes",
    "FxSwapRateHelperSpec": ".cross_currency_helpers",
    "INTEREST_RATE_FUTURE_HELPER_TYPES": ".helper_key_nodes",
    "InterestRateFutureHelperKeyNode": ".helper_key_nodes",
    "InterestRateFutureHelperSpec": ".helpers",
    "MissingRateHelperDependencyError": ".helper_resolution",
    "OIS_HELPER_TYPES": ".helper_key_nodes",
    "OISRateHelperKeyNode": ".helper_key_nodes",
    "OISRateHelperSpec": ".helpers",
    "OVERNIGHT_DEPOSIT_HELPER_TYPE": ".helper_key_nodes",
    "OvernightDepositHelperKeyNode": ".helper_key_nodes",
    "OvernightDepositHelperSpec": ".helpers",
    "OvernightIndexResolver": ".helper_key_nodes",
    "ParsedRateHelperKeyNodes": ".helper_key_nodes",
    "RATE_HELPER_BUILDER_TYPES": ".adapters",
    "PRICE_QUOTE_TYPES": ".quote_units",
    "RATE_QUOTE_TYPES": ".quote_units",
    "RateHelperRuntimeResolver": ".helper_resolution",
    "RateHelperKeyNode": ".helper_key_nodes",
    "RateHelperSpec": ".helpers",
    "SOFR_FUTURE_HELPER_TYPE": ".helper_key_nodes",
    "SUPPORTED_BOOTSTRAP_METHODS": ".reconstruction",
    "SUPPORTED_RATE_HELPER_KEY_NODE_TYPES": ".helper_key_nodes",
    "SUPPORTED_RATE_HELPER_TYPES": ".helper_key_nodes",
    "StaticRateHelperRuntimeResolver": ".helper_resolution",
    "ZERO_COUPON_BOND_HELPER_TYPE": ".bond_helper_key_nodes",
    "ZeroCouponBondHelperKeyNode": ".bond_helper_key_nodes",
    "ZeroCouponBondHelperSpec": ".bond_helpers",
    "bond_helper_spec_from_key_node": ".bond_helper_key_nodes",
    "bond_helper_specs_from_key_nodes": ".bond_helper_key_nodes",
    "build_const_notional_cross_currency_basis_swap_rate_helper": ".cross_currency_helpers",
    "build_bond_helper": ".bond_helpers",
    "build_bond_helpers": ".bond_helpers",
    "build_cross_currency_rate_helper": ".cross_currency_helpers",
    "build_fixed_rate_bond_helper": ".bond_helpers",
    "build_fx_swap_rate_helper": ".cross_currency_helpers",
    "build_interest_rate_future_helper": ".helpers",
    "build_ois_rate_helper": ".helpers",
    "build_overnight_deposit_helper": ".helpers",
    "build_zero_coupon_bond_helper": ".bond_helpers",
    "build_curve_from_helper_key_nodes": ".reconstruction",
    "build_rate_helper": ".helpers",
    "build_rate_helper_vector": ".helpers",
    "build_rate_helpers": ".helpers",
    "curve_observation_value": ".observations",
    "export_curve_observation_nodes": ".observations",
    "cross_currency_context_from_key_nodes": ".cross_currency_key_nodes",
    "cross_currency_helper_spec_from_key_node": ".cross_currency_key_nodes",
    "cross_currency_helper_specs_from_key_nodes": ".cross_currency_key_nodes",
    "key_node_basis_spread": ".quote_units",
    "helper_specs_from_key_nodes": ".helper_key_nodes",
    "is_rate_helper_curve_build": ".adapters",
    "key_node_decimal_rate": ".quote_units",
    "key_node_fx_forward_points": ".quote_units",
    "key_node_price": ".quote_units",
    "key_nodes_contain_bond_helpers": ".bond_helper_key_nodes",
    "key_nodes_contain_cross_currency_helpers": ".cross_currency_key_nodes",
    "key_nodes_contain_rate_helpers": ".helper_key_nodes",
    "normalize_basis_spread_value": ".quote_units",
    "normalize_bond_helper_type": ".bond_helper_key_nodes",
    "normalize_bond_price_value": ".bond_helpers",
    "normalize_cross_currency_helper_type": ".cross_currency_key_nodes",
    "normalize_fx_forward_points_value": ".quote_units",
    "normalize_helper_type": ".helper_key_nodes",
    "normalize_price_value": ".quote_units",
    "normalize_rate_value": ".quote_units",
    "parse_bond_helper_key_node": ".bond_helper_key_nodes",
    "parse_cross_currency_key_node": ".cross_currency_key_nodes",
    "parse_rate_helper_key_nodes": ".helper_key_nodes",
    "parse_rate_helper_key_node": ".helper_key_nodes",
    "ql_period_from_tenor": ".helpers",
    "reconstruct_curve_from_curve_building_details": ".adapters",
    "reconstruct_curve_handle": ".reconstruction",
    "reconstruct_curve_handle_from_helper_specs": ".reconstruction",
    "reconstruct_curve_handle_from_key_nodes": ".reconstruction",
    "reconstruct_curve_result_from_helper_specs": ".reconstruction",
    "reconstruct_curve_result_from_key_nodes": ".reconstruction",
    "reconstruct_curve_term_structure": ".reconstruction",
    "reconstruct_curve_term_structure_from_helper_specs": ".reconstruction",
    "reconstruct_curve_term_structure_from_key_nodes": ".reconstruction",
}


def __getattr__(name: str) -> Any:
    """Lazily load curve reconstruction exports."""

    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return importable curve reconstruction names for interactive discovery."""

    return sorted(set(globals()) | set(__all__))


__all__ = sorted(_EXPORTS)
