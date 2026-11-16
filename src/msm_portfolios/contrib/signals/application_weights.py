"""Signal weights an application hands in, keyed by asset unique identifier.

A provider that receives weights (chosen by a person, a model or another system)
binds this signal to its own ``SignalWeightsTS`` instance and calls ``publish``
each time it has a new set. The configuration names the stream, never the weights,
so the signal uid stays the same while the weights change.
"""

from __future__ import annotations

import datetime
import math
import numbers
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import pandas as pd
from pydantic import Field

from metatables import TimeIndexTableUpdater
from msm_portfolios.configuration import PortfolioConfigBaseModel
from msm_portfolios.time_index import ASSET_IDENTIFIER, SIGNAL_UID, SignalWeights
from msm_portfolios.time_index.signals.weights import normalize_signal_weights_frame

Observation = tuple[pd.Timestamp, dict[str, float]]

_EMPTY_COLUMNS = ["time_index", ASSET_IDENTIFIER, "signal_weight"]


class ApplicationWeightsConfig(PortfolioConfigBaseModel):
    """Identity of one stream of application weights.

    Nothing about the weights is here, so new weights never change the signal uid.
    ``provider`` keeps two providers that chose the same ``key`` apart, since
    signal metadata is one Markets registry.
    """

    provider: str = Field(
        min_length=1,
        description="Namespace of the provider that publishes, e.g. its MetaTables namespace.",
    )
    key: str = Field(
        min_length=1,
        description="The provider's own stable key for this stream of weights.",
    )


class ApplicationWeights(SignalWeights):
    """Weights an application gives; observations are published, never calculated.

    ``publish`` writes one or more observations. Each observation is the whole set
    of weights at its time: an asset the previous observation held and this one
    leaves out is written at ``0``, so the portfolio leaves it. Weights are stored
    as given (no normalisation, negatives allowed) and stand until the next
    observation.
    """

    # Scoped update statistics fall back to the offset start for an asset the
    # signal has never published; keep it early so no observation is below it.
    OFFSET_START = datetime.datetime(1970, 1, 1, tzinfo=datetime.UTC)

    @property
    def application_weights_config(self) -> ApplicationWeightsConfig:
        if not isinstance(self.signal_configuration, ApplicationWeightsConfig):
            raise TypeError(
                "ApplicationWeights requires ApplicationWeightsConfig as signal_configuration."
            )
        return self.signal_configuration

    def dependencies(self) -> dict:
        return {}

    def maximum_forward_fill(self) -> timedelta:
        return timedelta(days=36500)

    def get_explanation(self) -> str:
        config = self.application_weights_config
        return (
            f"{self.__class__.__name__}: weights published by {config.provider!r} "
            f"under key {config.key!r}."
        )

    def get_asset_list(self) -> list[str] | None:
        """Every asset this signal has published, or ``None`` before its first publication."""
        latest = self._latest_published_weights()
        return sorted(latest) or None

    def publish(
        self,
        observations: Mapping[datetime.datetime, Mapping[str, float]],
        *,
        description: str | None = None,
    ) -> None:
        """Write ``observations`` (time -> {asset unique_identifier: weight}) in one update.

        Refuses the whole call, writing nothing, when a time is naive,
        a weight is not a finite number, an asset identifier is unknown, or an
        observation is at or before the signal's last stored time.
        """
        pending = _validated_observations(observations)
        _require_known_assets({asset for _, weights in pending for asset in weights})

        self._pending_observations = pending
        self._signal_description = description
        try:
            self.run(update_tree=False)
        finally:
            self._pending_observations = None
            self._signal_description = None

    def _calculate_signal_weights(self) -> pd.DataFrame:
        pending: list[Observation] | None = getattr(self, "_pending_observations", None)
        if not pending:
            return pd.DataFrame(columns=_EMPTY_COLUMNS)

        latest = self._latest_published_weights()
        last_time = max((time for time, _ in latest.values()), default=None)
        first_time = pending[0][0]
        if last_time is not None and first_time <= last_time:
            raise ValueError(
                f"Observation at {first_time.isoformat()} is at or before this signal's last "
                f"stored observation ({last_time.isoformat()}). Published observations are "
                "never restated: portfolios that rebalanced on them would keep the old weights."
            )

        held = {asset for asset, (_, weight) in latest.items() if weight != 0}
        rows: list[tuple[pd.Timestamp, str, float]] = []
        for time, weights in pending:
            observation_rows = [(time, asset, 0.0) for asset in sorted(held - weights.keys())]
            observation_rows += [(time, asset, weight) for asset, weight in weights.items()]
            if not observation_rows:
                raise ValueError(
                    f"Observation at {time.isoformat()} has no weights and the signal holds "
                    "nothing to close."
                )
            rows += observation_rows
            held = {asset for asset, weight in weights.items() if weight != 0}

        frame = normalize_signal_weights_frame(
            pd.DataFrame(rows, columns=_EMPTY_COLUMNS),
            signal_uid=self.signal_uid,
            output_table=self.output_table,
        )
        self._refuse_rows_the_update_would_drop(frame)
        return frame

    def _refuse_rows_the_update_would_drop(self, frame: pd.DataFrame) -> None:
        """The updater persists only rows newer than each series' last row; say so instead."""
        update_statistics = getattr(self, "update_statistics", None)
        if update_statistics is None or update_statistics.max_time_index_value is None:
            return
        kept = update_statistics.filter_df_by_latest_value(frame)
        if len(kept) == len(frame):
            return
        dropped = frame.index.difference(kept.index)
        raise ValueError(
            "These rows are at or before their series' last stored time and would not be "
            f"written: {[tuple(str(value) for value in row) for row in dropped[:5]]}."
        )

    def _latest_published_weights(self) -> dict[str, tuple[pd.Timestamp, float]]:
        """Each published asset's last stored row: asset -> (time, weight)."""
        # TimeIndexTableUpdater's reader, not AssetIndexedUpdater's: that one scopes
        # the read by get_asset_list(), which is answered from this read.
        frame = TimeIndexTableUpdater.get_last_observation(
            self,
            dimension_filters={SIGNAL_UID: [self.signal_uid]},
        )
        if frame is None or frame.empty:
            return {}
        flat = frame.reset_index() if ASSET_IDENTIFIER not in frame.columns else frame
        flat = flat[flat[SIGNAL_UID].astype(str) == str(self.signal_uid)]
        times = pd.to_datetime(flat["time_index"], utc=True)
        return {
            str(asset): (time, 0.0 if pd.isna(weight) else float(weight))
            for asset, time, weight in zip(
                flat[ASSET_IDENTIFIER], times, flat["signal_weight"], strict=True
            )
        }


