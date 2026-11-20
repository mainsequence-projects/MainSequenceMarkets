from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pandas as pd
import pytz

from msm_portfolios.rebalance_strategy import RebalanceStrategyBase

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
from .rebalance import PortfolioRebalance
from .storage import PortfolioWeightsStorage


class PortfolioWeights(PublishedSeriesNode):
    """Projection of rebalance state into executed weights, published as
    ``PortfolioWeightsSeries`` (ADR 0060, decision 5)."""

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)
    series_resource = "portfolio-weights"
    key_column = PORTFOLIO_IDENTIFIER

    def __init__(
        self,
        *,
        portfolio_configuration: Any | None = None,
        portfolio_rebalance: PortfolioRebalance | None = None,
        rebalance_output_table: OutputTable | None = None,
        namespace: str | None = None,
    ):
        """Create the executed-weights node.

        ``rebalance_output_table`` binds the internally built ``PortfolioRebalance`` to
        the application's own ``PortfolioRebalanceStateTS`` instance: rebalance state is
        private to the application that runs the portfolio. The weights themselves are
        published to Markets.
        """
        self._portfolio_configuration = portfolio_configuration
        self.portfolio_rebalance = portfolio_rebalance
        self._rebalance_output_table = rebalance_output_table
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
        portfolio_rebalance: PortfolioRebalance | None = None,
    ) -> PortfolioWeights:
        """Attach the portfolio contract and its rebalance-state source."""
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_identifier = portfolio_identifier
        self._portfolio = portfolio
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        if portfolio_rebalance is not None:
            self.portfolio_rebalance = portfolio_rebalance
        if self.portfolio_rebalance is None:
            rebalance_kwargs: dict[str, Any] = {}
            if self._rebalance_output_table is not None:
                rebalance_kwargs["output_table"] = self._rebalance_output_table
            self.portfolio_rebalance = PortfolioRebalance(
                namespace=self.hash_namespace,
                **rebalance_kwargs,
            )
        self.portfolio_rebalance.set_portfolio_configuration(
            portfolio_configuration,
            portfolio_identifier=portfolio_identifier,
            portfolio=portfolio,
            portfolio_resolver=portfolio_resolver,
        )
        return self

    def set_weights_frame(
        self,
        weights_frame: pd.DataFrame,
        *,
        portfolio_identifier: str | None = None,
        portfolio_configuration: Any | None = None,
        portfolio: Any | None = None,
        portfolio_resolver: Any | None = None,
        portfolio_description: str | None = None,
        metadata_updater: Any | None = None,
    ) -> PortfolioWeights:
        """Attach direct canonical rows for storage-only use."""
        self._weights_frame = weights_frame
        self._portfolio_identifier = portfolio_identifier
        self._portfolio_configuration = portfolio_configuration
        self._portfolio = portfolio
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        return self

    def dependencies(self) -> dict[str, Any]:
        """The portfolio's signal, then its rebalance state, which this node projects."""
        if getattr(self, "_portfolio_configuration", None) is None:
            return {}
        if self.portfolio_rebalance is None:
            raise ValueError("PortfolioWeights requires PortfolioRebalance.")
        return {
            "signal_weights": self.portfolio_rebalance.signal_weights,
            "portfolio_rebalance": self.portfolio_rebalance,
        }

    def series_key(self) -> str:
        return self._resolve_portfolio_identifier()

    def update(self) -> pd.DataFrame:
        if getattr(self, "_portfolio_configuration", None) is not None:
            frame = normalize_portfolio_weights_frame(
                self._calculate_projected_weights(),
                portfolio_identifier=self._resolve_portfolio_identifier(),
            )
        else:
            weights = getattr(self, "_weights_frame", None)
            if weights is None:
                raise ValueError(
                    "PortfolioWeights needs a portfolio configuration or set_weights_frame()."
                )
            frame = normalize_portfolio_weights_frame(
                weights,
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
        state = self.portfolio_rebalance.get_df_between_dates(
            start_date=start,
            end_date=end,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={PORTFOLIO_IDENTIFIER: [self._resolve_portfolio_identifier()]},
        )
        if state is None or state.empty:
            return pd.DataFrame()
        flat = state.reset_index().copy()
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        if latest is not None:
            flat = flat[flat["time_index"] > pd.Timestamp(latest)]
        # A cancelled row can still have filled part of its order (ADR 0058).
        flat = flat[~flat["execution_status"].isin({"superseded", "rejected"})]
        if flat.empty:
            return pd.DataFrame()
        flat = flat.sort_values(
            ["time_index", "target_signal_time_index", "rebalance_intent_id"],
            kind="stable",
        ).drop_duplicates(
            subset=["time_index", ASSET_IDENTIFIER],
            keep="last",
        )
        changed_times = flat.groupby("time_index")["executed_weight_delta"].apply(
            lambda values: values.abs().gt(0.0).any()
        )
        flat = flat[flat["time_index"].isin(changed_times[changed_times].index)]
        if flat.empty:
            return pd.DataFrame()

        projected = flat.rename(
            columns={
                "weight_after": "weight",
                "execution_price": "price_current",
                "observed_volume": "volume_current",
            }
        )
        # The rebalance book's shares and cash, which value a portfolio without a
        # ledger (ADR 0059). Strategies that record no book leave them empty.
        states = [
            RebalanceStrategyBase.parse_strategy_state(row)
            for row in projected.to_dict(orient="records")
        ]
        projected["held_shares"] = [state.get("held_shares") for state in states]
        projected["book_cash"] = [state.get("cash") for state in states]
        projected = projected[
            [
                "time_index",
                ASSET_IDENTIFIER,
                "weight",
                "weight_before",
                "price_current",
                "volume_current",
                "held_shares",
                "book_cash",
            ]
        ].sort_values(["time_index", ASSET_IDENTIFIER], kind="stable")

        seed = self._last_projected_weights(latest)
        history = projected.copy()
        if seed is not None and not seed.empty:
            seed_flat = seed.reset_index().rename(
                columns={PORTFOLIO_IDENTIFIER: "_portfolio_identifier"}
            )
            seed_flat = seed_flat[
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

    @staticmethod
    def normalize_weights_frame(
        weights_frame: pd.DataFrame,
        *,
        portfolio_identifier: str,
    ) -> pd.DataFrame:
        return normalize_portfolio_weights_frame(
            weights_frame,
            portfolio_identifier=portfolio_identifier,
        )

    @classmethod
    def _required_output_table(cls) -> type[PortfolioWeightsStorage]:
        return PortfolioWeightsStorage


def normalize_portfolio_weights_frame(
    weights_frame: pd.DataFrame,
    *,
    portfolio_identifier: str,
) -> pd.DataFrame:
    """Normalize executed-weight projections into canonical PortfolioWeights rows."""
    required_columns = list(PortfolioWeights._column_dtypes_map_for_storage())
    flat = _reset_frame_index(weights_frame)
    if flat.empty:
        flat = _empty_flat_frame(column_names=required_columns)
    flat = flat.rename(columns=PORTFOLIO_WEIGHT_SOURCE_COLUMN_ALIASES)
    flat[PORTFOLIO_IDENTIFIER] = str(portfolio_identifier)
    # Weights supplied without a rebalance book carry no shares (ADR 0059).
    for column in ("held_shares", "book_cash"):
        if column in required_columns and column not in flat.columns:
            flat[column] = None
    _require_columns(
        flat,
        required_columns=required_columns,
        frame_name="PortfolioWeights",
    )
    return PortfolioWeights.validate_frame(flat[required_columns])


__all__ = ["PortfolioWeights", "normalize_portfolio_weights_frame"]
