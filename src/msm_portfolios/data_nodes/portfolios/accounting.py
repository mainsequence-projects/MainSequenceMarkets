"""Authoritative position-aware portfolio accounting updater."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import pandas as pd
from pydantic import ConfigDict, Field, field_serializer

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater
from msm_portfolios.accounting import (
    LifecycleInputContract,
    PortfolioAccounting,
    PortfolioAccountingConfiguration,
    event_digest,
)
from msm_portfolios.rebalance_strategy import (
    AccountingRebalanceEvent,
    RebalanceStrategyBase,
)

from ..base import PortfolioCanonicalDataNode, PortfolioCanonicalDataNodeConfiguration
from .rebalance import normalize_rebalance_input
from .storage import PortfolioEventLedgerStorage


class PortfolioEngineConfiguration(PortfolioCanonicalDataNodeConfiguration):
    """Hash-bearing opt-in position-accounting updater configuration."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    portfolio_identifier: str = Field(min_length=1)
    accounting_configuration: PortfolioAccountingConfiguration
    signal_weights_instance: TimeIndexTableUpdater | TimeIndexTableRef
    rebalance_strategy_instance: RebalanceStrategyBase

    @field_serializer("signal_weights_instance", when_used="json")
    def serialize_signal_weights(
        self,
        value: TimeIndexTableUpdater | TimeIndexTableRef,
    ) -> dict[str, Any]:
        from msm_portfolios.data_nodes.signals.weights import (
            canonical_signal_configuration,
        )

        return canonical_signal_configuration(value)

    @field_serializer("rebalance_strategy_instance", when_used="json")
    def serialize_rebalance_strategy(
        self,
        value: RebalanceStrategyBase,
    ) -> dict[str, Any]:
        from msm_portfolios.configuration import (
            canonical_rebalance_strategy_configuration,
        )

        return canonical_rebalance_strategy_configuration(value)


