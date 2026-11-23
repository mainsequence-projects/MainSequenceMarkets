from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AssetCalendarMissingError": ".calendars",
    "PersistedCalendarSchedule": ".calendars",
    "PortfolioDeleteConflictError": ".portfolio_deletion",
    "PortfolioDeletePlan": ".portfolio_deletion",
    "PortfolioTimestampRepairIssue": ".portfolio_timestamp_repair",
    "PortfolioTimestampRepairPlan": ".portfolio_timestamp_repair",
    "PortfolioTimestampRollback": ".portfolio_timestamp_repair",
    "SignalDeleteConflictError": ".public_api",
    "apply_legacy_midnight_portfolio_timestamp_repair": ".portfolio_timestamp_repair",
    "bulk_delete_accounts_with_portfolios": ".account_portfolio_deletion",
    "bulk_delete_portfolio_records": ".portfolio_deletion",
    "build_legacy_midnight_portfolio_timestamp_repair_plan": ".portfolio_timestamp_repair",
    "create_signal_metadata_response": ".public_api",
    "create_portfolio_metadata": ".market_metadata",
    "create_rebalance_strategy_metadata": ".market_metadata",
    "create_signal_metadata": ".market_metadata",
    "delete_account_with_portfolios": ".account_portfolio_deletion",
    "delete_portfolio_metadata": ".market_metadata",
    "delete_portfolio_record": ".portfolio_deletion",
    "delete_portfolio_weights": ".public_api",
    "delete_rebalance_strategy_metadata": ".market_metadata",
    "delete_signal_metadata": ".market_metadata",
    "delete_signal_metadata_record": ".public_api",
    "end_signal_metadata_records": ".public_api",
    "delete_signal_weights": ".public_api",
    "get_signal_metadata_response": ".public_api",
    "get_portfolio_metadata_by_unique_identifier": ".market_metadata",
    "get_portfolio_detail_response": ".public_api",
    "get_portfolio_frontend_detail_summary": ".public_api",
    "get_portfolio_signal_weights_frame_response": ".public_api",
    "get_portfolio_values_frame_response": ".public_api",
    "get_portfolio_weights_snapshot_response": ".public_api",
    "latest_portfolio_weights": ".portfolio_reads",
    "list_portfolio_rows_response": ".public_api",
    "list_signal_metadata_response": ".public_api",
    "portfolio_values": ".portfolio_reads",
    "plan_legacy_midnight_portfolio_timestamp_repair": ".portfolio_timestamp_repair",
    "plan_portfolio_deletes": ".portfolio_deletion",
    "preflight_account_delete_with_portfolios": ".account_portfolio_deletion",
    "preflight_bulk_delete_accounts_with_portfolios": ".account_portfolio_deletion",
    "preflight_bulk_delete_portfolio_records": ".portfolio_deletion",
    "search_portfolio_metadata": ".market_metadata",
    "search_rebalance_strategy_metadata": ".market_metadata",
    "search_signal_metadata": ".market_metadata",
    "signal_weights": ".portfolio_reads",
    "resolve_asset_schedules": ".calendars",
    "resolve_rebalance_calendar": ".calendars",
    "update_portfolio_metadata": ".market_metadata",
    "update_rebalance_strategy_metadata": ".market_metadata",
    "update_signal_metadata": ".market_metadata",
    "update_signal_metadata_response": ".public_api",
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
