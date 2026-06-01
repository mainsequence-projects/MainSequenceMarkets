from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import (  # noqa: E402
    EXAMPLE_METATABLE_NAMESPACE,
    EXAMPLE_NAMESPACE_ENV,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm_portfolios  # noqa: E402
from msm.api.indices import Index, IndexType  # noqa: E402
from msm_portfolios.api.portfolios import Portfolio  # noqa: E402
from msm_portfolios.configuration import (  # noqa: E402
    AssetsConfiguration,
    BacktestingWeightsConfig,
    MarketsTimeSeries,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
    PortfolioExecutionConfiguration,
    PortfolioMarketsConfig,
    PricesConfiguration,
)
from msm_portfolios.contrib.signals.fixed_weights import (  # noqa: E402
    AUIDWeight,
    FixedWeights,
    FixedWeightsConfig,
)
from msm_portfolios.data_nodes import (  # noqa: E402
    PortfoliosDataNode,
    PortfolioWeights,
    compute_portfolio_configuration_hash,
    normalize_signal_weights_frame,
)
from msm_portfolios.enums import PriceTypeNames  # noqa: E402
from msm_portfolios.rebalance_strategy import ImmediateSignal  # noqa: E402

NAMESPACE = "mainsequence.examples.portfolios"
INDEX_TYPE_PORTFOLIO = "portfolio"
PORTFOLIO_UNIQUE_IDENTIFIER = "example-equal-weight-portfolio"
PORTFOLIO_INDEX_UNIQUE_IDENTIFIER = "example-equal-weight-portfolio-index"
PORTFOLIO_INDEX_DISPLAY_NAME = "Example Equal Weight Portfolio Index"
TIME_INDEX = pd.Timestamp("2026-05-25T00:00:00Z")
ASSET_UNIQUE_IDENTIFIERS = [
    "BINANCE_SPOT_BTC_USDT",
    "BINANCE_SPOT_ETH_USDT",
    "BINANCE_SPOT_SOL_USDT",
]


def start_portfolio_example_runtime() -> None:
    """Register the tables/storage used by this portfolio example."""

    msm_portfolios.start_engine(
        models=[
            "IndexType",
            "Index",
            "Portfolio",
            "SignalMetadata",
            "RebalanceStrategyMetadata",
            "PortfolioWeightsStorage",
            "SignalWeightsStorage",
            "PortfoliosStorage",
        ],
    )


def register_portfolio_index() -> Index:
    """Create the optional Index row that represents this portfolio as a series."""

    IndexType.upsert(
        index_type=INDEX_TYPE_PORTFOLIO,
        display_name="Portfolio",
        description="Synthetic index rows that represent portfolio value series.",
    )
    return Index.upsert(
        unique_identifier=PORTFOLIO_INDEX_UNIQUE_IDENTIFIER,
        index_type=INDEX_TYPE_PORTFOLIO,
        display_name=PORTFOLIO_INDEX_DISPLAY_NAME,
        provider="msm_portfolios.examples",
        metadata_json={"portfolio_unique_identifier": PORTFOLIO_UNIQUE_IDENTIFIER},
    )


def build_assets_configuration() -> AssetsConfiguration:
    return AssetsConfiguration(
        assets_category_unique_id=None,
        price_type=PriceTypeNames.CLOSE,
        prices_configuration=PricesConfiguration(
            bar_frequency_id="1d",
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
            markets_time_series=MarketsTimeSeries(unique_identifier="example_1d_bars"),
        ),
    )


def build_fixed_weights_config() -> FixedWeightsConfig:
    weight = 1.0 / len(ASSET_UNIQUE_IDENTIFIERS)
    return FixedWeightsConfig(
        signal_assets_configuration=build_assets_configuration(),
        asset_unique_identifier_weights=[
            AUIDWeight(unique_identifier=asset_uid, weight=weight)
            for asset_uid in ASSET_UNIQUE_IDENTIFIERS
        ],
    )


def build_portfolio_configuration(signal_weights: FixedWeights) -> PortfolioConfiguration:
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            assets_configuration=build_assets_configuration(),
            portfolio_prices_frequency="1d",
            execution_configuration=PortfolioExecutionConfiguration(commission_fee=0.00018),
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal_weights,
                rebalance_strategy_instance=ImmediateSignal(calendar_key="24/7"),
            ),
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(
            portfolio_name="Example Equal Weight Portfolio",
        ),
    )


def build_signal_weights_node() -> FixedWeights:
    signal_configuration = build_fixed_weights_config()
    signal_weights = FixedWeights.from_signal_configuration(
        signal_configuration,
        namespace=NAMESPACE,
    )
    signal_weights.set_signal_weights_frame(
        build_signal_weights_frame(),
        signal_configuration=signal_configuration,
        signal_description="Equal-weight target signal for the portfolio example.",
    )
    return signal_weights


