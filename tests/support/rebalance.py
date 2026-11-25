"""Published tables and strategies for running rebalances at the next observed price.

`tests/msm_portfolios/time_index/test_next_observed_price.py` (issue #89, ADR 0058) and
`test_execution_policy.py` define these; the currency, signal-lifetime and bar-strategy
tests reuse them.
"""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pandas as pd

from metatables import TimeIndexMetaTable, TimeIndexTableUpdater
from msm_portfolios.accounting import MarketPriceValuationModel, PortfolioAccountingConfiguration
from msm_portfolios.rebalance_strategy import (
    ImmediateSignal,
    InstrumentExecutionSpec,
    TargetWeightExecutionModel,
    observed_prices,
)
from msm_portfolios.time_index.constants import ASSET_IDENTIFIER
from msm_portfolios.time_index.portfolios.accounting import PortfolioEngine
from msm_portfolios.time_index.portfolios.rebalance import (
    PortfolioRebalance,
    read_rebalance_input,
)

EVENT_INDEX = ["time_index", "calendar_identifier", "session_label", "event_type"]
SIGNAL_UID = "signal-a"


def utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def output_table_stub(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        get_time_index_meta_table=lambda: TimeIndexMetaTable.model_construct(
            uid=f"{name}-table",
            data_source_uid="source",
        ),
        get_data_source_uid=lambda: "source",
        get_meta_table_uid=lambda: f"{name}-table",
    )


def nyse_sessions(first: str, last: str) -> list[tuple[dt.date, pd.Timestamp, pd.Timestamp]]:
    """NYSE regular sessions in UTC: Thanksgiving closed, half day after it."""
    holidays = {dt.date(2026, 11, 26)}
    early_closes = {dt.date(2026, 11, 27): "18:00"}
    sessions = []
    for day in pd.date_range(first, last, freq="D"):
        local = day.date()
        if local.weekday() >= 5 or local in holidays:
            continue
        close = early_closes.get(local, "21:00")
        sessions.append((local, utc(f"{local}T14:30:00Z"), utc(f"{local}T{close}:00Z")))
    return sessions


NYSE = nyse_sessions("2026-11-09", "2026-11-30")


class PublishedCalendarEvents(TimeIndexTableUpdater):
    """Calendar events as PortfolioCalendarEvents stores them, published up to a run time."""

    def update(self) -> pd.DataFrame:
        return pd.DataFrame()

    def dependencies(self) -> dict:
        return {}

    @classmethod
    def build(
        cls,
        *,
        calendar_identifier: str,
        sessions,
        published_until: str,
        event_types: tuple[str, ...] = ("market_open", "market_close"),
    ) -> PublishedCalendarEvents:
        source = object.__new__(cls)
        source.update_hash = f"calendar-events-{calendar_identifier}"
        source._output_table = output_table_stub("calendar-events")
        source.update_statistics = None
        source.rows = pd.DataFrame(
            [
                {
                    "time_index": timestamp,
                    "calendar_identifier": calendar_identifier,
                    "session_label": "regular",
                    "event_type": event_type,
                    "local_date": local_date.isoformat(),
                }
                for local_date, opens_at, closes_at in sessions
                for event_type, timestamp in (
                    ("market_open", opens_at),
                    ("market_close", closes_at),
                )
                if event_type in event_types
            ]
        )
        source.published_until = utc(published_until)
        source.seed_calls = []
        return source

    def _published(self) -> pd.DataFrame:
        return self.rows[self.rows["time_index"] <= self.published_until]

    def get_df_between_dates(
        self,
        *,
        start_date=None,
        end_date=None,
        great_or_equal=True,
        less_or_equal=True,
        dimension_filters=None,
        **_kwargs,
    ) -> pd.DataFrame:
        frame = self._published()
        times = frame["time_index"]
        mask = pd.Series(True, index=frame.index)
        if start_date is not None:
            start = pd.Timestamp(start_date)
            mask &= times >= start if great_or_equal else times > start
        if end_date is not None:
            end = pd.Timestamp(end_date)
            mask &= times <= end if less_or_equal else times < end
        for name, values in (dimension_filters or {}).items():
            mask &= frame[name].isin(values)
        return frame[mask].set_index(EVENT_INDEX)

    def get_last_observation(self, *, dimension_filters=None, dimension_range_map=None, **_):
        self.seed_calls.append(dimension_range_map)
        published = self._published()
        selected = []
        for entry in dimension_range_map or []:
            end = pd.Timestamp(entry["end_date"])
            times = published["time_index"]
            mask = times <= end if entry["end_date_operand"] == "<=" else times < end
            for name, value in entry["coordinate"].items():
                mask &= published[name] == value
            selected.append(published[mask].sort_values("time_index").tail(1))
        return pd.concat(selected).set_index(EVENT_INDEX)


