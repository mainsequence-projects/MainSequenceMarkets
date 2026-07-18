from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from msm.analytics.indices.contracts import (
    IndexCalculationDefinition,
    IndexCalculationLeg,
    ResolvedIndexLeg,
)
from msm.analytics.indices.engine import (
    IndexCalculationError,
    _align,
    _apply_rebalance_policy,
    _apply_missing_policy,
    _coefficient_frame,
    _datetime_index,
    _normalize_units,
    _observation_series,
    _rebalance_times,
    validate_calculation_contract,
)
from msm.analytics.indices.registries import (
    COEFFICIENT_REGISTRY,
    FuturesRankParameters,
    NearestTenorParameters,
    SELECTOR_REGISTRY,
    TRANSFORM_REGISTRY,
)


def _candidate_frame(candidates: pd.DataFrame) -> pd.DataFrame:
    frame = candidates.copy()
    if "time_index" not in frame.columns:
        if isinstance(frame.index, pd.DatetimeIndex):
            frame = frame.reset_index().rename(columns={frame.index.name or "index": "time_index"})
        else:
            raise IndexCalculationError("selector candidates require time_index")
    frame["time_index"] = pd.to_datetime(frame["time_index"], utc=True)
    return frame.sort_values("time_index")


def _latest_candidate_snapshot(
    candidates: pd.DataFrame, calculation_time: pd.Timestamp
) -> pd.DataFrame:
    eligible = candidates.loc[candidates["time_index"] <= calculation_time]
    if eligible.empty:
        return eligible
    latest = eligible["time_index"].max()
    return eligible.loc[eligible["time_index"] == latest]


def _nearest_tenor_selector(
    candidates: pd.DataFrame,
    calculation_times: pd.DatetimeIndex,
    parameters: NearestTenorParameters,
) -> pd.DataFrame:
    frame = _candidate_frame(candidates)
    rows: list[dict[str, Any]] = []
    for calculation_time in calculation_times:
        snapshot = _latest_candidate_snapshot(frame, calculation_time)
        if snapshot.empty:
            continue
        if parameters.tenor_column not in snapshot or parameters.component_column not in snapshot:
            raise IndexCalculationError(
                "nearest_tenor selector candidates are missing required columns"
            )
        ranked = snapshot.assign(
            _distance=(
                pd.to_numeric(snapshot[parameters.tenor_column], errors="coerce")
                - parameters.target_tenor_years
            ).abs()
        )
        sort_columns = ["_distance", parameters.component_column]
        if parameters.liquidity_column:
            if parameters.liquidity_column not in ranked:
                raise IndexCalculationError("liquidity selector column is missing")
            ranked = ranked.assign(
                _liquidity=-pd.to_numeric(
                    ranked[parameters.liquidity_column], errors="coerce"
                ).fillna(float("-inf"))
            )
            sort_columns = ["_distance", "_liquidity", parameters.component_column]
        selected = ranked.sort_values(sort_columns).iloc[0]
        rows.append(
            {
                "time_index": calculation_time,
                "resolved_component_key": str(selected[parameters.component_column]),
                "component_kind": str(selected.get("component_kind", "asset")),
                "source_observation_time": selected["time_index"],
            }
        )
    return pd.DataFrame(rows)


def _futures_rank_selector(
    candidates: pd.DataFrame,
    calculation_times: pd.DatetimeIndex,
    parameters: FuturesRankParameters,
) -> pd.DataFrame:
    frame = _candidate_frame(candidates)
    rows: list[dict[str, Any]] = []
    for calculation_time in calculation_times:
        snapshot = _latest_candidate_snapshot(frame, calculation_time)
        if snapshot.empty:
            continue
        if parameters.rank_column not in snapshot or parameters.component_column not in snapshot:
            raise IndexCalculationError(
                "futures_rank selector candidates are missing required columns"
            )
        selected_rows = snapshot.loc[
            pd.to_numeric(snapshot[parameters.rank_column], errors="coerce") == parameters.rank
        ].sort_values(parameters.component_column)
        if selected_rows.empty:
            continue
        selected = selected_rows.iloc[0]
        rows.append(
            {
                "time_index": calculation_time,
                "resolved_component_key": str(selected[parameters.component_column]),
                "component_kind": str(selected.get("component_kind", "asset")),
                "source_observation_time": selected["time_index"],
            }
        )
    return pd.DataFrame(rows)