class PortfolioEngine(PortfolioCanonicalDataNode):
    """Coordinate declared inputs and publish one authoritative event ledger."""

    @classmethod
    def from_portfolio_configuration(
        cls,
        portfolio_configuration,
        *,
        portfolio_identifier: str,
        namespace: str | None = None,
        **kwargs,
    ) -> PortfolioEngine:
        """Construct the opt-in engine from the nested portfolio build contract."""

        accounting = getattr(
            portfolio_configuration.portfolio_build_configuration,
            "accounting_configuration",
            None,
        )
        if accounting is None:
            raise ValueError(
                "PortfolioEngine requires enabled PortfolioBuildConfiguration.accounting_configuration."
            )
        return cls(
            config=PortfolioEngineConfiguration(
                portfolio_identifier=portfolio_identifier,
                accounting_configuration=accounting,
                signal_weights_instance=(
                    portfolio_configuration.portfolio_build_configuration
                    .backtesting_weights_configuration.signal_weights_instance
                ),
                rebalance_strategy_instance=(
                    portfolio_configuration.portfolio_build_configuration
                    .backtesting_weights_configuration.rebalance_strategy_instance
                ),
            ),
            namespace=namespace,
            **kwargs,
        )

    def dependencies(self) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        accounting = self._engine_config().accounting_configuration
        engine = self._engine_config()
        dependencies: dict[str, TimeIndexTableUpdater | TimeIndexTableRef] = {
            "signal_weights": engine.signal_weights_instance,
        }
        for name, dependency in sorted(
            engine.rebalance_strategy_instance.declared_dependencies().items()
        ):
            dependencies[f"rebalance.{name}"] = dependency
        for name, dependency in sorted(
            accounting.position_valuation_model_instance.declared_dependencies().items()
        ):
            dependencies[f"valuation.{name}"] = dependency
        for model in sorted(
            accounting.lifecycle_event_model_instances,
            key=lambda value: value.model_identifier,
        ):
            for name, dependency in sorted(model.declared_dependencies().items()):
                key = f"lifecycle.{model.model_identifier}.{name}"
                if key in dependencies:
                    raise ValueError(f"Duplicate accounting dependency key {key!r}.")
                dependencies[key] = dependency
        return dependencies

    def update(self) -> pd.DataFrame:
        config = self._engine_config()
        accounting_config = config.accounting_configuration
        start = pd.Timestamp(accounting_config.initial_state_time_index)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        else:
            start = start.tz_convert("UTC")
        end = pd.Timestamp.now(tz="UTC")
        maximum_window = os.getenv("MAX_TD_FROM_LATEST_VALUE")
        if maximum_window:
            end = min(end, start + pd.Timedelta(maximum_window))

        signal_filters = None
        signal_uid = getattr(config.signal_weights_instance, "signal_uid", None)
        if signal_uid not in (None, ""):
            signal_filters = {"signal_uid": [str(signal_uid)]}
        signals = _normalize_signal_observations(
            _read_dependency(
                config.signal_weights_instance,
                start=start,
                end=end,
                dimension_filters=signal_filters,
            )
        )
        rebalance_inputs: dict[str, pd.DataFrame] = {}
        strategy_dependencies = config.rebalance_strategy_instance.declared_dependencies()
        strategy_contracts = config.rebalance_strategy_instance.required_input_contract()
        if set(strategy_dependencies) != set(strategy_contracts):
            raise ValueError(
                "Rebalance strategy dependency names and input-contract names must match."
            )
        for name, dependency in sorted(strategy_dependencies.items()):
            source_start, source_end = config.rebalance_strategy_instance.dependency_window(
                name,
                start.to_pydatetime(),
                end.to_pydatetime(),
            )
            frame = _read_dependency(
                dependency,
                start=pd.Timestamp(source_start),
                end=pd.Timestamp(source_end),
            )
            rebalance_inputs[name] = normalize_rebalance_input(
                frame,
                dependency_name=name,
                contract=strategy_contracts[name],
            )
        frames: dict[str, pd.DataFrame] = {}
        for name, dependency in sorted(
            accounting_config.position_valuation_model_instance.declared_dependencies().items()
        ):
            frames[f"valuation.{name}"] = _read_dependency(
                dependency,
                start=start,
                end=end,
            )
        for model in sorted(
            accounting_config.lifecycle_event_model_instances,
            key=lambda value: value.model_identifier,
        ):
            for name, dependency in sorted(model.declared_dependencies().items()):
                frames[f"lifecycle.{model.model_identifier}.{name}"] = _read_dependency(
                    dependency,
                    start=start,
                    end=end,
                )
        valuation_dependencies = (
            accounting_config.position_valuation_model_instance.declared_dependencies()
        )
        valuation_contracts = (
            accounting_config.position_valuation_model_instance.required_input_contracts()
        )
        if set(valuation_dependencies) != set(valuation_contracts):
            raise ValueError("Valuation dependency names and input-contract names must match.")
        for name, contract in valuation_contracts.items():
            key = f"valuation.{name}"
            frames[key] = _validate_declared_input(frames[key], contract=contract, name=key)
        for model in accounting_config.lifecycle_event_model_instances:
            lifecycle_dependencies = model.declared_dependencies()
            lifecycle_contracts = model.required_input_contracts()
            if set(lifecycle_dependencies) != set(lifecycle_contracts):
                raise ValueError(
                    f"PortfolioEngine requires declared dependencies for every "
                    f"{model.model_identifier} input contract."
                )
            for name, contract in lifecycle_contracts.items():
                key = f"lifecycle.{model.model_identifier}.{name}"
                frames[key] = _validate_declared_input(frames[key], contract=contract, name=key)
        valuations = frames.get("valuation.valuations", pd.DataFrame())
        if valuations.empty:
            raise ValueError("PortfolioEngine requires declared valuation observations.")
        fx = frames.get("valuation.fx", pd.DataFrame())
        lifecycle_inputs: dict[str, dict[str, pd.DataFrame]] = {}
        for model in accounting_config.lifecycle_event_model_instances:
            lifecycle_inputs[model.model_identifier] = {
                name: frames[f"lifecycle.{model.model_identifier}.{name}"]
                for name in model.declared_dependencies()
            }
        valuation_times = pd.to_datetime(valuations.reset_index()["time_index"], utc=True).unique()
        reducer = self.calculate_backtest(
            portfolio_identifier=config.portfolio_identifier,
            accounting_configuration=accounting_config,
            rebalance_strategy=config.rebalance_strategy_instance,
            signal_observations=signals,
            rebalance_inputs=rebalance_inputs,
            valuation_observations=valuations,
            fx_observations=fx,
            lifecycle_inputs=lifecycle_inputs,
            valuation_times=valuation_times,
        )
        ledger = reducer.ledger
        existing = self.get_df_between_dates(
            start_date=start,
            end_date=end,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={
                "portfolio_identifier": [config.portfolio_identifier],
            },
        )
        _validate_replay_against_existing(existing, ledger)
        ledger = _new_ledger_tail(existing, ledger)
        return normalize_portfolio_event_ledger_frame(
            ledger,
            output_table=self.output_table,
        )

    @classmethod
    def calculate_backtest(
        cls,
        *,
        portfolio_identifier: str,
        accounting_configuration: PortfolioAccountingConfiguration,
        rebalance_strategy: RebalanceStrategyBase,
        signal_observations: pd.DataFrame,
        rebalance_inputs: dict[str, pd.DataFrame],
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame | None = None,
        lifecycle_inputs: dict[str, dict[str, pd.DataFrame]] | None = None,
        valuation_times: Any = (),
    ) -> PortfolioAccounting:
        """Calculate one deterministic backtest without any external execution ingress."""

        fx = pd.DataFrame() if fx_observations is None else fx_observations
        valuation_times = tuple(valuation_times)
        calculation_end = _calculation_end(
            signal_observations,
            rebalance_inputs,
            valuation_observations,
            lifecycle_inputs or {},
            valuation_times,
        )
        simulator = _CoordinatedExecutionSimulator(
            strategy=rebalance_strategy,
            start=accounting_configuration.initial_state_time_index,
            end=calculation_end,
            signal_observations=signal_observations,
            observed_inputs=rebalance_inputs,
            valuation_observations=valuation_observations,
            fx_observations=fx,
            valuation_asset_identifier=(
                accounting_configuration.valuation_asset_identifier
            ),
        )
        reducer = PortfolioAccounting(
            portfolio_identifier=portfolio_identifier,
            valuation_asset_identifier=accounting_configuration.valuation_asset_identifier,
            initial_nav=accounting_configuration.initial_nav,
            initial_state_time_index=accounting_configuration.initial_state_time_index,
            valuation_model=accounting_configuration.position_valuation_model_instance,
            balance_tolerance=(
                accounting_configuration.rounding_and_balance_policy.balance_tolerance
            ),
            historical_information_mode=(
                accounting_configuration.historical_information_policy.mode
            ),
        )
        reducer.run(
            valuation_observations=valuation_observations,
            fx_observations=fx,
            execution_simulator=simulator,
            lifecycle_models=accounting_configuration.lifecycle_event_model_instances,
            lifecycle_inputs=lifecycle_inputs,
            valuation_times=valuation_times,
            calculation_end=calculation_end,
        )
        return reducer

    @classmethod
    def _validate_config(
        cls,
        config: PortfolioCanonicalDataNodeConfiguration,
    ) -> PortfolioEngineConfiguration:
        if not isinstance(config, PortfolioEngineConfiguration):
            raise TypeError("PortfolioEngine requires PortfolioEngineConfiguration.")
        return config

    def _engine_config(self) -> PortfolioEngineConfiguration:
        return self.__class__._validate_config(self.config)

    @classmethod
    def _required_output_table(cls) -> type[PortfolioEventLedgerStorage]:
        return PortfolioEventLedgerStorage


