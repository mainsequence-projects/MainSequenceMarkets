from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AlwaysOpenCalendarSchedule": ".calendars",
    "PandasMarketCalendarSchedule": ".calendars",
    "PortfolioDeleteConflictError": ".public_api",
    "PersistedCalendarSchedule": ".calendars",
    "bulk_delete_portfolio_records": ".public_api",
    "create_portfolio_metadata": ".market_metadata",
    "create_rebalance_strategy_metadata": ".market_metadata",
    "create_signal_metadata": ".market_metadata",
    "delete_portfolio_metadata": ".market_metadata",
    "delete_portfolio_record": ".public_api",
    "delete_rebalance_strategy_metadata": ".market_metadata",
    "delete_signal_metadata": ".market_metadata",
    "get_portfolio_metadata_by_unique_identifier": ".market_metadata",
    "get_portfolio_detail_response": ".public_api",
    "get_portfolio_frontend_detail_summary": ".public_api",
    "get_portfolio_weights_snapshot_response": ".public_api",
    "search_portfolio_metadata": ".market_metadata",
    "search_rebalance_strategy_metadata": ".market_metadata",
    "search_signal_metadata": ".market_metadata",
    "update_portfolio_metadata": ".market_metadata",
    "update_rebalance_strategy_metadata": ".market_metadata",
    "update_signal_metadata": ".market_metadata",
    "list_portfolio_rows_response": ".public_api",
    "resolve_rebalance_calendar": ".calendars",
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
