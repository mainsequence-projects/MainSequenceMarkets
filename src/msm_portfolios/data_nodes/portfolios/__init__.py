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
from msm_portfolios.asset_scope import asset_unique_identifier, dedupe_asset_scope

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
        self.price_source = portfolio_build_configuration.price_source_instance
        self.price_column = portfolio_build_configuration.price_column
        self.price_alignment_policy = portfolio_build_configuration.price_alignment_policy
        self.portfolio_frequency = self._portfolio_update_frequency()

        self.signal_weights = self.backtesting_weights_config.signal_weights_instance
        if not isinstance(self.signal_weights, SignalWeights):
            raise TypeError(
                "PortfoliosDataNode requires signal_weights_instance to inherit from SignalWeights."
            )

        self.rebalancer = self.backtesting_weights_config.rebalance_strategy_instance
        self.rebalancer_explanation = ""

        get_prices = getattr(self.price_source, "get_df_between_dates", None)
        if not callable(get_prices):
            raise TypeError(
                "PortfolioBuildConfiguration.price_source_instance must expose "
                "get_df_between_dates(...)."
            )

        preflight_asset_list = self.signal_weights.get_asset_list()
        portfolio_asset_uid = self.signal_weights.get_asset_uid_to_override_portfolio_price()
        if portfolio_asset_uid is not None:
            preflight_asset_list = dedupe_asset_scope(
                [*(preflight_asset_list or []), portfolio_asset_uid]
            )
        self.required_price_asset_preflight = preflight_asset_list

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
        if getattr(self, "portfolio_configuration", None) is None:
            return {}
        return {"signal_weights": self.signal_weights, "price_source": self.price_source}

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
        if getattr(self, "portfolio_configuration", None) is None:
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
        portfolio_weights_node = self._canonical_portfolio_weights_node()

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

        weights = getattr(self, "_last_canonical_weights_frame", pd.DataFrame())
        portfolio_weights_result = None
        if weights is not None and not weights.empty:
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

        if update_pointers:
            portfolio = self._update_portfolio_pointers(
                portfolio=portfolio,
                portfolio_weights_node=portfolio_weights_node,
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
        portfolio_weights_node: PortfolioWeights,
    ) -> Any:
        from msm.api.portfolios import Portfolio

        portfolio = Portfolio.upsert(
            unique_identifier=str(portfolio.unique_identifier),
            calendar_uid=getattr(portfolio, "calendar_uid", None),
            calendar_name=getattr(portfolio, "calendar_name", None),
            published_index_uid=getattr(portfolio, "published_index_uid", None),
            backtest_table_price_column_name=(
                getattr(portfolio, "backtest_table_price_column_name", None) or "close"
            ),
            signal_weights_data_node_uid=self._required_data_node_update_uid(
                self.signal_weights,
                "signal weights",
            ),
            portfolio_weights_data_node_uid=self._required_data_node_update_uid(
                portfolio_weights_node,
                "portfolio weights",
            ),
            portfolio_data_node_uid=self._required_data_node_update_uid(
                self,
                "portfolio values",
            ),
        )
        self.target_portfolio = portfolio
        return portfolio

    @staticmethod
    def _required_data_node_update_uid(node: Any, label: str) -> str:
        data_node_update = getattr(node, "data_node_update", None)
        uid = getattr(data_node_update, "uid", None)
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
        if getattr(self, "portfolio_configuration", None) is not None:
            return self._calculate_portfolio_workflow_values()

        portfolio_values_frame = getattr(self, "_portfolio_values_frame", None)
        if portfolio_values_frame is None:
            return self.get_canonical_frame()
        return portfolio_values_frame

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
                "output is already ahead of usable price-source coverage.",
                price_source=self._price_source_identifier(self.price_source),
                latest_portfolio_time_index=start_date,
                usable_price_end_date=end_date,
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
        required_price_asset_identifiers = self._required_price_asset_identifiers(
            signal_weights=signal_weights,
            last_rebalance_weights=last_rebalance_weights,
        )
        raw_prices, interpolated_prices = self._interpolate_bars_index(
            new_index=new_index,
            price_source=self.price_source,
            index_freq=index_freq,
            unique_identifiers=required_price_asset_identifiers,
        )

        latest_value = self._latest_portfolio_time_index_value()
        if latest_value is not None:
            interpolated_prices = interpolated_prices[
                interpolated_prices.index.get_level_values("time_index") > latest_value
            ]
            signal_weights = signal_weights[signal_weights.index > latest_value]

        if interpolated_prices.empty:
            raise ValueError(
                "Interpolated Prices are empty. Check if asset prices exist for time window"
            )

        weights = self.rebalancer.apply_rebalance_logic(
            signal_weights=signal_weights,
            start_date=start_date,
            prices_df=interpolated_prices,
            end_date=end_date,
            last_rebalance_weights=last_rebalance_weights,
            price_type=self.price_column,
        )

        weights = self._postprocess_weights(weights)
        if len(weights) == 0:
            self.logger.info("No portfolio weights to update")
            return pd.DataFrame()

        portfolio_returns = self._calculate_portfolio_returns(weights, raw_prices)
        portfolio = self._apply_cumulative_portfolio_values(portfolio_returns)
        if len(portfolio) > 0 and latest_value is not None:
            portfolio = portfolio[portfolio.index > latest_value]

        portfolio = self._resample_portfolio_with_calendar(portfolio)
        asset_uid_to_override_portfolio_price = (
            self.signal_weights.get_asset_uid_to_override_portfolio_price()
        )
        if asset_uid_to_override_portfolio_price is not None:
            new_portfolio_price = self.price_source.get_df_between_dates(
                start_date=portfolio.index.min(),
                great_or_equal=True,
                dimension_filters={
                    ASSET_IDENTIFIER: [asset_uid_to_override_portfolio_price],
                },
            )
            if new_portfolio_price.empty:
                self.logger.error("No Prices on portfolio target asset")
                return pd.DataFrame()

            new_portfolio_price = new_portfolio_price.reset_index(ASSET_IDENTIFIER, drop=True)
            union_index = new_portfolio_price.index.union(portfolio.index.unique()).unique()
            new_portfolio_price = new_portfolio_price.reindex(union_index).ffill().bfill()
            new_portfolio_price = new_portfolio_price.reindex(portfolio.index)
            portfolio["calculated_close"] = portfolio["close"]
            portfolio["close"] = new_portfolio_price[self.price_column.value]
            portfolio["return"] = portfolio["close"].pct_change().fillna(0.0)

        self.logger.info(f"{len(portfolio)} new portfolio values have been calculated.")
        self._last_canonical_weights_frame = weights
        self._last_canonical_portfolio_values_frame = portfolio
        return portfolio

    def _canonical_namespace(self) -> str | None:
        namespace = getattr(self, "hash_namespace", "") or ""
        return namespace or None

    def _canonical_portfolio_weights_node(self) -> PortfolioWeights:
        node = getattr(self, "_portfolio_weights_node", None)
        if node is None:
            node = PortfolioWeights(namespace=self._canonical_namespace())
            self._portfolio_weights_node = node
        return node

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
        explicit_description = self.__dict__.get("_portfolio_description")
        if explicit_description is not None:
            return str(explicit_description)
        front_end_details = getattr(self.portfolio_markets_config, "front_end_details", None)
        if front_end_details is None:
            return None
        description = getattr(front_end_details, "description", None)
        return None if description is None else str(description)

    def _latest_portfolio_time_index_value(self):
        update_statistics = getattr(self, "update_statistics", None)
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
        portfolio_identifier = getattr(self, "_resolved_unique_identifier", None)
        if portfolio_identifier is not None:
            return str(portfolio_identifier)

        if (
            getattr(self, "portfolio_configuration", None) is not None
            or getattr(self, "_portfolio_configuration", None) is not None
        ):
            portfolio_identifier = self._unique_identifier()
            self._resolved_unique_identifier = portfolio_identifier
            return portfolio_identifier

        return None

    def _portfolio_dimension_range_map(
        self,
        *,
        start_date,
        start_date_operand: str = ">=",
        identifier_dimension: str = PORTFOLIO_IDENTIFIER,
    ) -> list[dict]:
        return [
            {
                "coordinate": {identifier_dimension: self._unique_identifier()},
                "start_date": start_date,
                "start_date_operand": start_date_operand,
            }
        ]

    def _calculate_start_end_dates(self):
        update_statics_from_dependencies = self.price_source.update_statistics
        progress_values = self._required_price_source_progress_values(
            update_statics_from_dependencies
        )
        earliest_last_value = min(progress_values) if progress_values else None

        if earliest_last_value is None:
            self.logger.warning(
                f"update_statics_from_dependencies {update_statics_from_dependencies}"
            )
            raise Exception("Prices are empty")

        if self.price_alignment_policy.forward_fill_to_now:
            end_date = datetime.now(pytz.utc)
        else:
            end_date = earliest_last_value + self._price_source_maximum_forward_fill()

        start_date = self._latest_portfolio_time_index_value() or self.OFFSET_START
        max_td_env = os.getenv("MAX_TD_FROM_LATEST_VALUE", None)
        if max_td_env is not None:
            new_end_date = start_date + pd.Timedelta(max_td_env)
            end_date = new_end_date if new_end_date < end_date else end_date

        return start_date, end_date

    def _required_price_source_progress_values(self, update_statistics) -> list:
        asset_identifiers = self._preflight_required_price_asset_identifiers()
        if not asset_identifiers:
            raise ValueError(
                "PortfoliosDataNode cannot derive the price-source update window "
                "without a required asset scope. The signal must expose a non-empty "
                "preflight get_asset_list(), or this portfolio must have previous "
                "weights that identify assets still needing valuation or liquidation."
            )

        progress_values = [
            update_statistics.get_earliest_update_for_identity(asset_identifier)
            for asset_identifier in asset_identifiers
        ]
        return [value for value in progress_values if value is not None]

    def _preflight_required_price_asset_identifiers(self) -> list[str]:
        required_assets = []
        preflight_asset_list = getattr(self, "required_price_asset_preflight", None)
        if preflight_asset_list is None:
            get_asset_list = getattr(self.signal_weights, "get_asset_list", None)
            if callable(get_asset_list):
                preflight_asset_list = get_asset_list()

        if preflight_asset_list:
            required_assets.extend(asset_unique_identifier(asset) for asset in preflight_asset_list)

        last_rebalance_weights = self._get_last_weights()
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

    def _generate_new_index(self, start_date, end_date, rebalancer_calendar):
        upsample_freq = self._portfolio_update_frequency()

        if "d" in upsample_freq:
            assert upsample_freq == "1d", "Only '1d' frequency is implemented."
            upsample_freq = translate_to_pandas_freq(upsample_freq)
            freq = upsample_freq.replace("days", "d")
            schedule = rebalancer_calendar.schedule(start_date=start_date, end_date=end_date)
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

    def _required_price_asset_identifiers(
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
        prices: pd.DataFrame,
    ) -> pd.DataFrame:
        weights = weights.reset_index().pivot(
            index="time_index",
            columns=[ASSET_IDENTIFIER],
            values=["price_current", "weights_before", "weights_current"],
        )

        price_current = weights.price_current
        weights_before = weights.weights_before.fillna(0)
        weights_current = weights.weights_current.fillna(0)
        prices = prices[self.price_column.value].unstack()
        first_price_date = (
            prices.stack().dropna().index.union(price_current.stack().dropna().index)[0][0]
        )

        prices = price_current.combine_first(prices).sort_index().ffill()
        prices = prices.reindex(weights.index)
        returns = (prices / prices.shift(1) - 1).fillna(0.0)
        returns.replace([np.inf, -np.inf], 0, inplace=True)
        weights_before = weights_before.reindex(returns.index, method="ffill").dropna()
        weights_current = weights_current.reindex(returns.index, method="ffill").dropna()
        weighted_returns = (weights_before * returns).dropna()
        weights_diff = (weights_current - weights_before).fillna(0)
        fees = (weights_diff.abs() * self.commission_fee).sum(axis=1)
        portfolio_returns = pd.DataFrame({"return": weighted_returns.sum(axis=1) - fees})
        return portfolio_returns[portfolio_returns.index >= first_price_date]

    def _apply_cumulative_portfolio_values(self, portfolio: pd.DataFrame) -> pd.DataFrame:
        last_portfolio = 1
        latest_value = self._latest_portfolio_time_index_value()
        if latest_value is not None:
            last_obs = self.get_df_between_dates(
                dimension_range_map=self._portfolio_dimension_range_map(
                    start_date=latest_value,
                    start_date_operand=">=",
                )
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

        portfolio_weights_node = self._canonical_portfolio_weights_node()
        last_obs = portfolio_weights_node.get_df_between_dates(
            dimension_range_map=self._portfolio_dimension_range_map(
                start_date=latest_value,
                start_date_operand=">=",
                identifier_dimension=PORTFOLIO_IDENTIFIER,
            )
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

    def _interpolate_bars_index(
        self,
        new_index: pd.DatetimeIndex,
        unique_identifiers: list,
        index_freq: str,
        price_source: DataNode | APIDataNode,
    ):
        fetch_end_date = new_index.max()
        raw_prices = price_source.get_df_between_dates(
            start_date=new_index.min() - pd.Timedelta(index_freq),
            end_date=fetch_end_date,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={ASSET_IDENTIFIER: unique_identifiers},
        )

        if len(raw_prices) == 0:
            self.logger.info(
                "No prices data in local portfolio price alignment for "
                f"price_source={self._price_source_identifier(price_source)}"
            )
            return pd.DataFrame(), pd.DataFrame()

        raw_prices = self._filter_price_frame_to_requested_assets(
            raw_prices,
            requested_asset_identifiers=unique_identifiers,
        )
        if len(raw_prices) == 0:
            self.logger.info(
                "Price source returned no rows for the signal-required assets.",
                price_source=self._price_source_identifier(price_source),
                requested_asset_identifiers=[str(value) for value in unique_identifiers],
            )
            return pd.DataFrame(), pd.DataFrame()

        self._diagnose_price_source_coverage(
            raw_prices,
            requested_asset_identifiers=unique_identifiers,
            price_source=price_source,
            start_date=new_index.min(),
            end_date=fetch_end_date,
        )

        if self.price_column.value not in raw_prices.columns:
            raise ValueError(
                "Portfolio price source is missing required price column "
                f"{self.price_column.value!r}. Available columns: "
                f"{list(raw_prices.columns)}."
            )

        raw_prices.sort_values("time_index", inplace=True)
        final_index_for_interpolation = new_index
        if self.price_alignment_policy.forward_fill_to_now:
            fill_end_date = datetime.now(pytz.utc)
            last_ts_in_df = raw_prices.index.get_level_values("time_index").max()
            self.logger.info(f"Forward-filling prices from {last_ts_in_df} to {fill_end_date}")
            pandas_freq = translate_to_pandas_freq(self.portfolio_prices_frequency)
            final_index_for_interpolation = pd.date_range(
                start=new_index.min(),
                end=fill_end_date,
                freq=pandas_freq,
            )

        interpolated_prices = raw_prices.unstack([ASSET_IDENTIFIER])
        raw_time_index = pd.DatetimeIndex(raw_prices.index.get_level_values("time_index").unique())
        missing_rebalance_times = pd.DatetimeIndex(final_index_for_interpolation).difference(
            raw_time_index
        )
        if len(missing_rebalance_times) > 0:
            self.logger.warning(
                "Portfolio local price alignment forward-filled consumed prices.",
                price_source=self._price_source_identifier(price_source),
                missing_timestamp_count=len(missing_rebalance_times),
                start_date=new_index.min(),
                end_date=fetch_end_date,
                price_column=self.price_column.value,
            )
        interpolated_prices = interpolated_prices.reindex(
            final_index_for_interpolation,
            method="ffill",
        )
        interpolated_prices.index.names = ["time_index"]
        interpolated_prices = interpolated_prices.stack([ASSET_IDENTIFIER])
        return raw_prices, interpolated_prices

    def _filter_price_frame_to_requested_assets(
        self,
        raw_prices: pd.DataFrame,
        *,
        requested_asset_identifiers: list,
    ) -> pd.DataFrame:
        if raw_prices.empty or not isinstance(raw_prices.index, pd.MultiIndex):
            return raw_prices
        if ASSET_IDENTIFIER not in raw_prices.index.names:
            return raw_prices
        requested_identifiers = {str(value) for value in requested_asset_identifiers}
        asset_level = raw_prices.index.get_level_values(ASSET_IDENTIFIER).map(str)
        return raw_prices[asset_level.isin(requested_identifiers)]

    def _diagnose_price_source_coverage(
        self,
        raw_prices: pd.DataFrame,
        *,
        requested_asset_identifiers: list,
        price_source: DataNode | APIDataNode,
        start_date,
        end_date,
    ) -> None:
        if raw_prices.empty or not isinstance(raw_prices.index, pd.MultiIndex):
            return

        available_identifiers = {
            str(value) for value in raw_prices.index.get_level_values(ASSET_IDENTIFIER).unique()
        }
        requested_identifiers = {str(value) for value in requested_asset_identifiers}
        missing_identifiers = sorted(requested_identifiers - available_identifiers)
        if not missing_identifiers:
            return

        self.logger.warning(
            "Portfolio price source is missing required signal assets.",
            price_source=self._price_source_identifier(price_source),
            missing_asset_identifiers=missing_identifiers,
            start_date=start_date,
            end_date=end_date,
            price_column=self.price_column.value,
            fail_on_missing_prices=self.price_alignment_policy.fail_on_missing_prices,
        )
        if self.price_alignment_policy.fail_on_missing_prices:
            raise ValueError(
                "Portfolio price source is missing required signal assets: "
                f"{', '.join(missing_identifiers)}."
            )

    def _price_source_identifier(self, price_source: DataNode | APIDataNode) -> str:
        if price_source.is_api:
            if not isinstance(price_source, APIDataNode):
                raise TypeError("API portfolio price sources must be APIDataNode instances.")
        else:
            if not isinstance(price_source, DataNode):
                raise TypeError(
                    "Portfolio price sources must be DataNode or APIDataNode instances."
                )
        return str(price_source.update_hash)

    def _price_source_maximum_forward_fill(self) -> pd.Timedelta:
        maximum_forward_fill = getattr(self.price_source, "maximum_forward_fill", None)
        if maximum_forward_fill is not None:
            return pd.Timedelta(maximum_forward_fill)
        return pd.Timedelta(translate_to_pandas_freq(self._portfolio_update_frequency()))

    def _portfolio_update_frequency(self) -> str:
        if self.portfolio_prices_frequency not in (None, ""):
            return str(self.portfolio_prices_frequency)
        for attribute_name in ("upsample_frequency_id", "bar_frequency_id"):
            frequency = getattr(self.price_source, attribute_name, None)
            if frequency not in (None, ""):
                return str(frequency)
        storage_table = getattr(self.price_source, "storage_table", None)
        cadence = getattr(storage_table, "__cadence__", None)
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
        portfolio_configuration = getattr(self, "_portfolio_configuration", None)
        portfolio_description = self.__dict__.get("_portfolio_description")
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
            updater=getattr(self, "_portfolio_metadata_updater", None),
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
