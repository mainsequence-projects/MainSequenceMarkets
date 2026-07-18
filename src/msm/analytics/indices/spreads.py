"""Canonical core cross-asset spread analytics primitives.

This module is deliberately pure-data. It accepts caller-supplied pandas
objects or numeric sequences, aligns observations in memory, and returns
dataclasses or DataFrames. It does not read Main Sequence backend rows, resolve
assets, inspect pricing instruments, or mutate submitted data.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib.util import find_spec
from typing import Literal

import numpy as np
import pandas as pd

NumericSeriesInput = pd.Series | Sequence[float]
HedgeRatioMethod = Literal["price_ols", "return_ols"]

_ZERO_TOLERANCE = 1e-12


@dataclass(frozen=True)
class SpreadSeries:
    """Aligned spread time series built from two caller-supplied legs.

    `values` is computed as `leg_a - hedge_ratio * leg_b`. Inputs are copied
    into a new pandas Series, so submitted Series or arrays are not mutated.
    The helper makes no assumption about asset class, currency, vendor source,
    curve identity, or portfolio ownership.
    """

    name: str
    values: pd.Series
    leg_a_name: str
    leg_b_name: str
    hedge_ratio: float
    metadata_json: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PairSpreadMetrics:
    """Statistical summary for a two-leg spread.

    Values are expressed in the same units as the supplied spread series.
    `z_score` is the latest observation's standard score against the full
    aligned history. `half_life_periods` is estimated from an AR(1)-style
    regression and is `None` when the history does not show mean reversion.
    """

    spread_name: str
    latest_spread: float | None
    mean: float | None
    standard_deviation: float | None
    z_score: float | None
    observation_count: int
    half_life_periods: float | None
    hedge_ratio: float


def require_optional_dependency(module_name: str, *, feature: str) -> None:
    """Raise a clear error when a dependency-heavy optional feature is missing.

    Parameters
    ----------
    module_name:
        Importable Python module required by the optional feature.
    feature:
        Human-readable feature name shown in the error message.

    Raises
    ------
    ImportError
        If `module_name` is not importable in the current environment.
    """

    if find_spec(module_name) is not None:
        return

    raise ImportError(
        f"{feature} requires optional dependency {module_name!r}. Install that "
        "package in the runtime environment before calling the optional analytics feature."
    )


def build_pair_history_frame(
    leg_a: NumericSeriesInput,
    leg_b: NumericSeriesInput,
    *,
    hedge_ratio: float = 1.0,
    leg_a_name: str = "leg_a",
    leg_b_name: str = "leg_b",
) -> pd.DataFrame:
    """Return an aligned two-leg history with a computed spread column.

    The returned frame has stable columns `leg_a`, `leg_b`, and `spread`.
    The spread is `leg_a - hedge_ratio * leg_b`. Observations are aligned by
    pandas index when Series are supplied and by positional index otherwise.
    Missing or non-finite rows are dropped from the returned copy.

    Raises
    ------
    ValueError
        If `hedge_ratio` is not finite or there are no overlapping finite
        observations after alignment.
    """

    hedge_ratio = _finite_float(hedge_ratio, field_name="hedge_ratio")
    aligned = _aligned_pair(
        leg_a,
        leg_b,
        leg_a_name=leg_a_name,
        leg_b_name=leg_b_name,
    )
    frame = pd.DataFrame(
        {
            "leg_a": aligned[leg_a_name].to_numpy(dtype=float),
            "leg_b": aligned[leg_b_name].to_numpy(dtype=float),
        },
        index=aligned.index.copy(),
    )
    frame["spread"] = frame["leg_a"] - hedge_ratio * frame["leg_b"]
    frame.attrs["leg_a_name"] = leg_a_name
    frame.attrs["leg_b_name"] = leg_b_name
    frame.attrs["hedge_ratio"] = hedge_ratio
    return frame


def build_spread_series(
    leg_a: NumericSeriesInput,
    leg_b: NumericSeriesInput,
    *,
    hedge_ratio: float = 1.0,
    name: str = "spread",
    leg_a_name: str = "leg_a",
    leg_b_name: str = "leg_b",
    metadata_json: Mapping[str, object] | None = None,
) -> SpreadSeries:
    """Build a copy-based spread series from two aligned numeric legs.

    The output values are `leg_a - hedge_ratio * leg_b`. Submitted Series and
    sequences are not mutated. The helper intentionally does not know whether
    the legs represent bonds, equities, indexes, commodities, options, or
    synthetic strategy marks.
    """

    frame = build_pair_history_frame(
        leg_a,
        leg_b,
        hedge_ratio=hedge_ratio,
        leg_a_name=leg_a_name,
        leg_b_name=leg_b_name,
    )
    values = frame["spread"].copy()
    values.name = name
    return SpreadSeries(
        name=name,
        values=values,
        leg_a_name=leg_a_name,
        leg_b_name=leg_b_name,
        hedge_ratio=float(hedge_ratio),
        metadata_json=dict(metadata_json or {}),
    )


def spread_zscore(
    spread: NumericSeriesInput,
    *,
    ddof: int = 1,
    min_observations: int = 2,
) -> float | None:
    """Return the latest z-score for a spread series.

    Units match the submitted spread series. `None` is returned when there are
    too few finite observations or the historical standard deviation is zero.
    """

    clean = _clean_series(spread, name="spread")
    if clean.size < min_observations:
        return None

    standard_deviation = float(clean.std(ddof=ddof))
    if not math.isfinite(standard_deviation) or abs(standard_deviation) <= _ZERO_TOLERANCE:
        return None

    return float((clean.iloc[-1] - clean.mean()) / standard_deviation)


def rolling_spread_zscore(
    spread: NumericSeriesInput,
    *,
    window: int,
    min_periods: int | None = None,
    ddof: int = 1,
) -> pd.Series:
    """Return rolling z-scores for a spread series.

    The returned Series is a new object with the submitted spread's index.
    Missing or non-finite input observations propagate as missing output values.
    """

    if window <= 0:
        raise ValueError("window must be a positive integer")
    if min_periods is not None and min_periods <= 0:
        raise ValueError("min_periods must be positive when provided")

    series = _numeric_series(spread, name="spread").replace([np.inf, -np.inf], np.nan)
    rolling = series.rolling(window=window, min_periods=min_periods or window)
    mean = rolling.mean()
    standard_deviation = rolling.std(ddof=ddof)
    z_scores = (series - mean) / standard_deviation
    return z_scores.where(standard_deviation.abs() > _ZERO_TOLERANCE)


def spread_zscore_matrix(
    spreads: Mapping[str, NumericSeriesInput] | pd.DataFrame,
    *,
    ddof: int = 1,
    min_observations: int = 2,
) -> pd.DataFrame:
    """Return latest z-score metrics for multiple spread series.

    The result is indexed by spread name with columns `latest_spread`, `mean`,
    `standard_deviation`, `z_score`, and `observation_count`. This function is
    cross-asset: callers decide whether each spread represents an equity pair,
    yield spread, commodity calendar spread, volatility spread, or another
    strategy mark.
    """

    if isinstance(spreads, pd.DataFrame):
        items = ((str(column), spreads[column]) for column in spreads.columns)
    else:
        items = spreads.items()

    records: list[dict[str, float | int | str | None]] = []
    for name, values in items:
        clean = _clean_series(values, name=str(name))
        latest_spread: float | None = None
        mean: float | None = None
        standard_deviation: float | None = None
        z_score: float | None = None
        if clean.size > 0:
            latest_spread = float(clean.iloc[-1])
            mean = float(clean.mean())
        if clean.size >= min_observations:
            computed_std = float(clean.std(ddof=ddof))
            if math.isfinite(computed_std) and abs(computed_std) > _ZERO_TOLERANCE:
                standard_deviation = computed_std
                z_score = float((clean.iloc[-1] - clean.mean()) / computed_std)

        records.append(
            {
                "spread_name": str(name),
                "latest_spread": latest_spread,
                "mean": mean,
                "standard_deviation": standard_deviation,
                "z_score": z_score,
                "observation_count": int(clean.size),
            }
        )

    if not records:
        return pd.DataFrame(
            columns=[
                "latest_spread",
                "mean",
                "standard_deviation",
                "z_score",
                "observation_count",
            ]
        ).rename_axis("spread_name")

    return pd.DataFrame.from_records(records).set_index("spread_name")


def estimate_hedge_ratio(
    leg_a: NumericSeriesInput,
    leg_b: NumericSeriesInput,
    *,
    method: HedgeRatioMethod = "price_ols",
    include_intercept: bool = True,
) -> float:
    """Estimate the hedge ratio that maps leg B onto leg A.

    `price_ols` regresses aligned levels. `return_ols` regresses aligned
    percentage changes after pairwise alignment. The returned beta is suitable
    for `leg_a - beta * leg_b` spread construction. Inputs are copied and not
    mutated.

    Raises
    ------
    ValueError
        If the method is unsupported or the hedge leg has no usable variation.
    """

    aligned = _aligned_pair(leg_a, leg_b, leg_a_name="leg_a", leg_b_name="leg_b")
    if method == "price_ols":
        regression_frame = aligned
    elif method == "return_ols":
        regression_frame = aligned.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    else:
        raise ValueError(f"unsupported hedge-ratio method: {method!r}")

    if regression_frame.shape[0] < 2:
        raise ValueError("at least two aligned observations are required to estimate a hedge ratio")

    x = regression_frame["leg_b"].to_numpy(dtype=float)
    y = regression_frame["leg_a"].to_numpy(dtype=float)
    if float(np.std(x)) <= _ZERO_TOLERANCE:
        raise ValueError("leg_b has no usable variation for hedge-ratio estimation")

    if include_intercept:
        design = np.column_stack([np.ones_like(x), x])
        coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
        beta = coefficients[1]
    else:
        denominator = float(np.dot(x, x))
        if abs(denominator) <= _ZERO_TOLERANCE:
            raise ValueError("leg_b has no usable variation for hedge-ratio estimation")
        beta = float(np.dot(x, y) / denominator)

    beta = float(beta)
    if not math.isfinite(beta):
        raise ValueError("estimated hedge ratio is not finite")
    return beta


def pair_spread_metrics(
    leg_a: NumericSeriesInput,
    leg_b: NumericSeriesInput,
    *,
    hedge_ratio: float | None = None,
    hedge_ratio_method: HedgeRatioMethod = "price_ols",
    spread_name: str = "spread",
    leg_a_name: str = "leg_a",
    leg_b_name: str = "leg_b",
    ddof: int = 1,
) -> PairSpreadMetrics:
    """Return cross-asset pair metrics for an aligned two-leg spread.

    When `hedge_ratio` is omitted, the ratio is estimated from the submitted
    history. No backend data is resolved and no instrument state is modified.
    """

    ratio = (
        estimate_hedge_ratio(leg_a, leg_b, method=hedge_ratio_method)
        if hedge_ratio is None
        else _finite_float(hedge_ratio, field_name="hedge_ratio")
    )
    spread = build_spread_series(
        leg_a,
        leg_b,
        hedge_ratio=ratio,
        name=spread_name,
        leg_a_name=leg_a_name,
        leg_b_name=leg_b_name,
    )
    clean = _clean_series(spread.values, name=spread.name)

    latest_spread: float | None = None
    mean: float | None = None
    standard_deviation: float | None = None
    if clean.size > 0:
        latest_spread = float(clean.iloc[-1])
        mean = float(clean.mean())
    if clean.size >= 2:
        computed_std = float(clean.std(ddof=ddof))
        if math.isfinite(computed_std) and abs(computed_std) > _ZERO_TOLERANCE:
            standard_deviation = computed_std

    z_score = spread_zscore(clean, ddof=ddof)
    return PairSpreadMetrics(
        spread_name=spread_name,
        latest_spread=latest_spread,
        mean=mean,
        standard_deviation=standard_deviation,
        z_score=z_score,
        observation_count=int(clean.size),
        half_life_periods=_estimate_half_life(clean),
        hedge_ratio=float(ratio),
    )


def ornstein_uhlenbeck_forecast_cone(
    spread: NumericSeriesInput,
    *,
    horizon: int,
    std_multipliers: Sequence[float] = (1.0, 2.0),
) -> pd.DataFrame:
    """Build a deterministic OU-style forecast cone from a spread history.

    The helper estimates a univariate AR(1) approximation to a mean-reverting
    process and returns expected spread levels plus standard-deviation bands for
    horizons `1..horizon`. Output units match the submitted spread series.

    This implementation has no heavy optional dependency. More advanced
    volatility models should call `require_optional_dependency(...)` in their
    own helper before importing dependency-heavy packages.

    Raises
    ------
    ValueError
        If fewer than three finite observations are supplied, `horizon` is not
        positive, or the fitted process is not mean reverting.
    """

    if horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    clean = _clean_series(spread, name="spread")
    if clean.size < 3:
        raise ValueError("at least three finite spread observations are required")

    multipliers = tuple(
        _finite_float(value, field_name="std_multipliers") for value in std_multipliers
    )
    if not multipliers:
        raise ValueError("std_multipliers must include at least one value")

    values = clean.to_numpy(dtype=float)
    x = values[:-1]
    y = values[1:]
    design = np.column_stack([np.ones_like(x), x])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    intercept = float(coefficients[0])
    phi = float(coefficients[1])
    if not math.isfinite(phi) or abs(phi) >= 1.0:
        raise ValueError("fitted process is not mean reverting")

    residuals = y - (intercept + phi * x)
    innovation_std = float(np.std(residuals, ddof=1)) if residuals.size > 1 else 0.0
    if not math.isfinite(innovation_std):
        raise ValueError("estimated innovation standard deviation is not finite")

    long_run_mean = intercept / (1.0 - phi)
    latest = float(values[-1])

    records: list[dict[str, float | int]] = []
    for step in range(1, horizon + 1):
        phi_power = phi**step
        expected = long_run_mean + phi_power * (latest - long_run_mean)
        variance = innovation_std**2 * (1.0 - phi ** (2 * step)) / (1.0 - phi**2)
        standard_deviation = math.sqrt(max(variance, 0.0))
        record: dict[str, float | int] = {
            "horizon": step,
            "expected": float(expected),
            "standard_deviation": float(standard_deviation),
        }
        for multiplier in multipliers:
            label = _std_multiplier_label(multiplier)
            record[f"lower_{label}"] = float(expected - multiplier * standard_deviation)
            record[f"upper_{label}"] = float(expected + multiplier * standard_deviation)
        records.append(record)

    return pd.DataFrame.from_records(records).set_index("horizon")


def _numeric_series(values: NumericSeriesInput, *, name: str) -> pd.Series:
    if isinstance(values, pd.Series):
        series = values.copy(deep=True)
    else:
        series = pd.Series(list(values), copy=True)
    series = pd.to_numeric(series, errors="coerce")
    series.name = name
    return series.astype(float)


def _clean_series(values: NumericSeriesInput, *, name: str) -> pd.Series:
    series = _numeric_series(values, name=name)
    return series.replace([np.inf, -np.inf], np.nan).dropna()


def _aligned_pair(
    leg_a: NumericSeriesInput,
    leg_b: NumericSeriesInput,
    *,
    leg_a_name: str,
    leg_b_name: str,
) -> pd.DataFrame:
    left = _numeric_series(leg_a, name=leg_a_name)
    right = _numeric_series(leg_b, name=leg_b_name)
    frame = pd.concat([left, right], axis=1, join="inner")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    if frame.empty:
        raise ValueError("legs have no overlapping finite observations")
    return frame


def _finite_float(value: float, *, field_name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _estimate_half_life(spread: pd.Series) -> float | None:
    clean = _clean_series(spread, name="spread")
    if clean.size < 3:
        return None

    values = clean.to_numpy(dtype=float)
    lagged = values[:-1]
    delta = np.diff(values)
    if float(np.std(lagged)) <= _ZERO_TOLERANCE:
        return None

    design = np.column_stack([np.ones_like(lagged), lagged])
    coefficients, *_ = np.linalg.lstsq(design, delta, rcond=None)
    beta = float(coefficients[1])
    if not math.isfinite(beta) or beta >= -_ZERO_TOLERANCE:
        return None

    return float(-math.log(2.0) / beta)


def _std_multiplier_label(multiplier: float) -> str:
    if float(multiplier).is_integer():
        return f"{int(multiplier)}std"
    return f"{str(multiplier).replace('.', '_')}std"


__all__ = [
    "HedgeRatioMethod",
    "NumericSeriesInput",
    "PairSpreadMetrics",
    "SpreadSeries",
    "build_pair_history_frame",
    "build_spread_series",
    "estimate_hedge_ratio",
    "ornstein_uhlenbeck_forecast_cone",
    "pair_spread_metrics",
    "require_optional_dependency",
    "rolling_spread_zscore",
    "spread_zscore",
    "spread_zscore_matrix",
]
