from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "PORTFOLIO_DESCRIPTION": ".data_nodes",
    "PORTFOLIO_METADATA_UNIQUE_IDENTIFIER": ".data_nodes",
    "PORTFOLIO_WEIGHTS_INDEX_NAMES": ".data_nodes",
    "PORTFOLIOS_INDEX_NAMES": ".data_nodes",
    "REBALANCE_STRATEGY_DESCRIPTION": ".data_nodes",
    "REBALANCE_STRATEGY_UID": ".data_nodes",
    "REBALANCE_STRATEGY_UID_EXCLUDED_CONFIGURATION_KEYS": ".data_nodes",
    "SIGNAL_UID_EXCLUDED_CONFIGURATION_KEYS": ".data_nodes",
    "SIGNAL_WEIGHTS_INDEX_NAMES": ".data_nodes",
    "PortfolioCanonicalDataNode": ".data_nodes",
    "PortfolioCanonicalDataNodeConfiguration": ".data_nodes",
    "PortfolioWeights": ".data_nodes",
    "PortfoliosDataNode": ".data_nodes",
    "SignalWeights": ".data_nodes",
    "SignalWeightsConfiguration": ".data_nodes",
    "attach_schemas": ".bootstrap",
    "canonical_portfolio_configuration": ".data_nodes",
    "canonical_signal_configuration": ".data_nodes",
    "compute_portfolio_configuration_hash": ".data_nodes",
    "compute_signal_uid": ".data_nodes",
    "get_or_create_portfolio_index": ".data_nodes",
    "get_runtime": ".bootstrap",
    "initialize_portfolio_storage_source_tables": ".data_nodes",
    "normalize_portfolio_values_frame": ".data_nodes",
    "normalize_portfolio_weights_frame": ".data_nodes",
    "normalize_signal_weights_frame": ".data_nodes",
    "start_engine": ".bootstrap",
}


def __getattr__(name: str) -> Any:
    if name == "logger":
        from mainsequence.logconf import logger as _logger

        value = _logger.bind(sub_application="portfolios")
    else:
        if name not in _EXPORTS:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        module = import_module(_EXPORTS[name], __name__)
        value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = sorted({*_EXPORTS, "logger"})
