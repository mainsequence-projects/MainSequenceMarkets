from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from msm.analytics.indices.contracts import (
    IndexCalculationDefinition,
    IndexCalculationLeg,
    IndexCalculationResult,
    validate_definition_hash,
)
from msm.analytics.indices.registries import (
    ALIGNMENT_REGISTRY,
    CALCULATION_REGISTRY,
    COEFFICIENT_REGISTRY,
    MISSING_DATA_REGISTRY,
    REBALANCE_REGISTRY,
    TRANSFORM_REGISTRY,
    AsOfParameters,
    ChainedReturnParameters,
    EventRebalanceParameters,
    ForwardFillParameters,
    LaggedCoefficientParameters,
    NoParameters,
    RebaseParameters,
    RollingCoefficientParameters,
    ScheduleParameters,
    SelfFinancingParameters,
    UNIT_REGISTRY,
)


class IndexCalculationError(ValueError):
    """Base structured calculation-contract failure."""


class IncompleteObservationsError(IndexCalculationError):
    """Raised when the methodology requires complete observations and they are absent."""


class LookAheadError(IndexCalculationError):
    """Raised when a coefficient would be effective before its source observation."""


def _datetime_index(values: Sequence[Any] | pd.Index) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(values, utc=True), dtype="datetime64[ns, UTC]")
    return index.sort_values().drop_duplicates()


def _observation_series(
    value: pd.Series | pd.DataFrame | Sequence[float],
    *,
    leg: IndexCalculationLeg,
) -> pd.Series:
    if isinstance(value, pd.DataFrame):
        if leg.observable_code not in value.columns:
            raise IndexCalculationError(
                f"leg {leg.leg_key!r} source is missing observable {leg.observable_code!r}"
            )
        series = value[leg.observable_code]
    elif isinstance(value, pd.Series):
        series = value
    else:
        raise TypeError(f"leg {leg.leg_key!r} observations must be a pandas Series or DataFrame")
    if not isinstance(series.index, pd.DatetimeIndex):
        raise IndexCalculationError(f"leg {leg.leg_key!r} observations require a DatetimeIndex")
    index = pd.DatetimeIndex(
        pd.to_datetime(series.index, utc=True),
        dtype="datetime64[ns, UTC]",
    )
    result = pd.Series(
        pd.to_numeric(series, errors="coerce").to_numpy(dtype=float),
        index=index,
        name=leg.leg_key,
    )
    if result.index.has_duplicates:
        raise IndexCalculationError(f"leg {leg.leg_key!r} contains duplicate timestamps")
    return result.replace([np.inf, -np.inf], np.nan).sort_index()


def _identity(values: pd.Series, _parameters: NoParameters) -> pd.Series:
    return values.copy()


def _rebase(values: pd.Series, parameters: RebaseParameters) -> pd.Series:
    first = values.dropna()
    if first.empty or math.isclose(float(first.iloc[0]), 0.0):
        raise IndexCalculationError("rebase requires a finite non-zero first observation")
    return values / float(first.iloc[0]) * parameters.base_value


def _log(values: pd.Series, _parameters: NoParameters) -> pd.Series:
    if (values.dropna() <= 0).any():
        raise IndexCalculationError("log transform requires strictly positive observations")
    return np.log(values)


def _simple_return(values: pd.Series, _parameters: NoParameters) -> pd.Series:
    return values.pct_change(fill_method=None)


def _log_return(values: pd.Series, _parameters: NoParameters) -> pd.Series:
    return _log(values, NoParameters()).diff()


def _linear_combination(
    values: pd.DataFrame,
    coefficients: pd.DataFrame,
    _parameters: NoParameters,
) -> pd.Series:
    return (values * coefficients).sum(axis=1, min_count=len(values.columns))