def normalize_portfolio_event_ledger_frame(
    frame: pd.DataFrame,
    *,
    output_table: type[PortfolioEventLedgerStorage] | None = None,
) -> pd.DataFrame:
    """Validate a complete canonical ledger frame against its storage schema."""

    required = list(PortfolioEngine._column_dtypes_map_for_storage(output_table))
    flat = frame.copy().reset_index()
    if flat.empty:
        flat = pd.DataFrame(columns=required)
    missing = sorted(set(required) - set(flat.columns))
    if missing:
        raise ValueError("Portfolio event ledger is missing columns: " + ", ".join(missing))
    canonical = PortfolioEngine.validate_frame(flat[required], output_table=output_table)
    _validate_complete_event_groups(canonical.reset_index())
    return canonical


def _validate_complete_event_groups(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    keys = ["portfolio_identifier", "event_identifier", "event_revision"]
    grouped = frame.groupby(keys, sort=False, dropna=False)
    sizes = grouped.size()
    counts = grouped["event_record_count"].first()
    if not sizes.equals(counts.astype("int64")):
        raise ValueError("Portfolio event ledger contains an incomplete event group.")
    digest_counts = grouped["event_digest"].nunique()
    if (digest_counts != 1).any():
        raise ValueError("Portfolio event ledger event records disagree on event_digest.")
    for _, event in grouped:
        expected = str(event["event_digest"].iloc[0])
        if event_digest(event) != expected:
            raise ValueError("Portfolio event ledger event_digest does not match its records.")


def _read_dependency(
    dependency: TimeIndexTableUpdater | TimeIndexTableRef,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    dimension_filters: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    kwargs: dict[str, Any] = dict(
        start_date=start,
        end_date=end,
        great_or_equal=True,
        less_or_equal=True,
    )
    if dimension_filters:
        kwargs["dimension_filters"] = dimension_filters
    frame = dependency.get_df_between_dates(**kwargs)
    return pd.DataFrame() if frame is None else frame


def _normalize_signal_observations(frame: pd.DataFrame) -> pd.DataFrame:
    flat = frame.copy().reset_index()
    required = {"time_index", "asset_identifier", "signal_weight"}
    missing = sorted(required - set(flat.columns))
    if missing:
        raise ValueError("Signal observations are missing: " + ", ".join(missing))
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
    flat["asset_identifier"] = flat["asset_identifier"].astype(str)
    if flat.duplicated(subset=["time_index", "asset_identifier"]).any():
        raise ValueError("Signal observations contain duplicate target coordinates.")
    index_names = ["time_index"]
    if "signal_uid" in flat.columns:
        index_names.append("signal_uid")
    index_names.append("asset_identifier")
    return flat.set_index(index_names).sort_index()


class _CoordinatedExecutionSimulator:
    """Bind one configured strategy to the reducer's execution phase."""

    def __init__(
        self,
        *,
        strategy: RebalanceStrategyBase,
        start: Any,
        end: Any,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
        valuation_asset_identifier: str,
    ) -> None:
        self.strategy = strategy
        self.valuation_observations = valuation_observations
        self.fx_observations = fx_observations
        self.valuation_asset_identifier = str(valuation_asset_identifier)
        for name, frame in observed_inputs.items():
            if frame is not None and not frame.empty and "source_revision" not in frame.reset_index():
                raise ValueError(
                    f"Position-aware rebalance dependency {name!r} requires source_revision."
                )
        schedule = strategy.build_accounting_schedule(
            start=_utc_timestamp(start).to_pydatetime(),
            end=_utc_timestamp(end).to_pydatetime(),
            signal_observations=signal_observations,
            observed_inputs=observed_inputs,
        )
        self._events: dict[pd.Timestamp, AccountingRebalanceEvent] = {
            event.time_index: event for event in schedule
        }
        if len(self._events) != len(schedule):
            raise ValueError("A rebalance strategy must schedule at most one event per timestamp.")
        self.event_times = tuple(sorted(self._events))
        event_frame = pd.DataFrame(
            [
                {"time_index": event.time_index, "event_source": event.event_source}
                for event in schedule
            ],
            columns=["time_index", "event_source"],
        )
        self._observations_by_event = strategy._observations_by_event(
            observed_inputs,
            event_times=pd.DatetimeIndex(self.event_times),
        )
        self._execution_context = strategy.prepare_execution_context(
            events=event_frame,
            observed_inputs=observed_inputs,
        )
        from msm_portfolios.configuration import canonical_rebalance_strategy_configuration

        self._strategy_revision = _digest(
            canonical_rebalance_strategy_configuration(strategy)
        )
        model = strategy.execution_model_instance
        if model is None:
            raise ValueError(
                f"{strategy.__class__.__name__} requires execution_model_instance for "
                "position-aware accounting."
            )
        strategy_name = f"{strategy.__class__.__module__}.{strategy.__class__.__qualname__}"
        self.model_identifier = f"{model.model_identifier}:{strategy_name}"
        self.model_version = model.model_version

    def simulate(self, *, time_index, state, valuation_result):
        timestamp = _utc_timestamp(time_index)
        scheduled_event = self._events[timestamp]
        event_observations = {
            name: grouped.get(timestamp, pd.DataFrame())
            for name, grouped in self._observations_by_event.items()
        }
        return self.strategy.simulate_accounting_event(
            scheduled_event=scheduled_event,
            state=state,
            valuation_result=valuation_result,
            valuation_asset_identifier=self.valuation_asset_identifier,
            valuation_observations=self.valuation_observations,
            fx_observations=self.fx_observations,
            event_observations=event_observations,
            execution_context=self._execution_context,
            strategy_revision=self._strategy_revision,
        )


def _calculation_end(
    signal_observations: pd.DataFrame,
    rebalance_inputs: dict[str, pd.DataFrame],
    valuation_observations: pd.DataFrame,
    lifecycle_inputs: dict[str, dict[str, pd.DataFrame]],
    valuation_times: Any,
) -> pd.Timestamp:
    values: list[pd.Timestamp] = []
    for frame in [signal_observations, valuation_observations, *rebalance_inputs.values()]:
        values.extend(_frame_time_values(frame))
    for model_inputs in lifecycle_inputs.values():
        for frame in model_inputs.values():
            values.extend(_frame_time_values(frame))
    values.extend(_utc_timestamp(value) for value in valuation_times)
    if not values:
        raise ValueError("Position-aware backtest has no economic input timestamps.")
    return max(values)


def _frame_time_values(frame: pd.DataFrame | None) -> list[pd.Timestamp]:
    if frame is None or frame.empty:
        return []
    flat = frame.reset_index()
    if "time_index" not in flat.columns:
        return []
    return [_utc_timestamp(value) for value in flat["time_index"]]


def _utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.as_unit("ns")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _validate_declared_input(
    frame: pd.DataFrame,
    *,
    contract: LifecycleInputContract,
    name: str,
) -> pd.DataFrame:
    flat = frame.copy().reset_index()
    required = {
        *contract.index_names,
        *contract.required_columns,
        contract.source_revision_column,
    }
    missing = sorted(required - set(flat.columns))
    if missing:
        raise ValueError(f"Accounting dependency {name!r} is missing: {', '.join(missing)}")
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True).astype("datetime64[ns, UTC]")
    if flat.duplicated(subset=list(contract.index_names)).any():
        raise ValueError(f"Accounting dependency {name!r} contains duplicate grain rows.")
    return flat.set_index(list(contract.index_names)).sort_index()


def _validate_replay_against_existing(
    existing: pd.DataFrame | None,
    calculated: pd.DataFrame,
) -> None:
    """Allow exact idempotent replay and block unsupported correction publication."""

    if existing is None or existing.empty:
        return
    old = _flat_ledger(existing)
    new = _flat_ledger(calculated)
    identity_columns = ["event_identifier", "source_revision", "event_revision"]
    old_events = (
        old[identity_columns].drop_duplicates("event_identifier").set_index("event_identifier")
    )
    new_events = (
        new[identity_columns].drop_duplicates("event_identifier").set_index("event_identifier")
    )
    removed = sorted(set(old_events.index) - set(new_events.index))
    if removed:
        raise NotImplementedError(
            "Source deletions require corrected portfolio-tail replay; affected events: "
            + ", ".join(removed)
        )
    shared = old_events.join(new_events, how="inner", lsuffix="_old", rsuffix="_new")
    corrected = shared[
        (shared["source_revision_old"] != shared["source_revision_new"])
        | (shared["event_revision_old"] != shared["event_revision_new"])
    ]
    if not corrected.empty:
        raise NotImplementedError(
            "Corrected source/state revisions require portfolio-tail replay; affected events: "
            + ", ".join(sorted(corrected.index.astype(str)))
        )
    old_digests = old.groupby("event_identifier", sort=False)["event_digest"].first()
    new_digests = new.groupby("event_identifier", sort=False)["event_digest"].first()
    mismatched = [
        identifier
        for identifier in sorted(set(old_digests.index) & set(new_digests.index))
        if str(old_digests[identifier]) != str(new_digests[identifier])
    ]
    if mismatched:
        raise ValueError(
            "Exact replay changed canonical event records without a new revision: "
            + ", ".join(mismatched)
        )
    sequence_columns = ["event_identifier", "event_sequence"]
    old_sequences = old[sequence_columns].drop_duplicates().set_index("event_identifier")
    new_sequences = new[sequence_columns].drop_duplicates().set_index("event_identifier")
    shared_sequences = old_sequences.join(
        new_sequences,
        how="inner",
        lsuffix="_old",
        rsuffix="_new",
    )
    changed_sequence = shared_sequences[
        shared_sequences["event_sequence_old"] != shared_sequences["event_sequence_new"]
    ]
    if not changed_sequence.empty:
        raise ValueError(
            "Exact incremental restart changed canonical event ordering: "
            + ", ".join(sorted(changed_sequence.index.astype(str)))
        )


def _new_ledger_tail(
    existing: pd.DataFrame | None,
    calculated: pd.DataFrame,
) -> pd.DataFrame:
    """Return only complete events not already present in the authoritative ledger."""

    if existing is None or existing.empty:
        return calculated
    old = _flat_ledger(existing)
    new = _flat_ledger(calculated)
    old_event_ids = set(old["event_identifier"].astype(str))
    tail = new[~new["event_identifier"].astype(str).isin(old_event_ids)].copy()
    if tail.empty:
        return new.iloc[0:0].copy()
    last_sequence = int(pd.to_numeric(old["event_sequence"], errors="raise").max())
    if (pd.to_numeric(tail["event_sequence"], errors="raise") <= last_sequence).any():
        raise ValueError("Incremental ledger tail is not strictly after existing history.")
    return tail


def _flat_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    if "event_identifier" in frame.columns:
        return frame.copy().reset_index(drop=True)
    return frame.copy().reset_index()


__all__ = [
    "PortfolioEngine",
    "PortfolioEngineConfiguration",
    "normalize_portfolio_event_ledger_frame",
]
