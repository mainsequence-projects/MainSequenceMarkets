from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytz

import mainsequence.meta_tables.data_nodes.build_operations as build_operations
from mainsequence.client.metatables import UpdateStatistics
from mainsequence.meta_tables import APIDataNode, DataNode
from msm_portfolios.asset_scope import dedupe_asset_scope

from ..base import (
    PortfolioCanonicalDataNode,
    PortfolioCanonicalDataNodeConfiguration,
    StorageTable,
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
from .weights import PortfolioWeights
from .storage import PortfoliosStorage


def translate_to_pandas_freq(custom_freq: str) -> str:
    freq_mapping = {
        "d": "D",
        "m": "min",
        "mo": "M",
    }

    import re

    match = re.match(r"(\d+)([a-z]+)", custom_freq)
    if not match:
        raise ValueError(f"Invalid frequency format: {custom_freq}")

    number, unit = match.groups()
    if unit not in freq_mapping:
        raise ValueError(f"Unsupported frequency unit: {unit}")
    return f"{number}{freq_mapping[unit]}"


def _calendar_schedule_name(calendar: Any) -> str:
    for attr_name in ("name", "calendar_key"):
        value = getattr(calendar, attr_name, None)
        if value not in (None, ""):
            return str(value)
    persisted_calendar = getattr(calendar, "calendar", None)
    if persisted_calendar is not None:
        for attr_name in ("unique_identifier", "display_name", "source_identifier", "uid"):
            value = getattr(persisted_calendar, attr_name, None)
            if value not in (None, ""):
                return str(value)
    return calendar.__class__.__name__


class PortfoliosDataNode(PortfolioCanonicalDataNode):
    """Canonical portfolio values DataNode and portfolio workflow orchestrator."""

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)

    def __init__(
        self,
        config: PortfolioCanonicalDataNodeConfiguration | None = None,
        *args,
        portfolio_configuration: Any | None = None,
        namespace: str | None = None,
        **kwargs,
    ):
        self.portfolio_configuration = portfolio_configuration
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_resolver = None
        self._explicit_portfolio_identifier: str | None = None
        self._portfolio_values_frame: pd.DataFrame | None = None
        self._portfolio_description: str | None = None
        self._portfolio_metadata_updater = None
        self._resolved_unique_identifier: str | None = None
        self.required_valuation_asset_preflight = None
        self.target_portfolio = None
        if portfolio_configuration is not None:
            self._initialize_from_portfolio_configuration(portfolio_configuration)
        super().__init__(config, *args, namespace=namespace, **kwargs)

    def _initialize_configuration(self, init_kwargs: dict) -> None:
        """Hash every workflow instance as the canonical Portfolios table."""
        _drop_empty_framework_init_kwargs(init_kwargs)
        for runtime_key in (
            "portfolio_configuration",
            "portfolio_resolver",
            "portfolio_description",
            "metadata_updater",
        ):
            init_kwargs.pop(runtime_key, None)
        init_kwargs["time_series_class_import_path"] = _class_import_path(PortfoliosDataNode)
        config = build_operations.create_config(
            kwargs=init_kwargs,
            ts_class_name=PortfoliosDataNode.__name__,
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
        self._initialize_from_portfolio_configuration(portfolio_configuration)
        return self

    def _initialize_from_portfolio_configuration(self, portfolio_configuration: Any) -> None:
        from ..signals import SignalWeights

        self.portfolio_configuration = portfolio_configuration
        self._portfolio_configuration = portfolio_configuration
        portfolio_build_configuration = portfolio_configuration.portfolio_build_configuration
        self.portfolio_build_configuration = portfolio_build_configuration
        self.execution_configuration = portfolio_build_configuration.execution_configuration
        self.backtesting_weights_config = (
            portfolio_build_configuration.backtesting_weights_configuration
        )
        self.portfolio_markets_config = portfolio_configuration.portfolio_markets_configuration
        self.commission_fee = self.execution_configuration.commission_fee
        self.portfolio_prices_frequency = portfolio_build_configuration.portfolio_prices_frequency
        self.valuation_source = portfolio_build_configuration.valuation_source_instance
        self.valuation_column = str(portfolio_build_configuration.valuation_column)
        self.price_alignment_policy = portfolio_build_configuration.price_alignment_policy
        self.portfolio_frequency = self._portfolio_update_frequency()

        self.signal_weights = self.backtesting_weights_config.signal_weights_instance
        if not isinstance(self.signal_weights, SignalWeights):
            raise TypeError(
                "PortfoliosDataNode requires signal_weights_instance to inherit from SignalWeights."
            )

        self.rebalancer = self.backtesting_weights_config.rebalance_strategy_instance
        self.rebalancer_explanation = ""

        get_valuations = self.valuation_source.get_df_between_dates
        if not callable(get_valuations):
            raise TypeError(
                "PortfolioBuildConfiguration.valuation_source_instance must expose "
                "get_df_between_dates(...)."
            )

        preflight_asset_list = self.signal_weights.get_asset_list()
        portfolio_asset_uid = self.signal_weights.get_asset_uid_to_override_portfolio_price()
        if portfolio_asset_uid is not None:
            preflight_asset_list = dedupe_asset_scope(
                [*(preflight_asset_list or []), portfolio_asset_uid]
            )
        self.required_valuation_asset_preflight = preflight_asset_list

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
        """Attach runtime value inputs without changing table identity."""
        self._portfolio_values_frame = portfolio_values_frame
        self._explicit_portfolio_identifier = unique_identifier
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        return self

    def dependencies(self) -> dict[str, DataNode | APIDataNode]:
        if self.portfolio_configuration is None:
            return {}
        return {
            "signal_weights": self.signal_weights,
            "valuation_source": self.valuation_source,
        }

    def run(
        self,
        debug_mode: bool = True,
        *,
        update_tree: bool = True,
        force_update: bool = False,
        update_only_tree: bool = False,
        update_pointers: bool = True,
        remote_scheduler: object | None = None,
        override_update_stats: UpdateStatistics | None = None,
    ):
        if self.portfolio_configuration is None:
            return super().run(
                debug_mode=debug_mode,
                update_tree=update_tree,
                force_update=force_update,
                update_only_tree=update_only_tree,
                remote_scheduler=remote_scheduler,
                override_update_stats=override_update_stats,
            )

        portfolio = self._resolve_portfolio_identity()
        portfolio_unique_identifier = str(portfolio.unique_identifier)
        self._resolved_unique_identifier = portfolio_unique_identifier
        portfolio_weights_node = PortfolioWeights(namespace=self._canonical_namespace())

        portfolio_values_result = super().run(
            debug_mode=debug_mode,
            update_tree=update_tree,
            force_update=force_update,
            update_only_tree=update_only_tree,
            remote_scheduler=remote_scheduler,
            override_update_stats=override_update_stats,
        )
        if update_only_tree:
            return portfolio_values_result

        weights = self._last_canonical_weights_frame
        portfolio_weights_result = None
        portfolio_weights_data_node_uid = portfolio.portfolio_weights_data_node_uid
        if not weights.empty:
            portfolio_weights_node.set_weights_frame(
                weights,
                portfolio_identifier=portfolio_unique_identifier,
                portfolio_configuration=self.portfolio_configuration,
                portfolio=portfolio,
                portfolio_description=self._resolve_portfolio_description(),
            )
            portfolio_weights_result = portfolio_weights_node.run(
                debug_mode=debug_mode,
                update_tree=False,
                force_update=force_update,
                remote_scheduler=remote_scheduler,
            )
            portfolio_weights_data_node_uid = self._required_data_node_update_uid(
                portfolio_weights_node,
                "portfolio weights",
            )

        if update_pointers:
            portfolio = self._update_portfolio_pointers(
                portfolio=portfolio,
                signal_weights_data_node_uid=self._required_data_node_update_uid(
                    self.signal_weights,
                    "signal weights",
                ),
                portfolio_weights_data_node_uid=portfolio_weights_data_node_uid,
                portfolio_data_node_uid=self._required_data_node_update_uid(
                    self,
                    "portfolio values",
                ),
            )

        return {
            "portfolio_weights": portfolio_weights_result,
            "portfolio_values": portfolio_values_result,
            "portfolio": portfolio,
        }

    def _update_portfolio_pointers(
        self,
        *,
        portfolio: Any,
        signal_weights_data_node_uid: str,
        portfolio_weights_data_node_uid: str | None,
        portfolio_data_node_uid: str,
    ) -> Any:
        from msm.api.portfolios import Portfolio

        calendar_uid = portfolio.calendar_uid
        if calendar_uid in (None, ""):
            raise ValueError(
                "PortfoliosDataNode cannot update PortfolioTable pointers for "
                f"{portfolio.unique_identifier!r} because portfolio.calendar_uid is missing. "
                "Portfolio rows must be created with calendar_uid before running the "
                "portfolio graph."
            )

        self._ensure_signal_metadata(self.signal_weights)
        signal_uid = self._required_signal_uid(self.signal_weights)
        portfolio = Portfolio.upsert(
            unique_identifier=str(portfolio.unique_identifier),
            calendar_uid=calendar_uid,
            published_index_uid=portfolio.published_index_uid,
            backtest_table_price_column_name=(
                portfolio.backtest_table_price_column_name or self.valuation_column
            ),
            signal_weights_data_node_uid=signal_weights_data_node_uid,
            signal_uid=signal_uid,
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
            raise RuntimeError(
                "Cannot update PortfolioTable signal pointer because signal_weights.signal_uid "
                "is not available."
            )
        return str(signal_uid)

    @staticmethod
    def _required_data_node_update_uid(node: Any, label: str) -> str:
        data_node_update = node.data_node_update
        uid = data_node_update.uid
        if uid in (None, ""):
            raise RuntimeError(
                f"Cannot update PortfolioTable DataNode pointers because {label} "
                "DataNodeUpdate.uid is not available."
            )
        return str(uid)

    def update(self) -> pd.DataFrame:
        raw_frame = self._calculate_portfolio_values()
        frame = (
            self.validate_frame(raw_frame, storage_table=self.storage_table)
            if _is_canonical_frame(raw_frame, storage_table=self.storage_table)
            else self.validate_frame(
                normalize_portfolio_values_frame(
                    raw_frame,
                    unique_identifier=self._resolve_unique_identifier(),
                    storage_table=self.storage_table,
                ),
                storage_table=self.storage_table,
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
        self.logger.debug("Starting update of portfolio weights.")
        self._last_canonical_weights_frame = pd.DataFrame()
        self._last_canonical_portfolio_values_frame = pd.DataFrame()
        start_date, end_date = self._calculate_start_end_dates()
        self.logger.debug(f"Update from {start_date} to {end_date}")

        if start_date is None:
            self.logger.info("Start date is None, no update is done")
            return pd.DataFrame()

        if pd.Timestamp(end_date) < pd.Timestamp(start_date):
            self.logger.info(
                "No new portfolio values to update because existing portfolio "
                "output is already ahead of usable valuation-source coverage.",
                valuation_source=self._valuation_source_identifier(self.valuation_source),
                latest_portfolio_time_index=start_date,
                usable_valuation_end_date=end_date,
            )
            return pd.DataFrame()

        new_index, index_freq = self._generate_new_index(
            start_date,
            end_date,
            self.rebalancer.calendar,
        )
        if len(new_index) == 0:
            self.logger.info("No new portfolio weights to update")
            return pd.DataFrame()

        signal_weights = self.signal_weights.interpolate_index(new_index).dropna()
        if len(signal_weights) == 0:
            self.logger.info("No signal weights found, no update is done")
            return pd.DataFrame()

        new_index = new_index[
            new_index <= signal_weights.index.max() + self.signal_weights.maximum_forward_fill()
        ]

        expected_columns = [ASSET_IDENTIFIER]
        assert signal_weights.columns.names == expected_columns, (
            f"signal_weights must have columns named {expected_columns}"
        )

        last_rebalance_weights = self._get_last_weights()
        required_valuation_asset_identifiers = self._required_valuation_asset_identifiers(
            signal_weights=signal_weights,
            last_rebalance_weights=last_rebalance_weights,
        )
        usable_valuation_end_date = self._usable_valuation_end_date(
            required_valuation_asset_identifiers
        )
        if pd.Timestamp(usable_valuation_end_date) < pd.Timestamp(start_date):
            self.logger.info(
                "No new portfolio values to update because existing portfolio "
                "output is already ahead of usable valuation-source coverage.",
                valuation_source=self._valuation_source_identifier(self.valuation_source),
                latest_portfolio_time_index=start_date,
                usable_valuation_end_date=usable_valuation_end_date,
            )
            return pd.DataFrame()

        new_index = new_index[new_index <= usable_valuation_end_date]
        signal_weights = signal_weights[signal_weights.index <= usable_valuation_end_date]
        if len(new_index) == 0 or len(signal_weights) == 0:
            self.logger.info(
                "No new portfolio values to update after applying valuation-source coverage.",
                valuation_source=self._valuation_source_identifier(self.valuation_source),
                latest_portfolio_time_index=start_date,
                usable_valuation_end_date=usable_valuation_end_date,
            )
            return pd.DataFrame()

        raw_valuations, aligned_valuations = self._align_valuation_source_to_index(
            new_index=new_index,
            valuation_source=self.valuation_source,
            index_freq=index_freq,
            unique_identifiers=required_valuation_asset_identifiers,
        )

        latest_value = self._latest_portfolio_time_index_value()
        if latest_value is not None:
            aligned_valuations = aligned_valuations[
                aligned_valuations.index.get_level_values("time_index") > latest_value
            ]
            signal_weights = signal_weights[signal_weights.index > latest_value]

        if aligned_valuations.empty:
            raise ValueError(
                "Aligned portfolio valuations are empty. Check whether asset valuations "
                "exist for the requested time window."
            )

        weights = self.rebalancer.apply_rebalance_logic(
            signal_weights=signal_weights,
            start_date=start_date,
            valuations_df=aligned_valuations,
            end_date=end_date,
            last_rebalance_weights=last_rebalance_weights,
            valuation_column=self.valuation_column,
        )

        weights = self._postprocess_weights(weights)
        if len(weights) == 0:
            self.logger.info("No portfolio weights to update")
            return pd.DataFrame()

        portfolio_returns = self._calculate_portfolio_returns(weights, raw_valuations)
        portfolio = self._apply_cumulative_portfolio_values(portfolio_returns)
        if len(portfolio) > 0 and latest_value is not None:
            portfolio = portfolio[portfolio.index > latest_value]

        portfolio = self._resample_portfolio_with_calendar(portfolio)
        asset_uid_to_override_portfolio_price = (
            self.signal_weights.get_asset_uid_to_override_portfolio_price()
        )
        if asset_uid_to_override_portfolio_price is not None:
            new_portfolio_valuation = self.valuation_source.get_df_between_dates(
                start_date=portfolio.index.min(),
                great_or_equal=True,
                dimension_filters={
                    ASSET_IDENTIFIER: [asset_uid_to_override_portfolio_price],
                },
            )
            if new_portfolio_valuation.empty:
                self.logger.error("No valuations on portfolio target asset")
                return pd.DataFrame()

            new_portfolio_valuation = new_portfolio_valuation.reset_index(
                ASSET_IDENTIFIER, drop=True
            )
            union_index = new_portfolio_valuation.index.union(portfolio.index.unique()).unique()
            new_portfolio_valuation = new_portfolio_valuation.reindex(union_index).ffill().bfill()
            new_portfolio_valuation = new_portfolio_valuation.reindex(portfolio.index)
            portfolio["calculated_close"] = portfolio["close"]
            portfolio["close"] = new_portfolio_valuation[self.valuation_column]
            portfolio["return"] = portfolio["close"].pct_change().fillna(0.0)

        self.logger.info(f"{len(portfolio)} new portfolio values have been calculated.")
        self._last_canonical_weights_frame = weights
        self._last_canonical_portfolio_values_frame = portfolio
        return portfolio

    def _canonical_namespace(self) -> str | None:
        namespace = self.hash_namespace or ""
        return namespace or None

    def _resolve_portfolio_identity(self) -> Any:
        if self.target_portfolio is not None and self.target_portfolio.unique_identifier:
            return self.target_portfolio

        portfolio_configuration = (
            self.portfolio_configuration
            if self.portfolio_configuration is not None
            else self._portfolio_configuration
        )
        if portfolio_configuration is None:
            raise ValueError(
                "PortfoliosDataNode requires a portfolio_configuration to resolve "
                "the portfolio identity."
            )

        portfolio = get_or_create_portfolio(
            portfolio_configuration,
            portfolio_resolver=self._portfolio_resolver,
        )
        self.target_portfolio = portfolio
        return portfolio

    def _unique_identifier(self) -> str:
        portfolio = self._resolve_portfolio_identity()
        unique_identifier = portfolio.unique_identifier
        if not unique_identifier:
            raise ValueError("Portfolio must expose unique_identifier.")
        return str(unique_identifier)

    def _resolve_portfolio_description(self) -> str | None:
        if self._portfolio_description is not None:
            return str(self._portfolio_description)
        front_end_details = self.portfolio_markets_config.front_end_details
        if front_end_details is None:
            return None
        description = front_end_details.description
        return None if description is None else str(description)

    def _latest_portfolio_time_index_value(self):
        update_statistics = self.update_statistics
        if update_statistics is None:
            return None

        portfolio_identifier = self._portfolio_progress_identifier()
        if portfolio_identifier is not None:
            progress = update_statistics.index_progress
            if progress is None:
                return None
            progress_value = progress.get(portfolio_identifier)
            if isinstance(progress_value, dict):
                return progress_value.get("max") or progress_value.get("time_index")
            return progress_value

        return update_statistics.max_time_index_value

    def _portfolio_progress_identifier(self) -> str | None:
        portfolio_identifier = self._resolved_unique_identifier
        if portfolio_identifier is not None:
            return str(portfolio_identifier)

        if self.portfolio_configuration is not None or self._portfolio_configuration is not None:
            portfolio_identifier = self._unique_identifier()
            self._resolved_unique_identifier = portfolio_identifier
            return portfolio_identifier

        return None

    def _calculate_start_end_dates(self):
        start_date = self._portfolio_update_start_date()
        end_date = datetime.now(pytz.utc)
        max_td_env = os.getenv("MAX_TD_FROM_LATEST_VALUE", None)
        if max_td_env is not None:
            new_end_date = start_date + pd.Timedelta(max_td_env)
            end_date = new_end_date if new_end_date < end_date else end_date

        return start_date, end_date

    def _portfolio_update_start_date(self):
        return self._latest_portfolio_time_index_value() or self.OFFSET_START

    def _usable_valuation_end_date(self, asset_identifiers: list[str]):
        update_statics_from_dependencies = self._valuation_source_update_statistics()
        progress_values = self._required_valuation_source_progress_values(
            update_statics_from_dependencies,
            asset_identifiers=asset_identifiers,
        )
        earliest_last_value = min(progress_values) if progress_values else None

        if earliest_last_value is None:
            self.logger.warning(
                f"update_statics_from_dependencies {update_statics_from_dependencies}"
            )
            raise Exception("Valuation source is empty")

        if self.price_alignment_policy.forward_fill_to_now:
            return datetime.now(pytz.utc)
        return earliest_last_value + self._valuation_source_maximum_forward_fill()

    def _valuation_source_update_statistics(self) -> UpdateStatistics:
        update_statistics = self.valuation_source.update_statistics
        if update_statistics is not None:
            return update_statistics

        if isinstance(self.valuation_source, APIDataNode):
            update_statistics = self.valuation_source.get_update_statistics()
            self.valuation_source.update_statistics = update_statistics
            return update_statistics

        if isinstance(self.valuation_source, DataNode):
            raise RuntimeError(
                "PortfoliosDataNode valuation source DataNode has no update_statistics. "
                "The SDK runner must populate dependency update_statistics before "
                "portfolio update-window calculation."
            )

        raise TypeError("PortfoliosDataNode valuation_source must be a DataNode or APIDataNode.")

    def _required_valuation_source_progress_values(
        self,
        update_statistics,
        *,
        asset_identifiers: list[str],
    ) -> list:
        if not asset_identifiers:
            raise ValueError(
                "PortfoliosDataNode cannot derive the valuation-source update window "
                "without a required asset scope. The actual signal frame must expose "
                "asset columns, or this portfolio must have previous weights that "
                "identify assets still needing valuation or liquidation."
            )

        progress_values = [
            update_statistics.get_earliest_update_for_identity(asset_identifier)
            for asset_identifier in asset_identifiers
        ]
        return [value for value in progress_values if value is not None]

    def _generate_new_index(self, start_date, end_date, rebalancer_calendar):
        upsample_freq = self._portfolio_update_frequency()

        if "d" in upsample_freq:
            assert upsample_freq == "1d", "Only '1d' frequency is implemented."
            upsample_freq = translate_to_pandas_freq(upsample_freq)
            freq = upsample_freq.replace("days", "d")
            schedule = rebalancer_calendar.schedule(start_date=start_date, end_date=end_date)
            if schedule.empty:
                calendar_name = _calendar_schedule_name(rebalancer_calendar)
                raise ValueError(
                    f"Calendar {calendar_name} has no sessions for requested "
                    f"portfolio update range {start_date} to {end_date}. "
                    "Materialize CalendarSession rows for this calendar before "
                    "running portfolio execution."
                )
            new_index = schedule.set_index("market_close").index
            new_index.name = None
            new_index = new_index[new_index <= end_date]
        else:
            upsample_freq = translate_to_pandas_freq(upsample_freq)
            self.logger.warning("Matching new index with calendar")
            freq = upsample_freq
            new_index = pd.date_range(start=start_date, end=end_date, freq=freq)
        return new_index, freq

    def _postprocess_weights(self, weights):
        latest_value = self._latest_portfolio_time_index_value()
        if latest_value is not None:
            weights = weights[weights.index > latest_value]
        if weights.empty:
            return pd.DataFrame()

        weights = weights.stack()
        required_columns = ["weights_before", "weights_current", "price_current", "price_before"]
        for col in required_columns:
            assert col in weights.columns, f"Column '{col}' is missing in weights"

        weights = weights.dropna(subset=["weights_current"])
        if latest_value is not None:
            weights = weights[weights.index.get_level_values("time_index") > latest_value]

        if latest_value is not None:
            last_weights = self._get_last_weights()
            if last_weights is not None and not last_weights.empty:
                weights = pd.concat([last_weights, weights], axis=0).fillna(0)

        return weights

    def _required_valuation_asset_identifiers(
        self,
        *,
        signal_weights: pd.DataFrame,
        last_rebalance_weights: pd.DataFrame | None,
    ) -> list[str]:
        required_assets = [
            str(value) for value in signal_weights.columns.get_level_values(ASSET_IDENTIFIER)
        ]
        if (
            last_rebalance_weights is not None
            and not last_rebalance_weights.empty
            and isinstance(last_rebalance_weights.index, pd.MultiIndex)
            and ASSET_IDENTIFIER in last_rebalance_weights.index.names
        ):
            required_assets.extend(
                str(value)
                for value in last_rebalance_weights.index.get_level_values(
                    ASSET_IDENTIFIER
                ).unique()
            )

        portfolio_price_asset = self.signal_weights.get_asset_uid_to_override_portfolio_price()
        if portfolio_price_asset is not None:
            required_assets.append(str(portfolio_price_asset))

        return list(dict.fromkeys(required_assets))

    def _calculate_portfolio_returns(
        self,
        weights: pd.DataFrame,
        valuations: pd.DataFrame,
    ) -> pd.DataFrame:
        weights = weights.reset_index().pivot(
            index="time_index",
            columns=[ASSET_IDENTIFIER],
            values=["price_current", "weights_before", "weights_current"],
        )

        price_current = weights.price_current
        weights_before = weights.weights_before.fillna(0)
        weights_current = weights.weights_current.fillna(0)
        valuations = valuations[self.valuation_column].unstack()
        first_valuation_date = (
            valuations.stack().dropna().index.union(price_current.stack().dropna().index)[0][0]
        )

        valuations = price_current.combine_first(valuations).sort_index().ffill()
        valuations = valuations.reindex(weights.index)
        returns = (valuations / valuations.shift(1) - 1).fillna(0.0)
        returns.replace([np.inf, -np.inf], 0, inplace=True)
        weights_before = weights_before.reindex(returns.index, method="ffill").dropna()
        weights_current = weights_current.reindex(returns.index, method="ffill").dropna()
        weighted_returns = (weights_before * returns).dropna()
        weights_diff = (weights_current - weights_before).fillna(0)
        fees = (weights_diff.abs() * self.commission_fee).sum(axis=1)
        portfolio_returns = pd.DataFrame({"return": weighted_returns.sum(axis=1) - fees})
        return portfolio_returns[portfolio_returns.index >= first_valuation_date]

    def _apply_cumulative_portfolio_values(self, portfolio: pd.DataFrame) -> pd.DataFrame:
        last_portfolio = 1
        latest_value = self._latest_portfolio_time_index_value()
        if latest_value is not None:
            last_obs = self.get_df_between_dates(
                start_date=latest_value,
                great_or_equal=True,
                dimension_filters={PORTFOLIO_IDENTIFIER: [self._unique_identifier()]},
            )
            if last_obs is not None and not last_obs.empty:
                last_obs = last_obs.sort_index()
                latest_time_index = last_obs.index.get_level_values("time_index").max()
                last_obs = last_obs[
                    last_obs.index.get_level_values("time_index") == latest_time_index
                ]
                last_portfolio = last_obs["close"].iloc[0]
                portfolio = portfolio[portfolio.index > latest_time_index]

        portfolio["close"] = last_portfolio * np.cumprod(portfolio["return"] + 1)
        return portfolio

    def _get_last_weights(self):
        latest_value = self._latest_portfolio_time_index_value()
        if latest_value is None:
            return None

        portfolio_weights_node = PortfolioWeights(namespace=self._canonical_namespace())
        last_obs = portfolio_weights_node.get_df_between_dates(
            start_date=latest_value,
            great_or_equal=True,
            dimension_filters={PORTFOLIO_IDENTIFIER: [self._unique_identifier()]},
        )
        if last_obs is None or last_obs.empty:
            return None

        last_obs = last_obs.sort_index()
        latest_time_index = last_obs.index.get_level_values("time_index").max()
        last_weights = last_obs[
            last_obs.index.get_level_values("time_index") == latest_time_index
        ].copy()
        if PORTFOLIO_IDENTIFIER in last_weights.index.names:
            last_weights = last_weights.droplevel(PORTFOLIO_IDENTIFIER)
        return last_weights.rename(columns={"weight": "weights_current"})

    def _align_valuation_source_to_index(
        self,
        new_index: pd.DatetimeIndex,
        unique_identifiers: list,
        index_freq: str,
        valuation_source: DataNode | APIDataNode,
    ):
        fetch_end_date = new_index.max()
        raw_valuations = valuation_source.get_df_between_dates(
            start_date=new_index.min() - pd.Timedelta(index_freq),
            end_date=fetch_end_date,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={ASSET_IDENTIFIER: unique_identifiers},
        )

        if len(raw_valuations) == 0:
            self.logger.info(
                "No valuation data in local portfolio valuation alignment for "
                f"valuation_source={self._valuation_source_identifier(valuation_source)}"
            )
            return pd.DataFrame(), pd.DataFrame()

        raw_valuations = self._filter_valuation_frame_to_requested_assets(
            raw_valuations,
            requested_asset_identifiers=unique_identifiers,
        )
        if len(raw_valuations) == 0:
            self.logger.info(
                "Valuation source returned no rows for the signal-required assets.",
                valuation_source=self._valuation_source_identifier(valuation_source),
                requested_asset_identifiers=[str(value) for value in unique_identifiers],
            )
            return pd.DataFrame(), pd.DataFrame()

        self._diagnose_valuation_source_coverage(
            raw_valuations,
            requested_asset_identifiers=unique_identifiers,
            valuation_source=valuation_source,
            start_date=new_index.min(),
            end_date=fetch_end_date,
        )

        if self.valuation_column not in raw_valuations.columns:
            raise ValueError(
                "Portfolio valuation source is missing required valuation column "
                f"{self.valuation_column!r}. Available columns: "
                f"{list(raw_valuations.columns)}."
            )

        raw_valuations.sort_values("time_index", inplace=True)
        final_index_for_interpolation = new_index
        if self.price_alignment_policy.forward_fill_to_now:
            fill_end_date = datetime.now(pytz.utc)
            last_ts_in_df = raw_valuations.index.get_level_values("time_index").max()
            self.logger.info(f"Forward-filling valuations from {last_ts_in_df} to {fill_end_date}")
            pandas_freq = translate_to_pandas_freq(self.portfolio_prices_frequency)
            final_index_for_interpolation = pd.date_range(
                start=new_index.min(),
                end=fill_end_date,
                freq=pandas_freq,
            )

        aligned_valuations = raw_valuations.unstack([ASSET_IDENTIFIER])
        raw_time_index = pd.DatetimeIndex(
            raw_valuations.index.get_level_values("time_index").unique()
        )
        missing_rebalance_times = pd.DatetimeIndex(final_index_for_interpolation).difference(
            raw_time_index
        )
        if len(missing_rebalance_times) > 0:
            self.logger.warning(
                "Portfolio local valuation alignment forward-filled consumed valuations.",
                valuation_source=self._valuation_source_identifier(valuation_source),
                missing_timestamp_count=len(missing_rebalance_times),
                start_date=new_index.min(),
                end_date=fetch_end_date,
                valuation_column=self.valuation_column,
            )
        aligned_valuations = aligned_valuations.reindex(
            final_index_for_interpolation,
            method="ffill",
        )
        aligned_valuations.index.names = ["time_index"]
        aligned_valuations = aligned_valuations.stack([ASSET_IDENTIFIER])
        return raw_valuations, aligned_valuations

    def _filter_valuation_frame_to_requested_assets(
        self,
        raw_valuations: pd.DataFrame,
        *,
        requested_asset_identifiers: list,
    ) -> pd.DataFrame:
        if raw_valuations.empty or not isinstance(raw_valuations.index, pd.MultiIndex):
            return raw_valuations
        if ASSET_IDENTIFIER not in raw_valuations.index.names:
            return raw_valuations
        requested_identifiers = {str(value) for value in requested_asset_identifiers}
        asset_level = raw_valuations.index.get_level_values(ASSET_IDENTIFIER).map(str)
        return raw_valuations[asset_level.isin(requested_identifiers)]

    def _diagnose_valuation_source_coverage(
        self,
        raw_valuations: pd.DataFrame,
        *,
        requested_asset_identifiers: list,
        valuation_source: DataNode | APIDataNode,
        start_date,
        end_date,
    ) -> None:
        if raw_valuations.empty or not isinstance(raw_valuations.index, pd.MultiIndex):
            return

        available_identifiers = {
            str(value) for value in raw_valuations.index.get_level_values(ASSET_IDENTIFIER).unique()
        }
        requested_identifiers = {str(value) for value in requested_asset_identifiers}
        missing_identifiers = sorted(requested_identifiers - available_identifiers)
        if not missing_identifiers:
            return

        self.logger.warning(
            "Portfolio valuation source is missing required signal assets.",
            valuation_source=self._valuation_source_identifier(valuation_source),
            missing_asset_identifiers=missing_identifiers,
            start_date=start_date,
            end_date=end_date,
            valuation_column=self.valuation_column,
            fail_on_missing_prices=self.price_alignment_policy.fail_on_missing_prices,
        )
        if self.price_alignment_policy.fail_on_missing_prices:
            raise ValueError(
                "Portfolio valuation source is missing required signal assets: "
                f"{', '.join(missing_identifiers)}."
            )

    def _valuation_source_identifier(self, valuation_source: DataNode | APIDataNode) -> str:
        if valuation_source.is_api:
            if not isinstance(valuation_source, APIDataNode):
                raise TypeError("API portfolio valuation sources must be APIDataNode instances.")
        else:
            if not isinstance(valuation_source, DataNode):
                raise TypeError(
                    "Portfolio valuation sources must be DataNode or APIDataNode instances."
                )
        return str(valuation_source.update_hash)

    def _valuation_source_maximum_forward_fill(self) -> pd.Timedelta:
        try:
            maximum_forward_fill = self.valuation_source.maximum_forward_fill
        except AttributeError:
            maximum_forward_fill = None
        if maximum_forward_fill is not None:
            return pd.Timedelta(maximum_forward_fill)
        return pd.Timedelta(translate_to_pandas_freq(self._portfolio_update_frequency()))

    def _portfolio_update_frequency(self) -> str:
        if self.portfolio_prices_frequency not in (None, ""):
            return str(self.portfolio_prices_frequency)
        try:
            upsample_frequency_id = self.valuation_source.upsample_frequency_id
        except AttributeError:
            upsample_frequency_id = None
        if upsample_frequency_id not in (None, ""):
            return str(upsample_frequency_id)

        try:
            bar_frequency_id = self.valuation_source.bar_frequency_id
        except AttributeError:
            bar_frequency_id = None
        if bar_frequency_id not in (None, ""):
            return str(bar_frequency_id)

        try:
            storage_table = self.valuation_source.storage_table
        except AttributeError:
            storage_table = None
        cadence = None if storage_table is None else storage_table.__cadence__
        if cadence not in (None, ""):
            return str(cadence)
        return "1d"

    def _resample_portfolio_with_calendar(self, portfolio: pd.DataFrame) -> pd.DataFrame:
        if len(portfolio) == 0:
            return portfolio
        portfolio.index = pd.to_datetime(portfolio.index)
        portfolio["close_time"] = portfolio.index.strftime("%Y-%m-%d %H:%M:%S")
        return (
            portfolio.resample(pd.to_timedelta(self.portfolio_frequency_to_pandas())).last().ffill()
        )

    def portfolio_frequency_to_pandas(self):
        return translate_to_pandas_freq(self.portfolio_prices_frequency)

    def get_portfolio_about_text(self):
        portfolio_about = """Portfolio created with Main Sequence Portfolios engine with the following signal and
rebalance details:"""
        import json

        return json.dumps(portfolio_about)

    def build_prefix(self):
        reba_strat = self.rebalance_strategy_name
        signa_name = self.signal_weights_name
        return f"{reba_strat}_{signa_name}"

    def _resolve_unique_identifier(self) -> str:
        explicit_identifier = self._explicit_portfolio_identifier
        if explicit_identifier:
            return str(explicit_identifier)

        if self._portfolio_configuration is not None:
            resolved_portfolio = get_or_create_portfolio(
                self._portfolio_configuration,
                portfolio_resolver=self._portfolio_resolver,
            )
            resolved_identifier = resolved_portfolio.unique_identifier
            if resolved_identifier:
                return str(resolved_identifier)

        raise ValueError(
            "PortfoliosDataNode requires a unique_identifier, "
            "or a portfolio_configuration that can resolve one before "
            "canonical rows can be written."
        )

    def _upsert_portfolio_metadata_if_available(self, frame: pd.DataFrame) -> None:
        portfolio_configuration = self._portfolio_configuration
        portfolio_description = self._portfolio_description
        if portfolio_configuration is None and portfolio_description is None:
            return

        flat = frame.reset_index()
        if flat.empty or PORTFOLIO_IDENTIFIER not in flat.columns:
            return
        unique_identifier = flat[PORTFOLIO_IDENTIFIER].iloc[0]
        if unique_identifier in (None, ""):
            return

        if (
            portfolio_description is None
            and extract_portfolio_description(portfolio_configuration) is None
        ):
            return

        emit_portfolio_metadata(
            unique_identifier=str(unique_identifier),
            description=portfolio_description
            or extract_portfolio_description(portfolio_configuration),
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
    def _required_storage_table(cls) -> type[PortfoliosStorage]:
        return PortfoliosStorage


def normalize_portfolio_values_frame(
    portfolio_values_frame: pd.DataFrame,
    *,
    unique_identifier: str,
    storage_table: StorageTable | None = None,
) -> pd.DataFrame:
    """Normalize Portfolios portfolio values into canonical PortfoliosDataNode rows."""
    required_columns = list(PortfoliosDataNode._column_dtypes_map_for_storage(storage_table))
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

    _require_columns(
        flat,
        required_columns=required_columns,
        frame_name="PortfoliosDataNode",
    )
    return PortfoliosDataNode.validate_frame(
        flat[required_columns],
        storage_table=storage_table,
    )
