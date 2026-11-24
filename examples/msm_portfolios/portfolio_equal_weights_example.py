from __future__ import annotations

import argparse
import sys
from pathlib import Path
from collections.abc import Sequence
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import use_local_runtime  # noqa: E402

if __name__ == "__main__":
    use_local_runtime()  # before any client model is imported

from examples.msm.assets.utils import (  # noqa: E402
    EXAMPLE_CRYPTO_ASSETS,
    EXAMPLE_CRYPTO_ASSET_TYPE,
    EXAMPLE_CURRENCY_ASSET_TYPE,
)
from examples.msm_portfolios.portfolio_equal_weights_config import (  # noqa: E402
    ASSET_UNIQUE_IDENTIFIERS,
    CRYPTO_CALENDAR_UNIQUE_IDENTIFIER,
    INTERPOLATED_PRICES_STORAGE,
    MIGRATION_COMMAND,
    NAMESPACE,
    PORTFOLIO_EXAMPLE_RUNTIME_MODELS,
    PORTFOLIO_UNIQUE_IDENTIFIER,
    PRICE_INTERPOLATION_RULE,
    PRICE_UPSAMPLE_FREQUENCY_ID,
    SIGNAL_TIME_INDEX,
    SIGNAL_WEIGHTS_STORAGE,
    SOURCE_PRICE_CADENCE,
    TIME_INDEX,
)

import msm_portfolios  # noqa: E402
from metatables import TimeIndexMetaTable  # noqa: E402
from metatables import TimeIndexTableRef, TimeIndexTableUpdater  # noqa: E402
from msm.api.assets import Asset, AssetType  # noqa: E402
from msm.constants import ASSET_TYPE_CURRENCY  # noqa: E402
from msm.api.calendars import Calendar  # noqa: E402
from msm.time_index.assets.asset_indexed import (  # noqa: E402
    AssetIndexedUpdater,
    AssetIndexedUpdaterConfiguration,
)
from msm.time_index.utils.time import normalize_datetime64_ns_utc  # noqa: E402
from msm.api.portfolios import Portfolio  # noqa: E402
from msm_portfolios.accounting import (  # noqa: E402
    MarketPriceValuationModel,
    PortfolioAccountingConfiguration,
)
from msm_portfolios.configuration import (  # noqa: E402
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
    PortfolioMarketsConfig,
)
from msm_portfolios.contrib.signals.fixed_weights import (  # noqa: E402
    AUIDWeight,
    FixedWeights,
    FixedWeightsConfig,
)
from msm_portfolios.contrib.prices.updaters import (  # noqa: E402
    InterpolatedPrices,
    InterpolatedPricesConfig,
)
from msm_portfolios.time_index.prices.storage import (  # noqa: E402
    ExternalPricesStorage,
)
from msm_portfolios.recipes import run_portfolio  # noqa: E402
from msm_portfolios.time_index import (  # noqa: E402
    PortfolioCalendarEvents,
    PortfolioCalendarEventsConfiguration,
    compute_portfolio_configuration_hash,
)
from msm_portfolios.rebalance_strategy import (  # noqa: E402
    CalendarEventSignal,
    ProportionalExecutionCostModel,
)


PORTFOLIO_CURRENCY = "USD"


class ExamplePortfolioResolver:
    """Bind one example portfolio configuration to its Portfolio row."""

    def __init__(self, *, portfolio: Portfolio) -> None:
        self.portfolio = portfolio

    def get_or_create_from_configuration_hash(
        self,
        *,
        portfolio_configuration_hash: str,
        portfolio_configuration: dict[str, Any],
        timeout: int | float | tuple[float, float] | None = None,
    ) -> Portfolio:
        del portfolio_configuration_hash, portfolio_configuration, timeout
        return self.portfolio


class ExampleDailyBars(AssetIndexedUpdater):
    """Daily OHLCV source supporting the portfolio's set-based seed observation read."""

    OFFSET_START = (TIME_INDEX - pd.Timedelta(days=90)).to_pydatetime()

    def __init__(
        self,
        *,
        asset_identifiers: Sequence[str],
        namespace: str | None = None,
    ) -> None:
        self._asset_identifiers = list(asset_identifiers)
        super().__init__(
            config=AssetIndexedUpdaterConfiguration(asset_list=self._asset_identifiers),
            output_table=ExternalPricesStorage,
            hash_namespace=namespace or NAMESPACE,
        )

    @classmethod
    def _required_output_table(cls) -> type[ExternalPricesStorage]:
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


