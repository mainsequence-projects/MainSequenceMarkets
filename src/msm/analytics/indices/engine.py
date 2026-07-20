from __future__ import annotations

import operator
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from msm.analytics.indices.contracts import (
    FormulaNode,
    FormulaNumber,
    FormulaReference,
    FormulaUnary,
    IndexFormula,
    IndexFormulaDefinition,
    IndexFormulaEvaluation,
    IndexFormulaInput,
    IndexFormulaResult,
    parse_formula,
    validate_formula_contract,
)


class IndexFormulaError(ValueError):
    """Base strict formula calculation failure."""


class IncompleteFormulaObservationsError(IndexFormulaError):
    """Raised when a formula configured with `fail` encounters missing observations."""


def _observation_series(
    value: pd.Series | pd.DataFrame,
    *,
    formula_input: IndexFormulaInput,
) -> pd.Series:
    reference = formula_input.reference
    if isinstance(value, pd.DataFrame):
        if formula_input.observable not in value.columns:
            raise IndexFormulaError(
                f"{reference.expression} source is missing observable {formula_input.observable!r}"
            )
        series = value[formula_input.observable]
    elif isinstance(value, pd.Series):
        series = value
    else:
        raise TypeError(f"{reference.expression} observations must be a pandas Series or DataFrame")
    if not isinstance(series.index, pd.DatetimeIndex):
        raise IndexFormulaError(f"{reference.expression} observations require a DatetimeIndex")
    if series.index.tz is None:
        raise IndexFormulaError(f"{reference.expression} observation timestamps must be timezone-aware")
    index = pd.DatetimeIndex(series.index).tz_convert("UTC")
    if index.has_duplicates:
        raise IndexFormulaError(f"{reference.expression} observations contain duplicate timestamps")
    try:
        numeric = pd.to_numeric(series, errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise IndexFormulaError(f"{reference.expression} observations must be numeric") from exc
    result = pd.Series(numeric, index=index, name=reference.expression).sort_index()
    return result.replace([np.inf, -np.inf], np.nan)


def _lookup_observation(
    observations: Mapping[FormulaReference | str, pd.Series | pd.DataFrame],
    reference: FormulaReference,
) -> pd.Series | pd.DataFrame:
    if reference in observations:
        return observations[reference]
    if reference.expression in observations:
        return observations[reference.expression]
    raise IndexFormulaError(f"observations are missing {reference.expression}")


def _target_index(
    series_by_reference: Mapping[FormulaReference, pd.Series],
    *,
    alignment_policy: str,
    times: Sequence[Any] | pd.DatetimeIndex | None,
) -> pd.DatetimeIndex:
    if times is not None:
        target = pd.DatetimeIndex(times)
        if target.tz is None:
            raise IndexFormulaError("calculation times must be timezone-aware")
        return target.tz_convert("UTC").sort_values().drop_duplicates()
    indexes = [series.index for series in series_by_reference.values()]
    if not indexes:
        raise IndexFormulaError("a formula must reference at least one input")
    target = indexes[0]
    if alignment_policy == "exact":
        for current in indexes[1:]:
            target = target.intersection(current)
    else:
        for current in indexes[1:]:
            target = target.union(current)
    return target.sort_values()


def _aligned_observations(
    formula: IndexFormula,
    series_by_reference: Mapping[FormulaReference, pd.Series],
    *,
    times: Sequence[Any] | pd.DatetimeIndex | None,
) -> tuple[dict[FormulaReference, pd.Series], pd.Series, pd.DataFrame]:
    target = _target_index(
        series_by_reference,
        alignment_policy=formula.alignment_policy,
        times=times,
    )
    values: dict[FormulaReference, pd.Series] = {}
    source_times: dict[str, pd.Series] = {}
    if formula.alignment_policy == "exact":
        for reference, series in series_by_reference.items():
            values[reference] = series.reindex(target)
            source_times[reference.expression] = pd.Series(target, index=target)
    else:
        tolerance = pd.Timedelta(
            seconds=float((formula.alignment_parameters_json or {})["max_staleness_seconds"])
        )
        for reference, series in series_by_reference.items():
            values[reference] = series.reindex(target, method="ffill", tolerance=tolerance)
            source_index = pd.Series(series.index, index=series.index)
            source_times[reference.expression] = source_index.reindex(
                target,
                method="ffill",
                tolerance=tolerance,
            )
    source_frame = pd.DataFrame(source_times, index=target)
    source_as_of = source_frame.max(axis=1)
    input_frame = pd.DataFrame(
        {reference.expression: series for reference, series in values.items()},
        index=target,
    )
    return values, source_as_of, input_frame


_BINARY_OPERATORS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "**": operator.pow,
}


