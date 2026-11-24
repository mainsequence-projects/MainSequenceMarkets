import datetime
from datetime import timedelta
from typing import Union

import pandas as pd
from pydantic import Field, field_validator

from msm_portfolios.time_index import (
    ASSET_IDENTIFIER,
    SIGNAL_UID,
    SignalWeights,
)
from msm_portfolios.configuration import PortfolioConfigBaseModel
from metatables import TimeIndexTableRef, TimeIndexTableUpdater


class AUIDWeight(PortfolioConfigBaseModel):
    unique_identifier: str
    weight: float


class FixedWeightsConfig(PortfolioConfigBaseModel):
    """Weights that never change, and the time they are stated.

    The signal has one observation, at ``signal_time_index``. A rebalance sizes it with
    the last prices strictly before its earliest moment (ADR 0058), so the time must
    come after the portfolio's first observed price.
    """

    asset_unique_identifier_weights: list[AUIDWeight]
    signal_time_index: datetime.datetime = Field(
        description="The time of the signal's one observation; timezone-aware.",
    )

    @field_validator("signal_time_index")
    @classmethod
    def require_aware_signal_time(cls, value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("signal_time_index must be timezone-aware.")
        return value.astimezone(datetime.UTC)


class FixedWeights(SignalWeights):
    @property
    def fixed_weights_config(self) -> FixedWeightsConfig:
        if not isinstance(self.signal_configuration, FixedWeightsConfig):
            raise TypeError("FixedWeights requires FixedWeightsConfig as signal_configuration.")
        return self.signal_configuration

    @property
    def asset_unique_identifier_weights(self) -> list[AUIDWeight]:
        return self.fixed_weights_config.asset_unique_identifier_weights

    def maximum_forward_fill(self):
        return timedelta(days=200 * 365)  # Always forward-fill to avoid filling the DB

    def get_explanation(self):
        return f"{self.__class__.__name__}: Signal uses fixed configured asset weights."

    def get_asset_list(self) -> None | list:
        return [w.unique_identifier for w in self.asset_unique_identifier_weights]

    def dependencies(self) -> dict[str, Union["TimeIndexTableUpdater", "TimeIndexTableRef"]]:
        return {}

    def _calculate_signal_weights(self) -> pd.DataFrame:
        existing_signal_rows = self.get_df_between_dates(
            dimension_filters={SIGNAL_UID: [self.signal_uid]}
        )
        if not existing_signal_rows.empty:
            return pd.DataFrame(columns=["time_index", ASSET_IDENTIFIER, "signal_weight"])

        df = pd.DataFrame([m.model_dump() for m in self.asset_unique_identifier_weights]).rename(
            columns={"unique_identifier": ASSET_IDENTIFIER, "weight": "signal_weight"}
        )
        df = df.set_index([ASSET_IDENTIFIER])
        signals_weights = pd.concat(
            [df], axis=0, keys=[self.fixed_weights_config.signal_time_index]
        ).rename_axis(["time_index", ASSET_IDENTIFIER])

        signals_weights = signals_weights.dropna()
        return signals_weights