def print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def print_detail(label: str, value: object) -> None:
    print(f"   {label}: {value}")


def start_portfolio_example_runtime(
    *,
    models: Sequence[str | type[Any]] | None = None,
) -> Any:
    """Attach the already-registered tables/storage used by this portfolio example."""

    use_local_runtime()
    return msm_portfolios.start_engine(
        models=list(models or PORTFOLIO_EXAMPLE_RUNTIME_MODELS),
    )


def register_assets(calendar: Calendar) -> list[Asset]:
    """Register the asset types, then the assets: one upsert of each.

    Each crypto asset names the stored calendar whose sessions decide its price bars,
    so the upsert links it (ADR 0057). An asset with no link fails the price update;
    there is no default calendar. The portfolio's currency is an asset too, since the
    ledger's cash is in it (ADR 0065). It gets no price bars and needs no calendar.
    Returns the crypto assets.
    """

    asset_types = AssetType.upsert_many(
        [EXAMPLE_CRYPTO_ASSET_TYPE, EXAMPLE_CURRENCY_ASSET_TYPE]
    )
    *assets, currency = Asset.upsert_many(
        [
            *({**payload, "calendar_uid": calendar.uid} for payload in EXAMPLE_CRYPTO_ASSETS),
            {"unique_identifier": PORTFOLIO_CURRENCY, "asset_type": ASSET_TYPE_CURRENCY},
        ]
    )
    print_detail("asset_types", ", ".join(asset_type.asset_type for asset_type in asset_types))
    print_detail("assets", ", ".join(asset.unique_identifier for asset in assets))
    print_detail("asset_calendar", f"{len(assets)} assets -> {calendar.unique_identifier}")
    print_detail("portfolio_currency", currency.unique_identifier)
    return assets


def create_crypto_calendar_from_pandas() -> Calendar:
    portfolio_calendar = Calendar.create_from_pandas_calendar(
        "24/7",
        CRYPTO_CALENDAR_UNIQUE_IDENTIFIER,
        display_name="Crypto 24/7",
        metadata_json={"example": "portfolio_equal_weights_example"},
    )
    print_detail("calendar_uid", portfolio_calendar.uid)
    print_detail("calendar_identifier", portfolio_calendar.unique_identifier)
    print_detail(
        "calendar_source",
        f"{portfolio_calendar.source}:{portfolio_calendar.source_identifier}",
    )
    return portfolio_calendar


def build_fixed_weights_config() -> FixedWeightsConfig:
    weight = 1.0 / len(ASSET_UNIQUE_IDENTIFIERS)
    return FixedWeightsConfig(
        asset_unique_identifier_weights=[
            AUIDWeight(unique_identifier=asset_uid, weight=weight)
            for asset_uid in ASSET_UNIQUE_IDENTIFIERS
        ],
        signal_time_index=SIGNAL_TIME_INDEX.to_pydatetime(),
    )


def build_portfolio_configuration(
    signal_weights: FixedWeights,
    *,
    calendar: Calendar,
    calendar_events: PortfolioCalendarEvents,
    price_source: InterpolatedPrices,
) -> PortfolioConfiguration:
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            valuation_source_instance=price_source,
            valuation_asset_identifier=PORTFOLIO_CURRENCY,
            valuation_column="close",
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal_weights,
                rebalance_strategy_instance=CalendarEventSignal(
                    calendar_events_instance=calendar_events,
                    calendar_identifier=calendar.unique_identifier,
                    session_label="regular",
                    rebalance_event="market_close",
                    # A cost of 0.018% of each trade's notional, booked by the ledger.
                    execution_cost_model_instances=(
                        ProportionalExecutionCostModel(rate=0.00018),
                    ),
                ),
            ),
            # Every portfolio keeps a ledger (ADR 0065): 1,000,000 USD in cash from the
            # first source bar, valued at the interpolated closes.
            accounting_configuration=PortfolioAccountingConfiguration(
                initial_nav=1_000_000.0,
                initial_state_time_index=(TIME_INDEX - pd.Timedelta(days=3)).to_pydatetime(),
                position_valuation_model_instance=MarketPriceValuationModel(),
            ),
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(
            portfolio_name="Example Equal Weight Portfolio",
        ),
    )


