from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from msm_pricing.analytics.spreads import (  # noqa: E402
    fixed_income_spread_metrics,
    ornstein_uhlenbeck_forecast_cone,
    spread_zscore_matrix,
)


def build_fixed_income_spread_analytics_example() -> dict[str, Any]:
    dates = pd.date_range("2026-01-01", periods=10, freq="D", tz="UTC")
    hedge_ratio = 1.25
    hedge_marks = pd.Series(
        [80.0, 80.08, 80.16, 80.24, 80.32, 80.40, 80.48, 80.56, 80.64, 80.72],
        index=dates,
    )

    spread_level = 0.75
    spread_marks: list[float] = []
    for _ in dates:
        spread_level = 0.30 + 0.55 * (spread_level - 0.30)
        spread_marks.append(spread_level)

    base_marks = pd.Series(
        [spread + hedge_ratio * hedge for spread, hedge in zip(spread_marks, hedge_marks)],
        index=dates,
    )
    metrics = fixed_income_spread_metrics(
        base_values=base_marks,
        hedge_values=hedge_marks,
        base_dv01=100_000.0,
        hedge_dv01=80_000.0,
        base_carry=12_500.0,
        hedge_carry=8_000.0,
        base_roll_down=9_000.0,
        hedge_roll_down=6_000.0,
        base_downside=-35_000.0,
        hedge_downside=-25_000.0,
        spread_name="asset_vs_benchmark",
        base_name="asset_bond",
        hedge_name="benchmark_bond",
    )
    zscores = spread_zscore_matrix({"asset_vs_benchmark": metrics.spread.values})
    cone = ornstein_uhlenbeck_forecast_cone(metrics.spread.values, horizon=3)

    return {
        "spread_name": metrics.spread_name,
        "hedge_ratio": metrics.hedge_ratio,
        "net_dv01": metrics.net_dv01,
        "latest_spread": metrics.pair_metrics.latest_spread,
        "z_score": metrics.pair_metrics.z_score,
        "carry": metrics.carry,
        "roll_down": metrics.roll_down,
        "downside": metrics.downside,
        "zscore_matrix": zscores.reset_index().to_dict(orient="records"),
        "forecast_cone": cone.reset_index().to_dict(orient="records"),
    }


if __name__ == "__main__":
    print(json.dumps(build_fixed_income_spread_analytics_example(), default=str, indent=2))
