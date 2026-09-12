from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.settings import ASSET_IDENTIFIER_DIMENSION

from .accounting import (
    AccountingExecutionContext,
    ExecutionCostModel,
    PositionExecutionModel,
)


RebalanceDependency = TimeIndexTableUpdater | TimeIndexTableRef
ExecutionStatus = Literal[
    "pending",
    "partial",
    "complete",
    "superseded",
    "cancelled",
    "rejected",
]
TERMINAL_EXECUTION_STATUSES = frozenset({"complete", "superseded", "cancelled", "rejected"})


@dataclass(frozen=True)
class RebalanceInputContract:
    """Required shape for one strategy-declared observed dependency."""

    index_names: tuple[str, ...]
    required_columns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.index_names or self.index_names[0] != "time_index":
            raise ValueError("Rebalance input contracts must be time-indexed.")

    @property
    def asset_scoped(self) -> bool:
        return ASSET_IDENTIFIER_DIMENSION in self.index_names


@dataclass(frozen=True)
class RebalanceTarget:
    """One signal observation promoted to an executable portfolio target."""

    intent_id: str
    signal_time_index: pd.Timestamp
    weights: dict[str, float]


@dataclass(frozen=True)
class AssetExecution:
    """Strategy result for one asset at one observed event."""

    weight_after: float
    execution_price: float | None = None
    executed_quantity: float | None = None
    executed_notional: float | None = None
    observed_volume: float | None = None
    observed_available_liquidity: float | None = None
    strategy_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountingRebalanceEvent:
    """One scheduled backtest execution decision and its active signal target."""

    time_index: pd.Timestamp
    event_source: str
    target: RebalanceTarget