def build_signal_weights_node() -> FixedWeights:
    """The computed signal: its own node, writing the example's signal table."""

    signal_configuration = build_fixed_weights_config()
    return FixedWeights.from_signal_configuration(
        signal_configuration,
        output_table=SIGNAL_WEIGHTS_STORAGE,
        namespace=NAMESPACE,
    )


def build_calendar_events_node(*, calendar: Calendar) -> PortfolioCalendarEvents:
    return PortfolioCalendarEvents(
        config=PortfolioCalendarEventsConfiguration(
            calendar_identifier=calendar.unique_identifier,
            session_label="regular",
            event_types=("market_open", "market_close"),
        ),
        namespace=NAMESPACE,
    )


def build_interpolated_prices_node(
    source_price_instance: TimeIndexTableUpdater | TimeIndexTableRef,
) -> InterpolatedPrices:
    return InterpolatedPrices(
        interpolation_config=InterpolatedPricesConfig(
            # The scope names the assets. Each asset's trading calendar is its
            # stored AssetCalendar link, written by register_assets().
            asset_list=list(ASSET_UNIQUE_IDENTIFIERS),
            intraday_bar_interpolation_rule=PRICE_INTERPOLATION_RULE,
            source_price_instance=source_price_instance,
            upsample_frequency_id=PRICE_UPSAMPLE_FREQUENCY_ID,
        ),
        output_table=INTERPOLATED_PRICES_STORAGE,
        hash_namespace=NAMESPACE,
    )


def build_source_bars_node() -> ExampleDailyBars:
    return ExampleDailyBars(
        asset_identifiers=ASSET_UNIQUE_IDENTIFIERS,
        namespace=NAMESPACE,
    )


def resolve_source_prices_storage(runtime: Any) -> str:
    """Return the registered source storage UID."""

    handle = runtime.table(ExternalPricesStorage)
    if handle.meta_table is None:
        raise RuntimeError(
            "ExternalPricesStorage is not attached to a registered TimeIndexMetaTable."
        )
    return str(handle.meta_table_uid)


def assert_example_storage_registered(storage: Any, description: str) -> Any:
    """Fail clearly when one of the example's own tables was not migrated first."""

    table_name = storage.__table__.name
    matches = TimeIndexMetaTable.filter_by_body(
        physical_table_name__in=[table_name],
        limit=1,
        offset=0,
    )
    if not matches:
        raise RuntimeError(
            f"The example's {description} table is missing: {table_name}. "
            f"Apply its committed revisions first: {MIGRATION_COMMAND}"
        )

    meta_table = matches[0]
    storage._bind_meta_table(meta_table)
    return meta_table


def assert_interpolated_prices_storage_registered() -> Any:
    return assert_example_storage_registered(INTERPOLATED_PRICES_STORAGE, "interpolated-price")


def assert_signal_weights_storage_registered() -> Any:
    return assert_example_storage_registered(SIGNAL_WEIGHTS_STORAGE, "signal")


def build_example_daily_bars_frame(asset_identifiers: Sequence[str]) -> pd.DataFrame:
    """Build source bars with explicit nanosecond UTC index and payload timestamps."""

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
    for timestamp_column in ("time_index", "open_time"):
        frame[timestamp_column] = normalize_datetime64_ns_utc(frame[timestamp_column])
    return frame.set_index(["time_index", "asset_identifier"]).sort_index()


