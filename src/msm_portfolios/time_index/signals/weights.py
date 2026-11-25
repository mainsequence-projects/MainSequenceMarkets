"""A portfolio's signal: a computed node with its own table, or a published series.

Every signal is a ``SignalWeightsSource``: its identity (``signal_uid``, the hash of its
class and configuration), how long a weight holds (``maximum_forward_fill``), its assets,
and the reads a rebalance makes of its weights (``get_df_between_dates``,
``get_last_observation`` and ``first_observation_time``). There are two kinds:

- **Computed** (``SignalWeights`` and its subclasses). A MetaTables node: its update
  computes the weights from what its ``dependencies()`` name, writes the new rows to the
  producer's own ``SignalWeightsTS`` instance (its ``output_table``) and publishes them
  to Markets' ``SignalWeightsTS`` (ADR 0060, amended on 2026-11-24). A portfolio's
  rebalance depends on it with an edge, so it runs first, and reads its rows from that
  table.
- **Published** (``ApplicationWeights``). Its weights arrive only by publication. It has
  no node and no edge, and a rebalance reads it from Markets.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

import metatables.updaters.configuration as update_configuration
from metatables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.identity import stable_identity_payload
from msm.storage_instances import STORAGE_CONTRACT_COMPONENT

from ..base import (
    AssetScopedPortfolioCanonicalUpdater,
    OutputTable,
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
from msm.time_index.assets.asset_indexed import asset_scope_identifier
from msm_portfolios.series_nodes import PublishedSeriesReader, publish_new_rows
from .storage import SignalWeightsStorage

SIGNAL_WEIGHTS_SERIES = PublishedSeriesReader(
    "signal-weights", key_column=SIGNAL_UID, asset_column=ASSET_IDENTIFIER
)
"""Markets' ``SignalWeightsTS``, through ``SignalWeightsSeries``."""


