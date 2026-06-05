from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from collections.abc import Sequence
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

from examples.msm.assets.utils import (  # noqa: E402
    EXAMPLE_CRYPTO_ASSETS,
    EXAMPLE_CRYPTO_ASSET_TYPE,
)
from examples.msm_portfolios.portfolio_equal_weights_config import (  # noqa: E402
    ACCOUNT_GROUP_NAME,
    ACCOUNT_UNIQUE_IDENTIFIER,
    ASSET_UNIQUE_IDENTIFIERS,
    CRYPTO_CALENDAR_UNIQUE_IDENTIFIER,
    DYNAMIC_MIGRATION_PROVIDER,
    INDEX_TYPE_PORTFOLIO,
    NAMESPACE,
    PORTFOLIO_EXAMPLE_RUNTIME_MODELS,
    PORTFOLIO_INDEX_DISPLAY_NAME,
    PORTFOLIO_INDEX_UNIQUE_IDENTIFIER,
    PORTFOLIO_UNIQUE_IDENTIFIER,
    PRICE_INTERPOLATION_RULE,
    PRICE_UPSAMPLE_FREQUENCY_ID,
    SOURCE_PRICE_CADENCE,
    TIME_INDEX,
    VIRTUAL_FUND_UNIQUE_IDENTIFIER,
    configured_equal_weight_interpolated_prices_storage,
    source_cadence_from_meta_table,
    source_storage_hash_from_meta_table,
)

