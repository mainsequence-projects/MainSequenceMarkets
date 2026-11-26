"""Authoritative position-aware portfolio accounting updater."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
from msm_portfolios.accounting.events import EventsInPrice, events_in_price, price_includes
from msm_portfolios.accounting.reducer import _validate_ledger_record_identities
from msm_portfolios.accounting.valuation import PRICE_COLUMN, VALUATIONS_INPUT
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy import RebalanceStrategyBase
from msm_portfolios.rebalance_strategy.accounting import (
    InstrumentExecutionSpec,
    PositionExecutionModel,
    TargetWeightExecutionModel,
    _empty_event_batch,
)
from msm_portfolios.rebalance_strategy.base import UNFILLED_ENDINGS

from msm_portfolios.retirement import (
    drop_retired_rows,
    end_before_retirement,
    retirement_boundary,
    window_is_empty,
)
from ..base import PortfolioCanonicalUpdater, PortfolioCanonicalUpdaterConfiguration
from .rebalance import _flat_frame, _last_rows_before
from .run_rows import ValuationRows, held_rows, rows_between
from .storage import PortfolioEventLedgerStorage


class PortfolioEngineConfiguration(PortfolioCanonicalUpdaterConfiguration):
    """Hash-bearing configuration of the portfolio's ledger updater (ADR 0065)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    portfolio_identifier: str = Field(min_length=1)
    accounting_configuration: PortfolioAccountingConfiguration
    valuation_asset_identifier: str = Field(
        min_length=1,
        description="The portfolio's currency, from its build configuration (ADR 0059).",
    )
    valuation_source_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        description=(
            "The portfolio's valuation source, from its build configuration: the ledger "
            "values every position at its prices (ADR 0065, decision 10)."
        ),
    )
    valuation_column: str = Field(
        min_length=1,
        description="The source column that holds the price, from the build configuration.",
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

    @field_serializer("valuation_source_instance", when_used="json")
    def serialize_valuation_source(
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
        """Construct the portfolio's ledger updater from its build configuration.

        The ledger follows the portfolio's ``PortfolioRebalance``; one is built from
        the same configuration unless ``portfolio_rebalance`` is given.
        """

        build = portfolio_configuration.portfolio_build_configuration
        accounting = build.accounting_configuration
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
                valuation_source_instance=build.valuation_source_instance,
                valuation_column=build.valuation_column,
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
            "valuation_source": engine.valuation_source_instance,
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

    def ledger_rows(self, *, start: Any, end: Any) -> pd.DataFrame:
        """This portfolio's ledger rows from ``start`` to ``end``, both included.

        In a portfolio run (``run_rows``) after this ledger's update, they are the rows the
        update kept: the stored ledger it replayed and the tail it wrote, so the run's
        weights and values read nothing (#139). Otherwise they are read.
        """

        identifier = self._engine_config().portfolio_identifier
        held = held_rows()
        if held is not None and identifier in held.ledgers:
            return rows_between(held.ledgers[identifier], start=start, end=end)
        return self.get_df_between_dates(
            start_date=start,
            end_date=end,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={"portfolio_identifier": [identifier]},
        )

    def rebalance_state_rows(self, *, start: Any, end: Any) -> pd.DataFrame:
        """This portfolio's rebalance state from ``start`` to ``end``, both included.

        In a portfolio run after this ledger's update, they are the rows the update read,
        from the ledger's initial state on (the ledger books nothing earlier). Otherwise
        they are read.
        """

        config = self._engine_config()
        held = held_rows()
        if held is not None and config.portfolio_identifier in held.rebalance_states:
            return rows_between(
                held.rebalance_states[config.portfolio_identifier], start=start, end=end
            )
        return _read_dependency(
            config.portfolio_rebalance_instance,
            start=start,
            end=end,
            dimension_filters={"portfolio_identifier": [config.portfolio_identifier]},
        )

    def update(self) -> pd.DataFrame:
        config = self._engine_config()
        held = held_rows()
        if held is not None:
            held.ledgers.pop(config.portfolio_identifier, None)
            held.rebalance_states.pop(config.portfolio_identifier, None)
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
        fills = recorded_fills(rebalance_state)
        if fills.empty:
            # Nothing traded yet: the ledger opens at its first fill's run.
            written = normalize_portfolio_event_ledger_frame(
                pd.DataFrame(),
                output_table=self.output_table,
            )
            self._keep(written, rebalance_state)
            return written
        assets = sorted(fills[ASSET_IDENTIFIER_DIMENSION].astype(str).unique())
        require_booked_events(
            assets,
            in_price=events_in_price(config.valuation_source_instance),
            lifecycle_models=accounting_config.lifecycle_event_model_instances,
        )
        valuation_model = accounting_config.position_valuation_model_instance
        read = held.valuations.get(config.portfolio_identifier) if held is not None else None
        frames: dict[str, pd.DataFrame] = {
            f"valuation.{VALUATIONS_INPUT}": portfolio_valuations(
                config.valuation_source_instance,
                valuation_column=config.valuation_column,
                currency=config.valuation_asset_identifier,
                start=start,
                end=end,
                assets=assets,
                rows=(
                    None
                    if read is None
                    else read.rows(
                        config.valuation_source_instance, start=start, end=end, assets=assets
                    )
                ),
            )
        }
        for name, dependency in sorted(valuation_model.declared_dependencies().items()):
            if name == VALUATIONS_INPUT:
                raise ValueError(
                    f"A valuation model's own input cannot be named {VALUATIONS_INPUT!r}: "
                    "PortfolioEngine fills it from the portfolio's valuation source."
                )
            frames[f"valuation.{name}"] = _read_dependency(dependency, start=start, end=end)
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
        valuation_contracts = valuation_model.required_input_contracts()
        provided = {*valuation_model.declared_dependencies(), VALUATIONS_INPUT}
        missing_inputs = sorted(set(valuation_contracts) - provided)
        if missing_inputs:
            raise ValueError(
                "The valuation model needs inputs it declares no source for: "
                + ", ".join(missing_inputs)
            )
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
        valuations = frames[f"valuation.{VALUATIONS_INPUT}"]
        if valuations.empty:
            raise ValueError(
                "PortfolioEngine found no prices for the portfolio's assets in its "
                "valuation source."
            )
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
        decisions = at_decision_rebalances(
            config.rebalance_strategy_instance, _booked_fills(fills, start)
        )
        earlier_valuations = _prices_before_opening(
            config.valuation_source_instance,
            decisions=decisions,
            valuations=valuations,
            start=start,
            read=read,
            valuation_column=config.valuation_column,
            currency=config.valuation_asset_identifier,
        )
        earlier_fx = (
            pd.DataFrame()
            if config.fx_source_instance is None
            else _fx_before_opening(
                config.fx_source_instance,
                decisions=decisions,
                valuations=_with_earlier(
                    valuations, earlier_valuations, keys=VALUATION_KEYS
                ),
                fx=fx,
                start=start,
                currency=config.valuation_asset_identifier,
            )
        )
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
            earlier_valuations=earlier_valuations,
            earlier_fx=earlier_fx,
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
        written = drop_retired_rows(
            normalize_portfolio_event_ledger_frame(
                ledger,
                output_table=self.output_table,
            ),
            boundary,
        )
        self._keep(_appended(existing, written), rebalance_state)
        return written

    def _keep(self, ledger: pd.DataFrame, rebalance_state: pd.DataFrame) -> None:
        """Keep the ledger and the state it read for the run's weights and values."""

        held = held_rows()
        if held is not None:
            identifier = self._engine_config().portfolio_identifier
            held.ledgers[identifier] = ledger
            held.rebalance_states[identifier] = rebalance_state

    def _retirement_boundary(self, portfolio_identifier: str) -> pd.Timestamp | None:
        """The portfolio's ``retired_at`` (ADR 0049), from the row the run resolved.

        The rebalance carries the ``Portfolio`` row its run prepared (#139); a ledger
        built without one reads it.
        """

        rebalance = self._engine_config().portfolio_rebalance_instance
        portfolio = getattr(rebalance, "_portfolio", None)
        if portfolio is None:
            from msm.api.portfolios import Portfolio

            portfolio = Portfolio.get_by_unique_identifier(portfolio_identifier)
        return retirement_boundary(portfolio)

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
        earlier_valuations: pd.DataFrame | None = None,
        earlier_fx: pd.DataFrame | None = None,
    ) -> PortfolioAccounting:
        """Book the fills ``PortfolioRebalance`` recorded, without external execution ingress.

        ``rebalance_state`` is the portfolio's rebalance-state rows. Every row whose
        executed weight changed is a fill, booked at its time and recorded price,
        with quantities sized from the ledger's NAV at that moment.
        ``earlier_valuations`` and ``earlier_fx`` are rows from before the ledger's
        window that its at-decision rebalances were decided with (#150); they size those
        decisions and value nothing.
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
            earlier_valuations=earlier_valuations,
            earlier_fx=earlier_fx,
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


def _appended(existing: pd.DataFrame | None, written: pd.DataFrame) -> pd.DataFrame:
    """The stored ledger with the tail the update wrote, indexed as the table is."""

    if existing is None or existing.empty:
        return written
    if written.empty:
        return existing
    index = list(written.index.names)
    return (
        pd.concat([existing.reset_index(), written.reset_index()], ignore_index=True)
        .set_index(index)
        .sort_index()
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

    A rebalance decided before the ledger opens is booked at the opening, still sized
    with the prices last observed before its earliest moment (#150): ``earlier_valuations``
    and ``earlier_fx`` hold those older than the ledger's window.
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
        earlier_valuations: pd.DataFrame | None = None,
        earlier_fx: pd.DataFrame | None = None,
    ) -> None:
        self.strategy = strategy
        self.valuation_observations = valuation_observations
        self.fx_observations = fx_observations
        self.valuation_asset_identifier = str(valuation_asset_identifier)
        start_ts = _utc_timestamp(start)
        booked = _booked_fills(fills, start_ts)
        self._fills_by_time: dict[pd.Timestamp, pd.DataFrame] = {
            _utc_timestamp(time_index): group
            for time_index, group in booked.groupby("time_index", sort=True)
        }
        self._decisions: dict[pd.Timestamp, list[_Decision]] = {}
        for decision in at_decision_rebalances(strategy, booked):
            self._decisions.setdefault(max(decision.priced_at, start_ts), []).append(decision)
        self._decision_valuations = _with_earlier(
            valuation_observations, earlier_valuations, keys=VALUATION_KEYS
        )
        self._decision_fx = _with_earlier(
            fx_observations, earlier_fx, keys=FX_INPUT_CONTRACT.index_names
        )
        self._decided: dict[str, dict[str, float]] = {}
        self.event_times = tuple(sorted(set(self._fills_by_time) | set(self._decisions)))
        from msm_portfolios.configuration import compute_strategy_revision

        self._strategy_revision = compute_strategy_revision(strategy)
        model = strategy.execution_model_instance
        if model is None:
            model = default_execution_model(
                booked[ASSET_IDENTIFIER_DIMENSION].astype(str).unique()
                if not booked.empty
                else (),
                valuation_observations=self._decision_valuations,
            )
        self._model = model
        strategy_name = f"{strategy.__class__.__module__}.{strategy.__class__.__qualname__}"
        self.model_identifier = f"{model.model_identifier}:{strategy_name}"
        self.model_version = model.model_version

    def simulate(self, *, time_index, state, valuation_result):
        timestamp = _utc_timestamp(time_index)
        for decision in self._decisions.get(timestamp, ()):
            quantities = self._model.decision_quantities(
                valuation_result=valuation_result,
                time_index=decision.priced_at,
                target_weights=decision.target_weights,
                valuation_asset_identifier=self.valuation_asset_identifier,
                valuation_observations=self._decision_valuations,
                fx_observations=self._decision_fx,
            )
            if quantities is not None:
                self._decided[decision.intent_id] = quantities
        fills = self._fills_by_time.get(timestamp)
        if fills is None:
            return _empty_event_batch()
        intent_id = str(fills["rebalance_intent_id"].iloc[0])
        return self.strategy.simulate_recorded_fills(
            time_index=timestamp,
            execution_model=self._model,
            fills=fills,
            state=state,
            valuation_result=valuation_result,
            valuation_asset_identifier=self.valuation_asset_identifier,
            valuation_observations=self.valuation_observations,
            fx_observations=self.fx_observations,
            strategy_revision=self._strategy_revision,
            decided_quantities=self._decided.get(intent_id),
        )


VALUATION_KEYS = ("time_index", ASSET_IDENTIFIER_DIMENSION)


@dataclass(frozen=True)
class _Decision:
    """A rebalance sized at its decision (ADR 0058): its intent, earliest moment and targets."""

    intent_id: str
    earliest: pd.Timestamp
    target_weights: dict[str, float]

    @property
    def priced_at(self) -> pd.Timestamp:
        """The instant it was decided at, just before its earliest moment."""
        return self.earliest - pd.Timedelta(1, unit="ns")

    @property
    def sized_assets(self) -> list[str]:
        """The assets it sizes from a price; a zero target is zero shares."""
        return sorted(asset for asset, weight in self.target_weights.items() if abs(weight) > 1e-15)


def at_decision_rebalances(
    strategy: RebalanceStrategyBase, fills: pd.DataFrame
) -> list[_Decision]:
    """The rebalances of ``fills`` that fix their share counts at their decision.

    Sizing at each fill is the execution policy's other choice (ADR 0058); a rebalance
    without a recorded earliest moment is sized at each fill too.
    """

    if fills.empty or strategy.fill_policy().sizing != "at_decision":
        return []
    decisions = []
    for intent_id, group in fills.groupby("rebalance_intent_id", sort=True):
        earliest = _recorded_earliest_moment(group)
        if earliest is None:
            continue
        decisions.append(
            _Decision(
                intent_id=str(intent_id),
                earliest=earliest,
                target_weights={
                    str(row[ASSET_IDENTIFIER_DIMENSION]): float(row["target_weight"])
                    for row in group.to_dict(orient="records")
                },
            )
        )
    return decisions


def _booked_fills(fills: pd.DataFrame, start: Any) -> pd.DataFrame:
    """The fills a ledger that opens at ``start`` books: those at or after it."""

    return fills[fills["time_index"] >= _utc_timestamp(start)] if not fills.empty else fills


def _with_earlier(
    window: pd.DataFrame, earlier: pd.DataFrame | None, *, keys: Sequence[str]
) -> pd.DataFrame:
    """``window`` and the ``earlier`` rows a decision prices with, one row per ``keys``."""

    if earlier is None or earlier.empty:
        return window
    frames = [_flat_frame(frame) for frame in (earlier, window) if not frame.empty]
    combined = pd.concat(frames, ignore_index=True)
    combined["time_index"] = pd.to_datetime(combined["time_index"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    return combined.drop_duplicates(subset=list(keys), keep="last").reset_index(drop=True)


def _unpriced(
    decisions: list[_Decision],
    rows: pd.DataFrame,
    *,
    start: pd.Timestamp,
    key: str,
    items: Callable[[_Decision], Any],
) -> dict[pd.Timestamp, list[str]]:
    """The rows older than the ledger's window that its decisions price with.

    ``rows`` are the ledger's, from its opening ``start`` on. A decision takes each of its
    ``items`` (assets or currencies, named by ``key``) at its last row at or before the
    instant it was decided at. That row is in ``rows`` when the item has one from
    ``start`` to that instant; otherwise it is the item's last row strictly before the
    earlier of the decision's earliest moment and ``start``. Returns, for each such
    bound, the items whose last row before it is needed.
    """

    flat = pd.DataFrame() if rows is None or rows.empty else _flat_frame(rows)
    times = None if flat.empty else pd.to_datetime(flat["time_index"], utc=True)
    needed: dict[pd.Timestamp, set[str]] = {}
    for decision in decisions:
        wanted = {str(item) for item in items(decision)}
        seen: set[str] = set()
        if times is not None and decision.priced_at >= start:
            within = (times >= start) & (times <= decision.priced_at)
            seen = set(flat.loc[within, key].astype(str))
        if wanted - seen:
            needed.setdefault(min(decision.earliest, start), set()).update(wanted - seen)
    return {before: sorted(values) for before, values in needed.items()}


def _prices_before_opening(
    source: TimeIndexTableUpdater | TimeIndexTableRef,
    *,
    decisions: list[_Decision],
    valuations: pd.DataFrame,
    start: pd.Timestamp,
    read: ValuationRows | None,
    valuation_column: str,
    currency: str,
) -> pd.DataFrame:
    """The prices older than the ledger's opening that its rebalances were decided with.

    A rebalance sizes its shares with each asset's last price before its earliest
    moment, the price its state records (#150). That price is older than the ledger's
    window when the rebalance was decided before the ledger opened, or when no price
    falls between the opening and the decision. In a portfolio run the rows the
    rebalance kept give it; otherwise, or when they do not hold it, the source is read.
    """

    needed = _unpriced(
        decisions,
        valuations,
        start=start,
        key=ASSET_IDENTIFIER_DIMENSION,
        items=lambda decision: decision.sized_assets,
    )
    frames = []
    for before, assets in sorted(needed.items()):
        rows = (
            None if read is None else read.last_rows_before(source, before=before, assets=assets)
        )
        if rows is None:
            rows = _last_rows_before(
                source,
                coordinates=tuple({ASSET_IDENTIFIER_DIMENSION: asset} for asset in assets),
                before=before,
            )
        if not rows.empty:
            frames.append(_flat_frame(rows))
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw["time_index"] = pd.to_datetime(raw["time_index"], utc=True)
    raw = raw.drop_duplicates(subset=list(VALUATION_KEYS))
    return portfolio_valuations(
        source,
        valuation_column=valuation_column,
        currency=currency,
        start=start,
        end=start,
        assets=sorted(set(raw[ASSET_IDENTIFIER_DIMENSION].astype(str))),
        rows=raw,
    )


def _fx_before_opening(
    fx_source: TimeIndexTableUpdater | TimeIndexTableRef,
    *,
    decisions: list[_Decision],
    valuations: pd.DataFrame,
    fx: pd.DataFrame,
    start: pd.Timestamp,
    currency: str,
) -> pd.DataFrame:
    """The FX rates older than the ledger's opening that its rebalances were decided with.

    A decision converts each price at its currency's last rate at or before the instant
    it was decided at (ADR 0059), which can be older than the ledger's window as its
    prices can. ``valuations`` are the ledger's prices with those older ones. The
    ledger reads its FX source itself, in a portfolio run too.
    """

    prices = pd.DataFrame() if valuations.empty else _flat_frame(valuations)

    def foreign(decision: _Decision) -> set[str]:
        if prices.empty:
            return set()
        rows = prices[prices[ASSET_IDENTIFIER_DIMENSION].astype(str).isin(decision.sized_assets)]
        return set(rows["price_asset_identifier"].astype(str)) - {currency}

    rates = pd.DataFrame() if fx.empty else _flat_frame(fx)
    if not rates.empty:
        rates = rates[rates["quote_asset_identifier"].astype(str) == currency]
    needed = _unpriced(
        decisions, rates, start=start, key="base_asset_identifier", items=foreign
    )
    frames = []
    for before, currencies in sorted(needed.items()):
        rows = _last_rows_before(
            fx_source,
            coordinates=tuple(
                {"base_asset_identifier": base, "quote_asset_identifier": currency}
                for base in currencies
            ),
            before=before,
        )
        if not rows.empty:
            frames.append(rows)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw = raw.drop_duplicates(subset=list(FX_INPUT_CONTRACT.index_names))
    return _validate_declared_input(raw, contract=FX_INPUT_CONTRACT, name="fx")


def default_execution_model(
    assets: Any,
    *,
    valuation_observations: pd.DataFrame,
) -> PositionExecutionModel:
    """The execution model of a strategy that states none (ADR 0065, decision 11).

    Every asset trades in fractional units, with multiplier 1 and cash settlement, priced
    in the currency of its valuation rows, as the rebalance's book does.
    """

    flat = valuation_observations.reset_index()
    specs = []
    for asset in sorted({str(value) for value in assets}):
        rows = flat[flat["asset_identifier"].astype(str) == asset]
        currencies = sorted(set(rows["price_asset_identifier"].astype(str)))
        if len(currencies) != 1:
            raise ValueError(
                f"Asset {asset!r} needs one price currency in the valuation source to "
                f"trade with the default execution model; found {currencies or 'none'}."
            )
        specs.append(
            InstrumentExecutionSpec(
                asset_identifier=asset,
                quantity_unit="units",
                target_measure="market_value_weight",
                contract_multiplier=1.0,
                price_asset_identifier=currencies[0],
                settlement_style="cash",
                terms_version="default",
            )
        )
    return TargetWeightExecutionModel(instrument_specs=tuple(specs))


def portfolio_valuations(
    source: TimeIndexTableUpdater | TimeIndexTableRef,
    *,
    valuation_column: str,
    currency: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    assets: Any,
    rows: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """The portfolio's prices, read from its valuation source (ADR 0065, decision 10).

    ``rows`` are the source's rows of ``assets`` from ``start`` to ``end`` when the run
    has read them already (the rebalance did, #139); without them the source is read.
    The price is the source's ``valuation_column``. It is in ``currency``, the
    portfolio's, unless the source has ``price_asset_identifier``. A row's
    ``source_revision`` is the source's own when it has one; otherwise it is computed
    from the row's time, asset and price, so a changed price is a changed source.
    """

    assets = [str(asset) for asset in assets]
    if not assets:
        return pd.DataFrame(
            columns=[PRICE_COLUMN, "price_asset_identifier", "source_revision"],
            index=pd.MultiIndex.from_arrays([[], []], names=["time_index", "asset_identifier"]),
        )
    frame = (
        rows
        if rows is not None
        else _read_dependency(
            source,
            start=start,
            end=end,
            dimension_filters={ASSET_IDENTIFIER_DIMENSION: assets},
        )
    )
    flat = frame.reset_index()
    if flat.empty:
        return portfolio_valuations(
            source, valuation_column=valuation_column, currency=currency,
            start=start, end=end, assets=(),
        )
    if valuation_column not in flat.columns:
        raise ValueError(
            f"The valuation source has no column {valuation_column!r}, the build's "
            "valuation_column."
        )
    prices = pd.DataFrame(
        {
            "time_index": pd.to_datetime(flat["time_index"], utc=True).astype(
                "datetime64[ns, UTC]"
            ),
            "asset_identifier": flat[ASSET_IDENTIFIER_DIMENSION].astype(str),
            PRICE_COLUMN: pd.to_numeric(flat[valuation_column], errors="coerce").astype(
                "float64"
            ),
        }
    )
    prices["price_asset_identifier"] = (
        flat["price_asset_identifier"].astype(str)
        if "price_asset_identifier" in flat.columns
        else str(currency)
    )
    if "source_revision" in flat.columns:
        prices["source_revision"] = flat["source_revision"].astype(str)
    else:
        prices["source_revision"] = pd.util.hash_pandas_object(
            prices[["time_index", "asset_identifier", PRICE_COLUMN]], index=False
        ).map("{:016x}".format)
    prices = prices[prices[PRICE_COLUMN].notna()]
    return prices.set_index(["time_index", "asset_identifier"]).sort_index()


def require_booked_events(
    assets: Any,
    *,
    in_price: EventsInPrice,
    lifecycle_models: Any,
) -> None:
    """Refuse to run while the portfolio holds an asset with an event nothing books.

    An asset's type lists the events it can have (``AssetType.event_types``). Each must
    be booked by a lifecycle model or included in the prices (ADR 0065, decision 2).
    Adjusted prices include every event, so nothing is read for them.
    """

    from msm_portfolios.accounting.events import ADJUSTED

    assets = sorted({str(asset) for asset in assets})
    if in_price == ADJUSTED or not assets:
        return
    from msm.api.assets import Asset, AssetType

    booked = {event_type for model in lifecycle_models for event_type in model.booked_event_types}
    rows = Asset.filter(unique_identifier__in=assets, limit=len(assets))
    asset_types = {str(row.unique_identifier): row.asset_type for row in rows}
    unknown = [asset for asset in assets if asset not in asset_types]
    if unknown:
        raise ValueError(
            "The portfolio trades assets Markets does not know, so their events are "
            "unknown: " + ", ".join(unknown)
        )
    type_keys = sorted({value for value in asset_types.values() if value})
    events_by_type = {
        str(row.asset_type): tuple(row.event_types)
        for row in (
            AssetType.filter(asset_type__in=type_keys, limit=len(type_keys)) if type_keys else []
        )
    }
    unbooked = {
        asset: [
            event_type
            for event_type in events_by_type.get(str(asset_types[asset]), ())
            if event_type not in booked and not price_includes(in_price, event_type)
        ]
        for asset in assets
    }
    unbooked = {asset: events for asset, events in unbooked.items() if events}
    if unbooked:
        listed = "; ".join(f"{asset}: {', '.join(events)}" for asset, events in unbooked.items())
        raise ValueError(
            "The portfolio holds assets with events nothing books, on prices that do not "
            f"include them: {listed}. Add a lifecycle model that books them, or value the "
            "portfolio with prices that include them (events_in_price, ADR 0065)."
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
    "default_execution_model",
    "normalize_portfolio_event_ledger_frame",
    "portfolio_valuations",
    "recorded_fills",
    "require_booked_events",
]