def _ratio(
    values: pd.DataFrame,
    coefficients: pd.DataFrame,
    _parameters: NoParameters,
) -> pd.Series:
    if len(values.columns) != 2:
        raise IndexCalculationError("ratio requires exactly two ordered legs")
    numerator = values.iloc[:, 0] * coefficients.iloc[:, 0]
    denominator = values.iloc[:, 1] * coefficients.iloc[:, 1]
    if (denominator.dropna() == 0).any():
        raise IndexCalculationError("ratio denominator contains zero")
    return numerator / denominator


def _rebased_basket(
    values: pd.DataFrame,
    coefficients: pd.DataFrame,
    parameters: RebaseParameters,
) -> pd.Series:
    rebased = pd.DataFrame(index=values.index)
    for column in values:
        rebased[column] = _rebase(values[column], parameters)
    return (rebased * coefficients).sum(axis=1, min_count=len(values.columns))


def _chained_return(
    values: pd.DataFrame,
    coefficients: pd.DataFrame,
    parameters: ChainedReturnParameters,
) -> pd.Series:
    period_return = (values * coefficients).sum(axis=1, min_count=len(values.columns))
    return parameters.base_value * (1.0 + period_return.fillna(0.0)).cumprod()


def _self_financing(
    values: pd.DataFrame,
    coefficients: pd.DataFrame,
    parameters: SelfFinancingParameters,
) -> pd.Series:
    positions = coefficients.shift(parameters.position_lag)
    price_changes = values.diff()
    pnl = (positions * price_changes).sum(axis=1, min_count=len(values.columns)).fillna(0.0)
    financing = pd.Series(
        parameters.initial_capital * parameters.financing_rate / parameters.periods_per_year,
        index=values.index,
        dtype=float,
    )
    if not financing.empty:
        financing.iloc[0] = 0.0
    turnover = (coefficients.diff().abs() * values).sum(axis=1, min_count=1).fillna(0.0)
    costs = turnover * parameters.transaction_cost_bps / 10_000.0
    level = parameters.initial_capital + (pnl + financing - costs).cumsum()
    return level / parameters.initial_capital * parameters.base_value


def _fixed_coefficient(
    _reference: pd.Series,
    _leg_values: pd.Series,
    _parameter_values: pd.Series | None,
    _parameters: NoParameters,
) -> pd.Series:
    raise IndexCalculationError("fixed coefficients are read from the definition leg")


def _equal_weight_coefficient(
    _reference: pd.Series,
    leg_values: pd.Series,
    _parameter_values: pd.Series | None,
    _parameters: NoParameters,
) -> pd.Series:
    return pd.Series(1.0, index=leg_values.index)


def _rolling_ols_coefficient(
    reference: pd.Series,
    leg_values: pd.Series,
    _parameter_values: pd.Series | None,
    parameters: RollingCoefficientParameters,
    *,
    returns: bool,
) -> pd.Series:
    pair = pd.concat([reference.rename("reference"), leg_values.rename("leg")], axis=1)
    if returns:
        reference_is_return = bool(reference.attrs.get("is_return_observation"))
        leg_is_return = bool(leg_values.attrs.get("is_return_observation"))
        if reference_is_return != leg_is_return:
            raise IndexCalculationError(
                "return OLS requires both legs to use return observations or both to use levels"
            )
        if not reference_is_return:
            pair = pair.pct_change(fill_method=None)
    coefficients = pd.Series(np.nan, index=pair.index, dtype=float)
    for location in range(len(pair)):
        start = max(0, location - parameters.window + 1)
        window = pair.iloc[start : location + 1].dropna()
        if len(window) < parameters.min_observations:
            continue
        x = window["leg"].to_numpy(dtype=float)
        y = window["reference"].to_numpy(dtype=float)
        if float(np.std(x)) <= 1e-12:
            continue
        if parameters.include_intercept:
            design = np.column_stack([np.ones_like(x), x])
            beta = float(np.linalg.lstsq(design, y, rcond=None)[0][1])
        else:
            denominator = float(np.dot(x, x))
            if abs(denominator) <= 1e-12:
                continue
            beta = float(np.dot(x, y) / denominator)
        coefficients.iloc[location] = parameters.sign * beta
    coefficients = coefficients.shift(parameters.lag)
    return _bounded(coefficients, parameters.lower_bound, parameters.upper_bound)


