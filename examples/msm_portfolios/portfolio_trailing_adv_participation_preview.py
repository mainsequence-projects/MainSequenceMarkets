"""Preview trailing-ADV rebalance transitions from registered market-data tables.

This example reads completed daily liquidity and observable intraday execution
bars for only the requested assets, as ``PortfolioRebalance`` reads them: the
execution bars include each asset's last bar before the window, which sizes the
order at its decision. It runs the same strategy state machine, but deliberately
does not persist the preview.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm_portfolios.portfolio_trailing_adv_participation_example import (  # noqa: E402
    build_trailing_adv_strategy,
)
from msm_portfolios.rebalance_strategy import (  # noqa: E402
    TrailingAverageDailyVolumeParticipation,
)
from msm_portfolios.time_index.portfolios.rebalance import (  # noqa: E402
    read_strategy_inputs,
)


ASSET_IDENTIFIER = "asset_identifier"
SIGNAL_UID = "example-trailing-adv-target"
PREVIEW_INITIAL_NAV = 50_000_000.0
"""The portfolio's initial NAV, the unit of the rebalance's book (ADR 0065)."""


def parse_utc_timestamp(value: str) -> pd.Timestamp:
    """Parse one timezone-aware timestamp and normalize it to UTC."""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"Invalid timestamp: {value!r}.") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"Timestamp must include a timezone or UTC suffix: {value!r}."
        )
    return timestamp.tz_convert("UTC")


def parse_target(value: str) -> tuple[str, float]:
    """Parse an ``ASSET_IDENTIFIER=WEIGHT`` command-line target."""
    asset_identifier, separator, raw_weight = value.partition("=")
    asset_identifier = asset_identifier.strip()
    if not separator or not asset_identifier or not raw_weight.strip():
        raise argparse.ArgumentTypeError(
            "Targets must use ASSET_IDENTIFIER=WEIGHT, for example BTC-USD=0.60."
        )
    try:
        weight = float(raw_weight)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid target weight in {value!r}.") from exc
    if not math.isfinite(weight):
        raise argparse.ArgumentTypeError(f"Target weight must be finite in {value!r}.")
    return asset_identifier, weight


def target_weights(targets: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Return unique target weights while preserving command-line order."""
    result: dict[str, float] = {}
    for asset_identifier, weight in targets:
        if asset_identifier in result:
            raise ValueError(f"Duplicate target asset: {asset_identifier!r}.")
        result[asset_identifier] = weight
    return result


def build_signal_frame(
    *,
    signal_time: pd.Timestamp,
    weights: dict[str, float],
) -> pd.DataFrame:
    """Build one deterministic signal target at its actual observation time."""
    return (
        pd.DataFrame(
            [
                (signal_time, asset_identifier, weight, SIGNAL_UID)
                for asset_identifier, weight in weights.items()
            ],
            columns=["time_index", ASSET_IDENTIFIER, "signal_weight", "signal_uid"],
        )
        .set_index(["time_index", ASSET_IDENTIFIER])
        .sort_index()
    )


def load_observed_inputs(
    strategy: TrailingAverageDailyVolumeParticipation,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    asset_identifiers: Sequence[str],
) -> dict[str, pd.DataFrame]:
    """Read bounded, asset-filtered observations declared by the strategy.

    The daily history is read from ``history_lookback_days`` before ``start``. The
    execution bars are read over the window, with each asset's last bar before it:
    an order is sized with the last bar before its earliest moment.
    """
    return read_strategy_inputs(
        strategy,
        start=start,
        end=end,
        assets=list(asset_identifiers),
    )


def transition_summary(
    strategy: TrailingAverageDailyVolumeParticipation,
    transitions: pd.DataFrame,
    *,
    initial_nav: float = PREVIEW_INITIAL_NAV,
) -> pd.DataFrame:
    """Expand the strategy state fields most useful when reviewing a preview.

    A row's ``executed_quantity`` is in shares of the rebalance's book, whose unit is the
    portfolio's ``initial_nav``; ``quantity`` is the same fill in shares of the asset.
    """
    if transitions.empty:
        return pd.DataFrame()
    result = transitions.copy().reset_index(drop=True)
    bar_states = [
        strategy.parse_strategy_state(row).get("bar") or {}
        for row in result.to_dict(orient="records")
    ]
    result["quantity"] = result["executed_quantity"] * initial_nav
    for field_name in (
        "history_observations",
        "trailing_average_daily_notional",
        "daily_notional_limit",
        "daily_notional_consumed",
        "daily_notional_remaining",
    ):
        result[field_name] = [state.get(field_name) for state in bar_states]
    return result[
        [
            "time_index",
            ASSET_IDENTIFIER,
            "execution_status",
            "execution_price",
            "quantity",
            "weight_before",
            "weight_after",
            "remaining_weight_delta",
            "history_observations",
            "trailing_average_daily_notional",
            "daily_notional_limit",
            "daily_notional_consumed",
            "daily_notional_remaining",
        ]
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-liquidity-table-uid", required=True)
    parser.add_argument("--execution-bars-table-uid", required=True)
    parser.add_argument("--signal-time", required=True, type=parse_utc_timestamp)
    parser.add_argument("--start", required=True, type=parse_utc_timestamp)
    parser.add_argument("--end", required=True, type=parse_utc_timestamp)
    parser.add_argument(
        "--target",
        action="append",
        required=True,
        type=parse_target,
        metavar="ASSET=WEIGHT",
        help="Target portfolio weight; repeat once per asset.",
    )
    parser.add_argument(
        "--initial-nav",
        type=float,
        default=PREVIEW_INITIAL_NAV,
        help="The portfolio's initial NAV, the unit of the rebalance's book.",
    )
    parser.add_argument(
        "--output-rows",
        type=int,
        default=30,
        help="Maximum number of final transition rows to print.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.start > args.end:
        raise ValueError("--start must be at or before --end.")
    if args.signal_time > args.end:
        raise ValueError("--signal-time must be at or before --end.")
    if args.output_rows < 1:
        raise ValueError("--output-rows must be positive.")

    weights = target_weights(args.target)
    strategy = build_trailing_adv_strategy(
        daily_liquidity_table_uid=args.daily_liquidity_table_uid,
        execution_bars_table_uid=args.execution_bars_table_uid,
    )
    observed_inputs = load_observed_inputs(
        strategy,
        start=args.start,
        end=args.end,
        asset_identifiers=list(weights),
    )
    transitions = strategy.build_transitions(
        start=args.start.to_pydatetime(),
        end=args.end.to_pydatetime(),
        signal_observations=build_signal_frame(
            signal_time=args.signal_time,
            weights=weights,
        ),
        observed_inputs=observed_inputs,
        previous_state=None,
        book_unit_value=args.initial_nav,
    )

    print(strategy.get_explanation())
    for dependency_name, frame in observed_inputs.items():
        print(f"{dependency_name}: {len(frame):,} bounded source rows")
    if transitions.empty:
        print("No strategy transition was produced for the requested execution window.")
        return 0

    summary = transition_summary(strategy, transitions, initial_nav=args.initial_nav)
    print(f"Transitions: {len(summary):,}; showing final {min(len(summary), args.output_rows):,}")
    print(summary.tail(args.output_rows).to_string(index=False))
    print("Preview only: no PortfolioRebalanceStateStorage rows were persisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
