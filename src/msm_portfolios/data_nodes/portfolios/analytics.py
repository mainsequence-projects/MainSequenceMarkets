"""Consumer-owned analytical sampling of canonical portfolio values."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import pandas as pd
import pytz
from pydantic import ConfigDict, Field

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater

from ..base import PortfolioCanonicalDataNode, PortfolioCanonicalDataNodeConfiguration
from ..constants import PORTFOLIO_IDENTIFIER
from .storage import PortfolioAnalyticsStorage


class PortfolioAnalyticsConfiguration(PortfolioCanonicalDataNodeConfiguration):
    """Hash-bearing analytical period and aggregation contract."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    portfolio_values_instance: TimeIndexTableUpdater | TimeIndexTableRef
    portfolio_identifier: str = Field(min_length=1)
    frequency: str = Field(
        min_length=1,
        description="Pandas-compatible analytical period frequency such as 1D, 1W, or 1ME.",
    )
    label: Literal["left", "right"] = "right"
    closed: Literal["left", "right"] = "right"
    timezone: str = "UTC"
    aggregation: Literal["last"] = "last"


class PortfolioAnalytics(PortfolioCanonicalDataNode):
    """Write resampled observations to storage separate from canonical values."""

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)

    def __init__(
        self,
        config: PortfolioAnalyticsConfiguration,
        *args,
        namespace: str | None = None,
        **kwargs,
    ):
        resolved = self._validate_config(config)
        self.portfolio_values = resolved.portfolio_values_instance
        self.portfolio_identifier = resolved.portfolio_identifier
        self.frequency = resolved.frequency
        self.label = resolved.label
        self.closed = resolved.closed
        self.timezone = resolved.timezone
        self.aggregation = resolved.aggregation
        super().__init__(resolved, *args, namespace=namespace, **kwargs)

    def dependencies(self) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        return {"portfolio_values": self.portfolio_values}

    @property
    def analysis_identifier(self) -> str:
        return str(self.update_hash)

    def update(self) -> pd.DataFrame:
        values = self.portfolio_values.get_df_between_dates(
            start_date=self.OFFSET_START,
            end_date=datetime.now(pytz.utc),
            dimension_filters={PORTFOLIO_IDENTIFIER: [self.portfolio_identifier]},
        )
        if values is None or values.empty:
            return self._empty_output()

        flat = values.reset_index()
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        series = flat.sort_values("time_index").set_index("time_index")["close"]
        local = series.tz_convert(self.timezone)
        offset = pd.tseries.frequencies.to_offset(self.frequency)
        rows: list[dict] = []
        for bucket_label, bucket in local.groupby(
            pd.Grouper(freq=self.frequency, label=self.label, closed=self.closed)
        ):
            if bucket.empty:
                continue
            source_time = bucket.index[-1].tz_convert("UTC")
            if self.label == "right":
                period_end = bucket_label
                period_start = bucket_label - offset
            else:
                period_start = bucket_label
                period_end = bucket_label + offset
            rows.append(
                {
                    "time_index": source_time,
                    PORTFOLIO_IDENTIFIER: self.portfolio_identifier,
                    "analysis_identifier": self.analysis_identifier,
                    "close": float(bucket.iloc[-1]),
                    "source_time_index": source_time,
                    "period_start": period_start.tz_convert("UTC"),
                    "period_end": period_end.tz_convert("UTC"),
                }
            )
        result = pd.DataFrame(rows)
        if result.empty:
            return self._empty_output()
        result["return"] = result["close"].pct_change(fill_method=None).fillna(0.0)
        latest = self._latest_analytics_time_index()
        if latest is not None:
            result = result[result["time_index"] > pd.Timestamp(latest)]
        return self.validate_frame(result, output_table=self.output_table)

    def _empty_output(self) -> pd.DataFrame:
        return self.validate_frame(
            pd.DataFrame(columns=list(self._bound_column_dtypes_map())),
            output_table=self.output_table,
        )

    def _latest_analytics_time_index(self):
        statistics = getattr(self, "update_statistics", None)
        return None if statistics is None else statistics.max_time_index_value

    @classmethod
    def _validate_config(
        cls,
        config: PortfolioCanonicalDataNodeConfiguration,
    ) -> PortfolioAnalyticsConfiguration:
        if not isinstance(config, PortfolioAnalyticsConfiguration):
            raise TypeError("PortfolioAnalytics requires PortfolioAnalyticsConfiguration.")
        return super()._validate_config(config)

    @classmethod
    def _required_output_table(cls) -> type[PortfolioAnalyticsStorage]:
        return PortfolioAnalyticsStorage


__all__ = ["PortfolioAnalytics", "PortfolioAnalyticsConfiguration"]
