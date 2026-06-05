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
from msm.api.accounts import Account, AccountGroup, AccountHoldingsSet  # noqa: E402
from msm.api.assets import Asset, AssetType  # noqa: E402
from msm.api.calendars import Calendar, CalendarType  # noqa: E402
from msm.api.indices import Index, IndexType  # noqa: E402
from msm.data_nodes.accounts import AccountHoldings  # noqa: E402
from msm_portfolios.api.portfolios import Portfolio  # noqa: E402
from msm_portfolios.api.virtual_funds import VirtualFund  # noqa: E402
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
    VirtualFundHoldings,
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
ACCOUNT_GROUP_NAME = "Example Portfolio Allocation Accounts"
ACCOUNT_UNIQUE_IDENTIFIER = "example-portfolio-allocation-account"
VIRTUAL_FUND_UNIQUE_IDENTIFIER = "example-equal-weight-virtual-fund"


def print_step(step: int, message: str) -> None:
    print(f"{step}. {message}")


def print_detail(label: str, value: object) -> None:
    print(f"   {label}: {value}")


def start_portfolio_example_runtime() -> None:
    """Register the tables/storage used by this portfolio example."""

    msm_portfolios.start_engine(
        models=[
            "IndexType",
            "Index",
            "AssetType",
            "Asset",
            "AccountGroup",
            "Account",
            "AccountHoldingsSet",
            "AccountHoldingsStorage",
            "Calendar",
            "Portfolio",
            "VirtualFund",
            "VirtualFundHoldingsSet",
            "VirtualFundHoldingsStorage",
            "SignalMetadata",
            "RebalanceStrategyMetadata",
            "PortfolioWeightsStorage",
            "SignalWeightsStorage",
            "PortfoliosStorage",
        ],
    )


def register_assets() -> list[Asset]:
    asset_type = AssetType.upsert(
        asset_type="crypto",
        display_name="Crypto",
        description="Crypto spot instruments used by portfolio examples.",
    )
    assets = [
        Asset.upsert(unique_identifier=asset_identifier, asset_type="crypto")
        for asset_identifier in ASSET_UNIQUE_IDENTIFIERS
    ]
    print_detail("asset_type", asset_type.asset_type)
    print_detail("assets", ", ".join(asset.unique_identifier for asset in assets))
    return assets


def register_account() -> Account:
    account_group = AccountGroup.upsert(
        group_name=ACCOUNT_GROUP_NAME,
        group_description="Example group for portfolio virtual-fund allocation.",
    )
    account = Account.upsert(
        unique_identifier=ACCOUNT_UNIQUE_IDENTIFIER,
        account_name="Example Portfolio Allocation Account",
        is_paper=True,
        account_is_active=True,
        account_group_uid=account_group.uid,
    )
    print_detail("account_group_uid", account_group.uid)
    print_detail("account_uid", account.uid)
    print_detail("account_identifier", account.unique_identifier)
    return account


def register_portfolio_index() -> Index:
    """Create the optional Index row that represents this portfolio as a series."""

    index_type = IndexType.upsert(
        index_type=INDEX_TYPE_PORTFOLIO,
        display_name="Portfolio",
        description="Synthetic index rows that represent portfolio value series.",
    )
    portfolio_index = Index.upsert(
        unique_identifier=PORTFOLIO_INDEX_UNIQUE_IDENTIFIER,
        index_type=INDEX_TYPE_PORTFOLIO,
        display_name=PORTFOLIO_INDEX_DISPLAY_NAME,
        provider="msm_portfolios.examples",
        metadata_json={"portfolio_unique_identifier": PORTFOLIO_UNIQUE_IDENTIFIER},
    )
    print_detail("index_type", index_type.index_type)
    print_detail("portfolio_index_uid", portfolio_index.uid)
    print_detail("portfolio_index_identifier", portfolio_index.unique_identifier)
    return portfolio_index


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
            "asset_identifier": ASSET_UNIQUE_IDENTIFIERS,
            "signal_weight": [weight] * len(ASSET_UNIQUE_IDENTIFIERS),
        }
    ).set_index(["time_index", "asset_identifier"])


def build_portfolio_weights_frame() -> pd.DataFrame:
    weight = 1.0 / len(ASSET_UNIQUE_IDENTIFIERS)
    return pd.DataFrame(
        {
            "time_index": [TIME_INDEX] * len(ASSET_UNIQUE_IDENTIFIERS),
            "asset_identifier": ASSET_UNIQUE_IDENTIFIERS,
            "weight": [weight] * len(ASSET_UNIQUE_IDENTIFIERS),
            "weight_before": [0.0] * len(ASSET_UNIQUE_IDENTIFIERS),
            "price_current": [100.0, 50.0, 25.0],
            "price_before": [100.0, 50.0, 25.0],
            "volume_current": [1.0, 1.0, 1.0],
            "volume_before": [0.0, 0.0, 0.0],
        }
    ).set_index(["time_index", "asset_identifier"])


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


