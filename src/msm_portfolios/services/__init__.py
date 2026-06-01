from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "build_fund_holdings_frame": ".holdings",
    "create_fund": ".virtual_funds",
    "create_portfolio": ".portfolios",
    "create_portfolio_metadata": ".market_metadata",
    "create_rebalance_strategy_metadata": ".market_metadata",
    "create_signal_metadata": ".market_metadata",
    "delete_fund": ".virtual_funds",
    "delete_portfolio": ".portfolios",
    "delete_portfolio_metadata": ".market_metadata",
    "delete_rebalance_strategy_metadata": ".market_metadata",
    "delete_signal_metadata": ".market_metadata",
    "get_fund_by_unique_identifier": ".virtual_funds",
    "get_funds_by_account": ".virtual_funds",
    "get_funds_by_portfolio": ".virtual_funds",
    "get_portfolio_by_unique_identifier": ".portfolios",
    "get_portfolio_metadata_by_unique_identifier": ".market_metadata",
    "search_portfolio_metadata": ".market_metadata",
    "search_portfolios": ".portfolios",
    "search_rebalance_strategy_metadata": ".market_metadata",
    "search_signal_metadata": ".market_metadata",
    "update_fund": ".virtual_funds",
    "update_portfolio": ".portfolios",
    "update_portfolio_metadata": ".market_metadata",
    "update_rebalance_strategy_metadata": ".market_metadata",
    "update_signal_metadata": ".market_metadata",
    "validate_holdings_frame": ".holdings",
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