def _evaluate(node: FormulaNode, values: Mapping[FormulaReference, pd.Series]) -> pd.Series | float:
    if isinstance(node, FormulaReference):
        return values[node]
    if isinstance(node, FormulaNumber):
        return float(node.value)
    if isinstance(node, FormulaUnary):
        operand = _evaluate(node.operand, values)
        return operand if node.operator == "+" else -operand
    left = _evaluate(node.left, values)
    right = _evaluate(node.right, values)
    if node.operator == "/":
        if isinstance(right, pd.Series):
            if (right.dropna() == 0).any():
                raise IndexFormulaError("formula division denominator contains zero")
        elif right == 0:
            raise IndexFormulaError("formula division denominator is zero")
    try:
        with np.errstate(all="ignore"):
            return _BINARY_OPERATORS[node.operator](left, right)
    except (ArithmeticError, FloatingPointError, OverflowError, ValueError) as exc:
        raise IndexFormulaError(f"formula operator {node.operator!r} failed: {exc}") from exc


def _evaluate_historical_formula(
    *,
    formula: IndexFormula,
    observations: Mapping[FormulaReference | str, pd.Series | pd.DataFrame],
    times: Sequence[Any] | pd.DatetimeIndex | None = None,
) -> IndexFormulaEvaluation:
    """Evaluate a self-contained formula against caller-supplied historical series."""

    series_by_reference = {
        item.reference: _observation_series(
            _lookup_observation(observations, item.reference),
            formula_input=item,
        )
        for item in formula.inputs
    }
    aligned, source_as_of, input_frame = _aligned_observations(
        formula,
        series_by_reference,
        times=times,
    )
    evaluated = _evaluate(parse_formula(formula.formula), aligned)
    if not isinstance(evaluated, pd.Series):
        evaluated = pd.Series(evaluated, index=input_frame.index, dtype=float)
    result_values = pd.to_numeric(evaluated, errors="coerce").astype(float)
    invalid = input_frame.isna().any(axis=1) | result_values.isna() | ~np.isfinite(result_values)
    if invalid.any() and formula.missing_data_policy == "fail":
        timestamps = [timestamp.isoformat() for timestamp in input_frame.index[invalid][:10]]
        raise IncompleteFormulaObservationsError(
            f"formula observations are incomplete or non-finite at {timestamps}"
        )
    if formula.missing_data_policy == "drop":
        keep = ~invalid
        result_values = result_values.loc[keep]
        source_as_of = source_as_of.loc[keep]
    values = pd.DataFrame(
        {
            "value": result_values.to_numpy(dtype=float),
            "source_as_of": source_as_of.to_numpy(),
        },
        index=result_values.index,
    )
    values.index.name = "time_index"
    return IndexFormulaEvaluation(values=values)


def calculate_formula_index(
    *,
    index_identifier: str,
    definition: IndexFormulaDefinition,
    inputs: Sequence[IndexFormulaInput],
    observations: Mapping[FormulaReference | str, pd.Series | pd.DataFrame],
    times: Sequence[Any] | pd.DatetimeIndex | None = None,
) -> IndexFormulaResult:
    """Calculate one formula definition without querying or mutating platform state."""

    typed_inputs = tuple(inputs)
    validate_formula_contract(definition, typed_inputs)
    if definition.uid is None:
        raise IndexFormulaError("persisted formula definition uid is required for calculation")
    formula = IndexFormula.from_definition(definition, typed_inputs)
    historical = _evaluate_historical_formula(
        formula=formula,
        observations=observations,
        times=times,
    ).values
    frame = pd.DataFrame(
        {
            "time_index": historical.index,
            "index_identifier": index_identifier,
            "value": historical["value"].to_numpy(dtype=float),
            "definition_uid": definition.uid,
            "observation_status": "ready",
            "source_as_of": historical["source_as_of"].to_numpy(),
            "metadata_json": None,
        }
    )
    return IndexFormulaResult(values=frame)


__all__ = [
    "IncompleteFormulaObservationsError",
    "IndexFormulaError",
    "calculate_formula_index",
]