def build_account_holdings_frame(
    node: AccountHoldings,
    account: Account,
    holdings_set: AccountHoldingsSet,
) -> pd.DataFrame:
    return node.build_account_holdings_frame(
        holdings_date=TIME_INDEX,
        account_uid=account.uid,
        holdings_set_uid=holdings_set.uid,
        positions=[
            {
                "asset_identifier": ASSET_UNIQUE_IDENTIFIERS[0],
                "quantity": 10.0,
                "direction": 1,
            },
            {
                "asset_identifier": ASSET_UNIQUE_IDENTIFIERS[1],
                "quantity": 5.0,
                "direction": 1,
            },
            {
                "asset_identifier": ASSET_UNIQUE_IDENTIFIERS[2],
                "quantity": 20.0,
                "direction": 1,
            },
        ],
    )


def run_storage_node(node: Any, *, enabled: bool, label: str) -> str | None:
    if not enabled:
        print_detail(f"{label}_data_node_uid", "skipped (--no-run-data-nodes)")
        return None
    node_uid = node.ensure_storage_ready(force_update=True)
    print_detail(f"{label}_data_node_uid", node_uid)
    return node_uid


def print_result_summary(result: dict[str, Any], *, run_data_nodes: bool) -> None:
    portfolio = result["portfolio"]
    portfolio_index = result["portfolio_index"]
    account = result["account"]
    virtual_fund = result["virtual_fund"]

    print_step(11, "Final portfolio workflow summary.")
    print_detail("portfolio_uid", portfolio.uid)
    print_detail("portfolio_identifier", portfolio.unique_identifier)
    print_detail("portfolio_index_uid", portfolio_index.uid)
    print_detail("portfolio_index_identifier", portfolio_index.unique_identifier)
    print_detail("account_uid", account.uid)
    print_detail("virtual_fund_uid", virtual_fund.uid)
    print_detail("virtual_fund_identifier", virtual_fund.unique_identifier)
    print_detail("portfolio_configuration_hash", result["portfolio_configuration_hash"])
    print_detail("signal_weights_rows", len(result["signal_weights_frame"]))
    print_detail("portfolio_weights_rows", len(result["portfolio_weights_frame"]))
    print_detail("portfolio_values_rows", len(result["portfolio_values_frame"]))
    print_detail("account_holdings_rows", len(result["account_holdings_frame"]))
    print_detail("virtual_fund_allocation_rows", len(result["virtual_fund_allocations_frame"]))
    if not run_data_nodes:
        print_detail("data_node_mode", "frames built locally; storage publication skipped")