def print_result_summary(result: dict[str, Any], *, run_updaters: bool) -> None:
    portfolio = result["portfolio"]
    portfolio_calendar = result["portfolio_calendar"]

    print_step(8, "Final portfolio workflow summary.")
    print_detail("portfolio_uid", portfolio.uid)
    print_detail("portfolio_identifier", portfolio.unique_identifier)
    print_detail("portfolio_calendar_uid", portfolio_calendar.uid)
    print_detail("portfolio_calendar_identifier", portfolio_calendar.unique_identifier)
    print_detail("portfolio_configuration_hash", result["portfolio_configuration_hash"])
    print_detail("source_prices_storage_uid", result["source_prices_storage_uid"])
    print_detail("source_prices_cadence", result["source_prices_cadence"])
    print_detail("interpolated_prices_storage_uid", result["interpolated_prices_storage_uid"])
    print_detail(
        "interpolated_prices_output_table",
        result["interpolated_prices_output_table"],
    )
    print_detail(
        "interpolated_prices_storage_cadence",
        result["interpolated_prices_storage_cadence"],
    )
    print_detail("source_prices_table_update_uid", result["source_prices_table_update_uid"])
    print_detail("interpolated_prices_table_update_uid", result["interpolated_prices_table_update_uid"])
    print_detail("calendar_events_table_update_uid", result["calendar_events_table_update_uid"])
    print_detail("signal_weights_output_table", result["signal_weights_output_table"])
    print_detail("signal_weights_table_update_uid", result["signal_weights_table_update_uid"])
    print_detail("published_signal_weights_rows", result["published_signal_weights_rows"])
    print_detail("published_portfolio_weights_rows", result["published_portfolio_weights_rows"])
    print_detail("published_portfolio_values_rows", result["published_portfolio_values_rows"])
    if not run_updaters:
        print_detail("updater_mode", "frames built locally; storage publication skipped")


