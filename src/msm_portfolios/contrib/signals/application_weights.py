"""Signal weights an application hands in, keyed by asset unique identifier.

An application that receives weights (chosen by a person, a model or another system)
calls ``publish`` each time it has a new set; the weights are published to Markets'
``SignalWeightsSeries`` (ADR 0060). The configuration names the stream, never the
weights, so the signal uid stays the same while the weights change.

It is the published kind of signal: nothing computes it, so it is no MetaTables node and
a portfolio's rebalance has no edge to it. The rebalance reads its weights from Markets.
"""

from __future__ import annotations

import datetime
from typing import Any, ClassVar
from collections.abc import Mapping
from datetime import timedelta

import pandas as pd
from pydantic import Field, field_validator

from msm_portfolios.configuration import PortfolioConfigBaseModel
from msm_portfolios.series_nodes import PublishedSeriesReads
from msm_portfolios.time_index import SIGNAL_UID, SignalWeightsConfiguration
from msm_portfolios.time_index.metadata import extract_signal_description
from msm_portfolios.time_index.signals.weights import SignalWeightsSource


class ApplicationWeightsConfig(PortfolioConfigBaseModel):
    """Identity of one stream of application weights.

    Nothing about the weights is here, so new weights never change the signal uid.
    ``provider`` keeps two providers that chose the same ``key`` apart, since
    signal metadata is one Markets registry.
    """

    provider: str = Field(
        min_length=1,
        description="Name of the application that publishes, e.g. its MetaTables namespace.",
    )
    key: str = Field(
        min_length=1,
        description="The provider's own stable key for this stream of weights.",
    )


class ApplicationWeights(SignalWeightsSource, PublishedSeriesReads, PortfolioConfigBaseModel):
    """Weights an application gives; observations are published, never calculated.

    ``publish`` writes one or more observations. Each observation is the whole set
    of weights at its time: an asset the previous observation held and this one
    leaves out is written at ``0``, so the portfolio leaves it. Weights are stored
    as given (no normalisation, negatives allowed) and stand until the next
    observation. Markets enforces these rules (``SignalWeightsSeries.publish``).

    It is read from Markets: ``get_df_between_dates``, ``get_last_observation`` and
    ``first_observation_time`` read its published series.

    It is a pydantic model of its configuration, so a portfolio's rebalance saved by
    MetaTables rebuilds it in a node Job run (ADR 0067, decision 4).
    """

    series_resource: ClassVar[str] = "signal-weights"
    key_column: ClassVar[str] = SIGNAL_UID

    config: SignalWeightsConfiguration = Field(default_factory=SignalWeightsConfiguration)

    @field_validator("config", mode="after")
    @classmethod
    def _signal_weights_configuration(cls, config: Any) -> SignalWeightsConfiguration:
        return cls._validate_config(config)

    @property
    def signal_configuration(self) -> Any:
        return self.config.signal_configuration

    def series_key(self) -> str:
        return self.signal_uid

    @property
    def application_weights_config(self) -> ApplicationWeightsConfig:
        if not isinstance(self.signal_configuration, ApplicationWeightsConfig):
            raise TypeError(
                "ApplicationWeights requires ApplicationWeightsConfig as signal_configuration."
            )
        return self.signal_configuration

    def maximum_forward_fill(self) -> timedelta:
        return timedelta(days=36500)

    def get_explanation(self) -> str:
        config = self.application_weights_config
        return (
            f"{self.__class__.__name__}: weights published by {config.provider!r} "
            f"under key {config.key!r}."
        )

    def first_observation_time(self) -> pd.Timestamp | None:
        """The time of the signal's first published observation, or ``None`` before it."""

        first_time = self.reader.bounds(self.signal_uid).first_time
        return None if first_time is None else pd.Timestamp(first_time)

    def get_asset_list(self) -> list[str] | None:
        """Every asset this signal has published, or ``None`` before its first publication."""
        from msm_portfolios.api import SignalWeightsSeries

        return SignalWeightsSeries.assets(self.signal_uid) or None

    def publish(
        self,
        observations: Mapping[datetime.datetime, Mapping[str, float]],
        *,
        description: str | None = None,
    ):
        """Publish ``observations`` (time -> {asset unique_identifier: weight}).

        Answers the ``SignalPublication`` of ``msm_portfolios.recipes.publish_signal_weights``.
        ``description`` replaces the signal's description; the first publication without
        one describes the signal from its configuration.
        Refuses the whole call, writing nothing, when a time is naive, a weight is not a
        finite number, an asset identifier is unknown, or an observation is at or before
        the signal's last stored time.
        """
        from msm_portfolios.api import SignalMetadata
        from msm_portfolios.recipes import publish_signal_weights

        if description is None and not SignalMetadata.filter(signal_uid=self.signal_uid, limit=1):
            description = extract_signal_description(self)
        return publish_signal_weights(self.signal_uid, observations, description=description)

__all__ = ["ApplicationWeights", "ApplicationWeightsConfig"]