import msm_portfolios  # noqa: E402
from mainsequence.client.metatables import TimeIndexMetaTable  # noqa: E402
from msm.api.accounts import Account, AccountGroup, AccountHoldingsSet  # noqa: E402
from msm.api.assets import Asset, AssetType  # noqa: E402
from msm.api.calendars import Calendar  # noqa: E402
from msm.api.indices import Index, IndexType  # noqa: E402
from msm.data_nodes.assets.asset_indexed import (  # noqa: E402
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
)
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc  # noqa: E402
from msm.data_nodes.accounts import AccountHoldings  # noqa: E402
from msm_portfolios.api.portfolios import Portfolio  # noqa: E402
from msm_portfolios.api.virtual_funds import VirtualFund  # noqa: E402
from msm_portfolios.configuration import (  # noqa: E402
    AssetsConfiguration,
    BacktestingWeightsConfig,
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
from msm_portfolios.data_nodes.storage import (  # noqa: E402
    ExternalPricesStorage,
)
from msm_portfolios.data_nodes import (  # noqa: E402
    PortfoliosDataNode,
    VirtualFundHoldings,
    compute_portfolio_configuration_hash,
)
from msm_portfolios.enums import PriceTypeNames  # noqa: E402
from msm_portfolios.rebalance_strategy import ImmediateSignal  # noqa: E402


class ExamplePortfolioResolver:
    """Bind one example portfolio configuration to its Portfolio and Index rows."""

    def __init__(self, *, portfolio: Portfolio, portfolio_index: Index) -> None:
        self.portfolio = portfolio
        self.portfolio_index = portfolio_index

    def get_or_create_from_configuration_hash(
        self,
        *,
        portfolio_configuration_hash: str,
        portfolio_configuration: dict[str, Any],
        timeout: int | float | tuple[float, float] | None = None,
    ) -> tuple[Portfolio, Index]:
        del portfolio_configuration_hash, portfolio_configuration, timeout
        return self.portfolio, self.portfolio_index


class ExampleDailyBars(AssetIndexedDataNode):
    """Example daily OHLCV bars used as the real portfolio price dependency."""

    OFFSET_START = (TIME_INDEX - pd.Timedelta(days=90)).to_pydatetime()

    def __init__(
        self,
        *,
        asset_identifiers: Sequence[str],
        namespace: str | None = None,
    ) -> None:
        self._asset_identifiers = list(asset_identifiers)
        super().__init__(
            config=AssetIndexedDataNodeConfiguration(asset_list=self._asset_identifiers),
            storage_table=ExternalPricesStorage,
            hash_namespace=namespace or NAMESPACE,
        )

    @classmethod
    def _required_storage_table(cls) -> type[ExternalPricesStorage]:
        return ExternalPricesStorage

    def get_asset_list(self) -> list[str]:
        return list(self._asset_identifiers)

    def dependencies(self) -> dict[str, Any]:
        return {}

    def update(self) -> pd.DataFrame:
        frame = build_example_daily_bars_frame(self._asset_identifiers)
        return self.update_statistics.filter_df_by_latest_value(frame)


def print_step(step: int, message: str) -> None:
    print(f"{step}. {message}")


def print_detail(label: str, value: object) -> None:
    print(f"   {label}: {value}")


def start_portfolio_example_runtime(
    *,
    models: Sequence[str | type[Any]] | None = None,
) -> Any:
    """Attach the already-registered tables/storage used by this portfolio example."""

    return msm_portfolios.start_engine(
        models=list(models or PORTFOLIO_EXAMPLE_RUNTIME_MODELS),
    )


def register_assets() -> list[Asset]:
    asset_type = AssetType.upsert(**EXAMPLE_CRYPTO_ASSET_TYPE)
    assets = [Asset.upsert(**asset_payload) for asset_payload in EXAMPLE_CRYPTO_ASSETS]
    print_detail("asset_type", asset_type.asset_type)
    print_detail("assets", ", ".join(asset.unique_identifier for asset in assets))
    return assets


def create_crypto_calendar_from_pandas() -> Calendar:
    portfolio_calendar = Calendar.create_from_pandas_calendar(
        source_identifier="24/7",
        unique_identifier=CRYPTO_CALENDAR_UNIQUE_IDENTIFIER,
        display_name="Crypto 24/7",
        valid_from=TIME_INDEX.date(),
        valid_to=TIME_INDEX.date(),
        timezone="UTC",
        metadata_json={"example": "portfolio_equal_weights_example"},
    )
    print_detail("calendar_uid", portfolio_calendar.uid)
    print_detail("calendar_identifier", portfolio_calendar.unique_identifier)
    print_detail(
        "calendar_source",
        f"{portfolio_calendar.source}:{portfolio_calendar.source_identifier}",
    )
    return portfolio_calendar


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


def build_assets_configuration(
    source_time_index_meta_table_uid: str,
) -> AssetsConfiguration:
    return AssetsConfiguration(
        assets_category_unique_id=None,
        price_type=PriceTypeNames.CLOSE,
        asset_list=list(ASSET_UNIQUE_IDENTIFIERS),
        prices_configuration=PricesConfiguration(
            upsample_frequency_id=PRICE_UPSAMPLE_FREQUENCY_ID,
            intraday_bar_interpolation_rule=PRICE_INTERPOLATION_RULE,
            source_time_index_meta_table_uid=source_time_index_meta_table_uid,
        ),
    )


def build_fixed_weights_config(
    source_time_index_meta_table_uid: str,
) -> FixedWeightsConfig:
    weight = 1.0 / len(ASSET_UNIQUE_IDENTIFIERS)
    return FixedWeightsConfig(
        signal_assets_configuration=build_assets_configuration(source_time_index_meta_table_uid),
        asset_unique_identifier_weights=[
            AUIDWeight(unique_identifier=asset_uid, weight=weight)
            for asset_uid in ASSET_UNIQUE_IDENTIFIERS
        ],
    )


def build_portfolio_configuration(
    signal_weights: FixedWeights,
    *,
    calendar: Calendar,
    source_time_index_meta_table_uid: str,
) -> PortfolioConfiguration:
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            assets_configuration=build_assets_configuration(source_time_index_meta_table_uid),
            portfolio_prices_frequency="1d",
            execution_configuration=PortfolioExecutionConfiguration(commission_fee=0.00018),
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal_weights,
                rebalance_strategy_instance=ImmediateSignal(
                    calendar_key=calendar.unique_identifier
                ),
            ),
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(
            portfolio_name="Example Equal Weight Portfolio",
        ),
    )


def build_signal_weights_node(
    source_time_index_meta_table_uid: str,
) -> FixedWeights:
    signal_configuration = build_fixed_weights_config(source_time_index_meta_table_uid)
    return FixedWeights.from_signal_configuration(
        signal_configuration,
        namespace=NAMESPACE,
    )


def build_portfolio_values_node(
    portfolio_configuration: PortfolioConfiguration,
    *,
    portfolio_resolver: ExamplePortfolioResolver,
) -> PortfoliosDataNode:
    return PortfoliosDataNode(namespace=NAMESPACE).set_portfolio_configuration(
        portfolio_configuration,
        portfolio_resolver=portfolio_resolver,
        portfolio_description="Published portfolio value series.",
    )


def build_source_bars_node() -> ExampleDailyBars:
    return ExampleDailyBars(
        asset_identifiers=ASSET_UNIQUE_IDENTIFIERS,
        namespace=NAMESPACE,
    )


