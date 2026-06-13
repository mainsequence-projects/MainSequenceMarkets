from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import (  # noqa: E402
    EXAMPLE_METATABLE_NAMESPACE,
    EXAMPLE_NAMESPACE_ENV,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

from examples.msm.assets.utils import EXAMPLE_CRYPTO_ASSETS  # noqa: E402
from examples.msm_portfolios.portfolio_equal_weights_config import (  # noqa: E402
    CRYPTO_CALENDAR_UNIQUE_IDENTIFIER,
    NAMESPACE,
)
from mainsequence.meta_tables import APIDataNode, DataNode  # noqa: E402
from msm_portfolios.configuration import (  # noqa: E402
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
    PortfolioExecutionConfiguration,
    PortfolioMarketsConfig,
)
from msm_portfolios.contrib.signals.fixed_weights import (  # noqa: E402
    AUIDWeight,
    FixedWeights,
    FixedWeightsConfig,
)
from msm_portfolios.data_nodes import compute_portfolio_configuration_hash  # noqa: E402
from msm_portfolios.rebalance_strategy import ImmediateSignal  # noqa: E402

FAIR_VALUE_SOURCE_UID_ENV = "MSM_EXAMPLE_FAIR_VALUE_TIME_INDEX_META_TABLE_UID"
FAIR_VALUE_COLUMN = "fair_value"
PORTFOLIO_UNIQUE_IDENTIFIER = "example-fair-value-portfolio"
ASSET_UNIQUE_IDENTIFIERS = [payload["unique_identifier"] for payload in EXAMPLE_CRYPTO_ASSETS]


def build_fixed_weights_signal() -> FixedWeights:
    weight = 1.0 / len(ASSET_UNIQUE_IDENTIFIERS)
    signal_config = FixedWeightsConfig(
        asset_unique_identifier_weights=[
            AUIDWeight(unique_identifier=asset_identifier, weight=weight)
            for asset_identifier in ASSET_UNIQUE_IDENTIFIERS
        ],
    )
    return FixedWeights.from_signal_configuration(
        signal_config,
        namespace=NAMESPACE,
    )


def build_fair_value_portfolio_configuration(
    *,
    valuation_source: DataNode | APIDataNode,
) -> PortfolioConfiguration:
    signal_weights = build_fixed_weights_signal()
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            valuation_source_instance=valuation_source,
            valuation_column=FAIR_VALUE_COLUMN,
            portfolio_prices_frequency="1d",
            execution_configuration=PortfolioExecutionConfiguration(commission_fee=0.00018),
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal_weights,
                rebalance_strategy_instance=ImmediateSignal(
                    calendar_key=CRYPTO_CALENDAR_UNIQUE_IDENTIFIER,
                ),
            ),
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(
            portfolio_name="Example Fair Value Portfolio",
        ),
    )


def valuation_source_from_uid(source_time_index_meta_table_uid: str) -> APIDataNode:
    if not source_time_index_meta_table_uid.strip():
        raise ValueError("source_time_index_meta_table_uid cannot be empty.")
    return APIDataNode.build_from_table_uid(source_time_index_meta_table_uid)


def run_configuration_example(
    *,
    source_time_index_meta_table_uid: str,
) -> dict[str, Any]:
    valuation_source = valuation_source_from_uid(source_time_index_meta_table_uid)
    portfolio_configuration = build_fair_value_portfolio_configuration(
        valuation_source=valuation_source,
    )
    return {
        "portfolio_unique_identifier": PORTFOLIO_UNIQUE_IDENTIFIER,
        "valuation_source_time_index_meta_table_uid": source_time_index_meta_table_uid,
        "valuation_column": FAIR_VALUE_COLUMN,
        "portfolio_configuration_hash": compute_portfolio_configuration_hash(
            portfolio_configuration
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-time-index-meta-table-uid",
        default=os.environ.get(FAIR_VALUE_SOURCE_UID_ENV),
        help=(
            "UID of a registered asset-indexed TimeIndexMetaTable with "
            "time_index, asset_identifier, and fair_value columns."
        ),
    )
    args = parser.parse_args()
    if args.source_time_index_meta_table_uid in (None, ""):
        raise RuntimeError(
            "Pass --source-time-index-meta-table-uid or set "
            f"{FAIR_VALUE_SOURCE_UID_ENV}. The source table must expose "
            f"{FAIR_VALUE_COLUMN!r}; the example does not rename it to 'close'."
        )

    result = run_configuration_example(
        source_time_index_meta_table_uid=str(args.source_time_index_meta_table_uid),
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