def build_equal_weight_portfolio(*, run_data_nodes: bool = True) -> dict[str, Any]:
    """Create the portfolio index, run portfolio DataNodes, and upsert Portfolio."""

    print_step(1, "Starting the portfolio example runtime.")
    start_portfolio_example_runtime()

    print_step(2, "Registering the crypto asset universe.")
    assets = register_assets()

    print_step(3, "Registering the allocation account.")
    account = register_account()

    print_step(4, "Registering the portfolio index row.")
    portfolio_index = register_portfolio_index()

    print_step(5, "Preparing equal-weight signal and portfolio DataNodes.")
    signal_weights_node = build_signal_weights_node()
    portfolio_configuration = build_portfolio_configuration(signal_weights_node)
    portfolio_weights_node = build_portfolio_weights_node(portfolio_index)
    portfolio_values_node = build_portfolio_values_node(portfolio_index)
    print_detail("signal_uid", signal_weights_node.signal_uid)
    print_detail(
        "portfolio_configuration_hash",
        compute_portfolio_configuration_hash(portfolio_configuration),
    )
    print_detail("signal_weights_rows", len(build_signal_weights_frame()))
    print_detail("portfolio_weights_rows", len(build_portfolio_weights_frame()))
    print_detail("portfolio_values_rows", len(build_portfolio_values_frame()))

    print_step(6, "Publishing portfolio DataNode storage outputs.")
    signal_weights_node_uid = run_storage_node(
        signal_weights_node,
        enabled=run_data_nodes,
        label="signal_weights",
    )
    portfolio_weights_node_uid = run_storage_node(
        portfolio_weights_node,
        enabled=run_data_nodes,
        label="portfolio_weights",
    )
    portfolio_values_node_uid = run_storage_node(
        portfolio_values_node,
        enabled=run_data_nodes,
        label="portfolio_values",
    )

    print_step(7, "Upserting the portfolio Calendar and Portfolio rows with DataNode links.")
    portfolio_calendar = Calendar.upsert(
        unique_identifier="CRYPTO_24_7",
        display_name="Crypto 24/7",
        calendar_type=CalendarType.TRADING,
        timezone="UTC",
        source="user",
        source_identifier="always_open",
        valid_from=TIME_INDEX.date(),
        valid_to=TIME_INDEX.date(),
        metadata_json={"example": "portfolio_equal_weights_example"},
    )
    print_detail("calendar_uid", portfolio_calendar.uid)
    portfolio = Portfolio.upsert(
        unique_identifier=PORTFOLIO_UNIQUE_IDENTIFIER,
        calendar_uid=portfolio_calendar.uid,
        calendar_name="24/7",
        portfolio_index_uid=portfolio_index.uid,
        signal_weights_data_node_uid=signal_weights_node_uid,
        portfolio_weights_data_node_uid=portfolio_weights_node_uid,
        portfolio_data_node_uid=portfolio_values_node_uid,
    )
    print_detail("portfolio_uid", portfolio.uid)
    print_detail("portfolio_identifier", portfolio.unique_identifier)

    print_step(8, "Creating source account holdings for virtual-fund allocation.")
    holdings_set = AccountHoldingsSet.upsert(account_uid=account.uid, time_index=TIME_INDEX)
    account_holdings_node = AccountHoldings(config=AccountHoldings.default_config())
    account_holdings_frame = build_account_holdings_frame(
        account_holdings_node, account, holdings_set
    )
    account_holdings_node.set_frame(account_holdings_frame)
    print_detail("account_holdings_set_uid", holdings_set.uid)
    print_detail("account_holdings_rows", len(account_holdings_frame))
    account_holdings_node_uid = run_storage_node(
        account_holdings_node,
        enabled=run_data_nodes,
        label="account_holdings",
    )

    print_step(9, "Upserting the VirtualFund row that targets the portfolio.")
    virtual_fund = VirtualFund.upsert(
        unique_identifier=VIRTUAL_FUND_UNIQUE_IDENTIFIER,
        account_uid=account.uid,
        target_portfolio_uid=portfolio.uid,
    )
    print_detail("virtual_fund_uid", virtual_fund.uid)
    print_detail("virtual_fund_identifier", virtual_fund.unique_identifier)

    print_step(10, "Allocating source account holdings into virtual-fund holdings.")
    virtual_fund_node = VirtualFundHoldings()
    virtual_fund_allocations_frame = virtual_fund.allocate_from_account_holdings_set(
        source_account_holdings_set_uid=holdings_set.uid,
        allocation_time=TIME_INDEX,
        allocations=[
            {
                "asset_identifier": ASSET_UNIQUE_IDENTIFIERS[0],
                "allocated_quantity": 4.0,
                "direction": 1,
            },
            {
                "asset_identifier": ASSET_UNIQUE_IDENTIFIERS[1],
                "allocated_quantity": 2.0,
                "direction": 1,
            },
        ],
        data_node=virtual_fund_node if run_data_nodes else None,
        run=run_data_nodes,
        validate_bounds=run_data_nodes,
    )
    print_detail("virtual_fund_allocation_rows", len(virtual_fund_allocations_frame))

    result = {
        "assets": assets,
        "account": account,
        "account_holdings_set": holdings_set,
        "account_holdings_node_uid": account_holdings_node_uid,
        "portfolio": portfolio,
        "portfolio_index": portfolio_index,
        "virtual_fund": virtual_fund,
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
            portfolio_index_identifier=portfolio_index.unique_identifier,
        ),
        "portfolio_values_frame": PortfoliosDataNode.normalize_values_frame(
            build_portfolio_values_frame(),
            unique_identifier=portfolio_index.unique_identifier,
        ),
        "account_holdings_frame": account_holdings_frame,
        "virtual_fund_allocations_frame": virtual_fund_allocations_frame,
    }
    print_result_summary(result, run_data_nodes=run_data_nodes)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-run-data-nodes",
        action="store_true",
        help="Build rows and frames without publishing DataNode storage.",
    )
    args = parser.parse_args()
    build_equal_weight_portfolio(run_data_nodes=not args.no_run_data_nodes)


if __name__ == "__main__":
    main()