class PublishedTable(TimeIndexTableUpdater):
    """An asset-indexed published table read by window, visible up to ``published_until``.

    A row is visible once ``published_until`` reaches its ``published_at`` when it has
    one (a slow source), otherwise its ``time_index``.
    """

    def update(self) -> pd.DataFrame:
        return pd.DataFrame()

    def dependencies(self) -> dict:
        return {}

    @classmethod
    def build(cls, name: str, frame: pd.DataFrame, *, index: list[str]) -> PublishedTable:
        source = object.__new__(cls)
        source.update_hash = name
        source._output_table = output_table_stub(name)
        source.update_statistics = None
        source.rows = frame.reset_index() if "time_index" not in frame.columns else frame.copy()
        source.rows["time_index"] = pd.to_datetime(source.rows["time_index"], utc=True)
        source.index = index
        source.published_until = pd.Timestamp.max.tz_localize("UTC")
        return source

    def _published(self) -> pd.DataFrame:
        stamp = "published_at" if "published_at" in self.rows.columns else "time_index"
        return self.rows[self.rows[stamp] <= self.published_until]

    def get_df_between_dates(
        self,
        *,
        start_date=None,
        end_date=None,
        dimension_filters=None,
        **_kwargs,
    ) -> pd.DataFrame:
        frame = self._published()
        times = frame["time_index"]
        mask = pd.Series(True, index=frame.index)
        if start_date is not None:
            mask &= times >= pd.Timestamp(start_date)
        if end_date is not None:
            mask &= times <= pd.Timestamp(end_date)
        for name, values in (dimension_filters or {}).items():
            mask &= frame[name].astype(str).isin([str(value) for value in values])
        return frame[mask].set_index(self.index)

    def first_observation_time(self) -> pd.Timestamp | None:
        """The first visible row's time, as a signal answers its first observation."""
        frame = self._published()
        return None if frame.empty else utc(frame["time_index"].min())

    def get_last_observation(self, *, dimension_range_map, **_kwargs) -> pd.DataFrame:
        frame = self._published()
        selected = []
        for entry in dimension_range_map:
            end = pd.Timestamp(entry["end_date"])
            times = frame["time_index"]
            mask = times <= end if entry["end_date_operand"] == "<=" else times < end
            for name, value in entry["coordinate"].items():
                mask &= frame[name].astype(str) == str(value)
            selected.append(frame[mask].sort_values("time_index").tail(1))
        return pd.concat(selected).set_index(self.index)