def _validated_observations(
    observations: Mapping[datetime.datetime, Mapping[str, float]],
) -> list[Observation]:
    if not isinstance(observations, Mapping) or not observations:
        raise ValueError("publish needs at least one observation: {time: {asset: weight}}.")

    validated: dict[pd.Timestamp, dict[str, float]] = {}
    for time, weights in observations.items():
        if not isinstance(time, datetime.datetime):
            raise TypeError(f"Observation times must be datetimes; got {type(time).__name__}.")
        if time.tzinfo is None or time.utcoffset() is None:
            raise ValueError(f"Observation time {time.isoformat()} has no timezone.")
        utc_time = pd.Timestamp(time).tz_convert("UTC")
        if not isinstance(weights, Mapping):
            raise TypeError(
                f"Observation at {utc_time.isoformat()} must map asset identifiers to weights."
            )
        validated[utc_time] = {
            _validated_asset(asset, utc_time): _validated_weight(weight, asset, utc_time)
            for asset, weight in weights.items()
        }
    return sorted(validated.items())


def _validated_asset(asset: Any, time: pd.Timestamp) -> str:
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError(
            f"Observation at {time.isoformat()} has an empty or non-string asset identifier "
            f"{asset!r}."
        )
    return asset


def _validated_weight(weight: Any, asset: str, time: pd.Timestamp) -> float:
    if isinstance(weight, bool) or not isinstance(weight, numbers.Real):
        raise TypeError(f"Weight of {asset!r} at {time.isoformat()} is not a number: {weight!r}.")
    if not math.isfinite(weight):
        raise ValueError(f"Weight of {asset!r} at {time.isoformat()} is not finite: {weight!r}.")
    return float(weight)


def _require_known_assets(asset_identifiers: set[str]) -> None:
    if not asset_identifiers:
        return
    from msm.api.assets import Asset

    known = Asset.get_many_by_unique_identifier(sorted(asset_identifiers))
    unknown = sorted(asset_identifiers - set(known))
    if unknown:
        raise LookupError(f"Unknown asset unique identifiers: {unknown}.")


__all__ = ["ApplicationWeights", "ApplicationWeightsConfig"]