def resolve_source_prices_storage(runtime: Any) -> tuple[str, Any]:
    """Return the registered source storage UID and backend metadata."""

    handle = runtime.table(ExternalPricesStorage)
    if handle.meta_table is None:
        raise RuntimeError(
            "ExternalPricesStorage is not attached to a registered TimeIndexMetaTable."
        )
    return str(handle.meta_table_uid), handle.meta_table


def build_example_interpolated_prices_storage(source_meta_table: Any) -> type[Any]:
    """Derive this example's configured interpolation storage from source metadata."""

    return configured_equal_weight_interpolated_prices_storage(
        source_storage_hash=source_storage_hash_from_meta_table(source_meta_table),
        source_cadence=source_cadence_from_meta_table(
            source_meta_table,
            fallback=SOURCE_PRICE_CADENCE,
        ),
    )


def assert_interpolated_prices_storage_registered(storage_table: type[Any]) -> Any:
    """Fail clearly when the dynamic interpolation table was not migrated first."""

    table_name = storage_table.__table__.name
    matches = TimeIndexMetaTable.filter_by_body(
        physical_table_name__in=[table_name],
        limit=1,
        offset=0,
    )
    if not matches:
        raise RuntimeError(
            "Configured interpolated price storage is missing: "
            f"{table_name}. Run "
            "`python examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py` "
            "before running the portfolio workflow. The dynamic migration provider is "
            f"{DYNAMIC_MIGRATION_PROVIDER}."
        )

    meta_table = matches[0]
    bind = getattr(storage_table, "_bind_meta_table", None)
    if callable(bind):
        bind(meta_table)
    return meta_table


def build_example_daily_bars_frame(asset_identifiers: Sequence[str]) -> pd.DataFrame:
    base_open = TIME_INDEX - pd.Timedelta(days=3)
    rows: list[dict[str, object]] = []
    for asset_position, asset_identifier in enumerate(asset_identifiers):
        base_price = 100.0 * (asset_position + 1)
        for day_offset, return_step in enumerate((0.00, 0.02, 0.05, 0.04)):
            open_time = base_open + pd.Timedelta(days=day_offset)
            close_time = open_time + pd.Timedelta(days=1)
            close = base_price * (1.0 + return_step)
            open_price = base_price * (1.0 + max(return_step - 0.01, 0.0))
            rows.append(
                {
                    "time_index": close_time,
                    "asset_identifier": asset_identifier,
                    "open_time": open_time,
                    "open": open_price,
                    "high": max(open_price, close) * 1.01,
                    "low": min(open_price, close) * 0.99,
                    "close": close,
                    "volume": 1000.0 * (asset_position + 1),
                    "trade_count": 100.0 + day_offset,
                    "vwap": (open_price + close) / 2.0,
                    "interpolated": False,
                }
            )
    frame = pd.DataFrame(rows)
    frame["time_index"] = normalize_datetime64_ns_utc(frame["time_index"])
    frame["open_time"] = normalize_datetime64_ns_utc(frame["open_time"])
    return frame.set_index(["time_index", "asset_identifier"]).sort_index()


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
                "asset_identifier": asset_identifier,
                "quantity": quantity,
                "direction": 1,
            }
            for asset_identifier, quantity in zip(
                ASSET_UNIQUE_IDENTIFIERS,
                [10.0, 5.0],
                strict=True,
            )
        ],
    )


def print_result_summary(result: dict[str, Any], *, run_data_nodes: bool) -> None:
    portfolio = result["portfolio"]
    portfolio_index = result["portfolio_index"]
    portfolio_calendar = result["portfolio_calendar"]
    account = result["account"]
    virtual_fund = result["virtual_fund"]

    print_step(12, "Final portfolio workflow summary.")
    print_detail("portfolio_uid", portfolio.uid)
    print_detail("portfolio_identifier", portfolio.unique_identifier)
    print_detail("portfolio_index_uid", portfolio_index.uid)
    print_detail("portfolio_index_identifier", portfolio_index.unique_identifier)
    print_detail("portfolio_calendar_uid", portfolio_calendar.uid)
    print_detail("portfolio_calendar_identifier", portfolio_calendar.unique_identifier)
    print_detail("account_uid", account.uid)
    print_detail("virtual_fund_uid", virtual_fund.uid)
    print_detail("virtual_fund_identifier", virtual_fund.unique_identifier)
    print_detail("portfolio_configuration_hash", result["portfolio_configuration_hash"])
    print_detail("source_prices_storage_uid", result["source_prices_storage_uid"])
    print_detail("source_prices_storage_hash", result["source_prices_storage_hash"])
    print_detail("source_prices_cadence", result["source_prices_cadence"])
    print_detail("interpolated_prices_storage_uid", result["interpolated_prices_storage_uid"])
    print_detail(
        "interpolated_prices_storage_table",
        result["interpolated_prices_storage_table"],
    )
    print_detail(
        "interpolated_prices_storage_cadence",
        result["interpolated_prices_storage_cadence"],
    )
    print_detail("source_prices_data_node_uid", result["source_prices_node_uid"])
    print_detail("signal_weights_data_node_uid", result["signal_weights_node_uid"])
    print_detail("portfolio_weights_data_node_uid", result["portfolio_weights_node_uid"])
    print_detail("portfolio_values_data_node_uid", result["portfolio_values_node_uid"])
    print_detail("account_holdings_rows", len(result["account_holdings_frame"]))
    print_detail("virtual_fund_allocation_rows", len(result["virtual_fund_allocations_frame"]))
    if not run_data_nodes:
        print_detail("data_node_mode", "frames built locally; storage publication skipped")


