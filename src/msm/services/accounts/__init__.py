from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ALLOCATION_MODE_PROPORTIONAL_ATTRIBUTION": ".account_virtual_allocations",
    "ALLOCATION_MODE_STRICT_FEASIBLE": ".account_virtual_allocations",
    "CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL": ".account_virtual_allocations",
    "CLAIM_TYPE_VIRTUAL_FUND_TARGET": ".account_virtual_allocations",
    "PLAN_STATUS_ATTRIBUTED_WITH_TARGET_GAP": ".account_virtual_allocations",
    "PLAN_STATUS_FEASIBLE": ".account_virtual_allocations",
    "PLAN_STATUS_INFEASIBLE": ".account_virtual_allocations",
    "AccountAllocationDeficit": ".account_virtual_allocations",
    "AccountAllocationResidual": ".account_virtual_allocations",
    "AccountHoldingsSnapshotExistsError": ".core",
    "AccountVirtualFundAllocationPlan": ".account_virtual_allocations",
    "AccountVirtualHoldingLine": ".account_virtual_allocations",
    "AllocationPolicy": ".account_virtual_allocations",
    "AllocationValuation": ".account_virtual_allocations",
    "HoldingValuationInput": ".account_virtual_allocations",
    "HoldingsSelectionPolicy": ".account_virtual_allocations",
    "TargetNotionalDemand": ".account_virtual_allocations",
    "TargetQuantityDemand": ".account_virtual_allocations",
    "ValuationDiagnostic": ".account_virtual_allocations",
    "ValuationMetricLine": ".account_virtual_allocations",
    "ValuationMetricResult": ".account_virtual_allocations",
    "ValuationMetricValue": ".account_virtual_allocations",
    "ValuationPolicy": ".account_virtual_allocations",
    "ValuationResolver": ".account_virtual_allocations",
    "add_account_holdings_snapshot_response": ".core",
    "apply_account_virtual_fund_allocation_plan": ".account_virtual_allocations",
    "build_virtual_fund_holdings_frame": ".virtual_fund_holdings",
    "create_account": ".core",
    "create_account_allocation_model": ".core",
    "create_account_target_allocation": ".core",
    "create_position_set": ".core",
    "create_virtual_fund": ".virtual_funds",
    "delete_account": ".core",
    "delete_account_target_allocation": ".core",
    "delete_position_set": ".core",
    "delete_virtual_fund": ".virtual_funds",
    "get_account_by_uid": ".core",
    "get_account_by_unique_identifier": ".core",
    "get_account_frontend_detail_summary": ".core",
    "get_account_holdings_snapshot_response": ".core",
    "get_virtual_fund_by_unique_identifier": ".virtual_funds",
    "get_virtual_funds_by_account": ".virtual_funds",
    "get_virtual_funds_by_portfolio": ".virtual_funds",
    "list_account_rows_response": ".core",
    "plan_account_virtual_fund_allocations": ".account_virtual_allocations",
    "search_account_allocation_models": ".core",
    "search_account_target_allocations": ".core",
    "search_accounts": ".core",
    "search_position_sets": ".core",
    "update_account": ".core",
    "update_virtual_fund": ".virtual_funds",
    "validate_holdings_frame": ".virtual_fund_holdings",
    "validate_virtual_fund_allocation_bounds": ".virtual_fund_holdings",
    "virtual_fund_unique_identifier_for_target": ".account_virtual_allocations",
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


__all__ = sorted(_EXPORTS)