def _register_selectors() -> None:
    if SELECTOR_REGISTRY.codes():
        return
    SELECTOR_REGISTRY.register(
        "nearest_tenor",
        _nearest_tenor_selector,
        parameters_model=NearestTenorParameters,
    )
    SELECTOR_REGISTRY.register(
        "most_liquid_near_tenor",
        _nearest_tenor_selector,
        parameters_model=NearestTenorParameters,
    )
    SELECTOR_REGISTRY.register(
        "futures_rank",
        _futures_rank_selector,
        parameters_model=FuturesRankParameters,
    )


_register_selectors()


def resolve_selector(
    selector_code: str,
    candidates: pd.DataFrame,
    calculation_times: Sequence[Any] | pd.DatetimeIndex,
    *,
    parameters: dict[str, Any] | None = None,
    rebalance_policy: str | None = None,
    rebalance_parameters: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Resolve one registered selector without using observations after calculation time."""

    times = _datetime_index(calculation_times)
    implementation = SELECTOR_REGISTRY.get(selector_code)
    parsed = SELECTOR_REGISTRY.validate_parameters(selector_code, parameters)
    selection_times = _rebalance_times(
        times,
        policy=rebalance_policy,
        parameters=rebalance_parameters,
    )
    resolved = implementation(candidates, selection_times, parsed)
    if resolved.empty:
        return pd.DataFrame(
            columns=[
                "time_index",
                "resolved_component_key",
                "component_kind",
                "source_observation_time",
            ]
        )
    resolved["time_index"] = pd.to_datetime(resolved["time_index"], utc=True)
    resolved["source_observation_time"] = pd.to_datetime(
        resolved["source_observation_time"], utc=True
    )
    if (resolved["source_observation_time"] > resolved["time_index"]).any():
        raise IndexCalculationError("selector attempted to use a future observation")
    if rebalance_policy not in {None, "daily"}:
        resolved = (
            resolved.sort_values("time_index")
            .set_index("time_index")
            .reindex(times, method="ffill")
            .rename_axis("time_index")
            .dropna(subset=["resolved_component_key"])
            .reset_index()
        )
    return resolved.sort_values("time_index").reset_index(drop=True)


def resolve_index_legs(
    definition: IndexCalculationDefinition,
    legs: Sequence[IndexCalculationLeg],
    observations: Mapping[str, pd.Series | pd.DataFrame],
    *,
    index_identifier: str,
    calculation_times: Sequence[Any] | pd.DatetimeIndex,
    selector_candidates: Mapping[str, pd.DataFrame] | None = None,
    component_identifiers: Mapping[uuid.UUID, str] | None = None,
    coefficient_inputs: Mapping[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """Return canonical resolved-leg audit rows for dynamic membership or coefficients."""

    if definition.uid is None:
        raise IndexCalculationError("persisted resolved legs require definition.uid")
    ordered = sorted(legs, key=lambda leg: (leg.leg_order, leg.leg_key))
    validate_calculation_contract(definition, ordered)
    times = _datetime_index(calculation_times)
    transformed: dict[str, pd.Series] = {}
    for leg in ordered:
        source = _observation_series(observations[leg.leg_key], leg=leg)
        transform = TRANSFORM_REGISTRY.get(leg.transform_code)
        parameters = TRANSFORM_REGISTRY.validate_parameters(
            leg.transform_code,
            leg.transform_parameters_json,
        )
        transformed[leg.leg_key] = transform(source, parameters)
    aligned, _source_times = _align(
        transformed,
        policy=definition.alignment_policy,
        parameters=definition.alignment_parameters_json,
        calculation_times=times,
    )
    aligned, _source_times = _apply_missing_policy(
        aligned,
        _source_times,
        policy=definition.missing_data_policy,
        parameters=definition.missing_data_parameters_json,
    )
    aligned = _normalize_units(definition, ordered, aligned)
    coefficients = _coefficient_frame(
        ordered,
        aligned,
        resolved_coefficients=None,
        resolved_coefficient_source_times=None,
        coefficient_inputs=coefficient_inputs,
    )
    coefficients = _apply_rebalance_policy(
        coefficients,
        policy=definition.rebalance_policy,
        parameters=definition.rebalance_parameters_json,
    )
    component_identifiers = component_identifiers or {}
    selector_candidates = selector_candidates or {}

    rows: list[dict[str, Any]] = []
    for leg in ordered:
        is_dynamic = leg.selector_code is not None or leg.coefficient_method not in {
            "fixed",
            "equal_weight",
        }
        if not is_dynamic:
            continue
        if leg.selector_code is not None:
            candidates = selector_candidates.get(leg.leg_key)
            if candidates is None:
                raise IndexCalculationError(
                    f"selector leg {leg.leg_key!r} requires selector_candidates"
                )
            components = resolve_selector(
                leg.selector_code,
                candidates,
                aligned.index,
                parameters=leg.selector_parameters_json,
                rebalance_policy=definition.rebalance_policy,
                rebalance_parameters=definition.rebalance_parameters_json,
            ).set_index("time_index")
        else:
            component_uid = leg.asset_uid or leg.component_index_uid
            component_key = component_identifiers.get(component_uid, str(component_uid))
            components = pd.DataFrame(
                {
                    "resolved_component_key": component_key,
                    "component_kind": leg.component_kind,
                    "source_observation_time": None,
                },
                index=aligned.index,
            )
        components = components.reindex(aligned.index, method="ffill")
        coefficient_lag: int | None = None
        if leg.coefficient_method not in {"fixed", "equal_weight"}:
            coefficient_parameters = COEFFICIENT_REGISTRY.validate_parameters(
                leg.coefficient_method,
                leg.coefficient_parameters_json,
            )
            coefficient_lag = int(getattr(coefficient_parameters, "lag", 1))
        for time_index in aligned.index:
            component = components.loc[time_index]
            coefficient = coefficients.loc[time_index, leg.leg_key]
            if pd.isna(coefficient) or pd.isna(component.get("resolved_component_key")):
                continue
            selector_source = component.get("source_observation_time")
            coefficient_source = None
            if coefficient_lag is not None:
                location = aligned.index.get_loc(time_index)
                if isinstance(location, int) and location >= coefficient_lag:
                    coefficient_source = aligned.index[location - coefficient_lag]
            source_candidates = [
                pd.Timestamp(value)
                for value in (selector_source, coefficient_source)
                if value is not None and not pd.isna(value)
            ]
            source_observation_time = max(source_candidates) if source_candidates else time_index
            resolved = ResolvedIndexLeg(
                time_index=time_index,
                index_identifier=index_identifier,
                definition_uid=definition.uid,
                leg_key=leg.leg_key,
                resolved_component_key=str(component["resolved_component_key"]),
                component_kind=str(component["component_kind"]),
                resolved_coefficient=float(coefficient),
                coefficient_method=leg.coefficient_method,
                observable_code=leg.observable_code,
                source_observation_time=source_observation_time,
                resolution_status="ready",
                metadata_json={
                    "selector_source_observation_time": (
                        pd.Timestamp(selector_source).isoformat()
                        if selector_source is not None and not pd.isna(selector_source)
                        else None
                    ),
                    "coefficient_source_observation_time": (
                        pd.Timestamp(coefficient_source).isoformat()
                        if coefficient_source is not None
                        else None
                    ),
                },
            )
            rows.append(resolved.model_dump(mode="python"))

    if not rows:
        index = pd.MultiIndex.from_arrays(
            [
                pd.DatetimeIndex([], dtype="datetime64[ns, UTC]"),
                pd.Index([], dtype="string"),
                pd.Index([], dtype="string"),
                pd.Index([], dtype="string"),
            ],
            names=[
                "time_index",
                "index_identifier",
                "leg_key",
                "resolved_component_key",
            ],
        )
        return pd.DataFrame(
            columns=[
                "definition_uid",
                "component_kind",
                "resolved_coefficient",
                "coefficient_method",
                "observable_code",
                "source_observation_time",
                "resolution_status",
                "metadata_json",
            ],
            index=index,
        )
    frame = pd.DataFrame(rows)
    frame["time_index"] = pd.DatetimeIndex(
        pd.to_datetime(frame["time_index"], utc=True), dtype="datetime64[ns, UTC]"
    )
    return frame.set_index(
        ["time_index", "index_identifier", "leg_key", "resolved_component_key"]
    ).sort_index()


__all__ = ["resolve_index_legs", "resolve_selector"]
