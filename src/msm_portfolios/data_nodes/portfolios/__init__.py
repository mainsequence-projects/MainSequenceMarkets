from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytz

import mainsequence.meta_tables.time_index_table_updates.configuration as update_configuration
from mainsequence.client import BaseUpdateStatistics
from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater

from ..base import (
    OutputTable,
    PortfolioCanonicalDataNode,
    PortfolioCanonicalDataNodeConfiguration,
    _class_import_path,
    _drop_empty_framework_init_kwargs,
    _empty_flat_frame,
    _is_canonical_frame,
    _require_columns,
    _reset_frame_index,
)
from ..constants import (
    ASSET_IDENTIFIER,
    PORTFOLIO_CANONICAL_TIME_INDEX_NAME,
    PORTFOLIO_IDENTIFIER,
)
from ..metadata import emit_portfolio_metadata, extract_portfolio_description
from ..portfolio_identity import get_or_create_portfolio
from .storage import PortfoliosStorage
from .temporal import align_asset_observations, fetch_asset_observations, utc_index
from .weights import PortfolioWeights


class PortfoliosDataNode(PortfolioCanonicalDataNode):
    """Valuation-only updater consuming canonical executed portfolio weights."""

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)

    def __init__(
        self,
        config: PortfolioCanonicalDataNodeConfiguration | None = None,
        *args,
        portfolio_configuration: Any | None = None,
        portfolio_resolver: Any | None = None,
        portfolio_description: str | None = None,
        metadata_updater: Any | None = None,
        namespace: str | None = None,
        **kwargs,
    ):
        self.portfolio_configuration = portfolio_configuration
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_resolver = portfolio_resolver
        self._explicit_portfolio_identifier: str | None = None
        self._portfolio_values_frame: pd.DataFrame | None = None
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        self._resolved_unique_identifier: str | None = None
        self.target_portfolio = None
        self.portfolio_weights: PortfolioWeights | None = None
        super().__init__(config, *args, namespace=namespace, **kwargs)
        if portfolio_configuration is not None:
            self._initialize_from_portfolio_configuration(portfolio_configuration)

    def _initialize_configuration(self, init_kwargs: dict) -> None:
        """Use the canonical portfolio-values updater class for shared storage."""
        _drop_empty_framework_init_kwargs(init_kwargs)
        for runtime_key in (
            "portfolio_resolver",
            "portfolio_description",
            "metadata_updater",
        ):
            init_kwargs.pop(runtime_key, None)
        init_kwargs["table_updater_class_import_path"] = _class_import_path(PortfoliosDataNode)
        config = update_configuration.create_config(
            kwargs=init_kwargs,
            updater_class_name=PortfoliosDataNode.__name__,
        )
        for field_name, value in config.__dict__.items():
            setattr(self, field_name, value)

    def set_portfolio_configuration(
        self,
        portfolio_configuration: Any,
        *,
        portfolio_resolver: Any | None = None,
        portfolio_description: str | None = None,
        metadata_updater: Any | None = None,
    ) -> PortfoliosDataNode:
        self.portfolio_configuration = portfolio_configuration
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        build_configuration = {
            "config": self.config,
            "portfolio_configuration": portfolio_configuration,
        }
        if self.hash_namespace:
            build_configuration["hash_namespace"] = self.hash_namespace
        self.build_configuration = build_configuration
        self._initialize_configuration(init_kwargs=build_configuration)
        self._initialize_from_portfolio_configuration(portfolio_configuration)
        return self

    def _initialize_from_portfolio_configuration(self, portfolio_configuration: Any) -> None:
        build = portfolio_configuration.portfolio_build_configuration
        backtesting = build.backtesting_weights_configuration
        self.portfolio_build_configuration = build
        self.execution_configuration = build.execution_configuration
        self.portfolio_markets_config = portfolio_configuration.portfolio_markets_configuration
        self.commission_fee = self.execution_configuration.commission_fee
        self.valuation_source = build.valuation_source_instance
        self.valuation_column = str(build.valuation_column)
        self.valuation_alignment_policy = build.valuation_alignment_policy
        self.signal_weights = backtesting.signal_weights_instance
        self._ensure_portfolio_weights_node()

    def _ensure_portfolio_weights_node(self) -> PortfolioWeights:
        if self.portfolio_configuration is None:
            raise ValueError("PortfolioWeights requires a portfolio configuration.")
        if self.portfolio_weights is None:
            self.portfolio_weights = PortfolioWeights(
                portfolio_configuration=self.portfolio_configuration,
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

    def set_portfolio_values_frame(
        self,
        portfolio_values_frame: pd.DataFrame,
        *,
        unique_identifier: str | None = None,
        portfolio_configuration: Any | None = None,
        portfolio_resolver: Any | None = None,
        portfolio_description: str | None = None,
        metadata_updater: Any | None = None,
    ) -> PortfoliosDataNode:
        """Attach direct canonical values for storage-only use."""
        self._portfolio_values_frame = portfolio_values_frame
        self._explicit_portfolio_identifier = unique_identifier
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        return self

    def dependencies(self) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        if self.portfolio_configuration is None:
            return {}
        return {
            "portfolio_weights": self._ensure_portfolio_weights_node(),
            "valuation_source": self.valuation_source,
        }

    def run(
        self,
        *,
        update_tree: bool = True,
        update_only_tree: bool = False,
        update_pointers: bool = True,
        override_update_stats: BaseUpdateStatistics | None = None,
    ):
        if self.portfolio_configuration is None:
            return super().run(
                update_tree=update_tree,
                update_only_tree=update_only_tree,
                override_update_stats=override_update_stats,
            )
        portfolio = self._resolve_portfolio_identity()
        self._resolved_unique_identifier = str(portfolio.unique_identifier)
        portfolio_weights = self._ensure_portfolio_weights_node()
        portfolio_values_result = super().run(
            update_tree=update_tree,
            update_only_tree=update_only_tree,
            override_update_stats=override_update_stats,
        )
        if update_only_tree:
            return portfolio_values_result
        if update_pointers:
            portfolio = self._update_portfolio_pointers(
                portfolio=portfolio,
                signal_weights_data_node_uid=self._required_table_update_uid(
                    self.signal_weights, "signal weights"
                ),
                portfolio_weights_data_node_uid=self._required_table_update_uid(
                    portfolio_weights, "portfolio weights"
                ),
                portfolio_data_node_uid=self._required_table_update_uid(self, "portfolio values"),
            )
        return {
            "portfolio_weights": portfolio_weights,
            "portfolio_values": portfolio_values_result,
            "portfolio": portfolio,
        }

    def update(self) -> pd.DataFrame:
        raw_frame = self._calculate_portfolio_values()
        frame = (
            self.validate_frame(raw_frame, output_table=self.output_table)
            if _is_canonical_frame(raw_frame, output_table=self.output_table)
            else self.validate_frame(
                normalize_portfolio_values_frame(
                    raw_frame,
                    unique_identifier=self._resolve_unique_identifier(),
                    output_table=self.output_table,
                ),
                output_table=self.output_table,
            )
        )
        self._upsert_portfolio_metadata_if_available(frame)
        return frame

    def _calculate_portfolio_values(self) -> pd.DataFrame:
        if self.portfolio_configuration is not None:
            return self._calculate_portfolio_workflow_values()
        if self._portfolio_values_frame is None:
            return self.get_canonical_frame()
        return self._portfolio_values_frame

    def _calculate_portfolio_workflow_values(self) -> pd.DataFrame:
        latest_value = self._latest_portfolio_time_index_value()
        start, end = self._valuation_window(latest_value)
        weights = self._executed_weights_between(start=start, end=end)
        if weights.empty:
            self.logger.info("No executed portfolio weights are available for valuation.")
            return pd.DataFrame()

        assets = list(
            dict.fromkeys(weights.index.get_level_values(ASSET_IDENTIFIER).astype(str).tolist())
        )
        override_asset = self.signal_weights.get_asset_uid_to_override_portfolio_price()
        valuation_assets = list(assets)
        if override_asset is not None:
            valuation_assets.append(str(override_asset))
        valuation_assets = list(dict.fromkeys(valuation_assets))

        valuation_window, valuation_seed = fetch_asset_observations(
            self.valuation_source,
            start=start,
            end=end,
            asset_identifiers=valuation_assets,
        )
        if valuation_window.empty:
            return pd.DataFrame()
        observation_index = utc_index(valuation_window.index.get_level_values("time_index"))
        if latest_value is not None:
            observation_index = observation_index[observation_index > pd.Timestamp(latest_value)]
        first_execution = weights.index.get_level_values("time_index").min()
        observation_index = observation_index[observation_index >= first_execution]
        if len(observation_index) == 0:
            return pd.DataFrame()

        calculation_index = observation_index
        if latest_value is not None:
            calculation_index = utc_index([latest_value, *observation_index])
        all_valuations = pd.concat([valuation_seed, valuation_window]).sort_index()
        aligned = align_asset_observations(
            all_valuations,
            target_index=calculation_index,
            asset_identifiers=valuation_assets,
            value_columns=[self.valuation_column],
            maximum_staleness=self.valuation_alignment_policy.maximum_staleness,
            fail_on_missing_values=self.valuation_alignment_policy.fail_on_missing_values,
        )
        prices = aligned[self.valuation_column].unstack(ASSET_IDENTIFIER)
        eligible = prices.reindex(columns=valuation_assets).notna().all(axis=1)
        observation_index = observation_index.intersection(eligible[eligible].index)
        if len(observation_index) == 0:
            return pd.DataFrame()
        calculation_index = observation_index
        if latest_value is not None and bool(eligible.get(pd.Timestamp(latest_value), False)):
            calculation_index = utc_index([latest_value, *observation_index])
        prices = prices.reindex(calculation_index)
        held_weights = self._weights_as_of(weights, calculation_index, assets)
        portfolio_returns = self._calculate_portfolio_returns(
            held_weights=held_weights,
            valuations=prices,
            executed_weights=weights,
            latest_value=latest_value,
        ).loc[observation_index]
        portfolio = self._apply_cumulative_portfolio_values(portfolio_returns)
        portfolio["calculated_close"] = portfolio["close"]

        if override_asset is not None:
            override_values = prices[str(override_asset)].reindex(portfolio.index)
            portfolio["close"] = override_values
            previous_override = prices[str(override_asset)].shift(1).reindex(portfolio.index)
            portfolio["return"] = (override_values / previous_override - 1).fillna(0.0)
        portfolio["close_time"] = portfolio.index
        return portfolio

    @staticmethod
    def _weights_as_of(
        weights: pd.DataFrame,
        target_index: pd.DatetimeIndex,
        assets: list[str],
    ) -> pd.DataFrame:
        wide = weights["weight"].unstack(ASSET_IDENTIFIER).reindex(columns=assets)
        combined = wide.index.union(target_index).sort_values()
        return wide.reindex(combined).ffill().reindex(target_index).fillna(0.0)

    def _calculate_portfolio_returns(
        self,
        *,
        held_weights: pd.DataFrame,
        valuations: pd.DataFrame,
        executed_weights: pd.DataFrame,
        latest_value: Any | None,
    ) -> pd.DataFrame:
        valuations = valuations.reindex(columns=held_weights.columns)
        asset_returns = valuations.pct_change(fill_method=None).replace([np.inf, -np.inf], 0.0)
        asset_returns = asset_returns.fillna(0.0)
        period_weights = held_weights.shift(1).fillna(held_weights)
        result = pd.DataFrame({"return": (period_weights * asset_returns).sum(axis=1)})
        events = executed_weights.reset_index()
        if latest_value is not None:
            events = events[events["time_index"] > pd.Timestamp(latest_value)]
        if not events.empty:
            events["turnover"] = (
                events["weight"].fillna(0.0) - events["weight_before"].fillna(0.0)
            ).abs()
            turnover = events.groupby("time_index")["turnover"].sum()
            fee_by_target = pd.Series(0.0, index=result.index)
            target_positions = result.index.searchsorted(turnover.index, side="left")
            for event_time, position in zip(turnover.index, target_positions, strict=True):
                if position < len(fee_by_target):
                    fee_by_target.iloc[position] += turnover.loc[event_time] * self.commission_fee
            result["return"] = result["return"] - fee_by_target
        return result

    def _executed_weights_between(self, *, start: datetime, end: datetime) -> pd.DataFrame:
        portfolio_identifier = self._unique_identifier()
        node = self._ensure_portfolio_weights_node()
        window = self._normalize_weights_frame(
            node.get_df_between_dates(
                start_date=start,
                end_date=end,
                great_or_equal=True,
                less_or_equal=True,
                dimension_filters={PORTFOLIO_IDENTIFIER: [portfolio_identifier]},
            )
        )
        assets = [
            str(node._asset_unique_identifier(asset))
            for asset in (self.signal_weights.get_asset_list() or [])
        ]
        if not assets and not window.empty:
            assets = window.index.get_level_values(ASSET_IDENTIFIER).astype(str).unique().tolist()
        seed = pd.DataFrame()
        if assets:
            seed = self._normalize_weights_frame(
                node.get_last_observation(
                    dimension_range_map=[
                        {
                            "coordinate": {
                                PORTFOLIO_IDENTIFIER: portfolio_identifier,
                                ASSET_IDENTIFIER: asset,
                            },
                            "end_date": start,
                            "end_date_operand": "<",
                        }
                        for asset in assets
                    ]
                )
            )
        return pd.concat([seed, window]).sort_index() if not seed.empty else window

    @staticmethod
    def _normalize_weights_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame()
        flat = frame.copy().reset_index()
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        flat[ASSET_IDENTIFIER] = flat[ASSET_IDENTIFIER].map(str)
        return flat.set_index(["time_index", ASSET_IDENTIFIER]).sort_index()

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
        statistics = getattr(self, "update_statistics", None)
        if statistics is None:
            return None
        identifier = self._portfolio_progress_identifier()
        progress = statistics.index_progress
        if identifier is not None and isinstance(progress, dict):
            value = progress.get(identifier)
            if isinstance(value, dict):
                return value.get("max") or value.get("time_index")
            if value is not None:
                return value
        return statistics.max_time_index_value

    def _portfolio_progress_identifier(self) -> str | None:
        if self._resolved_unique_identifier is not None:
            return self._resolved_unique_identifier
        if self.portfolio_configuration is None and self._portfolio_configuration is None:
            return None
        self._resolved_unique_identifier = self._unique_identifier()
        return self._resolved_unique_identifier

    def _apply_cumulative_portfolio_values(self, portfolio: pd.DataFrame) -> pd.DataFrame:
        last_close = 1.0
        latest_value = self._latest_portfolio_time_index_value()
        if latest_value is not None:
            previous = self.get_df_between_dates(
                start_date=latest_value,
                end_date=latest_value,
                dimension_filters={PORTFOLIO_IDENTIFIER: [self._unique_identifier()]},
            )
            if previous is not None and not previous.empty:
                last_close = float(previous.sort_index()["close"].iloc[-1])
        result = portfolio.copy()
        result["close"] = last_close * np.cumprod(result["return"] + 1.0)
        return result

    def _canonical_namespace(self) -> str | None:
        namespace = self.hash_namespace or ""
        return namespace or None

    def _resolve_portfolio_identity(self) -> Any:
        if self.target_portfolio is not None and self.target_portfolio.unique_identifier:
            return self.target_portfolio
        configuration = self.portfolio_configuration or self._portfolio_configuration
        if configuration is None:
            raise ValueError("PortfoliosDataNode requires a portfolio_configuration.")
        self.target_portfolio = get_or_create_portfolio(
            configuration,
            portfolio_resolver=self._portfolio_resolver,
        )
        return self.target_portfolio

    def _unique_identifier(self) -> str:
        identifier = self._resolve_portfolio_identity().unique_identifier
        if not identifier:
            raise ValueError("Portfolio must expose unique_identifier.")
        return str(identifier)

    def _resolve_unique_identifier(self) -> str:
        if self._explicit_portfolio_identifier:
            return str(self._explicit_portfolio_identifier)
        return self._unique_identifier()

    def _resolve_portfolio_description(self) -> str | None:
        if self._portfolio_description is not None:
            return str(self._portfolio_description)
        markets_config = getattr(self, "portfolio_markets_config", None)
        front_end_details = getattr(markets_config, "front_end_details", None)
        return None if front_end_details is None else str(front_end_details.description)

    def _update_portfolio_pointers(
        self,
        *,
        portfolio: Any,
        signal_weights_data_node_uid: str,
        portfolio_weights_data_node_uid: str,
        portfolio_data_node_uid: str,
    ) -> Any:
        from msm.api.portfolios import Portfolio

        if portfolio.calendar_uid in (None, ""):
            raise ValueError(
                "PortfoliosDataNode cannot update PortfolioTable pointers because "
                "portfolio.calendar_uid is missing."
            )
        self._ensure_signal_metadata(self.signal_weights)
        portfolio = Portfolio.upsert(
            unique_identifier=str(portfolio.unique_identifier),
            calendar_uid=portfolio.calendar_uid,
            published_index_uid=portfolio.published_index_uid,
            backtest_table_price_column_name=(
                portfolio.backtest_table_price_column_name or self.valuation_column
            ),
            signal_weights_data_node_uid=signal_weights_data_node_uid,
            signal_uid=self._required_signal_uid(self.signal_weights),
            portfolio_weights_data_node_uid=portfolio_weights_data_node_uid,
            portfolio_data_node_uid=portfolio_data_node_uid,
        )
        self.target_portfolio = portfolio
        return portfolio

    @staticmethod
    def _ensure_signal_metadata(signal_weights: Any) -> None:
        signal_weights._upsert_signal_metadata_if_available()

    @staticmethod
    def _required_signal_uid(signal_weights: Any) -> str:
        signal_uid = signal_weights.signal_uid
        if signal_uid in (None, ""):
            raise RuntimeError("signal_weights.signal_uid is not available.")
        return str(signal_uid)

    @staticmethod
    def _required_table_update_uid(node: Any, label: str) -> str:
        uid = node.table_update.uid
        if uid in (None, ""):
            raise RuntimeError(f"{label} TimeIndexTableUpdate.uid is not available.")
        return str(uid)

    def _upsert_portfolio_metadata_if_available(self, frame: pd.DataFrame) -> None:
        configuration = self._portfolio_configuration
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

    @staticmethod
    def normalize_values_frame(
        portfolio_values_frame: pd.DataFrame,
        *,
        unique_identifier: str,
    ) -> pd.DataFrame:
        return normalize_portfolio_values_frame(
            portfolio_values_frame,
            unique_identifier=unique_identifier,
        )

    @classmethod
    def _required_output_table(cls) -> type[PortfoliosStorage]:
        return PortfoliosStorage


def normalize_portfolio_values_frame(
    portfolio_values_frame: pd.DataFrame,
    *,
    unique_identifier: str,
    output_table: OutputTable | None = None,
) -> pd.DataFrame:
    """Normalize portfolio values into canonical valuation-observation rows."""
    required_columns = list(PortfoliosDataNode._column_dtypes_map_for_storage(output_table))
    flat = _reset_frame_index(portfolio_values_frame)
    if flat.empty:
        flat = _empty_flat_frame(column_names=required_columns)
    if PORTFOLIO_CANONICAL_TIME_INDEX_NAME not in flat.columns and "index" in flat.columns:
        flat = flat.rename(columns={"index": PORTFOLIO_CANONICAL_TIME_INDEX_NAME})
    flat[PORTFOLIO_IDENTIFIER] = str(unique_identifier)
    if "calculated_close" not in flat.columns and "close" in flat.columns:
        flat["calculated_close"] = flat["close"]
    if "close_time" not in flat.columns and PORTFOLIO_CANONICAL_TIME_INDEX_NAME in flat.columns:
        flat["close_time"] = flat[PORTFOLIO_CANONICAL_TIME_INDEX_NAME]
    _require_columns(flat, required_columns=required_columns, frame_name="PortfoliosDataNode")
    return PortfoliosDataNode.validate_frame(flat[required_columns], output_table=output_table)


__all__ = ["PortfoliosDataNode", "normalize_portfolio_values_frame"]