def _price_ols_coefficient(
    reference: pd.Series,
    leg_values: pd.Series,
    parameter_values: pd.Series | None,
    parameters: RollingCoefficientParameters,
) -> pd.Series:
    return _rolling_ols_coefficient(
        reference,
        leg_values,
        parameter_values,
        parameters,
        returns=False,
    )


def _return_ols_coefficient(
    reference: pd.Series,
    leg_values: pd.Series,
    parameter_values: pd.Series | None,
    parameters: RollingCoefficientParameters,
) -> pd.Series:
    return _rolling_ols_coefficient(
        reference,
        leg_values,
        parameter_values,
        parameters,
        returns=True,
    )


def _lagged_parameter_coefficient(
    _reference: pd.Series,
    leg_values: pd.Series,
    parameter_values: pd.Series | None,
    parameters: LaggedCoefficientParameters,
) -> pd.Series:
    if parameter_values is None:
        raise IndexCalculationError("dynamic risk coefficient requires caller-supplied risk values")
    values = parameter_values.reindex(leg_values.index).astype(float) * parameters.sign
    return _bounded(
        values.shift(parameters.lag),
        parameters.lower_bound,
        parameters.upper_bound,
    )


def _dv01_neutral_coefficient(
    reference: pd.Series,
    leg_values: pd.Series,
    parameter_values: pd.Series | None,
    parameters: LaggedCoefficientParameters,
) -> pd.Series:
    if parameter_values is None:
        raise IndexCalculationError("dv01_neutral requires caller-supplied hedge DV01 values")
    reference_risk = reference.attrs.get("coefficient_parameter_series")
    if not isinstance(reference_risk, pd.Series):
        raise IndexCalculationError("dv01_neutral requires reference-leg DV01 values")
    ratio = reference_risk.reindex(leg_values.index) / parameter_values.reindex(leg_values.index)
    if (parameter_values.dropna() == 0).any():
        raise IndexCalculationError("dv01_neutral hedge DV01 contains zero")
    return _bounded(
        ratio.astype(float).shift(parameters.lag) * parameters.sign,
        parameters.lower_bound,
        parameters.upper_bound,
    )


def _bounded(values: pd.Series, lower: float | None, upper: float | None) -> pd.Series:
    if lower is not None and upper is not None and lower > upper:
        raise IndexCalculationError("coefficient lower_bound cannot exceed upper_bound")
    return values.clip(lower=lower, upper=upper)


