"""Fixed-income spread analytics built on cross-asset spread primitives.

This module adds fixed-income interpretation such as DV01-neutral hedge ratios,
carry, roll-down, and downside aggregation. It still operates on caller-supplied
series and metrics only; it does not resolve curves, query portfolios, read
pricing DataNodes, or mutate submitted instruments.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import pandas as pd

from .base import (
    NumericSeriesInput,
    PairSpreadMetrics,
    SpreadSeries,
    build_pair_history_frame,
    build_spread_series,
    pair_spread_metrics,
)

_ZERO_TOLERANCE = 1e-12


@dataclass(frozen=True)
class FixedIncomeLegMetrics:
    """Fixed-income metrics for one spread leg.

    `dv01` is expressed in currency value per one basis point. Carry,
    roll-down, downside, and market value use caller-defined currency units.
    The model is an in-memory input/output record and is not persisted.
    """

    name: str
    dv01: float
    market_value: float | None = None
    carry: float | None = None
    roll_down: float | None = None
    downside: float | None = None
    yield_value: float | None = None
    z_spread_decimal: float | None = None
    metadata_json: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FixedIncomeSpreadMetrics:
    """Fixed-income spread result with generic pair metrics and FI overlays.

    `hedge_ratio` is the multiplier subtracted from the hedge leg in
    `base - hedge_ratio * hedge` spread construction. `dv01_hedge_ratio` is the
    DV01-neutral ratio implied by the submitted leg DV01 values. `net_dv01`,
    `carry`, `roll_down`, and `downside` are combined as
    `base_metric - hedge_ratio * hedge_metric`.
    """

    spread_name: str
    spread: SpreadSeries
    pair_metrics: PairSpreadMetrics
    base_leg: FixedIncomeLegMetrics
    hedge_leg: FixedIncomeLegMetrics
    hedge_ratio: float
    dv01_hedge_ratio: float
    net_dv01: float
    carry: float | None
    roll_down: float | None
    downside: float | None


def dv01_hedge_ratio(base_dv01: float, hedge_dv01: float) -> float:
    """Return the hedge-leg multiplier that neutralizes base-leg DV01.

    DV01 values are currency value per one basis point. The returned ratio is
    `base_dv01 / hedge_dv01`, suitable for spread and metric construction of
    the form `base - ratio * hedge`.

    Raises
    ------
    ValueError
        If either DV01 is not finite or `hedge_dv01` is zero.
    """

    base = _finite_float(base_dv01, field_name="base_dv01")
    hedge = _finite_float(hedge_dv01, field_name="hedge_dv01")
    if abs(hedge) <= _ZERO_TOLERANCE:
        raise ValueError("hedge_dv01 must be non-zero")
    return float(base / hedge)


def fixed_income_spread_metrics(
    base_values: NumericSeriesInput,
    hedge_values: NumericSeriesInput,
    *,
    base_dv01: float,
    hedge_dv01: float,
    hedge_ratio: float | None = None,
    spread_name: str = "fixed_income_spread",
    base_name: str = "base",
    hedge_name: str = "hedge",
    base_carry: float | None = None,
    hedge_carry: float | None = None,
    base_roll_down: float | None = None,
    hedge_roll_down: float | None = None,
    base_downside: float | None = None,
    hedge_downside: float | None = None,
    base_yield: float | None = None,
    hedge_yield: float | None = None,
    base_z_spread_decimal: float | None = None,
    hedge_z_spread_decimal: float | None = None,
    metadata_json: Mapping[str, object] | None = None,
) -> FixedIncomeSpreadMetrics:
    """Return fixed-income spread metrics from supplied leg histories.

    The function is pure-data: callers supply historical values plus already
    computed leg-level DV01/carry/roll/downside metrics. No curves, pricing
    contexts, portfolio rows, or backend data are resolved here.
    """

    neutral_ratio = dv01_hedge_ratio(base_dv01, hedge_dv01)
    ratio = neutral_ratio if hedge_ratio is None else _finite_float(hedge_ratio, "hedge_ratio")
    base_dv01 = _finite_float(base_dv01, "base_dv01")
    hedge_dv01 = _finite_float(hedge_dv01, "hedge_dv01")

    frame = build_pair_history_frame(
        base_values,
        hedge_values,
        hedge_ratio=ratio,
        leg_a_name=base_name,
        leg_b_name=hedge_name,
    )
    spread = build_spread_series(
        frame["leg_a"],
        frame["leg_b"],
        hedge_ratio=ratio,
        name=spread_name,
        leg_a_name=base_name,
        leg_b_name=hedge_name,
        metadata_json=metadata_json,
    )
    pair_metrics = pair_spread_metrics(
        frame["leg_a"],
        frame["leg_b"],
        hedge_ratio=ratio,
        spread_name=spread_name,
        leg_a_name=base_name,
        leg_b_name=hedge_name,
    )
    base_leg = FixedIncomeLegMetrics(
        name=base_name,
        dv01=base_dv01,
        market_value=_latest_value(frame["leg_a"]),
        carry=_optional_finite(base_carry, "base_carry"),
        roll_down=_optional_finite(base_roll_down, "base_roll_down"),
        downside=_optional_finite(base_downside, "base_downside"),
        yield_value=_optional_finite(base_yield, "base_yield"),
        z_spread_decimal=_optional_finite(base_z_spread_decimal, "base_z_spread_decimal"),
        metadata_json=dict(metadata_json or {}),
    )
    hedge_leg = FixedIncomeLegMetrics(
        name=hedge_name,
        dv01=hedge_dv01,
        market_value=_latest_value(frame["leg_b"]),
        carry=_optional_finite(hedge_carry, "hedge_carry"),
        roll_down=_optional_finite(hedge_roll_down, "hedge_roll_down"),
        downside=_optional_finite(hedge_downside, "hedge_downside"),
        yield_value=_optional_finite(hedge_yield, "hedge_yield"),
        z_spread_decimal=_optional_finite(hedge_z_spread_decimal, "hedge_z_spread_decimal"),
        metadata_json=dict(metadata_json or {}),
    )

    return FixedIncomeSpreadMetrics(
        spread_name=spread_name,
        spread=spread,
        pair_metrics=pair_metrics,
        base_leg=base_leg,
        hedge_leg=hedge_leg,
        hedge_ratio=ratio,
        dv01_hedge_ratio=neutral_ratio,
        net_dv01=base_dv01 - ratio * hedge_dv01,
        carry=_combine_optional(base_leg.carry, hedge_leg.carry, ratio),
        roll_down=_combine_optional(base_leg.roll_down, hedge_leg.roll_down, ratio),
        downside=_combine_optional(base_leg.downside, hedge_leg.downside, ratio),
    )


def _finite_float(value: float, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _optional_finite(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, field_name)


def _combine_optional(base: float | None, hedge: float | None, ratio: float) -> float | None:
    if base is None or hedge is None:
        return None
    return float(base - ratio * hedge)


def _latest_value(series: pd.Series) -> float | None:
    clean = pd.to_numeric(series, errors="coerce").replace([float("inf"), float("-inf")], pd.NA)
    clean = clean.dropna()
    if clean.empty:
        return None
    return float(clean.iloc[-1])
