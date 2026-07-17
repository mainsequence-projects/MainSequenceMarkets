"""QuantLib-backed pricing engine helpers."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "apply_z_spread_to_curve": ".curve_overlays",
    "build_bond_helper": ".curves",
    "build_bond_helpers": ".curves",
    "build_const_notional_cross_currency_basis_swap_rate_helper": ".curves",
    "build_cross_currency_rate_helper": ".curves",
    "build_fixed_rate_bond_helper": ".curves",
    "build_fx_swap_rate_helper": ".curves",
    "build_interest_rate_future_helper": ".curves",
    "build_ois_rate_helper": ".curves",
    "build_overnight_deposit_helper": ".curves",
    "build_zero_coupon_bond_helper": ".curves",
    "build_curve_from_helper_key_nodes": ".curves",
    "build_rate_helper": ".curves",
    "build_rate_helper_vector": ".curves",
    "build_rate_helpers": ".curves",
    "compare_bond_to_market_quote": ".bond_analytics",
    "compute_coupon_schedule_force_match": ".coupon_schedules",
    "CurveObservationExportConfig": ".curves",
    "CurveObservationNode": ".curves",
    "CurveReconstructionConfig": ".curves",
    "CurveReconstructionResult": ".curves",
    "curve_observation_value": ".curves",
    "export_curve_observation_nodes": ".curves",
    "ConstNotionalCrossCurrencyBasisSwapRateHelperSpec": ".curves",
    "CrossCurrencyRateHelperSpec": ".curves",
    "FixedRateBondHelperSpec": ".curves",
    "FxSwapRateHelperSpec": ".curves",
    "helper_specs_from_key_nodes": ".curves",
    "add_historical_fixings": ".resolvers",
    "build_curve_from_curve_row": ".resolvers",
    "CurveSelectionContext": ".resolvers",
    "is_rate_helper_curve_build": ".curves",
    "InterestRateFutureHelperSpec": ".curves",
    "OISRateHelperSpec": ".curves",
    "normalize_curve_quote_side": ".resolvers",
    "OvernightDepositHelperSpec": ".curves",
    "ql_period_from_tenor": ".curves",
    "RateHelperRuntimeResolver": ".curves",
    "reconstruct_curve_handle": ".curves",
    "reconstruct_curve_handle_from_helper_specs": ".curves",
    "reconstruct_curve_handle_from_key_nodes": ".curves",
    "reconstruct_curve_result_from_helper_specs": ".curves",
    "reconstruct_curve_result_from_key_nodes": ".curves",
    "reconstruct_curve_term_structure": ".curves",
    "reconstruct_curve_term_structure_from_helper_specs": ".curves",
    "reconstruct_curve_term_structure_from_key_nodes": ".curves",
    "resolve_curve_building_details": ".resolvers",
    "resolve_curve_for_index_binding": ".resolvers",
    "resolve_index_convention": ".resolvers",
    "resolve_pricing_curve": ".resolvers",
    "resolve_quantlib_index": ".resolvers",
    "select_curve": ".resolvers",
    "ZeroCouponBondHelperSpec": ".curves",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "add_historical_fixings",
    "apply_z_spread_to_curve",
    "build_bond_helper",
    "build_bond_helpers",
    "build_const_notional_cross_currency_basis_swap_rate_helper",
    "build_cross_currency_rate_helper",
    "build_fixed_rate_bond_helper",
    "build_fx_swap_rate_helper",
    "build_interest_rate_future_helper",
    "build_ois_rate_helper",
    "build_overnight_deposit_helper",
    "build_zero_coupon_bond_helper",
    "build_curve_from_helper_key_nodes",
    "build_curve_from_curve_row",
    "build_rate_helper",
    "build_rate_helper_vector",
    "build_rate_helpers",
    "compare_bond_to_market_quote",
    "compute_coupon_schedule_force_match",
    "CurveObservationExportConfig",
    "CurveObservationNode",
    "CurveReconstructionConfig",
    "CurveReconstructionResult",
    "curve_observation_value",
    "CurveSelectionContext",
    "export_curve_observation_nodes",
    "ConstNotionalCrossCurrencyBasisSwapRateHelperSpec",
    "CrossCurrencyRateHelperSpec",
    "FixedRateBondHelperSpec",
    "FxSwapRateHelperSpec",
    "helper_specs_from_key_nodes",
    "is_rate_helper_curve_build",
    "InterestRateFutureHelperSpec",
    "normalize_curve_quote_side",
    "OISRateHelperSpec",
    "OvernightDepositHelperSpec",
    "ql_period_from_tenor",
    "RateHelperRuntimeResolver",
    "reconstruct_curve_handle",
    "reconstruct_curve_handle_from_helper_specs",
    "reconstruct_curve_handle_from_key_nodes",
    "reconstruct_curve_result_from_helper_specs",
    "reconstruct_curve_result_from_key_nodes",
    "reconstruct_curve_term_structure",
    "reconstruct_curve_term_structure_from_helper_specs",
    "reconstruct_curve_term_structure_from_key_nodes",
    "resolve_curve_building_details",
    "resolve_curve_for_index_binding",
    "resolve_index_convention",
    "resolve_pricing_curve",
    "resolve_quantlib_index",
    "select_curve",
    "ZeroCouponBondHelperSpec",
]
