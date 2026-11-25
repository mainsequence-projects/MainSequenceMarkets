"""Configure trailing daily-liquidity participation with observable execution bars."""

from __future__ import annotations

import argparse

from metatables import TimeIndexTableRef
from msm_portfolios.rebalance_strategy import (
    TrailingAverageDailyVolumeParticipation,
)


def build_trailing_adv_strategy(
    *,
    daily_liquidity_table_name: str,
    execution_bars_table_name: str,
) -> TrailingAverageDailyVolumeParticipation:
    """Build a strategy that never treats historical VWAP as an execution price.

    Both sources are another owner's registered tables, referred to by their physical
    names, which are the same in every Environment (ADR 0066).
    """
    return TrailingAverageDailyVolumeParticipation(
        daily_liquidity_instance=TimeIndexTableRef.from_physical_identity(
            schema="public", table_name=daily_liquidity_table_name
        ),
        execution_bars_instance=TimeIndexTableRef.from_physical_identity(
            schema="public", table_name=execution_bars_table_name
        ),
        daily_vwap_column="vwap",
        daily_volume_column="volume",
        execution_price_column="close",
        execution_volume_column="volume",
        lookback_observations=20,
        history_lookback_days=60,
        session_timezone="America/New_York",
        execution_start="09:30",
        execution_end="16:00",
        max_daily_participation=0.05,
        max_bar_participation=0.10,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-liquidity-table-name", required=True)
    parser.add_argument("--execution-bars-table-name", required=True)
    args = parser.parse_args()
    strategy = build_trailing_adv_strategy(
        daily_liquidity_table_name=args.daily_liquidity_table_name,
        execution_bars_table_name=args.execution_bars_table_name,
    )
    print(strategy.get_explanation())
    print("Declared dependencies:", ", ".join(strategy.declared_dependencies()))


if __name__ == "__main__":
    main()
