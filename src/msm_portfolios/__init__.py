from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "PORTFOLIO_DESCRIPTION": ".time_index",
    "PORTFOLIO_METADATA_UNIQUE_IDENTIFIER": ".time_index",
    "PORTFOLIO_WEIGHTS_INDEX_NAMES": ".time_index",
    "PORTFOLIOS_INDEX_NAMES": ".time_index",
    "REBALANCE_STRATEGY_DESCRIPTION": ".time_index",
    "REBALANCE_STRATEGY_UID": ".time_index",
    "REBALANCE_STRATEGY_UID_EXCLUDED_CONFIGURATION_KEYS": ".time_index",
    "SIGNAL_UID_EXCLUDED_CONFIGURATION_KEYS": ".time_index",
    "SIGNAL_WEIGHTS_INDEX_NAMES": ".time_index",
    "PortfolioCanonicalUpdater": ".time_index",
    "PortfolioCanonicalUpdaterConfiguration": ".time_index",
    "PortfolioEngine": ".time_index",
    "PortfolioEngineConfiguration": ".time_index",
    "PortfolioAnalytics": ".time_index",
    "PortfolioAnalyticsConfiguration": ".time_index",
    "PortfolioCalendarEvents": ".time_index",
    "PortfolioCalendarEventsConfiguration": ".time_index",
    "PortfolioRebalance": ".time_index",
    "PortfolioWeights": ".time_index",
    "PortfoliosUpdater": ".time_index",
    "SignalWeights": ".time_index",
    "SignalWeightsConfiguration": ".time_index",
    "attach_schemas": ".bootstrap",
    "canonical_portfolio_configuration": ".time_index",
    "canonical_signal_configuration": ".time_index",
    "compute_portfolio_configuration_hash": ".time_index",
    "compute_signal_uid": ".time_index",
    "get_or_create_portfolio": ".time_index",
    "get_runtime": ".bootstrap",
    "normalize_portfolio_values_frame": ".time_index",
    "normalize_portfolio_event_ledger_frame": ".time_index",
    "normalize_portfolio_weights_frame": ".time_index",
    "normalize_rebalance_state_frame": ".time_index",
    "normalize_signal_weights_frame": ".time_index",
    "start_engine": ".bootstrap",
}


def __getattr__(name: str) -> Any:
    if name == "logger":
        from mainsequence.logconf import logger as _logger

        value = _logger.bind(sub_application="portfolios")
    else:
        if name not in _EXPORTS:
            from msm._deprecated_imports import RENAMED_CLASS_NAMES, warn_renamed

            current = RENAMED_CLASS_NAMES.get(name)
            if current in _EXPORTS:
                warn_renamed(f"{__name__}.{name}", f"{__name__}.{current}")
                return getattr(import_module(_EXPORTS[current], __name__), current)
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        module = import_module(_EXPORTS[name], __name__)
        value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = sorted({*_EXPORTS, "logger"})
