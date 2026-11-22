"""Authoritative position-aware portfolio accounting updater."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import pandas as pd
from pydantic import ConfigDict, Field, field_serializer

from metatables import TimeIndexTableRef, TimeIndexTableUpdater
from msm_portfolios.accounting import (
    LifecycleInputContract,
    PortfolioAccounting,
    PortfolioAccountingConfiguration,
    event_digest,
)
from msm_portfolios.accounting.reducer import _validate_ledger_record_identities
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy import RebalanceStrategyBase
from msm_portfolios.rebalance_strategy.accounting import _empty_event_batch
from msm_portfolios.rebalance_strategy.base import UNFILLED_ENDINGS

from msm_portfolios.retirement import (
    drop_retired_rows,
    end_before_retirement,
    retirement_boundary,
    window_is_empty,
)
from ..base import PortfolioCanonicalUpdater, PortfolioCanonicalUpdaterConfiguration
from .storage import PortfolioEventLedgerStorage


class PortfolioEngineConfiguration(PortfolioCanonicalUpdaterConfiguration):
    """Hash-bearing opt-in position-accounting updater configuration."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    portfolio_identifier: str = Field(min_length=1)
    accounting_configuration: PortfolioAccountingConfiguration
    valuation_asset_identifier: str = Field(
        min_length=1,
        description="The portfolio's currency, from its build configuration (ADR 0059).",
    )
    fx_source_instance: TimeIndexTableUpdater | TimeIndexTableRef | None = Field(
        default=None,
        description="The portfolio's FX source, from its build configuration (ADR 0059).",
    )
    portfolio_rebalance_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        description=(
            "The portfolio's rebalance state. The ledger books exactly the fills it "
            "recorded: time, asset and price (ADR 0058)."
        ),
    )
    rebalance_strategy_instance: RebalanceStrategyBase = Field(
        description="The strategy whose execution model sizes and costs each recorded fill.",
    )

    @field_serializer("portfolio_rebalance_instance", when_used="json")
    def serialize_portfolio_rebalance(
        self,
        value: TimeIndexTableUpdater | TimeIndexTableRef,
    ) -> dict[str, Any]:
        from msm_portfolios.configuration import canonical_valuation_source_configuration

        return canonical_valuation_source_configuration(value)

    @field_serializer("fx_source_instance", when_used="json")
    def serialize_fx_source(
        self,
        value: TimeIndexTableUpdater | TimeIndexTableRef | None,
    ) -> dict[str, Any] | None:
        from msm_portfolios.configuration import canonical_valuation_source_configuration

        return None if value is None else canonical_valuation_source_configuration(value)

    @field_serializer("rebalance_strategy_instance", when_used="json")
    def serialize_rebalance_strategy(
        self,
        value: RebalanceStrategyBase,
    ) -> dict[str, Any]:
        from msm_portfolios.configuration import (
            canonical_rebalance_strategy_configuration,
        )

        return canonical_rebalance_strategy_configuration(value)