class RebalanceStrategyBase(BaseModel):
    """Dependency-declaring state machine for portfolio rebalance execution."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    timing_mode: str = Field(
        ...,
        min_length=1,
        description=(
            "Descriptive timing category retained for metadata. Generic orchestration "
            "does not branch on this value."
        ),
    )
    completion_tolerance: float = Field(
        default=1e-12,
        ge=0.0,
        description="Absolute remaining-weight tolerance used to mark an intent complete.",
    )
    target_succession: Literal["supersede_active"] = Field(
        default="supersede_active",
        description="Policy applied when a newer signal replaces unfinished execution.",
    )
    execution_model_instance: SerializeAsAny[PositionExecutionModel] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "Explicit position sizing and settlement model used only by the "
            "position-aware backtest engine."
        ),
    )
    execution_cost_model_instances: tuple[SerializeAsAny[ExecutionCostModel], ...] = Field(
        default=(),
        exclude_if=lambda value: not value,
        description="Composable fill-time cost models owned by this rebalance strategy.",
    )

    def get_explanation(self) -> str:
        return f"{self.__class__.__name__}: dependency-declaring rebalance state machine."

    def declared_dependencies(self) -> dict[str, RebalanceDependency]:
        """Return deterministic named inputs required in addition to signal weights."""
        return {}

    def required_input_contract(self) -> dict[str, RebalanceInputContract]:
        """Return the required grain and value fields for each declared dependency."""
        return {}

    def dependency_window(
        self,
        dependency_name: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> tuple[dt.datetime, dt.datetime]:
        """Return source bounds needed to select events inside the execution window."""
        del dependency_name
        return start, end

    def select_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        *,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """Select ordered traceable events only from declared observations."""
        raise NotImplementedError

    def target_selection_mode(self) -> Literal["exact", "latest_at_or_before"]:
        """Define how a source event activates a signal target."""
        return "latest_at_or_before"

    def prepare_execution_context(
        self,
        *,
        events: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> Any:
        """Precompute immutable run-scoped facts used by repeated event transitions."""
        del events, observed_inputs
        return None

    def apply_event(
        self,
        *,
        event_time: pd.Timestamp,
        event_source: str,
        event_observations: dict[str, pd.DataFrame],
        target: RebalanceTarget,
        current_weights: dict[str, float],
        previous_asset_state: dict[str, dict[str, Any]],
        new_target: bool,
        execution_context: Any,
    ) -> dict[str, AssetExecution]:
        """Apply one event to the current executed state."""
        raise NotImplementedError

    def build_accounting_schedule(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> tuple[AccountingRebalanceEvent, ...]:
        """Resolve one deterministic active signal target per simulated execution time."""

        if self.execution_model_instance is None:
            raise ValueError(
                f"{self.__class__.__name__} requires execution_model_instance for "
                "position-aware accounting."
            )
        events = self._normalize_events(
            self.select_events(
                start,
                end,
                signal_observations=signal_observations,
                observed_inputs=observed_inputs,
            )
        )
        targets = self._targets_from_signal_observations(signal_observations)
        exact_targets = {target.signal_time_index: target for target in targets}
        next_target_index = 0
        latest_target: RebalanceTarget | None = None
        schedule: list[AccountingRebalanceEvent] = []
        for row in events.to_dict(orient="records"):
            timestamp = self._as_utc_timestamp(row["time_index"])
            if self.target_selection_mode() == "exact":
                target = exact_targets.get(timestamp)
            else:
                while (
                    next_target_index < len(targets)
                    and targets[next_target_index].signal_time_index <= timestamp
                ):
                    latest_target = targets[next_target_index]
                    next_target_index += 1
                target = latest_target
            if target is not None:
                schedule.append(
                    AccountingRebalanceEvent(
                        time_index=timestamp,
                        event_source=str(row["event_source"]),
                        target=target,
                    )
                )
        return tuple(schedule)

    def simulate_accounting_event(
        self,
        *,
        scheduled_event: AccountingRebalanceEvent,
        state: Any,
        valuation_result: Any,
        valuation_asset_identifier: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
        event_observations: dict[str, pd.DataFrame],
        execution_context: Any,
        strategy_revision: str,
    ):
        """Simulate one position-aware event from the post-lifecycle accounting state."""

        model = self.execution_model_instance
        if model is None:
            raise ValueError(
                f"{self.__class__.__name__} requires execution_model_instance for "
                "position-aware accounting."
            )
        current_weights = model.current_weights(
            state=state,
            valuation_result=valuation_result,
            time_index=scheduled_event.time_index,
            valuation_asset_identifier=str(valuation_asset_identifier),
            valuation_observations=valuation_observations,
            fx_observations=fx_observations,
        )
        previous_asset_state = self._accounting_progress_by_asset(state)
        target = scheduled_event.target
        active_intent = self._active_intent(previous_asset_state)
        asset_executions = self.apply_event(
            event_time=scheduled_event.time_index,
            event_source=scheduled_event.event_source,
            event_observations=event_observations,
            target=target,
            current_weights=dict(current_weights),
            previous_asset_state=previous_asset_state,
            new_target=active_intent != target.intent_id,
            execution_context=execution_context,
        )
        assets = sorted(set(current_weights) | set(target.weights))
        missing_assets = sorted(set(assets) - set(asset_executions))
        if missing_assets:
            raise ValueError(
                f"{self.__class__.__name__}.apply_event() omitted assets: "
                + ", ".join(missing_assets)
            )
        desired_weights = {
            asset: float(asset_executions[asset].weight_after) for asset in assets
        }
        for asset, value in desired_weights.items():
            self._require_finite("weight_after", value, asset=asset)
        context = AccountingExecutionContext(
            time_index=scheduled_event.time_index,
            event_source=scheduled_event.event_source,
            rebalance_intent_id=target.intent_id,
            signal_time_index=target.signal_time_index,
            signal_target_weights={asset: target.weights.get(asset, 0.0) for asset in assets},
            desired_weights=desired_weights,
            weight_before=current_weights,
            asset_executions=asset_executions,
            state=state,
            available_balances=(
                state.cash[
                    state.cash["balance_role"].astype(str) == "settled_cash"
                ].copy()
                if not state.cash.empty
                else state.cash.copy()
            ),
            pre_execution_nav=float(valuation_result.nav),
            valuation_asset_identifier=str(valuation_asset_identifier),
            valuation_references=str(valuation_result.valuation_references),
            valuation_observations=valuation_observations,
            fx_observations=fx_observations,
            event_observations=event_observations,
            strategy_revision=strategy_revision,
            completion_tolerance=self.completion_tolerance,
        )
        return model.simulate(
            context,
            cost_models=self.execution_cost_model_instances,
        )

    @classmethod
    def _accounting_progress_by_asset(cls, state: Any) -> dict[str, dict[str, Any]]:
        progress = getattr(state, "execution_progress", None)
        if progress is None or progress.empty:
            return {}
        rows: dict[str, dict[str, Any]] = {}
        for record in progress.to_dict(orient="records"):
            asset = str(record["asset_identifier"])
            payload = json.loads(str(record["extension_payload"]))
            if not isinstance(payload, dict):
                raise ValueError("Execution progress payload must decode to an object.")
            rows[asset] = {
                **payload,
                "asset_identifier": asset,
                "rebalance_intent_id": payload["rebalance_intent_id"],
                "target_signal_time_index": payload["target_signal_time_index"],
                "strategy_state": json.dumps(
                    payload.get("strategy_state", {}),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        return rows

    def build_transitions(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
        previous_state: pd.DataFrame | None,
    ) -> pd.DataFrame:
        """Run this strategy's state machine and return auditable transition rows."""
        events = self._normalize_events(
            self.select_events(
                start,
                end,
                signal_observations=signal_observations,
                observed_inputs=observed_inputs,
            )
        )
        if events.empty:
            return pd.DataFrame()

        observations_by_event = self._observations_by_event(
            observed_inputs,
            event_times=pd.DatetimeIndex(events["time_index"]),
        )
        signal_targets = self._targets_from_signal_observations(signal_observations)
        exact_targets = {target.signal_time_index: target for target in signal_targets}
        next_target_index = 0
        latest_target: RebalanceTarget | None = None
        execution_context = self.prepare_execution_context(
            events=events,
            observed_inputs=observed_inputs,
        )
        state_by_asset = self._state_by_asset(previous_state)
        current_weights = {
            asset: float(row.get("weight_after", 0.0)) for asset, row in state_by_asset.items()
        }
        rows: list[dict[str, Any]] = []
        active_intent = self._active_intent(state_by_asset)

        for event in events.to_dict(orient="records"):
            event_time = self._as_utc_timestamp(event["time_index"])
            event_source = str(event["event_source"])
            if self.target_selection_mode() == "exact":
                target = exact_targets.get(event_time)
            else:
                while (
                    next_target_index < len(signal_targets)
                    and signal_targets[next_target_index].signal_time_index <= event_time
                ):
                    latest_target = signal_targets[next_target_index]
                    next_target_index += 1
                target = latest_target
            persisted_target = self._target_from_state(state_by_asset)
            if target is None or (
                persisted_target is not None
                and persisted_target.signal_time_index > target.signal_time_index
            ):
                target = persisted_target
            if target is None:
                continue

            new_target = active_intent != target.intent_id
            if new_target and active_intent is not None:
                rows.extend(
                    self._superseded_rows(
                        event_time=event_time,
                        event_source=event_source,
                        active_intent=active_intent,
                        state_by_asset=state_by_asset,
                    )
                )

            if not new_target and self._intent_is_complete(state_by_asset, target.intent_id):
                continue

            event_observations = {
                name: grouped.get(event_time, pd.DataFrame())
                for name, grouped in observations_by_event.items()
            }
            executions = self.apply_event(
                event_time=event_time,
                event_source=event_source,
                event_observations=event_observations,
                target=target,
                current_weights=dict(current_weights),
                previous_asset_state=state_by_asset,
                new_target=new_target,
                execution_context=execution_context,
            )
            assets = sorted(set(current_weights) | set(target.weights))
            missing_assets = sorted(set(assets) - set(executions))
            if missing_assets:
                raise ValueError(
                    f"{self.__class__.__name__}.apply_event() omitted assets: "
                    + ", ".join(missing_assets)
                )

            pending_rows: list[dict[str, Any]] = []
            all_complete = True
            for asset in assets:
                before = float(current_weights.get(asset, 0.0))
                target_weight = float(target.weights.get(asset, 0.0))
                execution = executions[asset]
                after = float(execution.weight_after)
                self._require_finite("target_weight", target_weight, asset=asset)
                self._require_finite("weight_before", before, asset=asset)
                self._require_finite("weight_after", after, asset=asset)
                for fact_name in (
                    "execution_price",
                    "executed_quantity",
                    "executed_notional",
                    "observed_volume",
                    "observed_available_liquidity",
                ):
                    fact = getattr(execution, fact_name)
                    if fact is not None:
                        self._require_finite(fact_name, float(fact), asset=asset)
                remaining = target_weight - after
                all_complete = all_complete and abs(remaining) <= self.completion_tolerance
                pending_rows.append(
                    {
                        "time_index": event_time,
                        "rebalance_intent_id": target.intent_id,
                        "asset_identifier": asset,
                        "target_signal_time_index": target.signal_time_index,
                        "event_source": event_source,
                        "target_weight": target_weight,
                        "weight_before": before,
                        "weight_after": after,
                        "executed_weight_delta": after - before,
                        "remaining_weight_delta": remaining,
                        "execution_price": execution.execution_price,
                        "executed_quantity": execution.executed_quantity,
                        "executed_notional": execution.executed_notional,
                        "observed_volume": execution.observed_volume,
                        "observed_available_liquidity": (execution.observed_available_liquidity),
                        "strategy_state": json.dumps(
                            {"schema_version": 1, **execution.strategy_state},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                )

            status: ExecutionStatus
            if all_complete:
                status = "complete"
            elif all(
                abs(float(row["executed_weight_delta"])) <= self.completion_tolerance
                for row in pending_rows
            ):
                status = "pending"
            else:
                status = "partial"
            for row in pending_rows:
                row["execution_status"] = status
                state_by_asset[str(row["asset_identifier"])] = dict(row)
                current_weights[str(row["asset_identifier"])] = float(row["weight_after"])
            rows.extend(pending_rows)
            active_intent = target.intent_id

        return pd.DataFrame(rows)

    def _target_for_event(
        self,
        event_time: pd.Timestamp,
        signal_observations: pd.DataFrame,
    ) -> RebalanceTarget | None:
        targets = self._targets_from_signal_observations(signal_observations)
        if self.target_selection_mode() == "exact":
            return next(
                (target for target in targets if target.signal_time_index == event_time),
                None,
            )
        eligible = [target for target in targets if target.signal_time_index <= event_time]
        return eligible[-1] if eligible else None

    def _targets_from_signal_observations(
        self,
        signal_observations: pd.DataFrame,
    ) -> list[RebalanceTarget]:
        if signal_observations is None or signal_observations.empty:
            return []
        flat = signal_observations.reset_index().copy()
        if "signal_weight" not in flat.columns:
            raise ValueError("Signal observations must include 'signal_weight'.")
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        targets = [
            self._target_from_signal_rows(signal_time, selected)
            for signal_time, selected in flat.groupby("time_index", sort=True)
        ]
        return targets

    def _target_from_signal_rows(
        self,
        signal_time: Any,
        selected: pd.DataFrame,
    ) -> RebalanceTarget:
        signal_time = self._as_utc_timestamp(signal_time)
        selected = selected.sort_values(ASSET_IDENTIFIER_DIMENSION)
        if selected[ASSET_IDENTIFIER_DIMENSION].astype(str).duplicated().any():
            raise ValueError(
                "Signal target contains duplicate asset rows at " + signal_time.isoformat()
            )
        weights = {
            str(row[ASSET_IDENTIFIER_DIMENSION]): float(row["signal_weight"])
            for row in selected.to_dict(orient="records")
        }
        for asset, weight in weights.items():
            self._require_finite("signal_weight", weight, asset=asset)
        signal_uid_values = (
            selected["signal_uid"].dropna().unique() if "signal_uid" in selected.columns else []
        )
        payload = {
            "signal_time_index": signal_time.isoformat(),
            "signal_uids": sorted(str(value) for value in signal_uid_values),
            "weights": sorted(weights.items()),
        }
        intent_id = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return RebalanceTarget(
            intent_id=intent_id,
            signal_time_index=signal_time,
            weights=weights,
        )

    @classmethod
    def _normalize_events(cls, events: pd.DataFrame | None) -> pd.DataFrame:
        if events is None or events.empty:
            return pd.DataFrame(columns=["time_index", "event_source"])
        flat = events.copy().reset_index()
        if "time_index" not in flat.columns or "event_source" not in flat.columns:
            raise ValueError("Strategy events must include time_index and event_source.")
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        flat["event_source"] = flat["event_source"].map(str)
        flat = flat.sort_values(["time_index", "event_source"], kind="stable")
        duplicate_times = flat[flat["time_index"].duplicated(keep=False)]["time_index"]
        if not duplicate_times.empty:
            duplicate_values = ", ".join(
                timestamp.isoformat()
                for timestamp in pd.DatetimeIndex(duplicate_times.unique()).sort_values()
            )
            raise ValueError(
                "select_events() must consolidate strategy input precedence to one "
                f"event per timestamp; duplicates: {duplicate_values}"
            )
        return flat.reset_index(drop=True)

    @classmethod
    def _observations_by_event(
        cls,
        observed_inputs: dict[str, pd.DataFrame],
        *,
        event_times: pd.DatetimeIndex,
    ) -> dict[str, dict[pd.Timestamp, pd.DataFrame]]:
        """Group each dependency once so event dispatch is linear in input rows."""
        selected_times = set(pd.to_datetime(event_times, utc=True))
        indexed: dict[str, dict[pd.Timestamp, pd.DataFrame]] = {}
        for name, frame in observed_inputs.items():
            if frame is None or frame.empty:
                indexed[name] = {}
                continue
            flat = frame.reset_index().copy()
            flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
            flat = flat[flat["time_index"].isin(selected_times)]
            indexed[name] = {
                cls._as_utc_timestamp(timestamp): group.copy()
                for timestamp, group in flat.groupby("time_index", sort=False)
            }
        return indexed

    @staticmethod
    def _state_by_asset(previous_state: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
        if previous_state is None or previous_state.empty:
            return {}
        flat = previous_state.reset_index().copy()
        if "time_index" in flat.columns:
            flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
            flat = flat.sort_values("time_index", kind="stable")
        if "execution_status" in flat.columns:
            active = flat[~flat["execution_status"].isin({"superseded", "cancelled", "rejected"})]
            if not active.empty:
                flat = active
        latest = flat.groupby(ASSET_IDENTIFIER_DIMENSION, sort=False).tail(1)
        return {
            str(row[ASSET_IDENTIFIER_DIMENSION]): row for row in latest.to_dict(orient="records")
        }

    @staticmethod
    def _active_intent(state_by_asset: dict[str, dict[str, Any]]) -> str | None:
        intents = {
            str(row["rebalance_intent_id"])
            for row in state_by_asset.values()
            if row.get("rebalance_intent_id") not in (None, "")
        }
        if len(intents) > 1:
            raise ValueError("Persisted rebalance state contains multiple active intents.")
        return next(iter(intents), None)

    @classmethod
    def _target_from_state(
        cls,
        state_by_asset: dict[str, dict[str, Any]],
    ) -> RebalanceTarget | None:
        active_intent = cls._active_intent(state_by_asset)
        if active_intent is None:
            return None
        rows = {
            asset: row
            for asset, row in state_by_asset.items()
            if str(row.get("rebalance_intent_id")) == active_intent
        }
        if not rows:
            return None
        signal_times = {
            cls._as_utc_timestamp(row["target_signal_time_index"]) for row in rows.values()
        }
        if len(signal_times) != 1:
            raise ValueError("Persisted active intent contains multiple target signal timestamps.")
        return RebalanceTarget(
            intent_id=active_intent,
            signal_time_index=next(iter(signal_times)),
            weights={asset: float(row["target_weight"]) for asset, row in sorted(rows.items())},
        )

    @staticmethod
    def _intent_is_complete(
        state_by_asset: dict[str, dict[str, Any]],
        intent_id: str,
    ) -> bool:
        rows = [
            row
            for row in state_by_asset.values()
            if str(row.get("rebalance_intent_id")) == intent_id
        ]
        return bool(rows) and all(row.get("execution_status") == "complete" for row in rows)

    @staticmethod
    def _superseded_rows(
        *,
        event_time: pd.Timestamp,
        event_source: str,
        active_intent: str,
        state_by_asset: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for asset, prior in sorted(state_by_asset.items()):
            if str(prior.get("rebalance_intent_id")) != active_intent:
                continue
            if prior.get("execution_status") in TERMINAL_EXECUTION_STATUSES:
                continue
            weight = float(prior.get("weight_after", 0.0))
            rows.append(
                {
                    **prior,
                    "time_index": event_time,
                    "asset_identifier": asset,
                    "event_source": event_source,
                    "execution_status": "superseded",
                    "weight_before": weight,
                    "weight_after": weight,
                    "executed_weight_delta": 0.0,
                    "execution_price": None,
                    "executed_quantity": None,
                    "executed_notional": None,
                    "observed_volume": None,
                    "observed_available_liquidity": None,
                }
            )
        return rows

    @staticmethod
    def _as_utc_timestamp(value: Any) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        return (
            timestamp.tz_localize("UTC")
            if timestamp.tzinfo is None
            else timestamp.tz_convert("UTC")
        )

    @staticmethod
    def parse_strategy_state(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        value = row.get("strategy_state")
        if isinstance(value, dict):
            return dict(value)
        if value in (None, "") or pd.isna(value):
            return {}
        parsed = json.loads(str(value))
        if not isinstance(parsed, dict):
            raise ValueError("Persisted strategy_state must decode to an object.")
        return parsed

    @staticmethod
    def _require_finite(name: str, value: float, *, asset: str) -> None:
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite for asset {asset!r}.")


def dependency_events(frame: pd.DataFrame, *, source: str) -> pd.DataFrame:
    """Return one deterministic event per observed timestamp in a dependency frame."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["time_index", "event_source"])
    flat = frame.reset_index()
    if "time_index" not in flat.columns:
        raise ValueError(f"Declared dependency {source!r} has no time_index.")
    times = pd.DatetimeIndex(pd.to_datetime(flat["time_index"], utc=True)).unique().sort_values()
    return pd.DataFrame({"time_index": times, "event_source": source})


__all__ = [
    "AccountingRebalanceEvent",
    "AssetExecution",
    "ExecutionStatus",
    "RebalanceDependency",
    "RebalanceInputContract",
    "RebalanceStrategyBase",
    "RebalanceTarget",
    "dependency_events",
]
