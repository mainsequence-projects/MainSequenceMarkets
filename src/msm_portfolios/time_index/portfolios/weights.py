from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pandas as pd
import pytz

from msm_portfolios.accounting.projections import project_portfolio_weights
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
    ASSET_IDENTIFIER,
    PORTFOLIO_IDENTIFIER,
    PORTFOLIO_WEIGHT_SOURCE_COLUMN_ALIASES,
)
from ..metadata import emit_portfolio_metadata, extract_portfolio_description
from ..portfolio_identity import (
    canonical_portfolio_configuration,
    compute_portfolio_configuration_hash,
    get_or_create_portfolio,
)
from msm_portfolios.series_nodes import PublishedSeriesNode
from .accounting import PortfolioEngine
from .rebalance import PortfolioRebalance
from .storage import PortfolioWeightsStorage


class PortfolioWeights(PublishedSeriesNode):
    """The weights of the assets each ledger event changed, published as
    ``PortfolioWeightsSeries`` (ADR 0060, decision 5; ADR 0065, decision 5).

    It depends on the portfolio's ``PortfolioEngine``, which books the fills
    ``PortfolioRebalance`` records. An asset's weight is its position value over the
    NAV after the event, as the ledger recorded them.
    """

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)
    series_resource = "portfolio-weights"
    key_column = PORTFOLIO_IDENTIFIER

    def __init__(
        self,
        *,
        portfolio_configuration: Any | None = None,
        rebalance_output_table: OutputTable | None = None,
        event_ledger_output_table: OutputTable | None = None,
        namespace: str | None = None,
    ):
        """Create the weights node.

        ``rebalance_output_table`` and ``event_ledger_output_table`` bind the internally
        built ``PortfolioRebalance`` and ``PortfolioEngine`` to the application's own
        ``PortfolioRebalanceStateTS`` and ``PortfolioEventLedgerTS`` instances: both are
        private to the application that runs the portfolio (ADR 0060, decision 7). The
        weights themselves are published to Markets.
        """
        self._portfolio_configuration = portfolio_configuration
        self._rebalance_output_table = rebalance_output_table
        self._event_ledger_output_table = event_ledger_output_table
        self.portfolio_engine: PortfolioEngine | None = None
        super().__init__(None, namespace=namespace)
        if portfolio_configuration is not None:
            self.set_portfolio_configuration(portfolio_configuration)

    def set_portfolio_configuration(
        self,
        portfolio_configuration: Any,
        *,
        portfolio_identifier: str | None = None,
        portfolio: Any | None = None,
        portfolio_resolver: Any | None = None,
        portfolio_description: str | None = None,
        metadata_updater: Any | None = None,
    ) -> PortfolioWeights:
        """Attach the portfolio contract; its ledger is built once its identity is known."""
        if portfolio_configuration is not self._portfolio_configuration:
            self.portfolio_engine = None
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_identifier = portfolio_identifier
        self._portfolio = portfolio
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        if (
            self.portfolio_engine is not None
            and portfolio_identifier is not None
            and self.portfolio_engine.config.portfolio_identifier != str(portfolio_identifier)
        ):
            self.portfolio_engine = None
        return self

    def ensure_portfolio_engine(self) -> PortfolioEngine:
        """The portfolio's ledger updater, built from its configuration and identity."""
        if self.portfolio_engine is None:
            configuration = self._portfolio_configuration
            if configuration is None:
                raise ValueError("PortfolioWeights requires a portfolio configuration.")
            identifier = self._resolve_portfolio_identifier()
            rebalance_kwargs: dict[str, Any] = {}
            if self._rebalance_output_table is not None:
                rebalance_kwargs["output_table"] = self._rebalance_output_table
            portfolio_rebalance = PortfolioRebalance(
                namespace=self.hash_namespace,
                **rebalance_kwargs,
            )
            portfolio_rebalance.set_portfolio_configuration(
                configuration,
                portfolio_identifier=identifier,
                portfolio=getattr(self, "_portfolio", None),
                portfolio_resolver=getattr(self, "_portfolio_resolver", None),
            )
            engine_kwargs: dict[str, Any] = {}
            if self._event_ledger_output_table is not None:
                engine_kwargs["output_table"] = self._event_ledger_output_table
            self.portfolio_engine = PortfolioEngine.from_portfolio_configuration(
                configuration,
                portfolio_identifier=identifier,
                namespace=self.hash_namespace,
                portfolio_rebalance=portfolio_rebalance,
                **engine_kwargs,
            )
        return self.portfolio_engine

    @property
    def portfolio_rebalance(self) -> PortfolioRebalance:
        """The portfolio's rebalance state, which its ledger books."""
        return self.ensure_portfolio_engine().config.portfolio_rebalance_instance

    def dependencies(self) -> dict[str, Any]:
        """The portfolio's signal, then its ledger, which runs its rebalance state and prices.

        The signal is a published series: the rebalance reads it and never runs it, so a
        signal that computes its weights is computed here, before the ledger's run.
        """
        if getattr(self, "_portfolio_configuration", None) is None:
            return {}
        engine = self.ensure_portfolio_engine()
        return {
            "signal_weights": engine.config.portfolio_rebalance_instance.signal_weights,
            "portfolio_engine": engine,
        }

    def series_key(self) -> str:
        return self._resolve_portfolio_identifier()

    def update(self) -> pd.DataFrame:
        if getattr(self, "_portfolio_configuration", None) is None:
            raise ValueError("PortfolioWeights needs a portfolio configuration.")
        frame = normalize_portfolio_weights_frame(
            self._calculate_projected_weights(),
            portfolio_identifier=self._resolve_portfolio_identifier(),
        )
        frame = drop_retired_rows(frame, self._retirement_boundary())
        self._upsert_portfolio_metadata_if_available(frame)
        return frame

    def _retirement_boundary(self) -> pd.Timestamp | None:
        portfolio = getattr(self, "_portfolio", None)
        configuration = getattr(self, "_portfolio_configuration", None)
        if portfolio is None and configuration is not None:
            portfolio = get_or_create_portfolio(
                configuration,
                portfolio_resolver=getattr(self, "_portfolio_resolver", None),
            )
        return retirement_boundary(portfolio)

    def _calculate_projected_weights(self) -> pd.DataFrame:
        latest = self._latest_projection_time_index_value()
        start, end = self._projection_window(latest)
        end = end_before_retirement(end, self._retirement_boundary())
        if window_is_empty(start, end):
            return pd.DataFrame()
        identifier = self._resolve_portfolio_identifier()
        engine = self.ensure_portfolio_engine()
        ledger = engine.get_df_between_dates(
            start_date=start,
            end_date=end,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={PORTFOLIO_IDENTIFIER: [identifier]},
        )
        if ledger is None or ledger.empty:
            return pd.DataFrame()
        projected = project_portfolio_weights(ledger).reset_index()
        if projected.empty:
            return pd.DataFrame()
        projected["time_index"] = pd.to_datetime(projected["time_index"], utc=True)
        if latest is not None:
            projected = projected[projected["time_index"] > pd.Timestamp(latest)]
        if projected.empty:
            return pd.DataFrame()
        projected = projected.drop(columns=[PORTFOLIO_IDENTIFIER])
        projected["volume_current"] = self._observed_volumes(projected, start=start, end=end)
        projected = projected[
            ["time_index", ASSET_IDENTIFIER, "weight", "weight_before", "price_current", "volume_current"]
        ].sort_values(["time_index", ASSET_IDENTIFIER], kind="stable")

        seed = self._last_projected_weights(latest)
        history = projected.copy()
        if seed is not None and not seed.empty:
            seed_flat = seed.reset_index()[
                [
                    "time_index",
                    ASSET_IDENTIFIER,
                    "weight",
                    "weight_before",
                    "price_current",
                    "volume_current",
                ]
            ]
            history = pd.concat([seed_flat, projected], ignore_index=True)
            history = history.sort_values(["time_index", ASSET_IDENTIFIER], kind="stable")
        history["price_before"] = history.groupby(ASSET_IDENTIFIER)["price_current"].shift(1)
        history["volume_before"] = history.groupby(ASSET_IDENTIFIER)["volume_current"].shift(1)
        return history[history["time_index"].isin(projected["time_index"])].set_index(
            ["time_index", ASSET_IDENTIFIER]
        )

    def _observed_volumes(self, projected: pd.DataFrame, *, start: Any, end: Any) -> pd.Series:
        """The bar volume the rebalance observed at each fill, where its strategy reads one."""
        state = self.portfolio_rebalance.get_df_between_dates(
            start_date=start,
            end_date=end,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={PORTFOLIO_IDENTIFIER: [self._resolve_portfolio_identifier()]},
        )
        if state is None or state.empty or "observed_volume" not in state.reset_index().columns:
            return pd.Series(None, index=projected.index, dtype="float64")
        flat = state.reset_index()
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        flat[ASSET_IDENTIFIER] = flat[ASSET_IDENTIFIER].astype(str)
        volumes = (
            flat.dropna(subset=["observed_volume"])
            .drop_duplicates(subset=["time_index", ASSET_IDENTIFIER], keep="last")
            .set_index(["time_index", ASSET_IDENTIFIER])["observed_volume"]
            .astype("float64")
        )
        keys = pd.MultiIndex.from_arrays(
            [projected["time_index"], projected[ASSET_IDENTIFIER].astype(str)]
        )
        return pd.Series(volumes.reindex(keys).to_numpy(), index=projected.index, dtype="float64")

    def _projection_window(self, latest: Any | None) -> tuple[Any, Any]:
        start: Any = self.OFFSET_START if latest is None else pd.Timestamp(latest)
        end: Any = pd.Timestamp.now(tz="UTC")
        maximum_window = os.getenv("MAX_TD_FROM_LATEST_VALUE")
        if maximum_window:
            end = min(end, pd.Timestamp(start) + pd.Timedelta(maximum_window))
        return start, end

    def _latest_projection_time_index_value(self) -> Any | None:
        """The portfolio's last published weights time: this node's progress."""
        last_time = self.reader.bounds(self._resolve_portfolio_identifier()).last_time
        return None if last_time is None else pd.Timestamp(last_time)

    def _last_projected_weights(self, latest: Any | None) -> pd.DataFrame | None:
        if latest is None:
            return None
        frame = self.get_df_between_dates(
            start_date=latest,
            end_date=latest,
            dimension_filters={PORTFOLIO_IDENTIFIER: [self._resolve_portfolio_identifier()]},
        )
        return None if frame is None or frame.empty else frame

    def _resolve_portfolio_identifier(self) -> str:
        explicit = getattr(self, "_portfolio_identifier", None)
        if explicit:
            return str(explicit)
        portfolio = getattr(self, "_portfolio", None)
        if getattr(portfolio, "unique_identifier", None):
            return str(portfolio.unique_identifier)
        configuration = getattr(self, "_portfolio_configuration", None)
        if configuration is not None:
            resolved = get_or_create_portfolio(
                configuration,
                portfolio_resolver=getattr(self, "_portfolio_resolver", None),
            )
            if getattr(resolved, "unique_identifier", None):
                self._portfolio = resolved
                return str(resolved.unique_identifier)
        raise ValueError(
            "PortfolioWeights requires a portfolio identifier or resolvable "
            "portfolio configuration."
        )

    def _upsert_portfolio_metadata_if_available(self, frame: pd.DataFrame) -> None:
        configuration = getattr(self, "_portfolio_configuration", None)
        description = getattr(self, "_portfolio_description", None)
        if configuration is None and description is None:
            return
        flat = frame.reset_index()
        if flat.empty or PORTFOLIO_IDENTIFIER not in flat.columns:
            return
        identifier = flat[PORTFOLIO_IDENTIFIER].iloc[0]
        if identifier in (None, ""):
            return
        if description is None and extract_portfolio_description(configuration) is None:
            return
        emit_portfolio_metadata(
            unique_identifier=str(identifier),
            description=description or extract_portfolio_description(configuration),
            updater=getattr(self, "_portfolio_metadata_updater", None),
        )

    @staticmethod
    def canonical_portfolio_configuration(
        portfolio_configuration: Any,
    ) -> dict[str, Any]:
        return canonical_portfolio_configuration(portfolio_configuration)

    @staticmethod
    def compute_portfolio_configuration_hash(
        portfolio_configuration: Any,
    ) -> str:
        return compute_portfolio_configuration_hash(portfolio_configuration)

    @classmethod
    def _required_output_table(cls) -> type[PortfolioWeightsStorage]:
        return PortfolioWeightsStorage


def normalize_portfolio_weights_frame(
    weights_frame: pd.DataFrame,
    *,
    portfolio_identifier: str,
) -> pd.DataFrame:
    """Normalize projected weights into canonical ``PortfolioWeightsTS`` rows."""
    required_columns = list(PortfolioWeights._column_dtypes_map_for_storage())
    flat = _reset_frame_index(weights_frame)
    if flat.empty:
        flat = _empty_flat_frame(column_names=required_columns)
    flat = flat.rename(columns=PORTFOLIO_WEIGHT_SOURCE_COLUMN_ALIASES)
    flat[PORTFOLIO_IDENTIFIER] = str(portfolio_identifier)
    _require_columns(
        flat,
        required_columns=required_columns,
        frame_name="PortfolioWeights",
    )
    return PortfolioWeights.validate_frame(flat[required_columns])


__all__ = ["PortfolioWeights", "normalize_portfolio_weights_frame"]