class PortfolioEngine(PortfolioCanonicalUpdater):
    """Coordinate declared inputs and publish one authoritative event ledger."""

    @classmethod
    def from_portfolio_configuration(
        cls,
        portfolio_configuration,
        *,
        portfolio_identifier: str,
        namespace: str | None = None,
        portfolio_rebalance: TimeIndexTableUpdater | TimeIndexTableRef | None = None,
        **kwargs,
    ) -> PortfolioEngine:
        """Construct the opt-in engine from the nested portfolio build contract.

        The ledger follows the portfolio's ``PortfolioRebalance``; one is built from
        the same configuration unless ``portfolio_rebalance`` is given.
        """

        build = portfolio_configuration.portfolio_build_configuration
        accounting = getattr(build, "accounting_configuration", None)
        if accounting is None:
            raise ValueError(
                "PortfolioEngine requires enabled PortfolioBuildConfiguration.accounting_configuration."
            )
        if portfolio_rebalance is None:
            from .rebalance import PortfolioRebalance

            portfolio_rebalance = PortfolioRebalance(namespace=namespace)
            portfolio_rebalance.set_portfolio_configuration(
                portfolio_configuration,
                portfolio_identifier=portfolio_identifier,
            )
        return cls(
            config=PortfolioEngineConfiguration(
                portfolio_identifier=portfolio_identifier,
                accounting_configuration=accounting,
                valuation_asset_identifier=build.valuation_asset_identifier,
                fx_source_instance=build.fx_source_instance,
                portfolio_rebalance_instance=portfolio_rebalance,
                rebalance_strategy_instance=(
                    build.backtesting_weights_configuration.rebalance_strategy_instance
                ),
            ),
            namespace=namespace,
            **kwargs,
        )

    def dependencies(self) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        accounting = self._engine_config().accounting_configuration
        engine = self._engine_config()
        dependencies: dict[str, TimeIndexTableUpdater | TimeIndexTableRef] = {
            "portfolio_rebalance": engine.portfolio_rebalance_instance,
        }
        if engine.fx_source_instance is not None:
            dependencies["fx"] = engine.fx_source_instance
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
        boundary = self._retirement_boundary(config.portfolio_identifier)
        end = end_before_retirement(end, boundary)
        if window_is_empty(start, end):
            return normalize_portfolio_event_ledger_frame(
                pd.DataFrame(),
                output_table=self.output_table,
            )

        rebalance_state = _read_dependency(
            config.portfolio_rebalance_instance,
            start=start,
            end=end,
            dimension_filters={"portfolio_identifier": [config.portfolio_identifier]},
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
        fx = pd.DataFrame()
        if config.fx_source_instance is not None:
            fx = _validate_declared_input(
                _read_dependency(config.fx_source_instance, start=start, end=end),
                contract=FX_INPUT_CONTRACT,
                name="fx",
            )
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
            valuation_asset_identifier=config.valuation_asset_identifier,
            rebalance_strategy=config.rebalance_strategy_instance,
            rebalance_state=rebalance_state,
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
        return drop_retired_rows(
            normalize_portfolio_event_ledger_frame(
                ledger,
                output_table=self.output_table,
            ),
            boundary,
        )

    @staticmethod
    def _retirement_boundary(portfolio_identifier: str) -> pd.Timestamp | None:
        """Read the portfolio row once per run for its ``retired_at`` (ADR 0049)."""

        from msm.api.portfolios import Portfolio

        return retirement_boundary(Portfolio.get_by_unique_identifier(portfolio_identifier))

    @classmethod
    def calculate_backtest(
        cls,
        *,
        portfolio_identifier: str,
        accounting_configuration: PortfolioAccountingConfiguration,
        valuation_asset_identifier: str,
        rebalance_strategy: RebalanceStrategyBase,
        rebalance_state: pd.DataFrame,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame | None = None,
        lifecycle_inputs: dict[str, dict[str, pd.DataFrame]] | None = None,
        valuation_times: Any = (),
    ) -> PortfolioAccounting:
        """Book the fills ``PortfolioRebalance`` recorded, without external execution ingress.

        ``rebalance_state`` is the portfolio's rebalance-state rows. Every row whose
        executed weight changed is a fill, booked at its time and recorded price,
        with quantities sized from the ledger's NAV at that moment.
        """

        fx = pd.DataFrame() if fx_observations is None else fx_observations
        valuation_times = tuple(valuation_times)
        fills = recorded_fills(rebalance_state)
        calculation_end = _calculation_end(
            fills,
            valuation_observations,
            lifecycle_inputs or {},
            valuation_times,
        )
        simulator = _RecordedFillBooker(
            strategy=rebalance_strategy,
            start=accounting_configuration.initial_state_time_index,
            fills=fills,
            valuation_observations=valuation_observations,
            fx_observations=fx,
            valuation_asset_identifier=valuation_asset_identifier,
        )
        reducer = PortfolioAccounting(
            portfolio_identifier=portfolio_identifier,
            valuation_asset_identifier=valuation_asset_identifier,
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
        config: PortfolioCanonicalUpdaterConfiguration,
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
    _validate_ledger_record_identities(frame)
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


FX_INPUT_CONTRACT = LifecycleInputContract(
    index_names=("time_index", "base_asset_identifier", "quote_asset_identifier"),
    required_columns=("rate", "source_revision"),
)


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


FILL_COLUMNS = (
    "time_index",
    "rebalance_intent_id",
    ASSET_IDENTIFIER_DIMENSION,
    "target_signal_time_index",
    "event_source",
    "target_weight",
    "weight_after",
    "executed_weight_delta",
    "execution_price",
    "execution_status",
    "strategy_state",
)


def recorded_fills(rebalance_state: pd.DataFrame | None) -> pd.DataFrame:
    """Return the trades ``PortfolioRebalance`` recorded, its cancellations and expiries.

    A row carries an ``execution_price`` exactly when its asset traded at that time,
    at that observed price. A cancelled row without a price cut an order that filled
    nothing then; an expired row dropped what was left of an order whose signal passed
    the strategy's lifetime, and never has a price. The ledger records both as progress
    with the status and the reason their state gives. A fill can leave the weight
    unchanged, when a new target repeats the asset's weight; the ledger then resizes
    the position at its NAV.
    Each fill keeps its time, asset, price and target, plus a ``source_revision``
    that digests them, so a changed fill is a changed source.
    """
    if rebalance_state is None or rebalance_state.empty:
        return pd.DataFrame(columns=[*FILL_COLUMNS, "source_revision"])
    flat = rebalance_state.reset_index()
    missing = [column for column in FILL_COLUMNS if column not in flat.columns]
    if missing:
        raise ValueError("Rebalance state is missing columns: " + ", ".join(missing))
    flat = flat[~flat["execution_status"].isin({"superseded", "rejected"})]
    ended = flat["execution_status"].astype(str).isin(UNFILLED_ENDINGS)
    flat = flat[flat["execution_price"].notna() | ended].copy()
    if flat.empty:
        return pd.DataFrame(columns=[*FILL_COLUMNS, "source_revision"])
    ended = flat["execution_status"].astype(str).isin(UNFILLED_ENDINGS)
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
    flat["target_signal_time_index"] = pd.to_datetime(
        flat["target_signal_time_index"], utc=True
    )
    flat[ASSET_IDENTIFIER_DIMENSION] = flat[ASSET_IDENTIFIER_DIMENSION].astype(str)
    price = pd.to_numeric(flat["execution_price"], errors="coerce")
    priced = price.notna() & (price > 0.0) & price.map(_is_finite)
    # A cancellation or an expiry that filled nothing carries no price; the ledger
    # records it.
    unpriced = flat[~priced & ~(ended & price.isna())]
    if not unpriced.empty:
        first = unpriced.iloc[0]
        raise ValueError(
            f"The recorded fill of {first[ASSET_IDENTIFIER_DIMENSION]} at "
            f"{first['time_index'].isoformat()} has no observed execution price."
        )
    flat["execution_price"] = price.astype("float64")
    flat["source_revision"] = [
        _digest(
            {
                "time_index": row["time_index"].isoformat(),
                "rebalance_intent_id": str(row["rebalance_intent_id"]),
                "asset_identifier": row[ASSET_IDENTIFIER_DIMENSION],
                "target_signal_time_index": row["target_signal_time_index"].isoformat(),
                "target_weight": float(row["target_weight"]),
                "weight_after": float(row["weight_after"]),
                "execution_price": (
                    None if pd.isna(row["execution_price"]) else float(row["execution_price"])
                ),
                "execution_status": str(row["execution_status"]),
                "strategy_state": RebalanceStrategyBase.parse_strategy_state(row),
            }
        )
        for row in flat.to_dict(orient="records")
    ]
    if flat.duplicated(subset=["time_index", ASSET_IDENTIFIER_DIMENSION]).any():
        raise ValueError("Rebalance state records two fills of one asset at one time.")
    return flat[[*FILL_COLUMNS, "source_revision"]].sort_values(
        ["time_index", ASSET_IDENTIFIER_DIMENSION], kind="stable"
    ).reset_index(drop=True)


def _is_finite(value: Any) -> bool:
    try:
        return bool(pd.notna(value)) and abs(float(value)) != float("inf")
    except (TypeError, ValueError):
        return False


class _RecordedFillBooker:
    """Book the fills ``PortfolioRebalance`` recorded, in time order (ADR 0058).

    With the execution policy's default sizing, a rebalance fixes its share counts
    once, at its decision: the instant before its earliest moment, with the NAV and
    the prices last observed before it, the same set for every asset. Each asset
    then fills its fixed count, or the recorded fraction of its open order, at its
    own recorded price; a strategy with its own bars records one fill per slice
    (#90). A rebalance sized at each fill, or without a recorded earliest moment, is
    sized at each fill.
    """

    def __init__(
        self,
        *,
        strategy: RebalanceStrategyBase,
        start: Any,
        fills: pd.DataFrame,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
        valuation_asset_identifier: str,
    ) -> None:
        self.strategy = strategy
        self.valuation_observations = valuation_observations
        self.fx_observations = fx_observations
        self.valuation_asset_identifier = str(valuation_asset_identifier)
        start_ts = _utc_timestamp(start)
        booked = fills[fills["time_index"] >= start_ts] if not fills.empty else fills
        self._fills_by_time: dict[pd.Timestamp, pd.DataFrame] = {
            _utc_timestamp(time_index): group
            for time_index, group in booked.groupby("time_index", sort=True)
        }
        self._decisions: dict[pd.Timestamp, dict[str, dict[str, float]]] = {}
        # Sizing at each fill is the execution policy's other choice (ADR 0058).
        sized_at_decision = strategy.fill_policy().sizing == "at_decision"
        for intent_id, group in booked.groupby("rebalance_intent_id", sort=True):
            if not sized_at_decision:
                break
            earliest = _recorded_earliest_moment(group)
            if earliest is None:
                continue
            decision_time = max(earliest - pd.Timedelta(1, unit="ns"), start_ts)
            self._decisions.setdefault(decision_time, {})[str(intent_id)] = {
                str(row[ASSET_IDENTIFIER_DIMENSION]): float(row["target_weight"])
                for row in group.to_dict(orient="records")
            }
        self._decided: dict[str, dict[str, float]] = {}
        self.event_times = tuple(sorted(set(self._fills_by_time) | set(self._decisions)))
        from msm_portfolios.configuration import compute_strategy_revision

        self._strategy_revision = compute_strategy_revision(strategy)
        model = strategy.execution_model_instance
        if model is None:
            raise ValueError(
                f"{strategy.__class__.__name__} requires execution_model_instance for "
                "position-aware accounting."
            )
        self._model = model
        strategy_name = f"{strategy.__class__.__module__}.{strategy.__class__.__qualname__}"
        self.model_identifier = f"{model.model_identifier}:{strategy_name}"
        self.model_version = model.model_version

    def simulate(self, *, time_index, state, valuation_result):
        timestamp = _utc_timestamp(time_index)
        for intent_id, target_weights in self._decisions.get(timestamp, {}).items():
            quantities = self._model.decision_quantities(
                valuation_result=valuation_result,
                time_index=timestamp,
                target_weights=target_weights,
                valuation_asset_identifier=self.valuation_asset_identifier,
                valuation_observations=self.valuation_observations,
                fx_observations=self.fx_observations,
            )
            if quantities is not None:
                self._decided[intent_id] = quantities
        fills = self._fills_by_time.get(timestamp)
        if fills is None:
            return _empty_event_batch()
        intent_id = str(fills["rebalance_intent_id"].iloc[0])
        return self.strategy.simulate_recorded_fills(
            time_index=timestamp,
            fills=fills,
            state=state,
            valuation_result=valuation_result,
            valuation_asset_identifier=self.valuation_asset_identifier,
            valuation_observations=self.valuation_observations,
            fx_observations=self.fx_observations,
            strategy_revision=self._strategy_revision,
            decided_quantities=self._decided.get(intent_id),
        )


def _recorded_earliest_moment(fills: pd.DataFrame) -> pd.Timestamp | None:
    """Return the earliest moment a rebalance's fills recorded, the first if several."""
    moments = []
    for value in fills["strategy_state"]:
        state = RebalanceStrategyBase.parse_strategy_state({"strategy_state": value})
        if state.get("earliest_time_index"):
            moments.append(_utc_timestamp(state["earliest_time_index"]))
    return min(moments) if moments else None


def _calculation_end(
    fills: pd.DataFrame,
    valuation_observations: pd.DataFrame,
    lifecycle_inputs: dict[str, dict[str, pd.DataFrame]],
    valuation_times: Any,
) -> pd.Timestamp:
    values: list[pd.Timestamp] = []
    for frame in [fills, valuation_observations]:
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

    new = _flat_ledger(calculated)
    _validate_ledger_record_identities(new)
    if existing is None or existing.empty:
        return
    old = _flat_ledger(existing)
    _validate_ledger_record_identities(old)
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
    "recorded_fills",
]
