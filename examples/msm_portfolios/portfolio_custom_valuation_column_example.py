from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.assets.utils import EXAMPLE_CRYPTO_ASSETS  # noqa: E402
from examples.msm_portfolios.portfolio_equal_weights_config import (  # noqa: E402
    CRYPTO_CALENDAR_UNIQUE_IDENTIFIER,
    NAMESPACE,
    EqualWeightSignalWeights,
)
from metatables import TimeIndexTableRef, TimeIndexTableUpdater  # noqa: E402
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
from msm_portfolios.time_index import compute_portfolio_configuration_hash  # noqa: E402
from msm_portfolios.rebalance_strategy import (  # noqa: E402
    CalendarEventSignal,
    ProportionalExecutionCostModel,
)

FAIR_VALUE_SOURCE_TABLE_ENV = "MSM_EXAMPLE_FAIR_VALUE_TABLE_NAME"
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
        # After the ledger opens (2026-01-01). The source needs a fair_value before the
        # first close after this time, or the rebalance cannot size the weights (ADR 0058).
        signal_time_index=dt.datetime(2026, 1, 2, 12, tzinfo=dt.UTC),
    )
    # The computed signal writes the equal-weight example's signal table, which that
    # example's provider migrates, and publishes the same rows to Markets.
    return FixedWeights.from_signal_configuration(
        signal_config,
        output_table=EqualWeightSignalWeights,
        namespace=NAMESPACE,
    )


def build_fair_value_portfolio_configuration(
    *,
    valuation_source: TimeIndexTableUpdater | TimeIndexTableRef,
    calendar_events: TimeIndexTableUpdater | TimeIndexTableRef,
) -> PortfolioConfiguration:
    signal_weights = build_fixed_weights_signal()
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            valuation_source_instance=valuation_source,
            valuation_asset_identifier="USD",
            valuation_column=FAIR_VALUE_COLUMN,
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal_weights,
                rebalance_strategy_instance=CalendarEventSignal(
                    calendar_events_instance=calendar_events,
                    calendar_identifier=CRYPTO_CALENDAR_UNIQUE_IDENTIFIER,
                    session_label="regular",
                    rebalance_event="market_close",
                    execution_cost_model_instances=(
                        ProportionalExecutionCostModel(rate=0.00018),
                    ),
                ),
            ),
            # The ledger values every position at the source's fair_value (ADR 0065).
            accounting_configuration=PortfolioAccountingConfiguration(
                initial_nav=1_000_000.0,
                initial_state_time_index=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                position_valuation_model_instance=MarketPriceValuationModel(),
            ),
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(
            portfolio_name="Example Fair Value Portfolio",
        ),
    )


def table_reference(table_name: str) -> TimeIndexTableRef:
    """Another owner's registered table, by its physical name (ADR 0066).

    The name is the same in every Environment, and the table's UID is not.
    """

    if not table_name.strip():
        raise ValueError("table_name cannot be empty.")
    return TimeIndexTableRef.from_physical_identity(schema="public", table_name=table_name)


def run_configuration_example(
    *,
    source_table_name: str,
    calendar_events_table_name: str,
) -> dict[str, Any]:
    portfolio_configuration = build_fair_value_portfolio_configuration(
        valuation_source=table_reference(source_table_name),
        calendar_events=table_reference(calendar_events_table_name),
    )
    return {
        "portfolio_unique_identifier": PORTFOLIO_UNIQUE_IDENTIFIER,
        "valuation_source_table_name": source_table_name,
        "valuation_column": FAIR_VALUE_COLUMN,
        "portfolio_configuration_hash": compute_portfolio_configuration_hash(
            portfolio_configuration
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-table-name",
        default=os.environ.get(FAIR_VALUE_SOURCE_TABLE_ENV),
        help=(
            "Physical name of a registered asset-indexed TimeIndexMetaTable with "
            "time_index, asset_identifier, and fair_value columns."
        ),
    )
    parser.add_argument(
        "--calendar-events-table-name",
        required=True,
        help=(
            "Physical name of the registered TimeIndexMetaTable that PortfolioCalendarEvents "
            f"publishes {CRYPTO_CALENDAR_UNIQUE_IDENTIFIER}'s market opens and closes to."
        ),
    )
    args = parser.parse_args()
    if args.source_table_name in (None, ""):
        raise RuntimeError(
            "Pass --source-table-name or set "
            f"{FAIR_VALUE_SOURCE_TABLE_ENV}. The source table must expose "
            f"{FAIR_VALUE_COLUMN!r}; the example does not rename it to 'close'."
        )

    result = run_configuration_example(
        source_table_name=str(args.source_table_name),
        calendar_events_table_name=args.calendar_events_table_name,
    )
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
