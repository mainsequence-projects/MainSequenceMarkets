from __future__ import annotations

from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from msm_portfolios.asset_scope import asset_field, asset_unique_identifier
from msm_portfolios.contrib.signals.regression_utils import (
    rolling_elastic_net,
    rolling_lasso_regression,
)
from msm_portfolios.data_nodes import ASSET_IDENTIFIER, SignalWeights
from msm_portfolios.configuration import PortfolioConfigBaseModel
from msm_portfolios.enums import PriceTypeNames
from msm_portfolios.utils import TIMEDELTA

from mainsequence.meta_tables import APIDataNode, DataNode


class TrackingStrategy(Enum):
    ELASTIC_NET = "elastic_net"
    LASSO = "lasso"


class TrackingStrategyConfiguration(PortfolioConfigBaseModel):
    configuration: dict = {"alpha": 0, "l1_ratio": 0}


class ETFReplicatorConfig(PortfolioConfigBaseModel):
    asset_list: list[Any]
    price_source_instance: DataNode | APIDataNode
    etf_price_source_instance: DataNode | APIDataNode
    etf_ticker: str
    tracking_strategy_configuration: TrackingStrategyConfiguration
    etf_asset: Any | None = None
    in_window: int = 60
    tracking_strategy: TrackingStrategy = TrackingStrategy.LASSO
    price_column: PriceTypeNames = PriceTypeNames.CLOSE


class ETFReplicator(SignalWeights):
    @property
    def replicator_config(self) -> ETFReplicatorConfig:
        if not isinstance(self.signal_configuration, ETFReplicatorConfig):
            raise TypeError("ETFReplicator requires ETFReplicatorConfig as signal_configuration.")
        return self.signal_configuration

    @property
    def in_window(self) -> int:
        return self.replicator_config.in_window

    @property
    def etf_ticker(self) -> str:
        return self.replicator_config.etf_ticker

    @property
    def tracking_strategy(self) -> TrackingStrategy:
        return self.replicator_config.tracking_strategy

    @property
    def tracking_strategy_configuration(self) -> TrackingStrategyConfiguration:
        return self.replicator_config.tracking_strategy_configuration

    @property
    def price_column(self) -> PriceTypeNames:
        return self.replicator_config.price_column

    @property
    def price_source(self):
        return self.replicator_config.price_source_instance

    @property
    def etf_price_source(self):
        return self.replicator_config.etf_price_source_instance

    def _require_etf_asset(self) -> Any:
        etf_asset = getattr(self, "etf_asset", None) or self.replicator_config.etf_asset
        if etf_asset is None:
            raise ValueError(
                "ETFReplicator requires ETFReplicatorConfig.etf_asset. Resolve the ETF "
                "through MetaTable services and pass the asset object or mapping explicitly."
            )
        self.etf_asset = etf_asset
        return etf_asset

    def get_asset_list(self) -> None | list:
        self.price_assets = self.replicator_config.asset_list
        self.etf_asset = self._require_etf_asset()
        return self.price_assets + [self.etf_asset]

    def dependencies(self) -> dict[str, DataNode | APIDataNode]:
        return {
            "price_source": self.price_source,
            "etf_price_source": self.etf_price_source,
        }

    def get_explanation(self):
        etf_asset = self._require_etf_asset()
        info = f"""
        <p>{self.__class__.__name__}: Signal aims to replicate {asset_field(etf_asset, "ticker", self.etf_ticker)} using a data-driven approach.
        This strategy will use {self.tracking_strategy} as approximation function with parameters </p>
        <code>{self.tracking_strategy_configuration}</code>
        """
        return info

    def maximum_forward_fill(self):
        freq = self.price_source.bar_frequency_id
        return pd.Timedelta(freq) - TIMEDELTA

    def get_tracking_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        etf_unique_identifier = asset_unique_identifier(self.etf_asset)
        prices = prices[~prices[etf_unique_identifier].isnull()]
        prices = prices.pct_change().iloc[1:]
        prices = prices.replace([np.inf, -np.inf], np.nan)

        y = prices[etf_unique_identifier]
        X = prices.drop(columns=[etf_unique_identifier])

        if self.tracking_strategy == TrackingStrategy.ELASTIC_NET:
            betas = rolling_elastic_net(
                y, X, window=self.in_window, **self.tracking_strategy_configuration.configuration
            )
        elif self.tracking_strategy == TrackingStrategy.LASSO:
            betas = rolling_lasso_regression(
                y, X, window=self.in_window, **self.tracking_strategy_configuration.configuration
            )
        else:
            raise NotImplementedError

        try:
            betas = pd.concat(betas, axis=0)
        except Exception as e:
            raise e
        betas.index.name = "time_index"
        return betas

    def _calculate_signal_weights(self) -> pd.DataFrame:
        self.price_assets = getattr(self, "price_assets", None) or self.replicator_config.asset_list
        self.etf_asset = getattr(self, "etf_asset", None) or self._require_etf_asset()
        if self.update_statistics.max_time_index_value:
            prices_start_date = self.update_statistics.max_time_index_value - pd.Timedelta(
                days=self.in_window
            )
        else:
            prices_start_date = self.OFFSET_START - pd.Timedelta(days=self.in_window)

        prices = self.price_source.get_df_between_dates(
            start_date=prices_start_date,
            end_date=None,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={
                ASSET_IDENTIFIER: [asset_unique_identifier(a) for a in self.price_assets]
            },
        )
        etf_prices = self.etf_price_source.get_df_between_dates(
            start_date=prices_start_date,
            end_date=None,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={ASSET_IDENTIFIER: [asset_unique_identifier(self.etf_asset)]},
        )

        prices = pd.concat([prices, etf_prices])
        prices = prices.reset_index().pivot_table(
            index="time_index",
            columns=ASSET_IDENTIFIER,
            values=self.price_column.value,
        )

        if prices.shape[0] < self.in_window:
            self.logger.warning("Not enough prices to run regression")
            return pd.DataFrame()

        weights = self.get_tracking_weights(prices=prices)
        weights = weights.unstack().to_frame(name="signal_weight")
        weights = weights.swaplevel()
        return weights