def _register_builtins() -> None:
    if not TRANSFORM_REGISTRY.codes():
        TRANSFORM_REGISTRY.register("identity", _identity)
        TRANSFORM_REGISTRY.register("rebase", _rebase, parameters_model=RebaseParameters)
        TRANSFORM_REGISTRY.register("log", _log)
        TRANSFORM_REGISTRY.register("simple_return", _simple_return)
        TRANSFORM_REGISTRY.register("log_return", _log_return)

    if not CALCULATION_REGISTRY.codes():
        CALCULATION_REGISTRY.register("linear_combination", _linear_combination)
        CALCULATION_REGISTRY.register("ratio", _ratio)
        CALCULATION_REGISTRY.register(
            "rebased_basket", _rebased_basket, parameters_model=RebaseParameters
        )
        CALCULATION_REGISTRY.register(
            "chained_return", _chained_return, parameters_model=ChainedReturnParameters
        )
        CALCULATION_REGISTRY.register(
            "self_financing", _self_financing, parameters_model=SelfFinancingParameters
        )

    if not COEFFICIENT_REGISTRY.codes():
        COEFFICIENT_REGISTRY.register("fixed", _fixed_coefficient)
        COEFFICIENT_REGISTRY.register("equal_weight", _equal_weight_coefficient)
        COEFFICIENT_REGISTRY.register(
            "price_ols", _price_ols_coefficient, parameters_model=RollingCoefficientParameters
        )
        COEFFICIENT_REGISTRY.register(
            "return_ols", _return_ols_coefficient, parameters_model=RollingCoefficientParameters
        )
        COEFFICIENT_REGISTRY.register(
            "beta_neutral", _return_ols_coefficient, parameters_model=RollingCoefficientParameters
        )
        COEFFICIENT_REGISTRY.register(
            "dv01_neutral",
            _dv01_neutral_coefficient,
            parameters_model=LaggedCoefficientParameters,
        )
        COEFFICIENT_REGISTRY.register(
            "delta", _lagged_parameter_coefficient, parameters_model=LaggedCoefficientParameters
        )

    if not ALIGNMENT_REGISTRY.codes():
        ALIGNMENT_REGISTRY.register("inner", "inner")
        ALIGNMENT_REGISTRY.register("asof", "asof", parameters_model=AsOfParameters)
        ALIGNMENT_REGISTRY.register(
            "calendar_aligned", "calendar_aligned", parameters_model=ScheduleParameters
        )
    if not MISSING_DATA_REGISTRY.codes():
        MISSING_DATA_REGISTRY.register("drop", "drop")
        MISSING_DATA_REGISTRY.register("fail", "fail")
        MISSING_DATA_REGISTRY.register(
            "forward_fill", "forward_fill", parameters_model=ForwardFillParameters
        )
    if not REBALANCE_REGISTRY.codes():
        REBALANCE_REGISTRY.register("daily", "daily", parameters_model=ScheduleParameters)
        REBALANCE_REGISTRY.register("weekly", "weekly", parameters_model=ScheduleParameters)
        REBALANCE_REGISTRY.register("monthly", "monthly", parameters_model=ScheduleParameters)
        REBALANCE_REGISTRY.register("quarterly", "quarterly", parameters_model=ScheduleParameters)
        REBALANCE_REGISTRY.register("event", "event", parameters_model=EventRebalanceParameters)


_register_builtins()


def validate_calculation_contract(
    definition: IndexCalculationDefinition,
    legs: Sequence[IndexCalculationLeg],
) -> str:
    if not legs:
        raise IndexCalculationError("a derived-index definition requires at least one leg")
    leg_keys = [leg.leg_key for leg in legs]
    leg_orders = [leg.leg_order for leg in legs]
    if len(set(leg_keys)) != len(leg_keys):
        raise IndexCalculationError("leg_key values must be unique within a definition")
    if len(set(leg_orders)) != len(leg_orders):
        raise IndexCalculationError("leg_order values must be unique within a definition")

    CALCULATION_REGISTRY.validate_parameters(
        definition.calculation_kind,
        definition.calculation_parameters_json,
    )
    ALIGNMENT_REGISTRY.validate_parameters(
        definition.alignment_policy,
        definition.alignment_parameters_json,
    )
    MISSING_DATA_REGISTRY.validate_parameters(
        definition.missing_data_policy,
        definition.missing_data_parameters_json,
    )
    if definition.rebalance_policy is not None:
        REBALANCE_REGISTRY.validate_parameters(
            definition.rebalance_policy,
            definition.rebalance_parameters_json,
        )
    for leg in legs:
        TRANSFORM_REGISTRY.validate_parameters(leg.transform_code, leg.transform_parameters_json)
        COEFFICIENT_REGISTRY.validate_parameters(
            leg.coefficient_method,
            leg.coefficient_parameters_json,
        )
        UNIT_REGISTRY.dimension(leg.input_unit)
    UNIT_REGISTRY.dimension(definition.output_unit)
    return validate_definition_hash(definition, list(legs))


