"""Asset frames and a portfolio values node that reads them, for portfolio contract tests."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pandas as pd

from msm_portfolios.configuration import ValuationAlignmentPolicy
from msm_portfolios.time_index import PortfoliosUpdater
from msm_portfolios.time_index.constants import ASSET_IDENTIFIER

def asset_frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["time_index", ASSET_IDENTIFIER, "close"])
    frame["time_index"] = pd.to_datetime(frame["time_index"], utc=True)
    return frame.set_index(["time_index", ASSET_IDENTIFIER])


class FrameSource:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def get_df_between_dates(self, **kwargs):
        start = pd.Timestamp(kwargs["start_date"])
        end = pd.Timestamp(kwargs["end_date"])
        times = self.frame.index.get_level_values("time_index")
        return self.frame[(times >= start) & (times <= end)]

    def get_last_observation(self, **_kwargs):
        return self.frame.iloc[0:0]


def portfolio_values_node_for_frames(
    *,
    valuations: pd.DataFrame,
    weights: pd.DataFrame,
    timestamps: pd.DatetimeIndex,
) -> PortfoliosUpdater:
    node = object.__new__(PortfoliosUpdater)
    node.valuation_source = FrameSource(valuations)
    node.valuation_column = "close"
    node.valuation_asset_identifier = "USD"
    node.fx_source = None
    node.valuation_alignment_policy = ValuationAlignmentPolicy(
        maximum_staleness=timedelta(hours=12)
    )
    node.signal_weights = SimpleNamespace(get_asset_uid_to_override_portfolio_price=lambda: None)
    node.commission_fee = 0.0
    node._latest_portfolio_time_index_value = lambda: None
    node._valuation_window = lambda _latest: (
        timestamps[0].to_pydatetime(),
        timestamps[-1].to_pydatetime(),
    )
    node._executed_weights_between = lambda **_kwargs: weights
    node._apply_cumulative_portfolio_values = lambda frame: frame.assign(
        close=(frame["return"] + 1.0).cumprod()
    )
    return node
