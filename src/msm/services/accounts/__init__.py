from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from typing import Any

from . import core as _core

_CORE_ADD_ACCOUNT_HOLDINGS_SNAPSHOT_RESPONSE = _core.add_account_holdings_snapshot_response
_CORE_GET_ACCOUNT_HOLDINGS_SNAPSHOT_RESPONSE = _core.get_account_holdings_snapshot_response

account_repository = _core.account_repository
uuid = _core.uuid
_asset_reference_details_by_identifier = _core._asset_reference_details_by_identifier
_asset_snapshot_references_by_unique_identifier = (
    _core._asset_snapshot_references_by_unique_identifier
)
_build_account_holdings_frame = _core._build_account_holdings_frame
_search_account_holdings_rows = _core._search_account_holdings_rows


def get_account_holdings_snapshot_response(*args: Any, **kwargs: Any) -> Any:
    with _core_account_hooks():
        return _CORE_GET_ACCOUNT_HOLDINGS_SNAPSHOT_RESPONSE(*args, **kwargs)


def add_account_holdings_snapshot_response(*args: Any, **kwargs: Any) -> Any:
    with _core_account_hooks():
        return _CORE_ADD_ACCOUNT_HOLDINGS_SNAPSHOT_RESPONSE(*args, **kwargs)


# The value each core hook has on this package when nothing has replaced it.
# A different value means the hook was replaced on the package (in a test).
_UNPATCHED_CORE_ACCOUNT_HOOKS: dict[str, Any] = {
    name: getattr(_core, name)
    for name in (
        "account_repository",
        "uuid",
        "get_account_by_uid",
        "_asset_reference_details_by_identifier",
        "_asset_snapshot_references_by_unique_identifier",
        "_build_account_holdings_frame",
        "_search_account_holdings_rows",
    )
}


@contextmanager
def _core_account_hooks() -> Iterator[None]:
    """Give one core call the hooks replaced on this package, then put core's back.

    A hook replaced on the package reaches core only while the call runs, so it
    cannot outlive whatever replaced it. With nothing replaced, core is not written.
    """

    replaced: dict[str, Any] = {}
    for name, unpatched in _UNPATCHED_CORE_ACCOUNT_HOOKS.items():
        value = globals().get(name, unpatched)
        if value is not unpatched:
            replaced[name] = value
    previous = {name: getattr(_core, name) for name in replaced}
    for name, value in replaced.items():
        setattr(_core, name, value)
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(_core, name, value)


_EXPORTS = {
    "AccountDeleteConflictError": ".deletion",
    "AccountDeleteImpact": ".deletion",
    "AccountHoldingsSnapshotExistsError": ".core",
    "AccountRegistrationResult": ".registration",
    "AccountRegistrationWrite": ".registration",
    "ALLOCATION_POLICIES": ".allocation_policies",
    "AccountAssetDelta": ".account_virtual_allocations",
    "AccountVirtualFundAllocationPlan": ".account_virtual_allocations",
    "AccountVirtualFundAllocationResult": ".account_virtual_allocations",
    "Allocation": ".allocation_policies",
    "AllocationError": ".allocation_policies",
    "AllocationFund": ".account_virtual_allocations",
    "AllocationLine": ".account_virtual_allocations",
    "AllocationPolicyChoice": ".allocation_policies",
    "AllocationPolicyDefinition": ".allocation_policies",
    "allocation_policy": ".allocation_policies",
    "describe_allocation_policy": ".allocation_policies",
    "proportional_attribution": ".allocation_policies",
    "resolve_allocation_policy": ".allocation_policies",
    "add_account_holdings_snapshot_response": ".core",
    "account_delete_impact": ".deletion",
    "apply_account_virtual_fund_allocation_plan": ".account_virtual_allocations",
    "bulk_delete_accounts": ".deletion",
    "build_virtual_fund_holdings_frame": ".virtual_fund_holdings",
    "create_account": ".core",
    "create_account_allocation_model": ".core",
    "create_account_target_allocation": ".core",
    "create_position_set": ".core",
    "create_virtual_fund": ".virtual_funds",
    "delete_account": ".deletion",
    "get_account_by_uid": ".core",
    "get_account_by_unique_identifier": ".core",
    "get_account_frontend_detail_summary": ".core",
    "get_account_holdings_by_fund_response": ".virtual_funds_public_api",
    "get_account_holdings_snapshot_response": ".core",
    "get_account_holdings_snapshots_response": ".core",
    "get_virtual_fund_by_unique_identifier": ".virtual_funds",
    "get_virtual_fund_detail_response": ".virtual_funds_public_api",
    "get_virtual_fund_frontend_detail_summary": ".virtual_funds_public_api",
    "get_virtual_fund_holdings_snapshot_response": ".virtual_funds_public_api",
    "get_virtual_funds_by_account": ".virtual_funds",
    "get_virtual_funds_by_portfolio": ".virtual_funds",
    "list_virtual_fund_rows_response": ".virtual_funds_public_api",
    "list_account_rows_response": ".core",
    "plan_account_virtual_fund_allocations": ".account_virtual_allocations",
    "preflight_account_delete": ".deletion",
    "preflight_bulk_delete_accounts": ".deletion",
    "register_account": ".registration",
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
