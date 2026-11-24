from __future__ import annotations

import datetime as dt
from collections import deque
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

import metatables.updaters.configuration as update_configuration
from metatables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.settings import ASSET_IDENTIFIER_DIMENSION

from .accounting import (
    AccountingExecutionContext,
    ExecutionCostModel,
    PositionExecutionModel,
)
from .execution_policy import (
    BookEntry,
    BookOrder,
    ExecutionPolicy,
    RebalanceBook,
    order_side as _order_side,
)


RebalanceDependency = TimeIndexTableUpdater | TimeIndexTableRef
ExecutionStatus = Literal[
    "pending",
    "partial",
    "complete",
    "superseded",
    "cancelled",
    "expired",
    "rejected",
]
TERMINAL_EXECUTION_STATUSES = frozenset(
    {"complete", "superseded", "cancelled", "expired", "rejected"}
)
# Statuses that drop what is left of an order. Their row carries no price when nothing
# filled then, and the ledger records it as progress.
UNFILLED_ENDINGS = frozenset({"cancelled", "expired"})


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
    price_time_index: pd.Timestamp | None = None
    target_quantity: float | None = None
    executed_quantity: float | None = None
    executed_notional: float | None = None
    observed_volume: float | None = None
    observed_available_liquidity: float | None = None
    strategy_state: dict[str, Any] = field(default_factory=dict)
    # The part of the order still open that this fill trades; the ledger scales its
    # own order by it. A cancelled order with nothing filled has no price.
    fill_fraction: float = 1.0
    status: str | None = None


