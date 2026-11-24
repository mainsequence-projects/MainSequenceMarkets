from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from examples.msm_portfolios.portfolio_trailing_adv_participation_preview import (
    ASSET_IDENTIFIER,
    SIGNAL_UID,
    build_signal_frame,
    load_observed_inputs,
    parse_target,
    parse_utc_timestamp,
    target_weights,
    transition_summary,
)
from msm_portfolios.rebalance_strategy import TrailingAverageDailyVolumeParticipation
from tests.support.rebalance import PublishedTable


def test_preview_parses_timezone_aware_targets_and_signal_frame() -> None:
    signal_time = parse_utc_timestamp("2026-01-05T09:25:00-05:00")
    weights = target_weights([parse_target("BTC-USD=0.60"), parse_target("ETH-USD=0.40")])

    frame = build_signal_frame(signal_time=signal_time, weights=weights)

    assert signal_time == pd.Timestamp("2026-01-05T14:25:00Z")
    assert frame.index.names == ["time_index", ASSET_IDENTIFIER]
    assert frame["signal_weight"].tolist() == [0.60, 0.40]
    assert frame["signal_uid"].unique().tolist() == [SIGNAL_UID]


@pytest.mark.parametrize("value", ["BTC-USD", "=0.5", "BTC-USD=nan"])
def test_preview_rejects_invalid_targets(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_target(value)


def test_preview_rejects_duplicate_assets_and_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="Duplicate target asset"):
        target_weights([("BTC-USD", 0.5), ("BTC-USD", 0.5)])
    with pytest.raises(argparse.ArgumentTypeError, match="timezone"):
        parse_utc_timestamp("2026-01-05T09:30:00")


def test_preview_reads_only_bounded_target_asset_inputs() -> None:
    """The daily history from 60 days back; the bars of the window, and each asset's
    last bar before it, which sizes an order whose first bar opens the window (#90)."""
    rows = [
        ("2026-01-02T21:00:00Z", asset, 100.0, 1_000.0)
        for asset in ("BTC-USD", "ETH-USD", "SOL-USD")
    ] + [
        ("2025-10-01T21:00:00Z", "BTC-USD", 100.0, 1_000.0),
        ("2026-01-05T14:00:00Z", "BTC-USD", 100.0, 1_000.0),
        ("2026-01-05T14:30:00Z", "BTC-USD", 100.0, 1_000.0),
        ("2026-01-05T15:00:00Z", "ETH-USD", 100.0, 1_000.0),
        ("2026-01-05T22:00:00Z", "BTC-USD", 100.0, 1_000.0),
    ]
    frame = pd.DataFrame(rows, columns=["time_index", ASSET_IDENTIFIER, "close", "volume"])
    frame["vwap"] = frame["close"]
    index = ["time_index", ASSET_IDENTIFIER]
    strategy = TrailingAverageDailyVolumeParticipation(
        daily_liquidity_instance=PublishedTable.build("daily", frame, index=index),
        execution_bars_instance=PublishedTable.build("bars", frame, index=index),
        history_lookback_days=60,
    )
    start = pd.Timestamp("2026-01-05T14:30:00Z")
    end = pd.Timestamp("2026-01-05T21:00:00Z")

    result = load_observed_inputs(
        strategy,
        start=start,
        end=end,
        asset_identifiers=["BTC-USD", "ETH-USD"],
    )

    assert set(result) == {"daily_liquidity", "execution_bars"}
    read = {
        name: sorted(
            (stamp.isoformat(), asset)
            for stamp, asset in frame_read.index.to_list()
        )
        for name, frame_read in result.items()
    }
    assert read["daily_liquidity"] == [
        ("2026-01-02T21:00:00+00:00", "BTC-USD"),
        ("2026-01-02T21:00:00+00:00", "ETH-USD"),
        ("2026-01-05T14:00:00+00:00", "BTC-USD"),
        ("2026-01-05T14:30:00+00:00", "BTC-USD"),
        ("2026-01-05T15:00:00+00:00", "ETH-USD"),
    ]
    assert read["execution_bars"] == [
        ("2026-01-02T21:00:00+00:00", "ETH-USD"),
        ("2026-01-05T14:00:00+00:00", "BTC-USD"),
        ("2026-01-05T14:30:00+00:00", "BTC-USD"),
        ("2026-01-05T15:00:00+00:00", "ETH-USD"),
    ]


def test_preview_summary_exposes_capacity_and_execution_facts() -> None:
    transitions = pd.DataFrame(
        [
            {
                "time_index": pd.Timestamp("2026-01-05T15:00:00Z"),
                ASSET_IDENTIFIER: "BTC-USD",
                "execution_status": "partial",
                "execution_price": 50_000.0,
                "executed_quantity": 1.0,
                "executed_notional": 50_000.0,
                "weight_before": 0.0,
                "weight_after": 0.05,
                "remaining_weight_delta": 0.55,
                "strategy_state": json.dumps(
                    {
                        "schema_version": 2,
                        "bar": {
                            "history_observations": 20,
                            "trailing_average_daily_notional": 10_000_000.0,
                            "daily_notional_limit": 500_000.0,
                            "daily_notional_consumed": 50_000.0,
                            "daily_notional_remaining": 450_000.0,
                        },
                    }
                ),
            }
        ]
    )
    strategy = SimpleNamespace(
        parse_strategy_state=lambda row: json.loads(row["strategy_state"]),
    )

    summary = transition_summary(  # type: ignore[arg-type]
        strategy, transitions, initial_nav=50_000_000.0
    )

    assert summary.iloc[0]["execution_price"] == 50_000.0
    # The book's unit is the initial NAV: 1 share of the book is 50,000,000 of the asset.
    assert summary.iloc[0]["quantity"] == 50_000_000.0
    assert summary.iloc[0]["history_observations"] == 20
    assert summary.iloc[0]["daily_notional_remaining"] == 450_000.0