class SignalWeightsSource:
    """What every signal is, computed or published.

    A subclass reads its weights with ``get_df_between_dates`` and
    ``get_last_observation``, as any time-index source does, and answers
    ``first_observation_time``. ``SignalWeights`` reads them from its own table and
    ``ApplicationWeights`` from Markets.
    """

    # Not annotated: a published signal is a pydantic model, which would make an annotated
    # class attribute of a base one of its fields.
    signal_configuration = None

    @classmethod
    def default_config(
        cls,
        *,
        signal_configuration: Any | None = None,
    ) -> SignalWeightsConfiguration:
        return SignalWeightsConfiguration(signal_configuration=signal_configuration)

    @classmethod
    def from_signal_configuration(cls, signal_configuration: Any, **kwargs: Any) -> Any:
        """The signal of ``signal_configuration``; ``kwargs`` go to the constructor."""

        return cls(config=cls.default_config(signal_configuration=signal_configuration), **kwargs)

    @classmethod
    def _validate_config(cls, config: Any) -> SignalWeightsConfiguration:
        if not isinstance(config, SignalWeightsConfiguration):
            raise TypeError(f"{cls.__name__} requires a SignalWeightsConfiguration.")
        return config

    # Identity ------------------------------------------------------------------------

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

    @staticmethod
    def canonical_signal_configuration(signal: Any) -> dict[str, Any]:
        return canonical_signal_configuration(signal)

    @staticmethod
    def compute_signal_uid(signal: Any) -> str:
        return compute_signal_uid(signal)

    # What the signal says about its weights ------------------------------------------

    def get_explanation(self):
        return f"{self.__class__.__name__}: canonical Portfolios signal weights."

    def maximum_forward_fill(self):
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement maximum_forward_fill()."
        )

    def get_asset_list(self) -> None | list:
        return None

    def first_observation_time(self) -> pd.Timestamp | None:
        """The time of the signal's first observation, or ``None`` before it has one.

        A rebalance's first run starts there (#138).
        """

        raise NotImplementedError(
            f"{self.__class__.__name__} must implement first_observation_time()."
        )

    @classmethod
    def _asset_unique_identifier(cls, asset: Any) -> str:
        return asset_scope_identifier(asset, identity_dimension=ASSET_IDENTIFIER)

    # Interpolation -------------------------------------------------------------------

    def interpolate_index(
        self,
        new_index: pd.DatetimeIndex,
        *,
        signal_weights_node=None,
    ):
        """
        Get interpolated signal weights for a time index.

        The weights are read from this signal, or from ``signal_weights_node`` when given.
        Signal weights are valid only for a bounded duration, enforced by
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
            _logger().warning("No weights data in index interpolation")
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
            _logger().info("Could not fully interpolate for signal weights")

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


class SignalWeights(SignalWeightsSource, AssetScopedPortfolioCanonicalUpdater):
    """A computed signal: a MetaTables node with its own table, which also publishes.

    ``output_table`` is the producer's own ``SignalWeightsTS`` instance, declared with a
    class statement on ``SignalWeightsInstance`` and migrated by the producer's provider,
    as its interpolated-price table is. It holds the rows of every
    signal the producer computes, keyed by ``signal_uid``. Markets' own
    ``SignalWeightsTS`` is refused: only publishing writes it.

    A subclass computes its weights in ``_calculate_signal_weights()``, from the updaters
    and tables ``dependencies()`` names; MetaTables runs those updaters first. ``update()``
    writes the signal's ``SignalMetadata`` row when it is missing or changed, keeps the
    rows after the signal's last row in its table, publishes them to Markets'
    ``SignalWeightsTS`` (``SignalWeightsSeries``, with ADR 0060's publish rules and
    manager check) and returns them for MetaTables to write. A failed publish writes
    nothing; a write that fails after the publish is computed again by the next run, and
    Markets leaves out the rows it already has.

    Its progress is its table's update statistics: ``_latest_signal_time_index_value()``
    is the signal's last row there, and ``_signal_asset_start_date(asset)`` an asset's.
    Its ``signal_uid`` is derived from its class and configuration only, never from its
    table or namespace.
    """

    def __init__(
        self,
        config: SignalWeightsConfiguration | None = None,
        *,
        output_table: OutputTable,
        namespace: str | None = None,
    ):
        _require_signal_weights_instance(output_table, signal_class=self.__class__)
        resolved_config = self._validate_config(config or self.default_config())
        self.signal_configuration = resolved_config.signal_configuration
        super().__init__(resolved_config, namespace=namespace, output_table=output_table)

    @classmethod
    def from_signal_configuration(
        cls,
        signal_configuration: Any,
        *,
        output_table: OutputTable,
        namespace: str | None = None,
    ) -> SignalWeights:
        return cls(
            config=cls.default_config(signal_configuration=signal_configuration),
            output_table=output_table,
            namespace=namespace,
        )

    @classmethod
    def _required_output_table(cls) -> type[SignalWeightsStorage]:
        """The storage contract; the node writes the producer's own instance of it."""

        return SignalWeightsStorage

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

    def dependencies(self) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        """The updaters and tables the calculation reads; none by default.

        MetaTables runs these updaters before the signal, once per run however many
        portfolios read the signal.
        """

        return {}

    def update(self) -> pd.DataFrame:
        """The signal's new rows: published to Markets, then written to its own table."""

        self._ensure_signal_metadata()
        frame = self.rows_after_last_observation(self._computed_rows())
        publish_new_rows(SIGNAL_WEIGHTS_SERIES, frame, publisher=self.__class__.__name__)
        return frame

    def _computed_rows(self) -> pd.DataFrame:
        raw_frame = self._calculate_signal_weights()
        if _is_canonical_frame(raw_frame, output_table=self.output_table):
            return self.validate_frame(raw_frame, output_table=self.output_table)
        return normalize_signal_weights_frame(
            raw_frame, signal_uid=self.signal_uid, output_table=self.output_table
        )

    def _calculate_signal_weights(self) -> pd.DataFrame:
        signal_weights_frame = getattr(self, "_signal_weights_frame", None)
        if signal_weights_frame is not None:
            return signal_weights_frame

        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _calculate_signal_weights()."
        )

    def _ensure_signal_metadata(self) -> None:
        if self.signal_configuration is None:
            return

        emit_signal_metadata(
            signal_uid=self.signal_uid,
            signal_description=(
                getattr(self, "_signal_description", None) or extract_signal_description(self)
            ),
            updater=getattr(self, "_signal_metadata_updater", None),
        )

    # Progress, from the table's update statistics --------------------------------------

    def first_observation_time(self) -> pd.Timestamp | None:
        """The time of the signal's first row in its table, or ``None`` before it has one.

        Read from the table's statistics when called (one request), so a rebalance that
        runs after this node in the same graph sees the rows it just wrote.
        """

        statistics = self.output_metadata.get_data_updates()
        first = _min_in_nested_values((statistics.index_min or {}).get(self.signal_uid))
        return None if first is None else pd.Timestamp(first)

    def _signal_progress(self) -> Any:
        statistics = getattr(self, "update_statistics", None)
        progress = getattr(statistics, "index_progress", None)
        return progress.get(self.signal_uid) if isinstance(progress, dict) else None

    def _latest_signal_time_index_value(self) -> pd.Timestamp | None:
        """The time of the signal's last row in its table, or ``None`` before its first."""

        latest = self._max_in_nested_values(self._signal_progress())
        return None if latest is None else pd.Timestamp(latest)

    def _signal_asset_latest_time_index_value(self, asset) -> pd.Timestamp | None:
        """The time of the signal's last row of ``asset`` in its table."""

        progress = self._signal_progress()
        if not isinstance(progress, dict):
            return None
        latest = self._max_in_nested_values(progress.get(str(self._asset_unique_identifier(asset))))
        return None if latest is None else pd.Timestamp(latest)

    def _signal_asset_start_date(self, asset):
        latest_value = self._signal_asset_latest_time_index_value(asset)
        if latest_value is not None:
            return latest_value
        return self.get_offset_start()

    def rows_after_last_observation(self, frame: pd.DataFrame) -> pd.DataFrame:
        """``frame`` without the rows at or before the signal's last row in its table.

        Markets never restates a published observation, so the table takes no row before
        the signal's last one either, and both hold the same observations.
        """

        latest = self._latest_signal_time_index_value()
        if latest is None or frame is None or frame.empty:
            return frame
        times = pd.to_datetime(frame.index.get_level_values("time_index"), utc=True)
        return frame[times > latest]


