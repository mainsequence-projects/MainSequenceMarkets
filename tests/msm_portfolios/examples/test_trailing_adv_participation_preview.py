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
    class Source:
        def __init__(self) -> None:
            self.queries: list[dict] = []

        def get_df_between_dates(self, **kwargs) -> pd.DataFrame:
            self.queries.append(kwargs)
            return pd.DataFrame()

    daily = Source()
    execution = Source()

    class Strategy:
        @staticmethod
        def declared_dependencies() -> dict:
            return {"daily_liquidity": daily, "execution_bars": execution}

        @staticmethod
        def required_input_contract() -> dict:
            contract = SimpleNamespace(asset_scoped=True)
            return {"daily_liquidity": contract, "execution_bars": contract}

        @staticmethod
        def dependency_window(name, start, end):
            if name == "daily_liquidity":
                start = pd.Timestamp(start) - pd.Timedelta(days=60)
            return pd.Timestamp(start).to_pydatetime(), pd.Timestamp(end).to_pydatetime()

    start = pd.Timestamp("2026-01-05T14:30:00Z")
    end = pd.Timestamp("2026-01-05T21:00:00Z")
    result = load_observed_inputs(
        Strategy(),  # type: ignore[arg-type]
        start=start,
        end=end,
        asset_identifiers=["BTC-USD", "ETH-USD"],
    )

    assert set(result) == {"daily_liquidity", "execution_bars"}
    assert daily.queries[0]["start_date"] == (start - pd.Timedelta(days=60)).to_pydatetime()
    assert execution.queries[0]["start_date"] == start.to_pydatetime()
    for query in (daily.queries[0], execution.queries[0]):
        assert query["end_date"] == end.to_pydatetime()
        assert query["dimension_filters"] == {
            ASSET_IDENTIFIER: ["BTC-USD", "ETH-USD"]
        }


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
                        "schema_version": 1,
                        "history_observations": 20,
                        "trailing_average_daily_notional": 10_000_000.0,
                        "daily_notional_limit": 500_000.0,
                        "daily_notional_consumed": 50_000.0,
                        "daily_notional_remaining": 450_000.0,
                    }
                ),
            }
        ]
    )
    strategy = SimpleNamespace(
        parse_strategy_state=lambda row: json.loads(row["strategy_state"])
    )

    summary = transition_summary(strategy, transitions)  # type: ignore[arg-type]

    assert summary.iloc[0]["execution_price"] == 50_000.0
    assert summary.iloc[0]["executed_quantity"] == 1.0
    assert summary.iloc[0]["history_observations"] == 20
    assert summary.iloc[0]["daily_notional_remaining"] == 450_000.0
