from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pandas as pd
import pytz

from msm_portfolios.accounting.projections import project_portfolio_values
from msm_portfolios.retirement import (
    drop_retired_rows,
    end_before_retirement,
    retirement_boundary,
    window_is_empty,
)
from ..base import (
    OutputTable,
    _empty_flat_frame,
    _require_columns,
    _reset_frame_index,
)
from ..constants import (
    PORTFOLIO_CANONICAL_TIME_INDEX_NAME,
    PORTFOLIO_IDENTIFIER,
)
from ..metadata import emit_portfolio_metadata, extract_portfolio_description
from ..portfolio_identity import get_or_create_portfolio
from msm_portfolios.series_nodes import PublishedSeriesNode
from .storage import PortfoliosStorage
from .weights import PortfolioWeights


class PortfolioValues(PublishedSeriesNode):
    """The portfolio's values, a projection of its ledger, published as
    ``PortfolioValuesSeries`` (ADR 0060, decision 5; ADR 0065, decision 5).

    Bound to no table: ``run()`` publishes the values of the ledger as it is and records
    the portfolio's signal on its ``Portfolio`` row. ``close`` is the NAV over the
    ledger's ``initial_nav``, so a portfolio starts at 1. The ledger and what it reads
    (signal, prices, calendar events, rebalance state) run first, in one joined
    MetaTables run of every portfolio's ledger (``msm_portfolios.recipes.run_portfolios``,
    issue #133).
    """

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)
    series_resource = "portfolio-values"
    key_column = PORTFOLIO_IDENTIFIER
    asset_column = None

    def __init__(
        self,
        *,
        portfolio_configuration: Any | None = None,
        portfolio_resolver: Any | None = None,
        portfolio_description: str | None = None,
        metadata_updater: Any | None = None,
        rebalance_output_table: OutputTable | None = None,
        event_ledger_output_table: OutputTable | None = None,
        namespace: str | None = None,
    ):
        """Create the values node.

        ``rebalance_output_table`` and ``event_ledger_output_table`` bind the internally
        built ``PortfolioRebalance`` and ``PortfolioEngine`` to the application's own
        ``PortfolioRebalanceStateTS`` and ``PortfolioEventLedgerTS`` instances; both are
        private (ADR 0060, decision 7). The weights and values are published to Markets.
        """
        self._rebalance_output_table = rebalance_output_table
        self._event_ledger_output_table = event_ledger_output_table
        self.portfolio_configuration = portfolio_configuration
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        self._resolved_unique_identifier: str | None = None
        self.target_portfolio = None
        self.portfolio_weights: PortfolioWeights | None = None
        super().__init__(None, namespace=namespace)
        if portfolio_configuration is not None:
            self._initialize_from_portfolio_configuration(portfolio_configuration)

    def set_portfolio_configuration(
        self,
        portfolio_configuration: Any,
        *,
        portfolio_resolver: Any | None = None,
        portfolio_description: str | None = None,
        metadata_updater: Any | None = None,
    ) -> PortfolioValues:
        self.portfolio_configuration = portfolio_configuration
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        self._initialize_from_portfolio_configuration(portfolio_configuration)
        return self

    def _initialize_from_portfolio_configuration(self, portfolio_configuration: Any) -> None:
        build = portfolio_configuration.portfolio_build_configuration
        self.portfolio_build_configuration = build
        self.portfolio_markets_config = portfolio_configuration.portfolio_markets_configuration
        self.valuation_source = build.valuation_source_instance
        self.valuation_column = str(build.valuation_column)
        self.initial_nav = float(build.accounting_configuration.initial_nav)
        self.signal_weights = build.backtesting_weights_configuration.signal_weights_instance
        self._ensure_portfolio_weights_node()

    def _ensure_portfolio_weights_node(self) -> PortfolioWeights:
        if self.portfolio_configuration is None:
            raise ValueError("PortfolioValues requires a portfolio configuration.")
        if self.portfolio_weights is None:
            self.portfolio_weights = PortfolioWeights(
                rebalance_output_table=self._rebalance_output_table,
                event_ledger_output_table=self._event_ledger_output_table,
                namespace=self._canonical_namespace(),
            )
        self.portfolio_weights.set_portfolio_configuration(
            self.portfolio_configuration,
            portfolio_identifier=self._resolved_unique_identifier,
            portfolio=self.target_portfolio,
            portfolio_resolver=self._portfolio_resolver,
            portfolio_description=self._resolve_portfolio_description(),
            metadata_updater=self._portfolio_metadata_updater,
        )
        return self.portfolio_weights

    def series_key(self) -> str:
        return self._unique_identifier()

    def run(self):
        """Publish the ledger's new values and record the portfolio's signal.

        Runs nothing: the ledger is as its last run left it. Prepares the portfolio
        (``prepare_portfolio``) unless that was done. Answers
        ``{"portfolio_weights", "portfolio_values", "portfolio"}``, where
        ``portfolio_values`` is the values' ``SeriesPublication`` (``None`` when nothing
        was new).
        """
        if self.portfolio_configuration is None:
            raise ValueError("PortfolioValues requires a portfolio configuration.")
        if self._resolved_unique_identifier is None:
            self.prepare_portfolio()
        portfolio = self._resolve_portfolio_identity()
        portfolio_weights = self._ensure_portfolio_weights_node()
        portfolio_values = self.publish_frame(self.update())
        portfolio = self._update_portfolio_pointers(portfolio=portfolio)
        return {
            "portfolio_weights": portfolio_weights,
            "portfolio_values": portfolio_values,
            "portfolio": portfolio,
        }

    def prepare_portfolio(self) -> Any:
        """Resolve the ``Portfolio`` row, check its calendar and bind the weights to it.

        Refuses a strategy that reads another calendar than the portfolio's. Answers the
        row; the weights node, its ledger and its rebalance then carry its identifier.
        """
        if self.portfolio_configuration is None:
            raise ValueError("PortfolioValues requires a portfolio configuration.")
        portfolio = self._resolve_portfolio_identity()
        self._require_strategy_calendar(portfolio)
        self._resolved_unique_identifier = str(portfolio.unique_identifier)
        self._ensure_portfolio_weights_node()
        return portfolio

    def update(self) -> pd.DataFrame:
        frame = normalize_portfolio_values_frame(
            self._calculate_portfolio_values(),
            unique_identifier=self._unique_identifier(),
        )
        frame = drop_retired_rows(frame, retirement_boundary(getattr(self, "target_portfolio", None)))
        self._upsert_portfolio_metadata_if_available(frame)
        return frame

    def _calculate_portfolio_values(self) -> pd.DataFrame:
        """The ledger's values after the last published one.

        The ledger is read from the last published time on, so the first new value's
        return is its change from the last published one.
        """
        latest = self._latest_portfolio_time_index_value()
        start, end = self._valuation_window(latest)
        end = end_before_retirement(end, retirement_boundary(getattr(self, "target_portfolio", None)))
        if window_is_empty(start, end):
            self.logger.info("The portfolio is retired and valued up to its retirement.")
            return pd.DataFrame()
        engine = self._ensure_portfolio_weights_node().ensure_portfolio_engine()
        ledger = engine.get_df_between_dates(
            start_date=start,
            end_date=end,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={PORTFOLIO_IDENTIFIER: [self._unique_identifier()]},
        )
        if ledger is None or ledger.empty:
            self.logger.info("The portfolio's ledger has nothing to value yet.")
            return pd.DataFrame()
        values = project_portfolio_values(ledger, initial_nav=self.initial_nav).reset_index()
        values["time_index"] = pd.to_datetime(values["time_index"], utc=True)
        values["return"] = values["return"].fillna(0.0)
        if latest is not None:
            values = values[values["time_index"] > pd.Timestamp(latest)]
        return values.drop(columns=[PORTFOLIO_IDENTIFIER]).set_index("time_index")

    def _valuation_window(self, latest_value: Any | None) -> tuple[datetime, datetime]:
        start = (
            pd.Timestamp(latest_value).to_pydatetime()
            if latest_value is not None
            else self.OFFSET_START
        )
        end = datetime.now(pytz.utc)
        maximum_window = os.getenv("MAX_TD_FROM_LATEST_VALUE")
        if maximum_window:
            end = min(end, (pd.Timestamp(start) + pd.Timedelta(maximum_window)).to_pydatetime())
        return start, end

    def _latest_portfolio_time_index_value(self) -> Any | None:
        """The portfolio's last published value time: this node's progress."""
        last_time = self.reader.bounds(self._unique_identifier()).last_time
        return None if last_time is None else pd.Timestamp(last_time)

    def _canonical_namespace(self) -> str | None:
        namespace = self.hash_namespace or ""
        return namespace or None

    def _resolve_portfolio_identity(self) -> Any:
        if self.target_portfolio is not None and self.target_portfolio.unique_identifier:
            return self.target_portfolio
        if self.portfolio_configuration is None:
            raise ValueError("PortfolioValues requires a portfolio_configuration.")
        self.target_portfolio = get_or_create_portfolio(
            self.portfolio_configuration,
            portfolio_resolver=self._portfolio_resolver,
        )
        return self.target_portfolio

    def _unique_identifier(self) -> str:
        identifier = self._resolve_portfolio_identity().unique_identifier
        if not identifier:
            raise ValueError("Portfolio must expose unique_identifier.")
        return str(identifier)

    def _resolve_portfolio_description(self) -> str | None:
        if self._portfolio_description is not None:
            return str(self._portfolio_description)
        markets_config = getattr(self, "portfolio_markets_config", None)
        front_end_details = getattr(markets_config, "front_end_details", None)
        return None if front_end_details is None else str(front_end_details.description)

    def _require_strategy_calendar(self, portfolio: Any) -> None:
        """Refuse a calendar-reading strategy on another calendar than the portfolio's.

        ``Portfolio.calendar_uid`` and the strategy's ``calendar_identifier`` are
        typed separately. They must name the same stored calendar, so the
        portfolio has one calendar (ADR 0056). ``ImmediateSignal`` and its
        subclass ``CalendarEventSignal`` read a calendar; the other strategies
        read none.
        """

        from msm.api.calendars import Calendar
        from msm_portfolios.rebalance_strategy import ImmediateSignal

        backtesting = self.portfolio_build_configuration.backtesting_weights_configuration
        strategy = backtesting.rebalance_strategy_instance
        if not isinstance(strategy, ImmediateSignal):
            return
        strategy_calendar = Calendar.get_by_unique_identifier(strategy.calendar_identifier)
        strategy_uid = None if strategy_calendar is None else str(strategy_calendar.uid)
        portfolio_uid = (
            None if portfolio.calendar_uid in (None, "") else str(portfolio.calendar_uid)
        )
        if strategy_uid is not None and strategy_uid == portfolio_uid:
            return
        portfolio_calendar = None if portfolio_uid is None else Calendar.get_by_uid(portfolio_uid)
        portfolio_label = (
            "no calendar"
            if portfolio_uid is None
            else f"calendar {getattr(portfolio_calendar, 'unique_identifier', portfolio_uid)!r}"
        )
        raise ValueError(
            f"Portfolio {portfolio.unique_identifier!r} has {portfolio_label} on its row, but "
            f"its rebalance strategy uses calendar {strategy.calendar_identifier!r}. Its "
            f"{type(strategy).__name__} must use the calendar of Portfolio.calendar_uid."
        )

    def _update_portfolio_pointers(self, *, portfolio: Any) -> Any:
        """Record the portfolio's current signal on its ``Portfolio`` row.

        Writes the row only when its signal or price column changes: ``portfolio`` is the
        row this run resolved. The signal's ``SignalMetadata`` row exists already: the
        signal's run, or its first publication, created it.
        """
        from msm.api.portfolios import Portfolio

        if portfolio.calendar_uid in (None, ""):
            raise ValueError(
                "PortfolioValues cannot update the Portfolio row because "
                "portfolio.calendar_uid is missing."
            )
        signal_uid = self._required_signal_uid(self.signal_weights)
        price_column = portfolio.backtest_table_price_column_name or self.valuation_column
        if (
            portfolio.signal_uid == signal_uid
            and portfolio.backtest_table_price_column_name == price_column
        ):
            return portfolio
        portfolio = Portfolio.upsert(
            unique_identifier=str(portfolio.unique_identifier),
            calendar_uid=portfolio.calendar_uid,
            published_index_uid=portfolio.published_index_uid,
            backtest_table_price_column_name=price_column,
            signal_uid=signal_uid,
        )
        self.target_portfolio = portfolio
        return portfolio

    @staticmethod
    def _required_signal_uid(signal_weights: Any) -> str:
        signal_uid = signal_weights.signal_uid
        if signal_uid in (None, ""):
            raise RuntimeError("signal_weights.signal_uid is not available.")
        return str(signal_uid)

    def _upsert_portfolio_metadata_if_available(self, frame: pd.DataFrame) -> None:
        configuration = self.portfolio_configuration
        description = self._portfolio_description
        if configuration is None and description is None:
            return
        flat = frame.reset_index()
        if flat.empty or PORTFOLIO_IDENTIFIER not in flat.columns:
            return
        if description is None and extract_portfolio_description(configuration) is None:
            return
        emit_portfolio_metadata(
            unique_identifier=str(flat[PORTFOLIO_IDENTIFIER].iloc[0]),
            description=description or extract_portfolio_description(configuration),
            updater=self._portfolio_metadata_updater,
        )

    @classmethod
    def _required_output_table(cls) -> type[PortfoliosStorage]:
        return PortfoliosStorage