def _require_signal_weights_instance(output_table: Any, *, signal_class: type) -> None:
    """Refuse a table that is not a producer's own ``SignalWeightsTS`` instance."""

    contract = SignalWeightsStorage.__markets_authored_identifier__
    identity = getattr(output_table, "__metatable_extra_hash_components__", None) or {}
    if identity.get(STORAGE_CONTRACT_COMPONENT) != contract:
        raise ValueError(
            f"{signal_class.__name__} writes its producer's own {contract} instance; "
            f"output_table={getattr(output_table, '__name__', output_table)!s} is not one. "
            "Declare it with a class statement on SignalWeightsInstance and the producer's "
            "base, and migrate it with the producer's provider. Markets' own "
            f"{contract} is written only by publishing (ADR 0060)."
        )


def _min_in_nested_values(value: Any) -> Any:
    if isinstance(value, dict):
        found = [_min_in_nested_values(child) for child in value.values()]
        found = [item for item in found if item is not None]
        return min(found) if found else None
    return value


def _logger() -> Any:
    from msm_portfolios import logger

    return logger


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
    output_table: OutputTable | None = None,
) -> pd.DataFrame:
    """Normalize signal output into canonical rows of ``output_table`` (the contract by default)."""
    required_columns = list(SignalWeights._column_dtypes_map_for_storage(output_table))
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
    return SignalWeights.validate_frame(flat[required_columns], output_table=output_table)


def _signal_configuration_payload(signal: Any) -> dict[str, Any]:
    if isinstance(signal, SignalWeightsSource):
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


_signal_identity_payloads: ContextVar[bool] = ContextVar(
    "msm_signal_identity_payloads", default=False
)


@contextlib.contextmanager
def signal_identity_payloads() -> Iterator[None]:
    """Serialize a signal as its ``signal_uid`` payload in the enclosed calls.

    A portfolio's identity names its signal by class and configuration (its
    ``signal_uid``), never by a node's update hash or table, which differ between
    namespaces and Environments (``compute_portfolio_configuration_hash``).
    """

    token = _signal_identity_payloads.set(True)
    try:
        yield
    finally:
        _signal_identity_payloads.reset(token)


@update_configuration.serialize_argument.register(SignalWeightsSource)
def _serialize_signal_weights_argument(value: SignalWeightsSource) -> dict:
    """A signal in a configuration, saved in a form MetaTables rebuilds (ADR 0067, decision 4).

    In an updater's configuration a computed signal is the updater it is, saved by its
    update, and a published one is the pydantic model it is. A node Job run rebuilds the
    rebalance with them. In an identity payload it is its ``signal_uid`` payload
    (``signal_identity_payloads``).
    """

    if _signal_identity_payloads.get():
        return canonical_signal_configuration(value)
    for form in (TimeIndexTableUpdater, BaseModel):
        if isinstance(value, form):
            return update_configuration.serialize_argument.dispatch(form)(value)
    raise TypeError(
        f"{type(value).__name__} is neither a computed signal (a SignalWeights updater) nor a "
        "published one (a pydantic model, as ApplicationWeights), so a node Job run could "
        "not rebuild it."
    )