def build_equal_weight_portfolio(
    *,
    run_updaters: bool = True,
    runtime_models: Sequence[str | type[Any]] | None = None,
) -> dict[str, Any]:
    """Create the portfolio, run portfolio updaters, and upsert Portfolio."""

    print_section("Equal-Weight Portfolio Workflow")

    print_step(1, "Starting the portfolio example runtime.")
    runtime = start_portfolio_example_runtime(models=runtime_models)

    print_step(2, "Creating or reusing the crypto 24/7 calendar with sessions.")
    portfolio_calendar = create_crypto_calendar_from_pandas()

    print_step(3, "Registering the crypto assets on that calendar, and the portfolio currency.")
    assets = register_assets(portfolio_calendar)

    print_step(4, "Preparing explicit price, signal, and portfolio updaters.")
    source_prices_storage_uid = resolve_source_prices_storage(runtime)
    source_prices_cadence = SOURCE_PRICE_CADENCE
    interpolated_prices_storage = INTERPOLATED_PRICES_STORAGE
    interpolated_prices_meta_table = assert_interpolated_prices_storage_registered()
    assert_signal_weights_storage_registered()
    source_bars_node = build_source_bars_node()
    interpolated_prices_node = build_interpolated_prices_node(source_bars_node)
    signal_weights_node = build_signal_weights_node()
    calendar_events_node = build_calendar_events_node(calendar=portfolio_calendar)
    portfolio_configuration = build_portfolio_configuration(
        signal_weights_node,
        calendar=portfolio_calendar,
        calendar_events=calendar_events_node,
        price_source=interpolated_prices_node,
    )
    portfolio = Portfolio.upsert(
        unique_identifier=PORTFOLIO_UNIQUE_IDENTIFIER,
        calendar_uid=portfolio_calendar.uid,
    )
    portfolio_resolver = ExamplePortfolioResolver(
        portfolio=portfolio,
    )
    print_detail("portfolio_uid", portfolio.uid)
    print_detail("portfolio_identifier", portfolio.unique_identifier)
    print_detail("signal_uid", signal_weights_node.signal_uid)
    print_detail("source_prices_storage_uid", source_prices_storage_uid)
    print_detail("source_prices_cadence", source_prices_cadence)
    print_detail("price_source_update_hash", interpolated_prices_node.update_hash)
    print_detail(
        "interpolated_prices_output_table",
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
    print_detail(
        "source_prices_rows", len(build_example_daily_bars_frame(ASSET_UNIQUE_IDENTIFIERS))
    )

    print_step(5, "Running the portfolio and publishing its series to Markets (ADR 0060).")
    if run_updaters:
        # One joined MetaTables run (issue #133): the source bars, the interpolated
        # prices, the calendar events and the signal run once, then the rebalance and the
        # ledger; the weights and values are published after. The signal is its own node:
        # it writes the example's signal table and publishes the same rows to Markets.
        portfolio_run = run_portfolio(
            portfolio_configuration,
            namespace=NAMESPACE,
            portfolio_resolver=portfolio_resolver,
            portfolio_description="Published portfolio value series.",
        )
        portfolio = portfolio_run.portfolio
        print_detail("first_rebalance", portfolio_run.first_rebalance)

        source_prices_table_update_uid = str(source_bars_node.table_update.uid)
        print_detail("source_prices_table_update_uid", source_prices_table_update_uid)
        interpolated_prices_table_update_uid = str(interpolated_prices_node.table_update.uid)
        print_detail("interpolated_prices_table_update_uid", interpolated_prices_table_update_uid)

        calendar_events_table_update_uid = str(calendar_events_node.table_update.uid)
        print_detail("calendar_events_table_update_uid", calendar_events_table_update_uid)
        signal_weights_table_update_uid = str(signal_weights_node.table_update.uid)
        print_detail("signal_weights_table_update_uid", signal_weights_table_update_uid)

        from msm_portfolios.api import (
            PortfolioValuesSeries,
            PortfolioWeightsSeries,
            SignalWeightsSeries,
        )

        published_signal_weights_rows = SignalWeightsSeries.bounds(
            [signal_weights_node.signal_uid]
        )[0].row_count
        published_portfolio_weights_rows = PortfolioWeightsSeries.bounds(
            [portfolio.unique_identifier]
        )[0].row_count
        published_portfolio_values_rows = PortfolioValuesSeries.bounds(
            [portfolio.unique_identifier]
        )[0].row_count
        print_detail("published_signal_weights_rows", published_signal_weights_rows)
        print_detail("published_portfolio_weights_rows", published_portfolio_weights_rows)
        print_detail("published_portfolio_values_rows", published_portfolio_values_rows)
    else:
        print_detail("source_prices_table_update_uid", "skipped (--no-run-updaters)")
        print_detail("interpolated_prices_table_update_uid", "skipped (--no-run-updaters)")
        print_detail("calendar_events_table_update_uid", "skipped (--no-run-updaters)")
        print_detail("signal_weights_table_update_uid", "skipped (--no-run-updaters)")
        print_detail("published series", "skipped (--no-run-updaters)")
        source_prices_table_update_uid = None
        interpolated_prices_table_update_uid = None
        calendar_events_table_update_uid = None
        signal_weights_table_update_uid = None
        published_signal_weights_rows = None
        published_portfolio_weights_rows = None
        published_portfolio_values_rows = None

    print_step(6, "The Portfolio row names its signal; its weights and values are published.")
    print_detail("portfolio_uid", portfolio.uid)
    print_detail("portfolio_identifier", portfolio.unique_identifier)

    result = {
        "assets": assets,
        "portfolio": portfolio,
        "portfolio_calendar": portfolio_calendar,
        "portfolio_configuration_hash": compute_portfolio_configuration_hash(
            portfolio_configuration
        ),
        "source_prices_storage_uid": source_prices_storage_uid,
        "source_prices_cadence": source_prices_cadence,
        "interpolated_prices_storage_uid": getattr(interpolated_prices_meta_table, "uid", None),
        "interpolated_prices_output_table": interpolated_prices_storage.__table__.name,
        "interpolated_prices_storage_cadence": interpolated_prices_storage.__cadence__,
        "source_prices_table_update_uid": source_prices_table_update_uid,
        "interpolated_prices_table_update_uid": interpolated_prices_table_update_uid,
        "calendar_events_table_update_uid": calendar_events_table_update_uid,
        "signal_weights_output_table": SIGNAL_WEIGHTS_STORAGE.__table__.name,
        "signal_weights_table_update_uid": signal_weights_table_update_uid,
        "published_signal_weights_rows": published_signal_weights_rows,
        "published_portfolio_weights_rows": published_portfolio_weights_rows,
        "published_portfolio_values_rows": published_portfolio_values_rows,
    }
    print_result_summary(result, run_updaters=run_updaters)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-run-updaters",
        action="store_true",
        help="Skip TimeIndexTableUpdater publication; by default the full dependency tree is published.",
    )
    args = parser.parse_args()
    build_equal_weight_portfolio(run_updaters=not args.no_run_updaters)


if __name__ == "__main__":
    main()
