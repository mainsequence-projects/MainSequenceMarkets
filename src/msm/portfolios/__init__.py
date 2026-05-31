from __future__ import annotations

from mainsequence.logconf import logger as _logger

from msm.portfolios.data_nodes import (
    PORTFOLIO_DESCRIPTION,
    PORTFOLIO_METADATA_UNIQUE_IDENTIFIER,
    PORTFOLIO_WEIGHTS_INDEX_NAMES,
    PORTFOLIOS_INDEX_NAMES,
    REBALANCE_STRATEGY_DESCRIPTION,
    REBALANCE_STRATEGY_UID,
    REBALANCE_STRATEGY_UID_EXCLUDED_CONFIGURATION_KEYS,
    SIGNAL_UID_EXCLUDED_CONFIGURATION_KEYS,
    SIGNAL_WEIGHTS_INDEX_NAMES,
    PortfolioCanonicalDataNode,
    PortfolioCanonicalDataNodeConfiguration,
    PortfolioWeights,
    PortfoliosDataNode,
    SignalWeights,
    SignalWeightsConfiguration,
    canonical_portfolio_configuration,
    canonical_signal_configuration,
    compute_portfolio_configuration_hash,
    compute_signal_uid,
    get_or_create_portfolio_index_asset,
    initialize_portfolio_storage_source_tables,
    normalize_portfolio_values_frame,
    normalize_portfolio_weights_frame,
    normalize_signal_weights_frame,
)


logger = _logger.bind(sub_application="portfolios")


__all__ = [
    "PORTFOLIO_DESCRIPTION",
    "PORTFOLIO_METADATA_UNIQUE_IDENTIFIER",
    "PORTFOLIO_WEIGHTS_INDEX_NAMES",
    "PORTFOLIOS_INDEX_NAMES",
    "REBALANCE_STRATEGY_DESCRIPTION",
    "REBALANCE_STRATEGY_UID",
    "REBALANCE_STRATEGY_UID_EXCLUDED_CONFIGURATION_KEYS",
    "SIGNAL_UID_EXCLUDED_CONFIGURATION_KEYS",
    "SIGNAL_WEIGHTS_INDEX_NAMES",
    "PortfolioCanonicalDataNode",
    "PortfolioCanonicalDataNodeConfiguration",
    "PortfolioWeights",
    "PortfoliosDataNode",
    "SignalWeights",
    "SignalWeightsConfiguration",
    "canonical_portfolio_configuration",
    "canonical_signal_configuration",
    "compute_portfolio_configuration_hash",
    "compute_signal_uid",
    "get_or_create_portfolio_index_asset",
    "initialize_portfolio_storage_source_tables",
    "logger",
    "normalize_portfolio_values_frame",
    "normalize_portfolio_weights_frame",
    "normalize_signal_weights_frame",
]
