import datetime as dt
from typing import Literal

import pandas as pd
from pydantic import Field, model_validator

from metatables import TimeIndexTableRef, TimeIndexTableUpdater
from msm_portfolios.rebalance_strategy.base import (
    RebalanceInputContract,
    RebalanceStrategyBase,
)
from msm_portfolios.rebalance_strategy.execution_policy import ExecutionPolicy

CALENDAR_EVENTS_DEPENDENCY = "calendar_events"
SESSION_EVENT_TYPES: tuple[str, str] = ("market_open", "market_close")
_EVENT_ORDER = {"market_open": 0, "market_close": 1}


class ImmediateSignal(RebalanceStrategyBase):
    """Rebalance to every new signal at the next price the portfolio could trade at.

    A signal is the application's target weights and can arrive at any hour. The
    strategy's moment is the signal's ``time_index``. The earliest moment it may
    trade is that time while the portfolio calendar is in session
    (``market_open <= t <= market_close``), otherwise the calendar's next
    ``market_open``. Each asset then trades at its first observed price in the
    portfolio's valuation source at or after the earliest moment and strictly
    after the signal (ADR 0058). On a 24/7 calendar the earliest moment is always
    the signal's time.

    Those are facts. The choices (when shares are sized, how much negative cash is
    allowed, sells before buys, how buys share too little cash, what happens to a
    buy cash cannot cover, and whether the portfolio calendar gates trading) are
    the ``execution_policy``, whose defaults are the owner's decisions.

    The calendar is the declared ``calendar_events`` dependency, which must
    publish both ``market_open`` and ``market_close`` and be the portfolio's
    ``calendar_uid`` (ADR 0056). It publishes events only up to the time it runs,
    so a target set while the market is closed waits until the next open has been
    published.
    """

    timing_mode: Literal["signal_time"] = "signal_time"
    calendar_events_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        ...,
        description=(
            "Published time-indexed calendar-event dependency. Its observation timestamps "
            "are the unshifted persisted events; the required fields identify calendar, "
            "session, event type, and local session date."
        ),
    )
    calendar_identifier: str = Field(
        ...,
        min_length=1,
        description="Calendar identifier selected from the declared event dependency.",
        examples=["XNYS", "CRYPTO_24_7"],
    )
    session_label: str = Field(
        "regular",
        min_length=1,
        description="Persisted calendar session label eligible for execution.",
    )
    signal_selection: Literal["latest_at_or_before_event"] = "latest_at_or_before_event"
    execution_policy: ExecutionPolicy = Field(
        default_factory=ExecutionPolicy,
        description=(
            "Execution choices for trading at the next observed price (ADR 0058): "
            "sizing time, negative cash limit, sells before buys, cash shortfall "
            "allocation, uncovered buys, and calendar gating."
        ),
    )

    @model_validator(mode="after")
    def _require_session_events(self) -> "ImmediateSignal":
        """Refuse a calendar dependency configured to publish only one event type.

        An updater that exposes ``config.event_types`` (``PortfolioCalendarEvents``)
        is checked here. A read-only table reference is checked when its events are
        read, in ``session_events``.
        """
        configured = getattr(
            getattr(self.calendar_events_instance, "config", None),
            "event_types",
            None,
        )
        if configured is None:
            return self
        missing = [event for event in SESSION_EVENT_TYPES if event not in tuple(configured)]
        if missing:
            raise ValueError(
                f"{self.__class__.__name__} needs a calendar_events_instance that publishes "
                "both market_open and market_close, to know when the market is in session; "
                f"this one does not publish {', '.join(missing)}."
            )
        return self

    def get_explanation(self):
        return (
            "ImmediateSignal: rebalances to every new signal. Each asset trades at its first "
            "observed price strictly after the signal, once calendar "
            f"{self.calendar_identifier!r} ({self.session_label}) is in session."
        )

    def declared_dependencies(
        self,
    ) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        return {CALENDAR_EVENTS_DEPENDENCY: self.calendar_events_instance}

    def fill_policy(self) -> ExecutionPolicy:
        return self.execution_policy

    def required_input_contract(self) -> dict[str, RebalanceInputContract]:
        return {
            CALENDAR_EVENTS_DEPENDENCY: RebalanceInputContract(
                index_names=(
                    "time_index",
                    "calendar_identifier",
                    "session_label",
                    "event_type",
                ),
                required_columns=("local_date",),
            )
        }

    def dependency_seed_coordinates(
        self,
        dependency_name: str,
    ) -> tuple[dict[str, str], ...]:
        if dependency_name != CALENDAR_EVENTS_DEPENDENCY:
            return super().dependency_seed_coordinates(dependency_name)
        return tuple(
            {
                "calendar_identifier": self.calendar_identifier,
                "session_label": self.session_label,
                "event_type": event_type,
            }
            for event_type in SESSION_EVENT_TYPES
        )

    def session_events(
        self,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        return self._session_events(observed_inputs.get(CALENDAR_EVENTS_DEPENDENCY))

    def select_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        *,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        """Return each signal observed in the window: the strategy's moments."""
        del observed_inputs
        empty = pd.DataFrame(columns=["time_index", "event_source"])
        if signal_observations is None or signal_observations.empty:
            return empty
        signal_times = (
            pd.DatetimeIndex(
                pd.to_datetime(
                    signal_observations.index.get_level_values("time_index"),
                    utc=True,
                ),
                name="time_index",
            )
            .unique()
            .sort_values()
        )
        start_ts = self._as_utc_timestamp(start)
        end_ts = self._as_utc_timestamp(end)
        signal_times = signal_times[(signal_times >= start_ts) & (signal_times <= end_ts)]
        return pd.DataFrame({"time_index": signal_times, "event_source": "signal_weights"})

    def _session_events(self, frame: pd.DataFrame | None) -> pd.DataFrame:
        """Return this calendar's opens and closes in session order, checked to alternate."""
        label = f"calendar {self.calendar_identifier!r}, session {self.session_label!r}"
        flat = pd.DataFrame() if frame is None else frame.reset_index()
        if not flat.empty:
            flat = flat[
                (flat["calendar_identifier"].astype(str) == self.calendar_identifier)
                & (flat["session_label"].astype(str) == self.session_label)
                & (flat["event_type"].astype(str).isin(SESSION_EVENT_TYPES))
            ].copy()
        if flat.empty:
            raise ValueError(
                f"{self.__class__.__name__} found no published market_open or market_close "
                f"for {label} in its calendar_events dependency. Publish the calendar's "
                "events before rebalancing the portfolio."
            )
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        flat["event_type"] = flat["event_type"].astype(str)
        flat["local_date"] = flat["local_date"].astype(str)
        flat["_order"] = flat["event_type"].map(_EVENT_ORDER)
        # A 24/7 session closes at the instant the next one opens. Ordering ties by
        # local date puts that close before the open, so the open is the latest event.
        flat = flat.sort_values(["time_index", "local_date", "_order"], kind="stable")
        types = flat["event_type"].tolist()
        times = flat["time_index"].tolist()
        for position in range(1, len(types)):
            if types[position] == types[position - 1]:
                raise ValueError(
                    f"{self.__class__.__name__} needs a calendar_events dependency that "
                    "publishes both market_open and market_close, one pair per session. "
                    f"For {label} it read two {types[position]} events in a row, at "
                    f"{times[position - 1].isoformat()} and {times[position].isoformat()}."
                )
        return flat[["time_index", "event_type"]].reset_index(drop=True)


__all__ = ["ImmediateSignal"]
