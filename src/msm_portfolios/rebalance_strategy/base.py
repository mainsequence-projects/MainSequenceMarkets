import datetime
import logging
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("portfolios")


class RebalanceStrategyBase(BaseModel):
    """Serialized economic timing contract for executed portfolio weights."""

    model_config = ConfigDict(extra="forbid")

    timing_mode: Literal["signal_time", "calendar_event", "bar_participation"] = Field(
        ...,
        description=(
            "Origin of execution timestamps. The mode participates in portfolio "
            "configuration hashing."
        ),
    )

    def get_explanation(self):
        return f"{self.__class__.__name__}: Rebalance strategy class."

    def execution_timestamps(
        self,
        start: datetime.datetime,
        end: datetime.datetime,
        *,
        signal_timestamps: pd.DatetimeIndex,
    ) -> pd.DatetimeIndex:
        """Return traceable execution events selected by this strategy."""
        raise NotImplementedError
