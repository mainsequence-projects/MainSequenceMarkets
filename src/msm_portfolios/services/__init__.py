from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AlwaysOpenCalendarSchedule": ".calendars",
    "PandasMarketCalendarSchedule": ".calendars",
    "PersistedCalendarSchedule": ".calendars",
    "create_portfolio_metadata": ".market_metadata",
    "create_rebalance_strategy_metadata": ".market_metadata",
    "create_signal_metadata": ".market_metadata",
    "delete_portfolio_metadata": ".market_metadata",
    "delete_rebalance_strategy_metadata": ".market_metadata",
    "delete_signal_metadata": ".market_metadata",
    "get_portfolio_metadata_by_unique_identifier": ".market_metadata",
    "search_portfolio_metadata": ".market_metadata",
    "search_rebalance_strategy_metadata": ".market_metadata",
    "search_signal_metadata": ".market_metadata",
    "update_portfolio_metadata": ".market_metadata",
    "update_rebalance_strategy_metadata": ".market_metadata",
    "update_signal_metadata": ".market_metadata",
    "build_virtual_fund_holdings_frame": ".holdings",
    "create_virtual_fund": ".virtual_funds",
    "delete_virtual_fund": ".virtual_funds",
    "get_virtual_fund_by_unique_identifier": ".virtual_funds",
    "get_virtual_funds_by_account": ".virtual_funds",
    "get_virtual_funds_by_portfolio": ".virtual_funds",
    "resolve_rebalance_calendar": ".calendars",
    "update_virtual_fund": ".virtual_funds",
    "validate_holdings_frame": ".holdings",
    "validate_virtual_fund_allocation_bounds": ".holdings",
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
