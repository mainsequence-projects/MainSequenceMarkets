from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import pandas as pd
from pydantic import BaseModel

import metatables.updaters.configuration as update_configuration
from msm.identity import stable_identity_payload

from ..base import (
    SignalWeightsConfiguration,
    _class_import_path,
    _drop_excluded_keys,
    _isoformat_dates_and_times,
    _empty_flat_frame,
    _is_canonical_frame,
    _normalize_pivoted_signal_weights,
    _require_columns,
    _reset_frame_index,
)
from ..constants import (
    ASSET_IDENTIFIER,
    SIGNAL_UID,
    SIGNAL_UID_EXCLUDED_CONFIGURATION_KEYS,
)
from ..metadata import emit_signal_metadata, extract_signal_description
from msm_portfolios.series_nodes import PublishedSeriesNode
from .storage import SignalWeightsStorage


class SignalWeights(PublishedSeriesNode):
    """A signal's weights, published as ``SignalWeightsSeries`` (ADR 0060, decision 5).

    A subclass computes weights in ``_calculate_signal_weights()``; ``run()`` publishes
    them under the signal's ``signal_uid``, after creating its ``SignalMetadata`` row.
    Its progress is the published series: ``_latest_signal_time_index_value()`` is the
    signal's last stored time and ``_signal_asset_start_date(asset)`` an asset's.

    ``dependencies()`` names the updaters and tables the calculation reads. The
    portfolio's ``PortfolioRebalance`` declares them as its own and computes the signal
    before it reads it, so one joined run refreshes them once for every portfolio that
    needs them (issue #133).
    """

    series_resource = "signal-weights"
    key_column = SIGNAL_UID
    computes_weights: ClassVar[bool] = True
    """Whether ``run()`` computes the weights; ``False`` when they arrive by publication."""

    def __init__(
        self,
        config: SignalWeightsConfiguration | None = None,
        *,
        namespace: str | None = None,
    ):
        super().__init__(config, namespace=namespace)
        self.signal_configuration = self.config.signal_configuration
        self._progress_by_asset: dict[str, pd.Timestamp] | None = None

    def set_signal_weights_frame(
        self,
        signal_weights_frame: pd.DataFrame,
        *,
        signal: Any | None = None,
        signal_configuration: Any | None = None,
        signal_description: str | None = None,
        metadata_updater: Any | None = None,
    ) -> SignalWeights:
        """Attach runtime signal inputs without changing the signal's identity."""
        self._signal_weights_frame = signal_weights_frame
        if signal is not None and signal_configuration is not None:
            raise ValueError("Pass either signal or signal_configuration, not both.")
        resolved_signal_configuration = (
            signal_configuration if signal_configuration is not None else signal
        )
        if resolved_signal_configuration is not None:
            self.signal_configuration = resolved_signal_configuration
        self._signal_description = signal_description
        self._signal_metadata_updater = metadata_updater
        return self

    def series_key(self) -> str:
        return self.signal_uid

    def dependencies(self) -> dict[str, Any]:
        """The updaters and tables the calculation reads; none by default."""

        return {}

    def run(self) -> Any:
        """Create the signal's metadata, then compute and publish its new weights."""

        self._progress_by_asset = None
        self._upsert_signal_metadata_if_available()
        try:
            return super().run()
        finally:
            self._progress_by_asset = None

    def update(self) -> pd.DataFrame:
        raw_frame = self._calculate_signal_weights()
        if _is_canonical_frame(raw_frame, output_table=SignalWeightsStorage):
            return self.validate_frame(raw_frame)
        return normalize_signal_weights_frame(raw_frame, signal_uid=self.signal_uid)

    def _calculate_signal_weights(self) -> pd.DataFrame:
        signal_weights_frame = getattr(self, "_signal_weights_frame", None)
        if signal_weights_frame is not None:
            return signal_weights_frame

        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _calculate_signal_weights()."
        )

    def _signal_uid_payload(self) -> dict[str, Any]:
        if self.signal_configuration is None:
            raise ValueError(
                f"{self.__class__.__name__} requires signal_configuration to compute signal_uid."
            )
        return {
            "table_updater_class_import_path": _class_import_path(self.__class__),
            "config": self.signal_configuration,
        }

    def _resolve_signal_uid(self) -> str:
        return compute_signal_uid(self._signal_uid_payload())

    @property
    def signal_uid(self) -> str:
        return self._resolve_signal_uid()

    def _upsert_signal_metadata_if_available(self) -> None:
        if self.signal_configuration is None:
            return

        emit_signal_metadata(
            signal_uid=self.signal_uid,
            signal_description=(
                getattr(self, "_signal_description", None) or extract_signal_description(self)
            ),
            updater=getattr(self, "_signal_metadata_updater", None),
        )

    def get_explanation(self):
        return f"{self.__class__.__name__}: canonical Portfolios signal weights."

    def maximum_forward_fill(self):
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement maximum_forward_fill()."
        )

    def get_asset_list(self) -> None | list:
        return None

    def get_update_asset_list(self) -> None | list:
        return self.get_asset_list()

    def _latest_signal_time_index_value(self) -> pd.Timestamp | None:
        """The signal's last published time, or ``None`` before its first observation."""

        last_time = self.reader.bounds(self.signal_uid).last_time
        return None if last_time is None else pd.Timestamp(last_time)

    def _signal_asset_latest_time_index_value(self, asset) -> pd.Timestamp | None:
        """The time of the signal's last published row of ``asset``."""

        if getattr(self, "_progress_by_asset", None) is None:
            latest = self.reader.last([self.signal_uid], by="asset")
            self._progress_by_asset = (
                {}
                if latest.empty
                else {
                    str(asset_identifier): pd.Timestamp(time)
                    for time, _signal, asset_identifier in latest.index
                }
            )
        return self._progress_by_asset.get(str(self._asset_unique_identifier(asset)))

    def _signal_asset_start_date(self, asset):
        latest_value = self._signal_asset_latest_time_index_value(asset)
        if latest_value is not None:
            return latest_value
        return self.OFFSET_START

    def rows_after_last_observation(self, frame: pd.DataFrame) -> pd.DataFrame:
        """``frame`` without the rows at or before the signal's last published time."""

        latest = self._latest_signal_time_index_value()
        if latest is None or frame is None or frame.empty:
            return frame
        times = pd.to_datetime(frame.index.get_level_values("time_index"), utc=True)
        return frame[times > latest]

    def interpolate_index(
        self,
        new_index: pd.DatetimeIndex,
        *,
        signal_weights_node=None,
    ):
        """
        Get interpolated signal weights for a time index.

        The weights are read from the published series, or from ``signal_weights_node``
        when given. Signal weights are valid only for a bounded duration, enforced by
        maximum_forward_fill().
        """
        weights_source = self if signal_weights_node is None else signal_weights_node
        if len(new_index) == 0:
            return pd.DataFrame()
        new_index = pd.DatetimeIndex(pd.to_datetime(new_index, utc=True), name="time_index")
        weights = self._get_signal_weights_between_dates(
            weights_source=weights_source,
            start_date=new_index.min(),
            end_date=new_index.max(),
        )
        seeds = self._signal_weight_seeds(
            weights_source=weights_source,
            before=new_index.min(),
            window_weights=weights,
        )
        weights = pd.concat([seeds, weights]).sort_index() if not seeds.empty else weights

        if len(weights) == 0:
            self.logger.warning("No weights data in index interpolation")
            return pd.DataFrame()

        weights = self._normalize_signal_weights_time_index(weights)
        weights_pivot = (
            weights.reset_index()
            .pivot(index="time_index", columns=[ASSET_IDENTIFIER], values="signal_weight")
            .fillna(0)
        )
        weights_pivot["last_weights"] = weights_pivot.index.get_level_values(level="time_index")

        combined_index = weights_pivot.index.union(new_index)
        combined_index.name = "time_index"
        weights_reindex = weights_pivot.reindex(combined_index)

        weights_reindex["last_weights"] = weights_reindex["last_weights"].ffill()
        weights_reindex["diff_to_last_weights"] = (
            weights_reindex.index.get_level_values(level="time_index")
            - weights_reindex["last_weights"]
        )

        invalid_forward_fills = (
            weights_reindex["diff_to_last_weights"] >= self.maximum_forward_fill()
        )
        weights_reindex.drop(columns=["last_weights", "diff_to_last_weights"], inplace=True)

        weights_reindex = weights_reindex.ffill()
        weights_reindex[invalid_forward_fills] = np.nan

        if weights_reindex.isna().values.any():
            self.logger.info("Could not fully interpolate for signal weights")

        weights_reindex = weights_reindex.loc[new_index]
        weights_reindex.index.name = "time_index"
        return weights_reindex

    def _signal_weight_seeds(
        self,
        *,
        weights_source,
        before: pd.Timestamp,
        window_weights: pd.DataFrame,
    ) -> pd.DataFrame:
        assets = [
            str(self._asset_unique_identifier(asset)) for asset in (self.get_asset_list() or [])
        ]
        if not assets and window_weights is not None and not window_weights.empty:
            assets = [
                str(value)
                for value in window_weights.index.get_level_values(ASSET_IDENTIFIER).unique()
            ]
        if not assets:
            return pd.DataFrame()

        get_last_observation = getattr(weights_source, "get_last_observation", None)
        if not callable(get_last_observation):
            return pd.DataFrame()
        range_map = [
            {
                "coordinate": {
                    SIGNAL_UID: self.signal_uid,
                    ASSET_IDENTIFIER: asset_identifier,
                },
                "end_date": before.to_pydatetime(),
                "end_date_operand": "<",
            }
            for asset_identifier in assets
        ]
        seeds = get_last_observation(dimension_range_map=range_map)
        if seeds is None or seeds.empty:
            return pd.DataFrame()
        seeds = self._normalize_signal_weights_time_index(seeds)
        flat = seeds.reset_index().sort_values("time_index")
        return (
            flat.groupby(ASSET_IDENTIFIER, as_index=False, sort=False)
            .tail(1)
            .set_index(seeds.index.names)
            .sort_index()
        )

    def _get_signal_weights_between_dates(
        self,
        *,
        weights_source,
        start_date=None,
        end_date=None,
        dimension_range_map=None,
    ) -> pd.DataFrame:
        kwargs = {
            "start_date": start_date,
            "end_date": end_date,
            "dimension_range_map": dimension_range_map,
        }
        kwargs = {key: value for key, value in kwargs.items() if value is not None}
        return weights_source.get_df_between_dates(
            **kwargs,
            dimension_filters={SIGNAL_UID: [self.signal_uid]},
        )

    def _normalize_signal_weights_time_index(self, weights: pd.DataFrame) -> pd.DataFrame:
        if weights is None or weights.empty:
            return weights

        normalized = weights.copy()
        if isinstance(normalized.index, pd.MultiIndex) and "time_index" in normalized.index.names:
            arrays = []
            for level_number, level_name in enumerate(normalized.index.names):
                level_values = normalized.index.get_level_values(level_number)
                if level_name == "time_index":
                    level_values = pd.to_datetime(level_values, utc=True)
                arrays.append(level_values)
            normalized.index = pd.MultiIndex.from_arrays(
                arrays,
                names=normalized.index.names,
            )
            return normalized

        if normalized.index.name == "time_index":
            normalized.index = pd.to_datetime(normalized.index, utc=True)
            return normalized

        if "time_index" in normalized.columns:
            normalized["time_index"] = pd.to_datetime(
                normalized["time_index"],
                utc=True,
            )
        return normalized

    @classmethod
    def default_config(
        cls,
        *,
        signal_configuration: Any | None = None,
    ) -> SignalWeightsConfiguration:
        return SignalWeightsConfiguration(signal_configuration=signal_configuration)

    @classmethod
    def from_signal_configuration(
        cls,
        signal_configuration: Any,
        *,
        namespace: str | None = None,
    ) -> SignalWeights:
        return cls(
            config=cls.default_config(signal_configuration=signal_configuration),
            namespace=namespace,
        )

    @classmethod
    def _validate_config(cls, config: Any) -> SignalWeightsConfiguration:
        if not isinstance(config, SignalWeightsConfiguration):
            raise TypeError(f"{cls.__name__} requires a SignalWeightsConfiguration.")
        return config

    @classmethod
    def _required_output_table(cls) -> type[SignalWeightsStorage]:
        return SignalWeightsStorage

    @staticmethod
    def canonical_signal_configuration(signal: Any) -> dict[str, Any]:
        return canonical_signal_configuration(signal)

    @staticmethod
    def compute_signal_uid(signal: Any) -> str:
        return compute_signal_uid(signal)