def build_portfolio_weights_node(portfolio_index: Index) -> PortfolioWeights:
    return PortfolioWeights(namespace=NAMESPACE).set_weights_frame(
        build_portfolio_weights_frame(),
        portfolio_index=portfolio_index,
        portfolio_description="Executed equal-weight portfolio allocations.",
    )


def build_portfolio_values_node(portfolio_index: Index) -> PortfoliosDataNode:
    return PortfoliosDataNode(namespace=NAMESPACE).set_portfolio_values_frame(
        build_portfolio_values_frame(),
        unique_identifier=portfolio_index.unique_identifier,
        portfolio_description="Published portfolio value series.",
    )


def build_signal_weights_frame() -> pd.DataFrame:
    weight = 1.0 / len(ASSET_UNIQUE_IDENTIFIERS)
    return pd.DataFrame(
        {
            "time_index": [TIME_INDEX] * len(ASSET_UNIQUE_IDENTIFIERS),
            "unique_identifier": ASSET_UNIQUE_IDENTIFIERS,
            "signal_weight": [weight] * len(ASSET_UNIQUE_IDENTIFIERS),
        }
    ).set_index(["time_index", "unique_identifier"])


def build_portfolio_weights_frame() -> pd.DataFrame:
    weight = 1.0 / len(ASSET_UNIQUE_IDENTIFIERS)
    return pd.DataFrame(
        {
            "time_index": [TIME_INDEX] * len(ASSET_UNIQUE_IDENTIFIERS),
            "unique_identifier": ASSET_UNIQUE_IDENTIFIERS,
            "weight": [weight] * len(ASSET_UNIQUE_IDENTIFIERS),
            "weight_before": [0.0] * len(ASSET_UNIQUE_IDENTIFIERS),
            "price_current": [100.0, 50.0, 25.0],
            "price_before": [100.0, 50.0, 25.0],
            "volume_current": [1.0, 1.0, 1.0],
            "volume_before": [0.0, 0.0, 0.0],
        }
    ).set_index(["time_index", "unique_identifier"])


def build_portfolio_values_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time_index": [TIME_INDEX],
            "close": [100.0],
            "return": [0.0],
            "calculated_close": [100.0],
            "close_time": [TIME_INDEX],
        }
    ).set_index("time_index")


def run_storage_node(node: Any, *, enabled: bool) -> str | None:
    if not enabled:
        return None
    return node.ensure_storage_ready(force_update=True)


def build_equal_weight_portfolio(*, run_data_nodes: bool = True) -> dict[str, Any]:
    """Create the portfolio index, run portfolio DataNodes, and upsert Portfolio."""

    start_portfolio_example_runtime()
    portfolio_index = register_portfolio_index()

    signal_weights_node = build_signal_weights_node()
    portfolio_configuration = build_portfolio_configuration(signal_weights_node)
    portfolio_weights_node = build_portfolio_weights_node(portfolio_index)
    portfolio_values_node = build_portfolio_values_node(portfolio_index)

    signal_weights_node_uid = run_storage_node(signal_weights_node, enabled=run_data_nodes)
    portfolio_weights_node_uid = run_storage_node(portfolio_weights_node, enabled=run_data_nodes)
    portfolio_values_node_uid = run_storage_node(portfolio_values_node, enabled=run_data_nodes)

    portfolio = Portfolio.upsert(
        unique_identifier=PORTFOLIO_UNIQUE_IDENTIFIER,
        calendar_name="24/7",
        portfolio_index_uid=portfolio_index.uid,
        signal_weights_data_node_uid=signal_weights_node_uid,
        portfolio_weights_data_node_uid=portfolio_weights_node_uid,
        portfolio_data_node_uid=portfolio_values_node_uid,
    )

    return {
        "portfolio": portfolio,
        "portfolio_index": portfolio_index,
        "portfolio_configuration_hash": compute_portfolio_configuration_hash(
            portfolio_configuration
        ),
        "signal_weights_node_uid": signal_weights_node_uid,
        "portfolio_weights_node_uid": portfolio_weights_node_uid,
        "portfolio_values_node_uid": portfolio_values_node_uid,
        "signal_weights_frame": normalize_signal_weights_frame(
            build_signal_weights_frame(),
            signal_uid=signal_weights_node.signal_uid,
        ),
        "portfolio_weights_frame": PortfolioWeights.normalize_weights_frame(
            build_portfolio_weights_frame(),
            portfolio_index_unique_identifier=portfolio_index.unique_identifier,
        ),
        "portfolio_values_frame": PortfoliosDataNode.normalize_values_frame(
            build_portfolio_values_frame(),
            unique_identifier=portfolio_index.unique_identifier,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-run-data-nodes",
        action="store_true",
        help="Build rows and frames without publishing DataNode storage.",
    )
    args = parser.parse_args()
    result = build_equal_weight_portfolio(run_data_nodes=not args.no_run_data_nodes)
    print(result)


if __name__ == "__main__":
    main()