@dataclass(frozen=True)
class BarSlice:
    """How much of one order a strategy's bar lets it trade (#90).

    ``shares`` is a non-negative magnitude in the book's share unit: at most that many
    of the order's open shares trade at the bar, in the order's direction. The
    execution policy's cash rules can trade less. ``state`` holds the strategy's own
    facts about the bar (elapsed time, volume, liquidity, daily capacity), recorded in
    the row's ``strategy_state`` under ``"bar"``.
    """

    shares: float
    observed_volume: float | None = None
    observed_available_liquidity: float | None = None
    state: dict[str, Any] = field(default_factory=dict)


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
    fill_rule: Literal["next_observed_price"] = Field(
        default="next_observed_price",
        description=(
            "Every asset trades only at a price observed strictly after the signal that "
            "set its target, at or after the earliest moment the portfolio calendar "
            "allows (ADR 0058). Hash-bearing."
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
    signal_lifetime: dt.timedelta | None = Field(
        default=None,
        gt=dt.timedelta(0),
        exclude_if=lambda value: value is None,
        description=(
            "How long a signal stays valid after its time_index, for example 30 minutes "
            "or 20 days. An event at time t acts only on the latest signal, and not at "
            "all when t - signal time_index > signal_lifetime; there is no fallback to "
            "an earlier signal. A rebalance whose signal passes it keeps what it filled "
            "and ends 'expired'. None: a signal never expires. Hash-bearing when set."
        ),
        examples=["PT30M", "P20D"],
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

    def signal_expired(self, signal_time_index: Any, time_index: Any) -> bool:
        """Return whether a signal is too old to act on at ``time_index``.

        The clock is economic time, never the job's: an event at ``time_index`` acts
        on the latest signal, which is too old when ``time_index - signal_time_index >
        signal_lifetime``. A signal exactly ``signal_lifetime`` old is still valid.
        Measuring the age from the signal's own ``time_index`` is inferred from the
        execution engine ADR's timer "at the signal's time plus the strategy's
        lifetime"; the owner's decision does not name the clock (#114). Without a
        lifetime no signal expires.
        """
        if self.signal_lifetime is None:
            return False
        age = self._as_utc_timestamp(time_index) - self._as_utc_timestamp(signal_time_index)
        return age > pd.Timedelta(self.signal_lifetime)

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

    def dependency_seed_coordinates(
        self,
        dependency_name: str,
    ) -> tuple[dict[str, str], ...]:
        """Return the coordinates the strategy follows in the dependency.

        Each coordinate names every non-time index dimension of the dependency.
        The reader reads the window at these coordinates only, and adds, for each
        coordinate, the latest row strictly before the start of
        ``dependency_window``, so a strategy can know the state in force when the
        window opens without guessing a lookback. Without coordinates the whole
        window is read.
        """
        del dependency_name
        return ()

    def session_events(
        self,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> pd.DataFrame | None:
        """Return the portfolio calendar's opens and closes, or ``None`` without a calendar.

        The frame has ``time_index`` and ``event_type`` (``market_open`` or
        ``market_close``) in session order. A strategy that declares the portfolio's
        calendar returns it, and the earliest moment of each of its targets is
        gated by it; a strategy without a calendar trades from its own moment.
        """
        del observed_inputs
        return None

    def own_execution_prices(self) -> tuple[str, str] | None:
        """Return ``(input name, price column)`` of the strategy's own observed bars.

        ``None`` (the default) means the strategy has no bars of its own: each asset
        trades at its next observed price in the portfolio's valuation source.
        """
        return None

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

    def prepare_execution_context(
        self,
        *,
        events: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> Any:
        """Precompute immutable run-scoped facts used by repeated event transitions."""
        del events, observed_inputs
        return None

    def bar_slices(
        self,
        *,
        event_time: pd.Timestamp,
        event_observations: dict[str, pd.DataFrame],
        book: RebalanceBook,
        prices: dict[str, float],
        bar_states: dict[str, dict[str, Any]],
        execution_context: Any,
    ) -> dict[str, BarSlice]:
        """Return the slice each open order of ``prices`` may trade at this bar.

        A strategy with its own bars implements it (#90). ``book`` holds every order,
        fixed at the decision: ``order_shares``, ``filled_shares``, and the
        ``earliest_time_index`` the strategy's clock starts at. ``prices`` are the
        bar's observed prices of the assets whose orders are open and may trade now;
        ``event_observations`` are the strategy's inputs at the bar, and
        ``bar_states`` each asset's latest ``"bar"`` state.
        """
        raise NotImplementedError

    def bar_state(
        self,
        *,
        bar_slice: BarSlice,
        entry: BookEntry,
        book: RebalanceBook,
    ) -> dict[str, Any]:
        """Return the ``"bar"`` state recorded once ``entry`` traded at the bar.

        The default is the slice's own state. A strategy that counts what traded, as a
        daily participation cap does, adds it here; ``book`` carries the book's unit.
        """
        del entry, book
        return dict(bar_slice.state)

    def simulate_recorded_fills(
        self,
        *,
        time_index: pd.Timestamp,
        fills: pd.DataFrame,
        state: Any,
        valuation_result: Any,
        valuation_asset_identifier: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
        strategy_revision: str,
        decided_quantities: dict[str, float] | None = None,
        execution_model: Any | None = None,
    ):
        """Book the fills ``PortfolioRebalance`` recorded at one time.

        ``fills`` holds one row per asset that traded at ``time_index``, with its
        ``weight_after``, ``execution_price`` and ``source_revision``, and one per
        order cancelled or expired then without a fill, which has no price and is
        recorded as progress. The strategy decides nothing here.
        ``decided_quantities`` are the share counts the rebalance fixed at its
        decision; each fill trades to its count at the recorded price. Without them,
        quantities are sized from the NAV now. ``execution_model`` is the model the
        ledger resolved: the strategy's own, or the default (ADR 0065, decision 11).
        """

        model = execution_model or self.execution_model_instance
        if model is None:
            raise ValueError(
                f"{self.__class__.__name__} has no execution model to book its fills with."
            )
        intents = fills["rebalance_intent_id"].astype(str).unique()
        if len(intents) != 1:
            raise ValueError(
                "Recorded fills at one time must belong to one rebalance intent; found "
                + ", ".join(sorted(intents))
            )
        signal_times = {
            self._as_utc_timestamp(value) for value in fills["target_signal_time_index"]
        }
        if len(signal_times) != 1:
            raise ValueError("Recorded fills of one intent must share one target signal.")
        current_weights = model.current_weights(
            state=state,
            valuation_result=valuation_result,
            time_index=time_index,
            valuation_asset_identifier=str(valuation_asset_identifier),
            valuation_observations=valuation_observations,
            fx_observations=fx_observations,
        )
        asset_executions: dict[str, AssetExecution] = {}
        signal_target_weights: dict[str, float] = {}
        for row in fills.to_dict(orient="records"):
            asset = str(row[ASSET_IDENTIFIER_DIMENSION])
            weight_after = float(row["weight_after"])
            self._require_finite("weight_after", weight_after, asset=asset)
            row_state = self.parse_strategy_state(row)
            # A cancelled or expired order dropped its remainder; the ledger records it.
            ending = str(row.get("execution_status"))
            price = row.get("execution_price")
            priced = price is not None and not pd.isna(price)
            asset_executions[asset] = AssetExecution(
                weight_after=weight_after,
                execution_price=float(price) if priced else None,
                price_time_index=(
                    self._as_utc_timestamp(row["time_index"]) if priced else None
                ),
                target_quantity=(
                    None if decided_quantities is None else decided_quantities.get(asset)
                ),
                strategy_state=row_state,
                fill_fraction=float(row_state.get("fill_fraction", 1.0)),
                status=ending if ending in UNFILLED_ENDINGS else None,
            )
            signal_target_weights[asset] = float(row["target_weight"])
        context = AccountingExecutionContext(
            time_index=time_index,
            event_source=str(fills["event_source"].iloc[0]),
            rebalance_intent_id=str(intents[0]),
            signal_time_index=next(iter(signal_times)),
            signal_target_weights=signal_target_weights,
            desired_weights={
                asset: execution.weight_after for asset, execution in asset_executions.items()
            },
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
            event_observations={
                "portfolio_rebalance": fills[
                    ["time_index", ASSET_IDENTIFIER_DIMENSION, "source_revision"]
                ].copy()
            },
            strategy_revision=strategy_revision,
            completion_tolerance=self.completion_tolerance,
            cash_floor=self.fill_policy().cash_floor(float(valuation_result.nav)),
        )
        return model.simulate(
            context,
            cost_models=self.execution_cost_model_instances,
        )

    def build_transitions(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
        previous_state: pd.DataFrame | None,
        fill_prices: pd.DataFrame | None = None,
        reference_prices: pd.DataFrame | None = None,
        price_conversion: PriceConversion | None = None,
        book_unit_value: float | None = None,
    ) -> pd.DataFrame:
        """Run this strategy's state machine and return auditable transition rows.

        Every asset trades only at a price observed strictly after the signal that
        set its target, at or after the earliest moment the portfolio calendar
        allows, and assets fill independently (ADR 0058). With a ``signal_lifetime``,
        a signal is acted on only until it is that old (``signal_expired``): a target
        too old at its first event never trades, and a running one ends ``expired``
        at its first event after it, keeping what it filled (#114). A strategy with
        its own bars trades at them, a slice of each order per bar (#90); any other
        strategy trades each asset at its next observed price in ``fill_prices``, the
        portfolio's valuation source as returned by ``observed_prices``. Both run their
        ``fill_policy`` on a book of shares and cash. A missing price never raises: the
        trade waits. ``reference_prices`` (``valuation_prices`` of the same source, with
        each asset's last row before the window) value the portfolio and size the
        decision; without them ``fill_prices`` do. A strategy with its own bars values
        and sizes with all the rows of its bars, interpolated ones too.
        ``price_conversion`` converts prices quoted in another currency into the
        portfolio's at the last observed FX rate (ADR 0059); without it every price is
        in the portfolio's currency, as the prices of a strategy's own bars always are.
        ``book_unit_value`` is the ledger's initial NAV, the book's unit (ADR 0065): a
        fixed-amount negative cash limit and a strategy sized in money or volume need it.
        """
        own_prices = self.own_execution_prices()
        if own_prices is None:
            if fill_prices is None:
                raise ValueError(
                    f"{self.__class__.__name__} trades at the portfolio's observed prices; "
                    "build_transitions needs fill_prices."
                )
            return self._transitions_at_next_observed_price(
                start=start,
                end=end,
                signal_observations=signal_observations,
                observed_inputs=observed_inputs,
                previous_state=previous_state,
                fill_prices=fill_prices,
                reference_prices=reference_prices,
                price_conversion=price_conversion,
                book_unit_value=book_unit_value,
            )
        input_name, price_column = own_prices
        require_observed_price_column(price_column)
        return self._transitions_at_own_bars(
            start=start,
            end=end,
            signal_observations=signal_observations,
            observed_inputs=observed_inputs,
            previous_state=previous_state,
            input_name=input_name,
            price_column=price_column,
            book_unit_value=book_unit_value,
        )

    def _activations(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
        sessions: pd.DataFrame | None,
    ) -> list[tuple[pd.Timestamp, RebalanceTarget]]:
        """Return ``(earliest moment, target)`` for each target this window activates.

        The strategy's moment is each selected event; its target is the latest
        signal at or before that moment. The earliest moment is the strategy's
        moment while the portfolio calendar is in session, otherwise the next
        session start. A target whose next session start is not published yet
        waits for a later run. A target whose signal is past its lifetime at its
        earliest moment never activates, and no earlier signal takes its place.
        """
        events = self._normalize_events(
            self.select_events(
                start,
                end,
                signal_observations=signal_observations,
                observed_inputs=observed_inputs,
            )
        )
        if events.empty:
            return []
        targets = self._targets_from_signal_observations(signal_observations)
        activations: list[tuple[pd.Timestamp, RebalanceTarget]] = []
        next_target = 0
        latest: RebalanceTarget | None = None
        for event_time in pd.DatetimeIndex(events["time_index"]):
            moment = self._as_utc_timestamp(event_time)
            while (
                next_target < len(targets)
                and targets[next_target].signal_time_index <= moment
            ):
                latest = targets[next_target]
                next_target += 1
            if latest is None:
                continue
            earliest = earliest_moment(moment, sessions)
            if earliest is None or self.signal_expired(latest.signal_time_index, earliest):
                continue
            if activations and activations[-1][1].intent_id == latest.intent_id:
                continue
            activations.append((earliest, latest))
        return activations

    def fill_policy(self) -> ExecutionPolicy:
        """Return the execution choices for the strategy's fills.

        The base enforces the facts; the policy owns the choices (ADR 0058). Every
        built-in strategy returns its configured ``execution_policy`` (#90).
        """
        return ExecutionPolicy()

    def _transitions_at_next_observed_price(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
        previous_state: pd.DataFrame | None,
        fill_prices: pd.DataFrame,
        reference_prices: pd.DataFrame | None,
        price_conversion: PriceConversion | None = None,
        book_unit_value: float | None = None,
    ) -> pd.DataFrame:
        """Run the execution policy at every eligible price; write a row per order step.

        The facts hold whatever the policy: a fill price is observed, not interpolated,
        strictly after the target's signal, at or after its earliest moment and, with
        the portfolio calendar, inside a session; a row is stamped at its price's time.
        A new target replaces the running rebalance at its earliest moment; the policy
        decides the rest. ``previous_state`` holds the latest row of every asset.
        ``reference_prices`` value the portfolio and size the decision: the valuation
        source's rows, with each asset's last row before the window.
        """
        policy = self.fill_policy()
        sessions = (
            self.session_events(observed_inputs)
            if policy.calendar_gating == "portfolio_calendar"
            else None
        )
        latest_rows = _latest_rows_by_asset(previous_state)
        # The book is in the portfolio's currency: reference prices are converted at
        # the last FX rate observed at the time they are read (ADR 0059).
        references = _PriceSeries(
            fill_prices if reference_prices is None else reference_prices,
            conversion=price_conversion,
        )
        held, cash = self._recorded_holdings(latest_rows)
        book, after = self._recorded_book(
            policy, latest_rows, signal_observations, references, held, cash, book_unit_value
        )
        start_ts = self._as_utc_timestamp(start)
        end_ts = self._as_utc_timestamp(end)
        # A moment at the last recorded row's time cannot have traded yet, since a fill
        # is strictly after its signal, so it is selected again.
        activation_start = start_ts
        if latest_rows:
            activation_start = min(
                start_ts,
                max(self._as_utc_timestamp(row["time_index"]) for row in latest_rows.values()),
            )
        activations = deque(
            (earliest, target)
            for earliest, target in self._activations(
                start=activation_start,
                end=end,
                signal_observations=signal_observations,
                observed_inputs=observed_inputs,
                sessions=sessions,
            )
            if earliest <= end_ts
            and (book is None or target.signal_time_index > book.signal_time_index)
        )
        # An order still open in the recorded rebalance trades at its first eligible
        # price from that rebalance's earliest moment on, even one older than the window.
        price_start = start_ts if book is None else min(start_ts, book.earliest_time_index)
        eligible = fill_prices[
            (fill_prices["time_index"] >= price_start) & (fill_prices["time_index"] <= end_ts)
        ]
        fills = _PriceSeries(
            eligible[in_session(pd.DatetimeIndex(eligible["time_index"]), sessions)]
        )
        rows: list[dict[str, Any]] = []
        while True:
            order_time = None if book is None else self._next_fill_time(book, fills, after)
            # A new target replaces the running rebalance at the first instant it could
            # trade itself: at or after its earliest moment and strictly after its signal.
            if activations and (
                order_time is None
                or (
                    order_time >= activations[0][0]
                    and order_time > activations[0][1].signal_time_index
                )
            ):
                earliest, target = activations.popleft()
                decision_time = earliest - pd.Timedelta(1, unit="ns")
                if book is not None:
                    held, cash = dict(book.held), book.cash
                elif cash is None:
                    held, cash = self._holdings_from_weights(latest_rows, references, decision_time)
                book = policy.open_book(
                    intent_id=target.intent_id,
                    signal_time_index=target.signal_time_index,
                    earliest_time_index=earliest,
                    target_weights=target.weights,
                    held=held,
                    cash=cash,
                    decision_prices=references.last_prices(
                        set(held) | set(target.weights), decision_time
                    ),
                    unit_value=book_unit_value,
                )
                after = {asset: decision_time for asset in book.orders}
                continue
            if book is None or order_time is None:
                break
            if self.signal_expired(book.signal_time_index, order_time):
                # The first instant an order could trade after the signal's lifetime:
                # the rebalance keeps what it filled and every open order expires.
                rows.extend(self._expired_rows(book, order_time, references))
                continue
            due = {
                asset: price
                for asset, order in book.orders.items()
                if order.status == "open"
                and order_time > after[asset]
                and (price := fills.price_at(asset, order_time)) is not None
            }
            entries = policy.step(
                book,
                time_index=order_time,
                fill_prices={
                    asset: price
                    * (1.0 if price_conversion is None else price_conversion.rate(asset, order_time))
                    for asset, price in due.items()
                },
                last_prices=references.last_prices(set(book.held) | set(due), order_time),
            )
            for asset in due:
                after[asset] = order_time
            rows.extend(
                self._book_row(book, entry, order_time, due[entry.asset_identifier])
                for entry in entries
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _next_fill_time(
        book: RebalanceBook,
        fills: _PriceSeries,
        after: dict[str, pd.Timestamp],
    ) -> pd.Timestamp | None:
        """Return the first instant an open order of ``book`` has an eligible price."""
        times = [
            fills.first_time(
                asset,
                at_or_after=book.earliest_time_index,
                strictly_after=max(after[asset], book.signal_time_index),
            )
            for asset, order in book.orders.items()
            if order.status == "open"
        ]
        return min((time for time in times if time is not None), default=None)

    def _expired_rows(
        self,
        book: RebalanceBook,
        time_index: pd.Timestamp,
        references: _PriceSeries,
        *,
        event_source: str = "valuation_source",
        bar_states: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """End every open order of ``book`` at ``time_index``: its signal is too old.

        The rebalance keeps what it filled; each open order writes an ``expired`` row
        with no price. A strategy with its own bars carries each asset's ``"bar"``
        state into the row.
        """
        last_prices = references.last_prices(set(book.held) | set(book.orders), time_index)
        return [
            self._book_row(
                book,
                entry,
                time_index,
                None,
                event_source=event_source,
                bar_state=(
                    None
                    if bar_states is None
                    else bar_states.get(entry.asset_identifier, {})
                ),
            )
            for entry in book.expire(last_prices, book.nav(last_prices))
        ]

    def _book_row(
        self,
        book: RebalanceBook,
        entry: BookEntry,
        time_index: pd.Timestamp,
        observed_price: float | None,
        *,
        event_source: str = "valuation_source",
        bar_slice: BarSlice | None = None,
        bar_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the row of one order step: the observed price, in its own currency.

        An expired order trades nothing and has no observed price. A strategy with its
        own bars records the bar's volume or liquidity and its ``"bar"`` state.
        """
        asset = entry.asset_identifier
        order = book.orders[asset]
        traded = observed_price is not None and (
            entry.status not in UNFILLED_ENDINGS or abs(entry.shares) > 0.0
        )
        target_weight = float(book.target_weights.get(asset, 0.0))
        self._require_finite("target_weight", target_weight, asset=asset)
        self._require_finite("weight_after", entry.weight_after, asset=asset)
        state = {
            "schema_version": 2,
            "earliest_time_index": book.earliest_time_index.isoformat(),
            "decision_nav": book.decision_nav,
            "fx_rate": None if observed_price is None else entry.price / observed_price,
            "weight_at_decision": order.weight_at_decision,
            "decision_price": order.decision_price,
            "target_shares": order.target_shares,
            "order_shares": order.order_shares,
            "filled_shares": order.filled_shares,
            "fill_fraction": entry.fill_fraction,
            "remaining_shares": order.remaining_shares,
            "cancelled_shares": entry.cancelled_shares,
            "cancel_reason": entry.cancel_reason,
            "held_shares": book.held.get(asset, 0.0),
            "cash": book.cash,
        }
        if bar_state is not None:
            state["bar"] = bar_state
        return {
            "time_index": time_index,
            "rebalance_intent_id": book.intent_id,
            "asset_identifier": asset,
            "target_signal_time_index": book.signal_time_index,
            "event_source": event_source,
            "target_weight": target_weight,
            "weight_before": entry.weight_before,
            "weight_after": entry.weight_after,
            "executed_weight_delta": entry.weight_after - entry.weight_before,
            "remaining_weight_delta": target_weight - entry.weight_after,
            "execution_price": observed_price if traded else None,
            "executed_quantity": entry.shares,
            "executed_notional": entry.shares * entry.price,
            "observed_volume": None if bar_slice is None else bar_slice.observed_volume,
            "observed_available_liquidity": (
                None if bar_slice is None else bar_slice.observed_available_liquidity
            ),
            "strategy_state": json.dumps(state, sort_keys=True, separators=(",", ":")),
            "execution_status": entry.status,
        }

    def recorded_earliest_moment(
        self,
        previous_state: pd.DataFrame | None,
        signal_observations: pd.DataFrame,
    ) -> pd.Timestamp | None:
        """Return the earliest moment of the newest recorded rebalance.

        Its open orders trade at their first eligible price from that moment on, and
        an order without a row is sized again with the last prices before it, so
        prices are read from there rather than from the window start: the valuation
        source's, or the strategy's own bars (#90).
        """
        _target, earliest = self._recorded_target(
            _latest_rows_by_asset(previous_state), signal_observations
        )
        return earliest

    def _recorded_target(
        self,
        latest_rows: dict[str, dict[str, Any]],
        signal_observations: pd.DataFrame,
    ) -> tuple[RebalanceTarget | None, pd.Timestamp | None]:
        """Return the newest target with a recorded row, and its earliest moment.

        Its weights come from the signal that set it, which the signal read seeds
        before the window; without that signal, from the target weights its rows
        recorded.
        """
        rows = [row for row in latest_rows.values() if row.get("rebalance_intent_id")]
        if not rows:
            return None, None
        newest = max(
            rows,
            key=lambda row: (
                self._as_utc_timestamp(row["target_signal_time_index"]),
                self._as_utc_timestamp(row["time_index"]),
            ),
        )
        intent_id = str(newest["rebalance_intent_id"])
        recorded_earliest = self.parse_strategy_state(newest).get("earliest_time_index")
        earliest = None if not recorded_earliest else self._as_utc_timestamp(recorded_earliest)
        for target in self._targets_from_signal_observations(signal_observations):
            if target.intent_id == intent_id:
                return target, earliest
        recorded = {
            asset: float(row["target_weight"])
            for asset, row in latest_rows.items()
            if str(row.get("rebalance_intent_id")) == intent_id
        }
        return (
            RebalanceTarget(
                intent_id=intent_id,
                signal_time_index=self._as_utc_timestamp(newest["target_signal_time_index"]),
                weights=recorded,
            ),
            earliest,
        )

    def _recorded_holdings(
        self,
        latest_rows: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, float], float | None]:
        """Return the shares and cash the latest rows recorded, in the book's unit.

        An asset's shares change only when it fills, and that fill's row records them;
        cash is the one recorded at the newest row. ``None`` cash means rows recorded
        without a book, whose holdings are rebuilt from their weights.
        """
        states = {asset: self.parse_strategy_state(row) for asset, row in latest_rows.items()}
        if not states or any("held_shares" not in state for state in states.values()):
            return {}, None
        newest = max(latest_rows, key=lambda asset: self._as_utc_timestamp(
            latest_rows[asset]["time_index"]
        ))
        return (
            {asset: float(state["held_shares"]) for asset, state in states.items()},
            float(states[newest]["cash"]),
        )

    def _holdings_from_weights(
        self,
        latest_rows: dict[str, dict[str, Any]],
        references: _PriceSeries,
        decision_time: pd.Timestamp,
    ) -> tuple[dict[str, float], float]:
        """Return shares and cash for weights recorded without a book: NAV 1 at the decision."""
        weights = {
            asset: float(row.get("weight_after", 0.0) or 0.0)
            for asset, row in latest_rows.items()
        }
        weights = {asset: weight for asset, weight in weights.items() if abs(weight) > 0.0}
        prices = references.last_prices(set(weights), decision_time)
        missing = sorted(set(weights) - set(prices))
        if missing:
            raise ValueError(
                f"No observed price at or before {decision_time.isoformat()} for "
                f"{', '.join(missing)}; the rebalance cannot value its holdings."
            )
        return (
            {asset: weight / prices[asset] for asset, weight in weights.items()},
            1.0 - sum(weights.values()),
        )

    def _recorded_book(
        self,
        policy: ExecutionPolicy,
        latest_rows: dict[str, dict[str, Any]],
        signal_observations: pd.DataFrame,
        references: _PriceSeries,
        held: dict[str, float],
        cash: float | None,
        unit_value: float | None = None,
    ) -> tuple[RebalanceBook | None, dict[str, pd.Timestamp]]:
        """Rebuild the newest recorded rebalance's book, and when each order last stepped.

        An order with a row of the rebalance resumes from it. Any other order is sized
        again as at the decision: its shares have not changed since, and its decision
        price is the last price observed before the earliest moment.
        """
        target, earliest = self._recorded_target(latest_rows, signal_observations)
        if target is None or earliest is None or cash is None:
            return None, {}
        own_rows = {
            asset: row
            for asset, row in latest_rows.items()
            if str(row.get("rebalance_intent_id")) == target.intent_id
        }
        states = {asset: self.parse_strategy_state(row) for asset, row in own_rows.items()}
        decision_time = earliest - pd.Timedelta(1, unit="ns")
        book = RebalanceBook(
            intent_id=target.intent_id,
            signal_time_index=target.signal_time_index,
            earliest_time_index=earliest,
            target_weights={asset: float(value) for asset, value in target.weights.items()},
            cash=cash,
            held={asset: shares for asset, shares in held.items() if abs(shares) > 0.0},
            decision_nav=float(next(iter(states.values()))["decision_nav"]),
            unit_value=unit_value,
        )
        assets = (
            set(book.held)
            | {asset for asset, weight in book.target_weights.items() if abs(weight) > 0.0}
            | set(own_rows)
        )
        decision_prices = references.last_prices(assets - set(own_rows), decision_time)
        after: dict[str, pd.Timestamp] = {}
        for asset in sorted(assets):
            if asset in own_rows:
                state = states[asset]
                order_shares = state.get("order_shares")
                order = BookOrder(
                    weight_at_decision=float(state["weight_at_decision"]),
                    decision_price=float(state["decision_price"]),
                    target_shares=state.get("target_shares"),
                    order_shares=order_shares,
                    remaining_shares=float(state.get("remaining_shares") or 0.0),
                    filled_shares=float(state.get("filled_shares") or 0.0),
                    side=_order_side(order_shares),
                    status=_ORDER_STATUS[str(own_rows[asset]["execution_status"])],
                )
                after[asset] = self._as_utc_timestamp(own_rows[asset]["time_index"])
            else:
                price = decision_prices.get(asset)
                if price is None:
                    raise ValueError(
                        f"No observed price for {asset} before the rebalance's earliest "
                        f"moment {earliest.isoformat()}; its shares cannot be sized."
                    )
                shares = book.held.get(asset, 0.0)
                weight = shares * price / book.decision_nav
                order = BookOrder(weight_at_decision=weight, decision_price=price)
                target_weight = book.target_weights.get(asset, 0.0)
                if policy.sizing == "at_decision":
                    order.size(target_weight * book.decision_nav / price, shares)
                else:
                    order.side = _order_side(target_weight - weight)
                after[asset] = decision_time
            book.orders[asset] = order
        return book, after

    def _transitions_at_own_bars(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
        previous_state: pd.DataFrame | None,
        input_name: str,
        price_column: str,
        book_unit_value: float | None,
    ) -> pd.DataFrame:
        """Run the execution policy at the strategy's own bars; write a row per order step.

        A bar trades only toward a signal observed strictly before it. A new target's
        earliest moment is the first of the strategy's events at which it is the latest
        signal, and its order is fixed at the decision, the instant before, with each
        asset's last bar strictly before the earliest moment: target weight x NAV /
        price (#90). At every bar the strategy's ``bar_slices`` decide how much of each
        open order may trade there; the ``fill_policy`` books the slices with its cash
        rules. An asset trades only at its own observed bar, at that bar's price; rows
        flagged ``interpolated`` never fill, though they value the book and size the
        decision as the ledger values the portfolio. A newer target replaces the running
        rebalance at its earliest moment. ``previous_state`` holds the latest row of
        every asset: a resumed run rebuilds the book from it.
        """
        policy = self.fill_policy()
        raw_bars = observed_inputs.get(input_name)
        references = _PriceSeries(valuation_prices(raw_bars, price_column=price_column))
        fills = _PriceSeries(observed_prices(raw_bars, price_column=price_column))
        observed = {**observed_inputs, input_name: _without_interpolated(raw_bars)}
        events = self._normalize_events(
            self.select_events(
                start,
                end,
                signal_observations=signal_observations,
                observed_inputs=observed,
            )
        )
        if events.empty:
            return pd.DataFrame()
        latest_rows = _latest_rows_by_asset(previous_state)
        held, cash = self._recorded_holdings(latest_rows)
        book, after = self._recorded_book(
            policy, latest_rows, signal_observations, references, held, cash, book_unit_value
        )
        bar_states = {
            asset: dict(self.parse_strategy_state(row).get("bar") or {})
            for asset, row in latest_rows.items()
        }
        targets = self._targets_from_signal_observations(signal_observations)
        execution_context = self.prepare_execution_context(
            events=events, observed_inputs=observed
        )
        observations_by_event = self._observations_by_event(
            observed, event_times=pd.DatetimeIndex(events["time_index"])
        )
        rows: list[dict[str, Any]] = []
        next_target = 0
        latest: RebalanceTarget | None = None
        for event in events.to_dict(orient="records"):
            event_time = self._as_utc_timestamp(event["time_index"])
            event_source = str(event["event_source"])
            while (
                next_target < len(targets)
                and targets[next_target].signal_time_index < event_time
            ):
                latest = targets[next_target]
                next_target += 1
            if latest is not None and (
                book is None or latest.signal_time_index > book.signal_time_index
            ):
                if self.signal_expired(latest.signal_time_index, event_time):
                    # The latest signal is the only candidate and it is too old: nothing
                    # trades, and a running rebalance of an older signal stops too.
                    if book is not None:
                        rows.extend(
                            self._expired_rows(
                                book,
                                event_time,
                                references,
                                event_source=event_source,
                                bar_states=bar_states,
                            )
                        )
                    continue
                decision_time = event_time - pd.Timedelta(1, unit="ns")
                if book is not None:
                    held, cash = dict(book.held), book.cash
                elif cash is None:
                    held, cash = self._holdings_from_weights(
                        latest_rows, references, decision_time
                    )
                book = policy.open_book(
                    intent_id=latest.intent_id,
                    signal_time_index=latest.signal_time_index,
                    earliest_time_index=event_time,
                    target_weights=latest.weights,
                    held=held,
                    cash=cash,
                    decision_prices=references.last_prices(
                        set(held) | set(latest.weights), decision_time
                    ),
                    unit_value=book_unit_value,
                )
                after = {asset: decision_time for asset in book.orders}
            if book is None:
                continue
            if self.signal_expired(book.signal_time_index, event_time):
                rows.extend(
                    self._expired_rows(
                        book,
                        event_time,
                        references,
                        event_source=event_source,
                        bar_states=bar_states,
                    )
                )
                continue
            due = {
                asset: price
                for asset, order in book.orders.items()
                if order.status == "open"
                and event_time > after[asset]
                and (price := fills.price_at(asset, event_time)) is not None
            }
            if not due:
                continue
            last_prices = references.last_prices(set(book.held) | set(due), event_time)
            # An order sized at its fill is sized before the strategy slices it.
            policy.size_at_fill(book, fill_prices=due, nav=book.nav(last_prices))
            slices = self.bar_slices(
                event_time=event_time,
                event_observations={
                    name: grouped.get(event_time, pd.DataFrame())
                    for name, grouped in observations_by_event.items()
                },
                book=book,
                prices=due,
                bar_states=bar_states,
                execution_context=execution_context,
            )
            entries = policy.step(
                book,
                time_index=event_time,
                fill_prices=due,
                last_prices=last_prices,
                slices={asset: slices[asset].shares for asset in due},
            )
            for asset in due:
                after[asset] = event_time
            for entry in entries:
                asset = entry.asset_identifier
                bar_states[asset] = {
                    **self.bar_state(bar_slice=slices[asset], entry=entry, book=book),
                    "slice_shares": slices[asset].shares,
                }
                rows.append(
                    self._book_row(
                        book,
                        entry,
                        event_time,
                        due[asset],
                        event_source=event_source,
                        bar_slice=slices[asset],
                        bar_state=bar_states[asset],
                    )
                )
        return pd.DataFrame(rows)

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


@update_configuration.serialize_argument.register(RebalanceStrategyBase)
def _serialize_rebalance_strategy(value: RebalanceStrategyBase) -> dict[str, Any]:
    """Serialize a strategy for MetaTables identities as any pydantic model is.

    MetaTables writes every field, also one the model leaves out of its own dump. A
    strategy without a ``signal_lifetime`` is written without it, so it keeps the
    portfolio and update identities it had before the field existed; a lifetime is
    hashed (#114).
    """
    serialized = update_configuration.serialize_argument.dispatch(BaseModel)(value)
    if value.signal_lifetime is None:
        serialized["serialized_model"].pop("signal_lifetime")
    return serialized


def earliest_moment(
    moment: pd.Timestamp,
    sessions: pd.DataFrame | None,
) -> pd.Timestamp | None:
    """Return the earliest moment a target set at ``moment`` may trade.

    Without a calendar it is ``moment``. With one, it is ``moment`` while a session
    is open (``market_open <= moment <= market_close``), otherwise the next published
    ``market_open``, or ``None`` when that open is not published yet. ``sessions``
    is in session order: a close and the next open at one instant (24/7) put the
    open last, so that instant is in session.
    """
    moment = RebalanceStrategyBase._as_utc_timestamp(moment)
    if sessions is None:
        return moment
    times = pd.DatetimeIndex(pd.to_datetime(sessions["time_index"], utc=True))
    types = sessions["event_type"].astype(str).to_numpy()
    latest = int(times.searchsorted(moment, side="right")) - 1
    if latest >= 0 and (types[latest] == "market_open" or times[latest] == moment):
        return moment
    opens = times[types == "market_open"]
    position = int(opens.searchsorted(moment, side="right"))
    return opens[position] if position < len(opens) else None


UNOBSERVED_PRICE_COLUMNS = frozenset({"open", "high", "low", "vwap"})


def require_observed_price_column(price_column: str) -> None:
    """Refuse a fill column whose value was not observed at its row's ``time_index``.

    A bar is stamped at its end. Its close, or a mark, was observed then; its
    open, high, low and VWAP describe the interval before it.
    """
    if str(price_column).strip().lower() in UNOBSERVED_PRICE_COLUMNS:
        raise ValueError(
            f"{price_column!r} cannot be a fill price: a trade's price must be observed at "
            "its row's time_index, as a close or a mark is. Open, high, low and VWAP "
            "describe the bar's interval."
        )


def in_session(times: pd.DatetimeIndex, sessions: pd.DataFrame | None) -> np.ndarray:
    """Return which ``times`` fall inside a session: ``market_open < t <= market_close``.

    A bar is stamped at its end, so a row stamped exactly at an open is not inside
    the session it opens. Without a calendar every time counts. ``times`` are compared
    in UTC, so an empty selection (whose times have no timezone) holds no time.
    """
    times = pd.DatetimeIndex(pd.to_datetime(times, utc=True))
    if sessions is None:
        return np.ones(len(times), dtype=bool)
    event_times = pd.DatetimeIndex(pd.to_datetime(sessions["time_index"], utc=True))
    event_types = sessions["event_type"].astype(str).to_numpy()
    positions = event_times.as_unit("ns").searchsorted(times.as_unit("ns"), side="left") - 1
    inside = np.zeros(len(times), dtype=bool)
    known = positions >= 0
    inside[known] = event_types[positions[known]] == "market_open"
    return inside


def observed_prices(frame: pd.DataFrame | None, *, price_column: str) -> pd.DataFrame:
    """Return the observed prices of an asset-indexed source for trading.

    The result has ``time_index``, ``asset_identifier`` and ``price``. Rows flagged
    ``interpolated`` are not observations and never count, and rows without a
    finite positive price are left out. ``price_column`` must be observed at its
    row's time: open, high, low and VWAP are refused.
    """
    require_observed_price_column(price_column)
    columns = ["time_index", ASSET_IDENTIFIER_DIMENSION, "price"]
    flat = _without_interpolated(frame)
    if flat.empty:
        return pd.DataFrame(columns=columns)
    flat = flat.reset_index() if list(flat.index.names) != [None] else flat.copy()
    missing = [
        column
        for column in ("time_index", ASSET_IDENTIFIER_DIMENSION, price_column)
        if column not in flat.columns
    ]
    if missing:
        raise ValueError("Observed prices are missing columns: " + ", ".join(missing))
    price = pd.to_numeric(flat[price_column], errors="coerce").astype("float64")
    result = pd.DataFrame(
        {
            "time_index": pd.to_datetime(flat["time_index"], utc=True),
            ASSET_IDENTIFIER_DIMENSION: flat[ASSET_IDENTIFIER_DIMENSION].astype(str),
            "price": price,
        }
    )
    result = result[result["price"].notna() & (result["price"] > 0.0)]
    result = result[result["price"].map(math.isfinite)]
    return (
        result.sort_values(["time_index", ASSET_IDENTIFIER_DIMENSION], kind="stable")
        .drop_duplicates(subset=["time_index", ASSET_IDENTIFIER_DIMENSION], keep="last")
        .reset_index(drop=True)
    )


def valuation_prices(frame: pd.DataFrame | None, *, price_column: str) -> pd.DataFrame:
    """Return the prices that value the portfolio: every row, interpolated ones too.

    Same shape as ``observed_prices``. A rebalance values its holdings and sizes its
    decision with them, as the ledger values the portfolio; it never fills at them.
    """
    require_observed_price_column(price_column)
    columns = ["time_index", ASSET_IDENTIFIER_DIMENSION, "price"]
    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)
    flat = frame.reset_index() if list(frame.index.names) != [None] else frame.copy()
    unflagged = flat.drop(columns=["interpolated"], errors="ignore")
    return observed_prices(unflagged, price_column=price_column)


def _without_interpolated(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Drop rows flagged ``interpolated``: they are not observed prices."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    if "interpolated" not in frame.columns:
        return frame
    flags = frame["interpolated"].astype("boolean").fillna(False).astype(bool)
    return frame[~flags.to_numpy()]


class PriceConversion:
    """Prices into the portfolio's currency at the last observed FX rate (ADR 0059).

    ``currencies`` maps each asset to its quote currency; an asset missing from it, or
    quoted in ``valuation_asset_identifier``, needs no rate. ``fx_rates`` has
    ``time_index``, ``base_asset_identifier``, ``quote_asset_identifier`` and ``rate``:
    one unit of the base is ``rate`` units of the quote. A rate never observed at or
    before the time it is needed raises.
    """

    def __init__(
        self,
        *,
        valuation_asset_identifier: str,
        currencies: dict[str, str],
        fx_rates: pd.DataFrame | None,
    ) -> None:
        self.valuation_asset_identifier = str(valuation_asset_identifier)
        self.currencies = {str(asset): str(currency) for asset, currency in currencies.items()}
        self._rates: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        flat = pd.DataFrame() if fx_rates is None or fx_rates.empty else fx_rates.reset_index()
        if flat.empty:
            return
        flat = flat[flat["quote_asset_identifier"].astype(str) == self.valuation_asset_identifier]
        flat = flat.assign(
            time_index=pd.to_datetime(flat["time_index"], utc=True),
            rate=pd.to_numeric(flat["rate"], errors="coerce").astype("float64"),
        ).sort_values("time_index", kind="stable")
        if not (flat["rate"].map(math.isfinite) & (flat["rate"] > 0.0)).all():
            raise ValueError("FX rates must be finite and strictly positive.")
        for currency, group in flat.groupby("base_asset_identifier", sort=True):
            self._rates[str(currency)] = (
                pd.DatetimeIndex(group["time_index"]).as_unit("ns").asi8,
                group["rate"].to_numpy(dtype="float64"),
            )

    def rate(self, asset: str, time_index: pd.Timestamp) -> float:
        currency = self.currencies.get(str(asset), self.valuation_asset_identifier)
        if currency == self.valuation_asset_identifier:
            return 1.0
        stamp = _PriceSeries._nanoseconds(time_index)
        series = self._rates.get(currency)
        position = (
            -1 if series is None else int(np.searchsorted(series[0], stamp, side="right")) - 1
        )
        if position < 0:
            raise ValueError(
                f"No FX rate from {currency} into {self.valuation_asset_identifier} observed "
                f"at or before {RebalanceStrategyBase._as_utc_timestamp(time_index).isoformat()}"
                f", needed for {asset}."
            )
        return float(series[1][position])


_ORDER_STATUS = {
    "partial": "open",
    "complete": "filled",
    "cancelled": "cancelled",
    "expired": "expired",
}


def _latest_rows_by_asset(previous_state: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """Return each asset's latest recorded row, whatever its status."""
    if previous_state is None or previous_state.empty:
        return {}
    flat = previous_state.reset_index().copy()
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
    latest = (
        flat.sort_values("time_index", kind="stable")
        .groupby(ASSET_IDENTIFIER_DIMENSION, sort=False)
        .tail(1)
    )
    return {
        str(row[ASSET_IDENTIFIER_DIMENSION]): row for row in latest.to_dict(orient="records")
    }


class _PriceSeries:
    """Each asset's prices in time order: the last one at a time, or the first after it."""

    def __init__(
        self,
        prices: pd.DataFrame | None,
        *,
        conversion: PriceConversion | None = None,
    ) -> None:
        self._conversion = conversion
        self._by_asset: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        if prices is None or prices.empty:
            return
        frame = prices.copy()
        frame["time_index"] = pd.to_datetime(frame["time_index"], utc=True)
        frame = frame.sort_values("time_index", kind="stable").drop_duplicates(
            subset=["time_index", ASSET_IDENTIFIER_DIMENSION], keep="last"
        )
        for asset, group in frame.groupby(ASSET_IDENTIFIER_DIMENSION, sort=True):
            self._by_asset[str(asset)] = (
                pd.DatetimeIndex(group["time_index"]).as_unit("ns").asi8,
                group["price"].to_numpy(dtype="float64"),
            )

    @staticmethod
    def _nanoseconds(time_index: pd.Timestamp) -> int:
        return int(RebalanceStrategyBase._as_utc_timestamp(time_index).as_unit("ns").value)

    def last_prices(self, assets: Any, time_index: pd.Timestamp) -> dict[str, float]:
        """Return each asset's last price at or before ``time_index``, when it has one.

        With a conversion, the price is in the portfolio's currency at the last FX rate
        observed at or before ``time_index``.
        """
        stamp = self._nanoseconds(time_index)
        result: dict[str, float] = {}
        for asset in sorted(assets):
            series = self._by_asset.get(str(asset))
            if series is None:
                continue
            position = int(np.searchsorted(series[0], stamp, side="right")) - 1
            if position >= 0:
                rate = (
                    1.0
                    if self._conversion is None
                    else self._conversion.rate(str(asset), time_index)
                )
                result[str(asset)] = float(series[1][position]) * rate
        return result

    def price_at(self, asset: str, time_index: pd.Timestamp) -> float | None:
        series = self._by_asset.get(asset)
        if series is None:
            return None
        stamp = self._nanoseconds(time_index)
        position = int(np.searchsorted(series[0], stamp, side="left"))
        if position < len(series[0]) and series[0][position] == stamp:
            return float(series[1][position])
        return None

    def first_time(
        self,
        asset: str,
        *,
        at_or_after: pd.Timestamp,
        strictly_after: pd.Timestamp,
    ) -> pd.Timestamp | None:
        series = self._by_asset.get(asset)
        if series is None:
            return None
        position = max(
            int(np.searchsorted(series[0], self._nanoseconds(at_or_after), side="left")),
            int(np.searchsorted(series[0], self._nanoseconds(strictly_after), side="right")),
        )
        if position >= len(series[0]):
            return None
        return pd.Timestamp(int(series[0][position]), unit="ns", tz="UTC")


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
    "AssetExecution",
    "BarSlice",
    "ExecutionStatus",
    "PriceConversion",
    "RebalanceDependency",
    "RebalanceInputContract",
    "RebalanceStrategyBase",
    "RebalanceTarget",
    "dependency_events",
    "earliest_moment",
    "in_session",
    "observed_prices",
    "require_observed_price_column",
    "valuation_prices",
]