def build_equal_weight_portfolio(
    *,
    run_data_nodes: bool = True,
    runtime_models: Sequence[str | type[Any]] | None = None,
) -> dict[str, Any]:
    """Create the portfolio index, run portfolio DataNodes, and upsert Portfolio."""

    print_step(1, "Starting the portfolio example runtime.")
    runtime = start_portfolio_example_runtime(models=runtime_models)

    print_step(2, "Registering the crypto asset universe.")
    assets = register_assets()

    print_step(3, "Creating or reusing the crypto 24/7 calendar.")
    portfolio_calendar = create_crypto_calendar_from_pandas()

    print_step(4, "Registering the allocation account.")
    account = register_account()

    print_step(5, "Registering the portfolio index row.")
    portfolio_index = register_portfolio_index()

    print_step(6, "Preparing equal-weight signal and portfolio DataNodes.")
    source_prices_storage_uid, source_prices_storage_meta_table = resolve_source_prices_storage(
        runtime
    )
    source_prices_cadence = source_cadence_from_meta_table(
        source_prices_storage_meta_table,
        fallback=SOURCE_PRICE_CADENCE,
    )
    interpolated_prices_storage = build_example_interpolated_prices_storage(
        source_prices_storage_meta_table
    )
    interpolated_prices_meta_table = assert_interpolated_prices_storage_registered(
        interpolated_prices_storage
    )
    source_bars_node = build_source_bars_node()
    signal_weights_node = build_signal_weights_node(source_prices_storage_uid)
    portfolio_configuration = build_portfolio_configuration(
        signal_weights_node,
        calendar=portfolio_calendar,
        source_time_index_meta_table_uid=source_prices_storage_uid,
    )
    portfolio = Portfolio.upsert(
        unique_identifier=PORTFOLIO_UNIQUE_IDENTIFIER,
        calendar_uid=portfolio_calendar.uid,
        calendar_name=portfolio_calendar.unique_identifier,
        portfolio_index_uid=portfolio_index.uid,
    )
    portfolio_resolver = ExamplePortfolioResolver(
        portfolio=portfolio,
        portfolio_index=portfolio_index,
    )
    portfolio_values_node = build_portfolio_values_node(
        portfolio_configuration,
        portfolio_resolver=portfolio_resolver,
    )
    print_detail("portfolio_uid", portfolio.uid)
    print_detail("portfolio_identifier", portfolio.unique_identifier)
    print_detail("signal_uid", signal_weights_node.signal_uid)
    print_detail("source_prices_storage_uid", source_prices_storage_uid)
    print_detail("source_prices_cadence", source_prices_cadence)
    print_detail("source_prices_storage_hash", source_prices_storage_meta_table.storage_hash)
    print_detail(
        "interpolated_prices_storage_table",
        interpolated_prices_storage.__table__.name,
    )
    print_detail(
        "interpolated_prices_storage_uid",
        getattr(interpolated_prices_meta_table, "uid", None),
    )
    print_detail(
        "interpolated_prices_storage_cadence",
        interpolated_prices_storage.__cadence__,
    )
    print_detail(
        "portfolio_configuration_hash",
        compute_portfolio_configuration_hash(portfolio_configuration),
    )
    print_detail("source_prices_rows", len(build_example_daily_bars_frame(ASSET_UNIQUE_IDENTIFIERS)))

    print_step(7, "Publishing portfolio DataNode storage outputs.")
    if run_data_nodes:
        source_bars_node.run(debug_mode=True, update_tree=False, force_update=True)
        source_prices_node_uid = str(source_bars_node.data_node_update.uid)
        print_detail("source_prices_data_node_uid", source_prices_node_uid)

        portfolio_values_node.run(debug_mode=True, update_tree=True, force_update=True)

        signal_weights_node_uid = str(signal_weights_node.data_node_update.uid)
        print_detail("signal_weights_data_node_uid", signal_weights_node_uid)

        portfolio_weights_node = portfolio_values_node._canonical_portfolio_weights_node()
        portfolio_weights_node_uid = str(portfolio_weights_node.data_node_update.uid)
        print_detail("portfolio_weights_data_node_uid", portfolio_weights_node_uid)

        portfolio_values_node_uid = str(portfolio_values_node.data_node_update.uid)
        print_detail("portfolio_values_data_node_uid", portfolio_values_node_uid)
    else:
        print_detail("source_prices_data_node_uid", "skipped (--no-run-data-nodes)")
        print_detail("signal_weights_data_node_uid", "skipped (--no-run-data-nodes)")
        print_detail("portfolio_weights_data_node_uid", "skipped (--no-run-data-nodes)")
        print_detail("portfolio_values_data_node_uid", "skipped (--no-run-data-nodes)")
        source_prices_node_uid = None
        signal_weights_node_uid = None
        portfolio_weights_node_uid = None
        portfolio_values_node_uid = None

    print_step(8, "Updating the Portfolio row with DataNode links.")
    portfolio = Portfolio.upsert(
        unique_identifier=PORTFOLIO_UNIQUE_IDENTIFIER,
        calendar_uid=portfolio_calendar.uid,
        calendar_name=portfolio_calendar.unique_identifier,
        portfolio_index_uid=portfolio_index.uid,
        signal_weights_data_node_uid=signal_weights_node_uid,
        portfolio_weights_data_node_uid=portfolio_weights_node_uid,
        portfolio_data_node_uid=portfolio_values_node_uid,
    )
    print_detail("portfolio_uid", portfolio.uid)
    print_detail("portfolio_identifier", portfolio.unique_identifier)

    print_step(9, "Creating source account holdings for virtual-fund allocation.")
    holdings_set = AccountHoldingsSet.upsert(account_uid=account.uid, time_index=TIME_INDEX)
    account_holdings_node = AccountHoldings(config=AccountHoldings.default_config())
    account_holdings_frame = build_account_holdings_frame(
        account_holdings_node, account, holdings_set
    )
    account_holdings_node.set_frame(account_holdings_frame)
    print_detail("account_holdings_set_uid", holdings_set.uid)
    print_detail("account_holdings_rows", len(account_holdings_frame))
    if run_data_nodes:
        account_holdings_node.run(debug_mode=True, update_tree=False, force_update=True)
        account_holdings_node_uid = str(account_holdings_node.data_node_update.uid)
        print_detail("account_holdings_data_node_uid", account_holdings_node_uid)
    else:
        print_detail("account_holdings_data_node_uid", "skipped (--no-run-data-nodes)")
        account_holdings_node_uid = None

    print_step(10, "Upserting the VirtualFund row that targets the portfolio.")
    virtual_fund = VirtualFund.upsert(
        unique_identifier=VIRTUAL_FUND_UNIQUE_IDENTIFIER,
        account_uid=account.uid,
        target_portfolio_uid=portfolio.uid,
    )
    print_detail("virtual_fund_uid", virtual_fund.uid)
    print_detail("virtual_fund_identifier", virtual_fund.unique_identifier)

    print_step(11, "Allocating source account holdings into virtual-fund holdings.")
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
        "portfolio_calendar": portfolio_calendar,
        "virtual_fund": virtual_fund,
        "portfolio_configuration_hash": compute_portfolio_configuration_hash(
            portfolio_configuration
        ),
        "source_prices_storage_uid": source_prices_storage_uid,
        "source_prices_storage_hash": source_prices_storage_meta_table.storage_hash,
        "source_prices_cadence": source_prices_cadence,
        "interpolated_prices_storage_uid": getattr(interpolated_prices_meta_table, "uid", None),
        "interpolated_prices_storage_table": interpolated_prices_storage.__table__.name,
        "interpolated_prices_storage_cadence": interpolated_prices_storage.__cadence__,
        "source_prices_node_uid": source_prices_node_uid,
        "signal_weights_node_uid": signal_weights_node_uid,
        "portfolio_weights_node_uid": portfolio_weights_node_uid,
        "portfolio_values_node_uid": portfolio_values_node_uid,
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
        help="Skip DataNode publication; by default the full dependency tree is published.",
    )
    args = parser.parse_args()
    build_equal_weight_portfolio(run_data_nodes=not args.no_run_data_nodes)


if __name__ == "__main__":
    main()