def signal_frame(rows: list[tuple[str, dict[str, float]]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            (utc(time_index), SIGNAL_UID, asset, weight)
            for time_index, weights in rows
            for asset, weight in weights.items()
        ],
        columns=["time_index", "signal_uid", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", "signal_uid", ASSET_IDENTIFIER])


def run_strategy(
    strategy,
    *,
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Read the calendar input as the updaters do and run the strategy once."""
    calendar_input = read_rebalance_input(
        strategy.calendar_events_instance,
        dependency_name="calendar_events",
        contract=strategy.required_input_contract()["calendar_events"],
        start=utc(start),
        end=utc(end),
        seed_coordinates=strategy.dependency_seed_coordinates("calendar_events"),
    )
    return strategy.build_transitions(
        start=utc(start),
        end=utc(end),
        signal_observations=signals,
        observed_inputs={"calendar_events": calendar_input},
        previous_state=None,
        fill_prices=observed_prices(prices, price_column="close"),
    )


def calendar(identifier: str = "XNYS", sessions=NYSE) -> PublishedCalendarEvents:
    return PublishedCalendarEvents.build(
        calendar_identifier=identifier,
        sessions=sessions,
        published_until="2026-11-30T23:00:00Z",
    )


class IncrementalRebalance:
    """Drive ``PortfolioRebalance.update()`` run after run against published inputs."""

    def __init__(
        self,
        *,
        strategy,
        signals: PublishedTable,
        prices: PublishedTable,
        storage,
        assets: tuple[str, ...] = ("AAPL", "ILLQ"),
        unit_value: float = 10_000.0,
    ):
        self.strategy = strategy
        self.signals = signals
        self.prices = prices
        self.persisted = pd.DataFrame()
        node = object.__new__(PortfolioRebalance)
        node._portfolio_configuration = SimpleNamespace()
        node._portfolio_identifier = "portfolio"
        signals.signal_uid = SIGNAL_UID
        # The rebalance reads the signal and never runs it: a computed signal is its own
        # node, which ran before it.
        node.signal_weights = signals
        node.rebalance_strategy = strategy
        node.valuation_source = prices
        node.valuation_column = "close"
        node.valuation_asset_identifier = "USD"
        node.fx_source = None
        # The book's unit, the ledger's initial NAV (ADR 0065).
        node.book_unit_value = unit_value
        node.output_table = storage
        node._retirement_boundary = lambda: None
        node._required_asset_identifiers = lambda: list(assets)
        node.get_last_observation = self._last_observation
        node.get_df_between_dates = self._rows_between
        self.node = node

    def _rows_between(self, *, start_date, end_date, **_kwargs) -> pd.DataFrame:
        times = self.persisted.index.get_level_values("time_index")
        return self.persisted[(times >= start_date) & (times <= end_date)]

    def _statistics(self) -> SimpleNamespace:
        """Update statistics as MetaTables keeps them: the latest time per index path."""
        if self.persisted.empty:
            return SimpleNamespace(index_progress=None, max_time_index_value=None)
        flat = self.persisted.reset_index()
        progress: dict = {}
        for row in flat.to_dict(orient="records"):
            by_asset = progress.setdefault(row["portfolio_identifier"], {}).setdefault(
                row["rebalance_intent_id"], {}
            )
            current = by_asset.get(row[ASSET_IDENTIFIER])
            by_asset[row[ASSET_IDENTIFIER]] = (
                row["time_index"] if current is None else max(current, row["time_index"])
            )
        return SimpleNamespace(
            index_progress=progress,
            max_time_index_value=flat["time_index"].max(),
        )

    def _last_observation(self, *, dimension_range_map, **_kwargs) -> pd.DataFrame:
        flat = self.persisted.reset_index()
        selected = []
        for entry in dimension_range_map:
            mask = flat["time_index"] <= pd.Timestamp(entry["end_date"])
            for name, value in entry["coordinate"].items():
                mask &= flat[name] == value
            selected.append(flat[mask].sort_values("time_index").tail(1))
        return pd.concat(selected).set_index(self.persisted.index.names)

    def run(self, at: str) -> pd.DataFrame:
        run_time = utc(at)
        sources = (*self.strategy.declared_dependencies().values(), self.signals, self.prices)
        for source in sources:
            source.published_until = run_time
        node = self.node
        node.update_statistics = self._statistics()
        node._execution_window = lambda latest, **kwargs: (
            PortfolioRebalance._execution_window(node, latest, **kwargs)[0],
            run_time,
        )
        written = node.update()
        if not written.empty:
            self.persisted = pd.concat([self.persisted, written]).sort_index()
        return written


def stock_strategy(
    events: PublishedCalendarEvents,
    assets=("AAPL",),
    *,
    strategy_class=ImmediateSignal,
    **strategy_fields,
):
    return strategy_class(
        calendar_events_instance=events,
        calendar_identifier="XNYS",
        **strategy_fields,
        execution_model_instance=stock_execution_model(assets),
    )


def stock_execution_model(assets=("AAPL",)) -> TargetWeightExecutionModel:
    """Whole shares quoted and settled in USD."""
    return TargetWeightExecutionModel(
        instrument_specs=tuple(
            InstrumentExecutionSpec(
                asset_identifier=asset,
                quantity_unit="shares",
                target_measure="market_value_weight",
                contract_multiplier=1.0,
                quantity_step=1.0,
                price_asset_identifier="USD",
                settlement_style="cash",
                terms_version="stock-v1",
            )
            for asset in assets
        )
    )


def marks(frame: pd.DataFrame) -> pd.DataFrame:
    """Valuation marks in the ledger's grain."""
    flat = frame.reset_index() if "time_index" not in frame.columns else frame.copy()
    return pd.DataFrame(
        {
            "time_index": pd.to_datetime(flat["time_index"], utc=True),
            ASSET_IDENTIFIER: flat[ASSET_IDENTIFIER],
            "price": flat["close"],
            "price_asset_identifier": "USD",
            "source_revision": [f"mark-{position}" for position in range(len(flat))],
        }
    )


def book(
    strategy,
    rebalance_state: pd.DataFrame,
    valuations: pd.DataFrame,
    *,
    initial_state,
    valuation_staleness: dt.timedelta = dt.timedelta(days=1),
):
    return PortfolioEngine.calculate_backtest(
        portfolio_identifier="recorded-fills",
        accounting_configuration=PortfolioAccountingConfiguration(
            initial_nav=10_000.0,
            initial_state_time_index=initial_state,
            position_valuation_model_instance=MarketPriceValuationModel(
                maximum_staleness=valuation_staleness
            ),
        ),
        valuation_asset_identifier="USD",
        rebalance_strategy=strategy,
        rebalance_state=rebalance_state,
        valuation_observations=valuations,
    ).ledger


def prices(*rows: tuple[str, str, float]) -> pd.DataFrame:
    """``(asset, time, price)`` rows of the valuation source."""
    return pd.DataFrame(
        [(utc(stamp), asset, price) for asset, stamp, price in rows],
        columns=["time_index", ASSET_IDENTIFIER, "close"],
    )


SWAP = signal_frame(
    [("2026-11-18T15:00:00Z", {"AAPL": 1.0}), ("2026-11-18T16:00:00Z", {"ILLQ": 1.0})]
)
HALTED_SELL = prices(
    ("AAPL", "2026-11-18T14:45Z", 100.0),
    ("ILLQ", "2026-11-18T14:45Z", 50.0),
    ("AAPL", "2026-11-18T15:01Z", 100.0),
    # AAPL is halted from 15:01 to 18:01.
    ("ILLQ", "2026-11-18T16:01Z", 50.0),
    ("ILLQ", "2026-11-18T17:01Z", 50.0),
    ("AAPL", "2026-11-18T18:01Z", 100.0),
    ("ILLQ", "2026-11-18T18:02Z", 50.0),
)


def rounded(result: pd.DataFrame) -> list[tuple]:
    ordered = result.sort_values(["time_index", ASSET_IDENTIFIER], kind="stable")
    return [
        (
            utc(row["time_index"]),
            row[ASSET_IDENTIFIER],
            row["execution_status"],
            round(float(row["executed_quantity"]), 12),
            round(float(row["weight_after"]), 12),
        )
        for row in ordered.to_dict(orient="records")
    ]


def progress(ledger: pd.DataFrame, asset: str) -> list[dict]:
    rows = ledger[
        (ledger["record_kind"] == "execution_progress") & (ledger["asset_identifier"] == asset)
    ]
    return [json.loads(payload) for payload in rows.sort_values("time_index")["extension_payload"]]


def position_deltas(ledger: pd.DataFrame) -> list[tuple[pd.Timestamp, str, float, float]]:
    deltas = ledger[ledger["record_kind"] == "position_delta"]
    return [
        (utc(row["time_index"]), row["asset_identifier"], row["quantity_delta"], row["price"])
        for row in deltas.sort_values(["time_index", "asset_identifier"]).to_dict("records")
    ]