def canonical_signal_configuration(signal: Any) -> dict[str, Any]:
    """Return the canonical hash payload for a Portfolios signal producer.

    The payload keeps signal class/config identity and removes storage/update
    identity so the same signal config keeps the same `signal_uid` across
    namespaces and backend table instances.
    """
    payload = _signal_configuration_payload(signal)
    serialized_payload = update_configuration.Serializer().serialize_init_kwargs(payload)
    return _drop_excluded_keys(
        _isoformat_dates_and_times(dict(serialized_payload)),
        excluded_keys=SIGNAL_UID_EXCLUDED_CONFIGURATION_KEYS,
    )


def compute_signal_uid(signal: Any) -> str:
    """Compute the deterministic Portfolios `signal_uid` for a signal producer."""
    payload = stable_identity_payload(canonical_signal_configuration(signal), sources=[signal])
    _update_hash, remote_identity_hash = update_configuration.hash_signature(payload)
    return remote_identity_hash


def normalize_signal_weights_frame(
    signal_weights_frame: pd.DataFrame,
    *,
    signal_uid: str,
) -> pd.DataFrame:
    """Normalize signal output into canonical SignalWeights rows."""
    required_columns = list(SignalWeights._column_dtypes_map_for_storage())
    flat = _reset_frame_index(signal_weights_frame)
    if flat.empty:
        flat = _empty_flat_frame(column_names=required_columns)

    if "signal_weight" not in flat.columns:
        flat = _normalize_pivoted_signal_weights(flat)
    flat[SIGNAL_UID] = str(signal_uid)

    _require_columns(
        flat,
        required_columns=required_columns,
        frame_name="SignalWeights",
    )
    return SignalWeights.validate_frame(flat[required_columns])


def _signal_configuration_payload(signal: Any) -> dict[str, Any]:
    if isinstance(signal, SignalWeights):
        return signal._signal_uid_payload()

    build_configuration = getattr(signal, "build_configuration", None)
    if callable(build_configuration):
        build_configuration = build_configuration()
    if isinstance(build_configuration, dict):
        return dict(build_configuration)

    if isinstance(signal, BaseModel):
        return {
            "config": signal,
            "table_updater_class_import_path": _class_import_path(signal.__class__),
        }

    signal_config = getattr(signal, "config", None)
    if signal_config is not None:
        return {
            "config": signal_config,
            "table_updater_class_import_path": _class_import_path(signal.__class__),
        }

    if isinstance(signal, dict):
        return dict(signal)

    raise TypeError(
        "signal must be a TimeIndexTableUpdater-like object with build_configuration/config, "
        "a Pydantic configuration model, or a dict payload."
    )


@update_configuration.serialize_argument.register(SignalWeights)
def _serialize_signal_weights_argument(value: SignalWeights, pickle_ts: bool = False) -> dict:
    return canonical_signal_configuration(value)