def _align(
    series_by_leg: Mapping[str, pd.Series],
    *,
    policy: str,
    parameters: dict[str, Any] | None,
    calculation_times: Sequence[Any] | pd.DatetimeIndex | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    policy = ALIGNMENT_REGISTRY.get(policy)
    parsed_parameters = ALIGNMENT_REGISTRY.validate_parameters(policy, parameters)

    if calculation_times is not None:
        target = _datetime_index(calculation_times)
    elif policy == "inner":
        target = None
        for series in series_by_leg.values():
            target = series.index if target is None else target.intersection(series.index)
        target = target if target is not None else pd.DatetimeIndex([], tz="UTC")
    else:
        target = _datetime_index(
            sorted({timestamp for series in series_by_leg.values() for timestamp in series.index})
        )

    aligned = pd.DataFrame(index=target)
    source_times = pd.DataFrame(index=target)
    for leg_key, series in series_by_leg.items():
        exact_source = pd.Series(series.index, index=series.index)
        if policy in {"inner", "calendar_aligned"}:
            aligned[leg_key] = series.reindex(target)
            source_times[leg_key] = exact_source.reindex(target)
            continue
        tolerance = pd.Timedelta(seconds=parsed_parameters.max_staleness_seconds)
        aligned[leg_key] = series.reindex(target, method="ffill", tolerance=tolerance)
        source_times[leg_key] = exact_source.reindex(target, method="ffill", tolerance=tolerance)
    return aligned, source_times


def _apply_missing_policy(
    values: pd.DataFrame,
    source_times: pd.DataFrame,
    *,
    policy: str,
    parameters: dict[str, Any] | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    policy = MISSING_DATA_REGISTRY.get(policy)
    parsed = MISSING_DATA_REGISTRY.validate_parameters(policy, parameters)
    if policy == "forward_fill":
        values = values.ffill()
        source_times = source_times.ffill()
        ages = pd.DataFrame(index=values.index)
        for column in source_times:
            ages[column] = values.index.to_series(index=values.index) - pd.to_datetime(
                source_times[column], utc=True
            )
        too_old = ages.apply(lambda column: column > pd.Timedelta(seconds=parsed.max_age_seconds))
        values = values.mask(too_old)
        source_times = source_times.mask(too_old)

    missing_rows = values.isna().any(axis=1)
    if policy == "fail" and missing_rows.any():
        missing_times = [timestamp.isoformat() for timestamp in values.index[missing_rows][:10]]
        raise IncompleteObservationsError(
            f"incomplete required observations at calculation times {missing_times!r}"
        )
    if policy in {"drop", "forward_fill"}:
        values = values.loc[~missing_rows]
        source_times = source_times.loc[values.index]
    return values, source_times


def _effective_input_unit(leg: IndexCalculationLeg) -> str:
    if leg.transform_code in {"simple_return", "log_return"}:
        return "decimal"
    if leg.transform_code == "rebase":
        return "index_points"
    return leg.input_unit


def _normalize_units(
    definition: IndexCalculationDefinition,
    legs: Sequence[IndexCalculationLeg],
    values: pd.DataFrame,
) -> pd.DataFrame:
    normalized = values.copy()
    kind = definition.calculation_kind
    if kind == "ratio":
        if len(legs) != 2:
            raise IndexCalculationError("ratio requires exactly two legs")
        UNIT_REGISTRY.ensure_compatible(
            _effective_input_unit(legs[0]),
            _effective_input_unit(legs[1]),
        )
        if UNIT_REGISTRY.dimension(definition.output_unit) != "ratio":
            raise IndexCalculationError("ratio calculation output_unit must be ratio")
        normalized[legs[1].leg_key] = UNIT_REGISTRY.convert(
            normalized[legs[1].leg_key],
            _effective_input_unit(legs[1]),
            _effective_input_unit(legs[0]),
        )
        return normalized
    if kind in {"rebased_basket", "self_financing"}:
        if UNIT_REGISTRY.dimension(definition.output_unit) != "index_level":
            raise IndexCalculationError(f"{kind} output_unit must be index_points")
        if kind == "self_financing":
            reference_unit = _effective_input_unit(legs[0])
            for leg in legs:
                normalized[leg.leg_key] = UNIT_REGISTRY.convert(
                    normalized[leg.leg_key],
                    _effective_input_unit(leg),
                    reference_unit,
                )
        return normalized
    if kind == "chained_return":
        if UNIT_REGISTRY.dimension(definition.output_unit) != "index_level":
            raise IndexCalculationError("chained_return output_unit must be index_points")
        for leg in legs:
            normalized[leg.leg_key] = UNIT_REGISTRY.convert(
                normalized[leg.leg_key],
                _effective_input_unit(leg),
                "decimal",
            )
        return normalized
    for leg in legs:
        normalized[leg.leg_key] = UNIT_REGISTRY.convert(
            normalized[leg.leg_key],
            _effective_input_unit(leg),
            definition.output_unit,
        )
    return normalized


def _coefficient_frame(
    legs: Sequence[IndexCalculationLeg],
    values: pd.DataFrame,
    *,
    resolved_coefficients: Mapping[str, pd.Series | float] | None,
    resolved_coefficient_source_times: Mapping[str, pd.Series] | None,
    coefficient_inputs: Mapping[str, pd.Series] | None,
) -> pd.DataFrame:
    coefficients = pd.DataFrame(index=values.index)
    reference_leg = legs[0]
    reference = values[reference_leg.leg_key].copy()
    reference.attrs["is_return_observation"] = _is_return_observation(reference_leg)
    if coefficient_inputs and reference_leg.leg_key in coefficient_inputs:
        reference.attrs["coefficient_parameter_series"] = _observation_series(
            coefficient_inputs[reference_leg.leg_key],
            leg=reference_leg,
        ).reindex(values.index)

    equal_weight_count = sum(leg.coefficient_method == "equal_weight" for leg in legs)
    for leg in legs:
        if resolved_coefficients and leg.leg_key in resolved_coefficients:
            supplied = resolved_coefficients[leg.leg_key]
            if isinstance(supplied, pd.Series):
                if not isinstance(supplied.index, pd.DatetimeIndex):
                    raise IndexCalculationError(
                        "resolved coefficient series require a DatetimeIndex"
                    )
                source = supplied.copy()
                source.index = pd.DatetimeIndex(
                    pd.to_datetime(source.index, utc=True),
                    dtype="datetime64[ns, UTC]",
                )
                if source.index.has_duplicates:
                    raise IndexCalculationError(
                        "resolved coefficient series contain duplicate timestamps"
                    )
                source = source.sort_index()
                coefficients[leg.leg_key] = source.reindex(values.index, method="ffill")
            else:
                coefficients[leg.leg_key] = float(supplied)
            if leg.coefficient_method not in {"fixed", "equal_weight"}:
                if not resolved_coefficient_source_times or leg.leg_key not in (
                    resolved_coefficient_source_times
                ):
                    raise LookAheadError(
                        f"dynamic resolved coefficient {leg.leg_key!r} requires source timestamps"
                    )
                source_times = resolved_coefficient_source_times[leg.leg_key].copy()
                if not isinstance(source_times.index, pd.DatetimeIndex):
                    raise LookAheadError("coefficient source timestamps require a DatetimeIndex")
                source_times.index = pd.DatetimeIndex(
                    pd.to_datetime(source_times.index, utc=True),
                    dtype="datetime64[ns, UTC]",
                )
                if source_times.index.has_duplicates:
                    raise LookAheadError(
                        "coefficient source timestamps contain duplicate timestamps"
                    )
                effective_sources = pd.to_datetime(
                    source_times.sort_index().reindex(values.index, method="ffill"),
                    utc=True,
                )
                calculation_index = pd.Series(values.index, index=values.index)
                if (effective_sources > calculation_index).any():
                    raise LookAheadError(
                        f"dynamic coefficient {leg.leg_key!r} uses a future source observation"
                    )
            continue
        if leg.coefficient_method == "fixed":
            coefficients[leg.leg_key] = float(leg.coefficient)
            continue
        if leg.coefficient_method == "equal_weight":
            coefficients[leg.leg_key] = 1.0 / float(equal_weight_count or len(legs))
            continue
        implementation = COEFFICIENT_REGISTRY.get(leg.coefficient_method)
        parameters = COEFFICIENT_REGISTRY.validate_parameters(
            leg.coefficient_method,
            leg.coefficient_parameters_json,
        )
        parameter_values = None
        if coefficient_inputs and leg.leg_key in coefficient_inputs:
            parameter_values = _observation_series(
                coefficient_inputs[leg.leg_key],
                leg=leg,
            ).reindex(values.index)
        leg_values = values[leg.leg_key].copy()
        leg_values.attrs["is_return_observation"] = _is_return_observation(leg)
        resolved = implementation(
            reference,
            leg_values,
            parameter_values,
            parameters,
        )
        if getattr(parameters, "fallback_policy", "drop") == "fail" and resolved.isna().any():
            raise IncompleteObservationsError(
                f"coefficient method {leg.coefficient_method!r} for leg {leg.leg_key!r} "
                "could not resolve every calculation time"
            )
        coefficients[leg.leg_key] = resolved
    if coefficients.isna().any(axis=1).all():
        raise IncompleteObservationsError("no calculation time has complete effective coefficients")
    return coefficients


def _rebalance_times(
    calculation_times: pd.DatetimeIndex,
    *,
    policy: str | None,
    parameters: dict[str, Any] | None,
) -> pd.DatetimeIndex:
    """Return deterministic first calculation timestamps for scheduled rebalances."""

    if policy is None:
        return calculation_times
    policy = REBALANCE_REGISTRY.get(policy)
    parsed = REBALANCE_REGISTRY.validate_parameters(policy, parameters)
    if policy == "daily" or calculation_times.empty:
        return calculation_times

    if policy == "event":
        positions = {
            int(calculation_times.searchsorted(pd.Timestamp(event_time), side="left"))
            for event_time in parsed.event_times
        }
        return calculation_times[
            sorted(position for position in positions if position < len(calculation_times))
        ]

    local_times = calculation_times.tz_convert(getattr(parsed, "timezone", "UTC"))
    if policy == "weekly":
        calendar = local_times.isocalendar()
        keys = list(zip(calendar["year"], calendar["week"], strict=True))
    elif policy == "monthly":
        keys = list(zip(local_times.year, local_times.month, strict=True))
    elif policy == "quarterly":
        quarters = ((local_times.month - 1) // 3) + 1
        keys = list(zip(local_times.year, quarters, strict=True))
    else:  # pragma: no cover - registry validation owns the reachable set
        raise IndexCalculationError(f"unsupported rebalance policy {policy!r}")

    positions: list[int] = []
    previous: tuple[Any, ...] | None = None
    for position, key in enumerate(keys):
        normalized = tuple(key) if isinstance(key, tuple) else (key,)
        if normalized != previous:
            positions.append(position)
            previous = normalized
    return calculation_times[positions]


def _apply_rebalance_policy(
    values: pd.DataFrame,
    *,
    policy: str | None,
    parameters: dict[str, Any] | None,
) -> pd.DataFrame:
    if policy is None or values.empty:
        return values
    effective_times = _rebalance_times(values.index, policy=policy, parameters=parameters)
    return values.loc[effective_times].reindex(values.index, method="ffill")


def _is_return_observation(leg: IndexCalculationLeg) -> bool:
    return leg.transform_code in {"simple_return", "log_return"} or leg.observable_code in {
        "simple_return",
        "log_return",
        "return",
        "total_return",
    }


def calculate_index(
    definition: IndexCalculationDefinition,
    legs: Sequence[IndexCalculationLeg],
    observations: Mapping[str, pd.Series | pd.DataFrame],
    *,
    index_identifier: str = "in_memory",
    calculation_times: Sequence[Any] | pd.DatetimeIndex | None = None,
    resolved_coefficients: Mapping[str, pd.Series | float] | None = None,
    resolved_coefficient_source_times: Mapping[str, pd.Series] | None = None,
    coefficient_inputs: Mapping[str, pd.Series] | None = None,
) -> IndexCalculationResult:
    """Calculate one derived-index version from caller-supplied observations."""

    definition_hash = validate_calculation_contract(definition, legs)
    ordered_legs = sorted(legs, key=lambda leg: (leg.leg_order, leg.leg_key))
    missing_inputs = [leg.leg_key for leg in ordered_legs if leg.leg_key not in observations]
    if missing_inputs:
        raise IndexCalculationError(f"missing observations for legs {missing_inputs!r}")

    transformed: dict[str, pd.Series] = {}
    for leg in ordered_legs:
        source = _observation_series(observations[leg.leg_key], leg=leg)
        transform = TRANSFORM_REGISTRY.get(leg.transform_code)
        parameters = TRANSFORM_REGISTRY.validate_parameters(
            leg.transform_code,
            leg.transform_parameters_json,
        )
        transformed[leg.leg_key] = transform(source, parameters)

    aligned, source_times = _align(
        transformed,
        policy=definition.alignment_policy,
        parameters=definition.alignment_parameters_json,
        calculation_times=calculation_times,
    )
    aligned, source_times = _apply_missing_policy(
        aligned,
        source_times,
        policy=definition.missing_data_policy,
        parameters=definition.missing_data_parameters_json,
    )
    if aligned.empty:
        return IndexCalculationResult(values=_empty_result_frame())

    aligned = _normalize_units(definition, ordered_legs, aligned)
    coefficients = _coefficient_frame(
        ordered_legs,
        aligned,
        resolved_coefficients=resolved_coefficients,
        resolved_coefficient_source_times=resolved_coefficient_source_times,
        coefficient_inputs=coefficient_inputs,
    )
    coefficients = _apply_rebalance_policy(
        coefficients,
        policy=definition.rebalance_policy,
        parameters=definition.rebalance_parameters_json,
    )
    complete = ~(aligned.isna().any(axis=1) | coefficients.isna().any(axis=1))
    aligned = aligned.loc[complete]
    coefficients = coefficients.loc[complete]
    source_times = source_times.loc[complete]
    if aligned.empty:
        return IndexCalculationResult(values=_empty_result_frame())

    calculation = CALCULATION_REGISTRY.get(definition.calculation_kind)
    calculation_parameters = CALCULATION_REGISTRY.validate_parameters(
        definition.calculation_kind,
        definition.calculation_parameters_json,
    )
    result_values = calculation(aligned, coefficients, calculation_parameters)

    latest_sources = source_times.apply(
        lambda row: pd.to_datetime(row, utc=True).max(),
        axis=1,
    )
    calculation_index = pd.Series(aligned.index, index=aligned.index)
    stale_rows = source_times.apply(
        lambda column: pd.to_datetime(column, utc=True) < calculation_index
    ).any(axis=1)
    statuses = pd.Series("ready", index=aligned.index, dtype="string")
    statuses.loc[stale_rows] = "stale"
    definition_uid = definition.uid
    frame = pd.DataFrame(
        {
            "value": result_values.astype(float),
            "unit": definition.output_unit,
            "definition_uid": definition_uid,
            "observation_status": statuses,
            "source_as_of": pd.to_datetime(latest_sources, utc=True),
            "metadata_json": [
                {"definition_hash": definition_hash} for _ in range(len(result_values))
            ],
        },
        index=aligned.index,
    )
    frame["index_identifier"] = index_identifier
    frame.index = pd.DatetimeIndex(frame.index, name="time_index", dtype="datetime64[ns, UTC]")
    frame = frame.reset_index().set_index(["time_index", "index_identifier"]).sort_index()
    return IndexCalculationResult(values=frame)


def _empty_result_frame() -> pd.DataFrame:
    index = pd.MultiIndex.from_arrays(
        [
            pd.DatetimeIndex([], dtype="datetime64[ns, UTC]"),
            pd.Index([], dtype="string"),
        ],
        names=["time_index", "index_identifier"],
    )
    return pd.DataFrame(
        columns=[
            "value",
            "unit",
            "definition_uid",
            "observation_status",
            "source_as_of",
            "metadata_json",
        ],
        index=index,
    )


__all__ = [
    "IncompleteObservationsError",
    "IndexCalculationError",
    "LookAheadError",
    "calculate_index",
    "validate_calculation_contract",
]
