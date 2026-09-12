"""Public columnar contracts for position-aware portfolio accounting."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Mapping

import numpy as np
import pandas as pd


AlignmentMode = Literal["exact", "asof", "interval", "event_to_position"]
EventPhase = Literal["pre_execution", "execution", "post_execution"]
RecordKind = Literal[
    "event_marker",
    "position_delta",
    "cash_delta",
    "obligation_delta",
    "lifecycle_state",
    "execution_progress",
    "cost",
    "valuation_summary",
]


@dataclass(frozen=True)
class SourceWindow:
    """Inclusive source window requested by a declared model dependency."""

    start: dt.datetime | pd.Timestamp
    end: dt.datetime | pd.Timestamp


@dataclass(frozen=True)
class LifecycleInputContract:
    """Truthful grain and required values for one lifecycle input."""

    index_names: tuple[str, ...]
    required_columns: tuple[str, ...] = ()
    units: Mapping[str, str] | None = None
    source_revision_column: str = "source_revision"

    def __post_init__(self) -> None:
        if not self.index_names or self.index_names[0] != "time_index":
            raise ValueError("Lifecycle inputs must be time-first.")
        if not self.source_revision_column:
            raise ValueError("Lifecycle inputs require a source revision column.")


@dataclass(frozen=True)
class LifecycleAlignmentContract:
    """Declarative alignment policy executed and checked by the engine."""

    mode: AlignmentMode
    maximum_staleness: dt.timedelta | None = None
    left_on: tuple[str, ...] = ()
    right_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode == "asof" and self.maximum_staleness is None:
            raise ValueError("As-of alignment requires a maximum_staleness bound.")
        if self.maximum_staleness is not None and self.maximum_staleness <= dt.timedelta(0):
            raise ValueError("maximum_staleness must be positive.")


@dataclass(frozen=True)
class LifecycleStateContract:
    """Versioned namespace owned by one lifecycle model."""

    namespace: str
    schema_version: int

    def __post_init__(self) -> None:
        if not self.namespace:
            raise ValueError("Lifecycle state namespace is required.")
        if self.schema_version < 1:
            raise ValueError("Lifecycle state schema_version must be positive.")


@dataclass(frozen=True)
class LifecycleInputBatch:
    """Validated source frames supplied to a lifecycle model."""

    frames: Mapping[str, pd.DataFrame]

    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", MappingProxyType(dict(self.frames)))


@dataclass(frozen=True)
class EventCandidateBatch:
    """Cold-path candidate table produced before engine alignment and grouping."""

    frame: pd.DataFrame

    def __post_init__(self) -> None:
        frame = self.frame.copy()
        if not frame.empty:
            required = {
                "time_index",
                "observed_at",
                "source_identifier",
                "source_revision",
                "event_type",
                "phase",
            }
            missing = sorted(required - set(frame.columns))
            if missing:
                raise ValueError("Event candidates are missing columns: " + ", ".join(missing))
            frame["time_index"] = pd.to_datetime(frame["time_index"], utc=True).astype(
                "datetime64[ns, UTC]"
            )
            frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True).astype(
                "datetime64[ns, UTC]"
            )
            invalid_phases = sorted(
                set(frame["phase"].astype(str))
                - {
                    "pre_execution",
                    "execution",
                    "post_execution",
                }
            )
            if invalid_phases:
                raise ValueError(f"Unsupported lifecycle phases: {invalid_phases}")
        object.__setattr__(self, "frame", frame.reset_index(drop=True))

    @classmethod
    def empty(cls) -> EventCandidateBatch:
        return cls(pd.DataFrame())


@dataclass(frozen=True)
class AccountingStateView:
    """Immutable portfolio state exposed to pure model kernels."""

    positions: pd.DataFrame
    cash: pd.DataFrame
    obligations: pd.DataFrame
    lifecycle_state: pd.DataFrame
    execution_progress: pd.DataFrame
    state_identifier: str


@dataclass(frozen=True)
class LifecycleBatchContext:
    """One engine-aligned homogeneous model invocation."""

    candidates: pd.DataFrame
    state: AccountingStateView
    valuation_context: Any = None


EVENT_BATCH_REQUIRED_COLUMNS = (
    "event_local_identifier",
    "time_index",
    "observed_at",
    "source_identifier",
    "source_revision",
    "event_type",
    "phase",
    "record_kind",
)


@dataclass(frozen=True)
class EventBatch:
    """Flat columnar event records with offsets for variable-length events.

    The arrays are the calculation boundary used by accounting reducers. Models
    can emit several records per event without constructing nested Python
    objects; ``event_offsets`` marks the start and end of each contiguous event.
    """

    columns: Mapping[str, np.ndarray]
    event_offsets: np.ndarray

    def __post_init__(self) -> None:
        columns = {name: np.asarray(values) for name, values in self.columns.items()}
        missing = sorted(set(EVENT_BATCH_REQUIRED_COLUMNS) - set(columns))
        if missing:
            raise ValueError("EventBatch is missing columns: " + ", ".join(missing))
        lengths = {len(values) for values in columns.values()}
        if len(lengths) != 1:
            raise ValueError("Every EventBatch column must have the same length.")
        length = next(iter(lengths), 0)
        offsets = np.asarray(self.event_offsets, dtype=np.int64)
        if offsets.ndim != 1 or not len(offsets) or offsets[0] != 0 or offsets[-1] != length:
            raise ValueError("event_offsets must start at zero and end at the record count.")
        if np.any(np.diff(offsets) <= 0):
            raise ValueError("Every event must contain at least one contiguous record.")
        for start, end in zip(offsets[:-1], offsets[1:], strict=True):
            event_ids = np.unique(columns["event_local_identifier"][start:end].astype(str))
            if len(event_ids) != 1:
                raise ValueError("Each EventBatch segment must contain exactly one event.")
        object.__setattr__(self, "columns", MappingProxyType(columns))
        object.__setattr__(self, "event_offsets", offsets)

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> EventBatch:
        flat = frame.copy().reset_index(drop=True)
        missing = sorted(set(EVENT_BATCH_REQUIRED_COLUMNS) - set(flat.columns))
        if missing:
            raise ValueError("EventBatch frame is missing columns: " + ", ".join(missing))
        if flat.empty:
            columns = {name: np.asarray([], dtype=object) for name in flat.columns}
            return cls(columns=columns, event_offsets=np.asarray([0], dtype=np.int64))
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True).astype(
            "datetime64[ns, UTC]"
        )
        flat["observed_at"] = pd.to_datetime(flat["observed_at"], utc=True).astype(
            "datetime64[ns, UTC]"
        )
        event_values = flat["event_local_identifier"].astype(str).to_numpy()
        changes = np.flatnonzero(event_values[1:] != event_values[:-1]) + 1
        offsets = np.concatenate(([0], changes, [len(flat)])).astype(np.int64)
        return cls(
            columns={name: flat[name].to_numpy() for name in flat.columns},
            event_offsets=offsets,
        )

    @property
    def record_count(self) -> int:
        return int(self.event_offsets[-1])

    @property
    def event_count(self) -> int:
        return len(self.event_offsets) - 1

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({name: values.copy() for name, values in self.columns.items()})


@dataclass(frozen=True)
class CashDeltaBatch:
    """Vectorized cash-only convenience result."""

    event_local_identifier: np.ndarray
    amount_delta: np.ndarray
    amount_asset_identifier: np.ndarray
    balance_role: np.ndarray
    recognized_pnl: np.ndarray

    def __post_init__(self) -> None:
        lengths = {
            len(np.asarray(self.event_local_identifier)),
            len(np.asarray(self.amount_delta)),
            len(np.asarray(self.amount_asset_identifier)),
            len(np.asarray(self.balance_role)),
            len(np.asarray(self.recognized_pnl)),
        }
        if len(lengths) != 1:
            raise ValueError("CashDeltaBatch arrays must have equal length.")


__all__ = [
    "AccountingStateView",
    "AlignmentMode",
    "CashDeltaBatch",
    "EventBatch",
    "EventCandidateBatch",
    "EventPhase",
    "LifecycleAlignmentContract",
    "LifecycleBatchContext",
    "LifecycleInputBatch",
    "LifecycleInputContract",
    "LifecycleStateContract",
    "RecordKind",
    "SourceWindow",
]