def normalize_portfolio_values_frame(
    portfolio_values_frame: pd.DataFrame,
    *,
    unique_identifier: str,
) -> pd.DataFrame:
    """Normalize projected values into canonical ``PortfoliosTS`` rows."""
    required_columns = list(PortfolioValues._column_dtypes_map_for_storage())
    flat = _reset_frame_index(portfolio_values_frame)
    if flat.empty:
        flat = _empty_flat_frame(column_names=required_columns)
    if PORTFOLIO_CANONICAL_TIME_INDEX_NAME not in flat.columns and "index" in flat.columns:
        flat = flat.rename(columns={"index": PORTFOLIO_CANONICAL_TIME_INDEX_NAME})
    flat[PORTFOLIO_IDENTIFIER] = str(unique_identifier)
    _require_columns(flat, required_columns=required_columns, frame_name="PortfolioValues")
    return PortfolioValues.validate_frame(flat[required_columns])


from .accounting import (  # noqa: E402
    PortfolioEngine,
    PortfolioEngineConfiguration,
    normalize_portfolio_event_ledger_frame,
)


__all__ = [
    "PortfolioEngine",
    "PortfolioEngineConfiguration",
    "PortfolioValues",
    "normalize_portfolio_event_ledger_frame",
    "normalize_portfolio_values_frame",
]
