from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd
from sqlalchemy import DateTime, Integer, String, and_, column, func, select, values

if TYPE_CHECKING:
    from msm.repositories.base import MarketsOperationContext

from msm.time_index.utils.time import normalize_datetime64_ns_utc, normalize_timestamp_ns_utc
from msm.time_index.assets.asset_indexed import (
    AssetIndexedUpdater,
    AssetIndexedUpdaterConfiguration,
)
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm.time_index.utils.stamped import (
    StampedUpdaterConfiguration,
    StampedFrameMixin,
    reset_frame_index,
)
from msm.settings import ASSET_IDENTIFIER_DIMENSION

AssetSnapshotInput = Mapping[str, Any] | Any

SNAPSHOT_VALUE_COLUMNS: tuple[str, ...] = ("name", "ticker", "exchange_code", "asset_ticker_group_id")
"""The columns a snapshot row is compared on; an empty string and ``None`` are equal."""

_SNAPSHOT_LOOKUP_BATCH = 500


class AssetUpdaterConfiguration(StampedUpdaterConfiguration, AssetIndexedUpdaterConfiguration):
    """Configuration for timestamped asset updaters.

    Storage-first: the column schema, index names, and the canonical
    ``Asset.unique_identifier`` foreign key live on the ``output_table``
    (an ``AssetSnapshotsStorage``-style ``PlatformTimeIndexMetaTable`` class),
    not on this configuration.
    """

    reference_dimension: ClassVar[str] = ASSET_IDENTIFIER_DIMENSION
    frame_label: ClassVar[str] = "Asset TimeIndexTableUpdater"


class AssetSnapshotConfiguration(AssetUpdaterConfiguration):
    """Configuration for the canonical AssetSnapshot TimeIndexTableUpdater."""


class AssetTimestampedFrameMixin(StampedFrameMixin):
    """Shared frame/config behavior for timestamped asset updaters."""

    configuration_class: ClassVar[type[AssetUpdaterConfiguration]] = AssetUpdaterConfiguration
    frame_label: ClassVar[str] = "Asset TimeIndexTableUpdater"


class AssetTimestampedUpdater(AssetTimestampedFrameMixin, AssetIndexedUpdater):
    """Base asset-indexed TimeIndexTableUpdater for timestamped facts keyed by asset_identifier."""

    def dependencies(self) -> dict:
        return {}


class AssetSnapshot(AssetTimestampedUpdater):
    """Timestamped asset display snapshots keyed by asset_identifier."""

    configuration_class = AssetSnapshotConfiguration

    @classmethod
    def build_frame(
        cls,
        snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
    ) -> pd.DataFrame:
        """Build a validated frame from row payloads with per-row `time_index`."""

        rows = []
        for snapshot in _snapshot_items(snapshots):
            payload = _snapshot_payload(snapshot)
            asset_identifier = _required_snapshot_string(payload, ASSET_IDENTIFIER_DIMENSION)
            rows.append(
                {
                    "time_index": _required_snapshot_time(payload),
                    ASSET_IDENTIFIER_DIMENSION: asset_identifier,
                    "name": _optional_snapshot_string(payload, "name"),
                    "ticker": _optional_snapshot_string(payload, "ticker"),
                    "exchange_code": _optional_snapshot_string(payload, "exchange_code"),
                    "asset_ticker_group_id": _optional_snapshot_string(
                        payload,
                        "asset_ticker_group_id",
                    ),
                }
            )

        if not rows:
            raise ValueError("At least one asset snapshot is required.")
        return cls.validate_frame(pd.DataFrame(rows))

    def set_snapshots(
        self,
        snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
        *,
        verify_existing: bool = True,
    ) -> AssetSnapshot:
        """Validate snapshot row payloads and attach them to this TimeIndexTableUpdater."""

        self._verify_existing_snapshot_index = verify_existing
        return self.set_frame(self.build_frame(snapshots))

    def _execute_local_update(self, table_update_run: Any):
        self._verify_backend_snapshot_index = True
        try:
            return super()._execute_local_update(table_update_run=table_update_run)
        finally:
            self._verify_backend_snapshot_index = False

    def update(self) -> pd.DataFrame:
        frame = super().update()
        if getattr(self, "_verify_backend_snapshot_index", False) and getattr(
            self,
            "_verify_existing_snapshot_index",
            True,
        ):
            frame = self.without_stored_snapshots(frame)
        return frame

    def without_stored_snapshots(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return ``frame`` without the rows already stored with the same values.

        A ``(time_index, asset_identifier)`` already stored with different values raises
        ``ValueError``: a snapshot is never rewritten.
        """

        stored = self.stored_snapshot_values(frame)
        if not stored:
            return frame
        validated = self.validate_frame(frame, output_table=self.output_table)
        flat = _flat_snapshot_frame(validated)
        keys = zip(flat["time_index"], flat[ASSET_IDENTIFIER_DIMENSION].astype(str))
        conflicts = []
        keep = []
        for key, row in zip(keys, flat.to_dict("records")):
            keep.append(key not in stored)
            if keep[-1]:
                continue
            self._log_existing_asset_snapshot_key(time_index=key[0], unique_identifier=key[1])
            if stored[key] != _snapshot_values(row):
                conflicts.append(key)
        if conflicts:
            raise ValueError(
                "AssetSnapshot rows already exist with different values for "
                f"(time_index, asset_identifier): {_format_snapshot_keys(conflicts)}."
            )
        return validated[keep]

    def stored_snapshot_values(
        self, frame: pd.DataFrame
    ) -> dict[tuple[pd.Timestamp, str], tuple[str, ...]]:
        """The stored values of the ``(time_index, asset_identifier)`` keys of ``frame``."""

        from msm.repositories.base import (
            MarketsRepositoryContext,
            compile_markets_statement,
            execute_markets_operation,
        )

        candidate_keys = _asset_snapshot_index_keys(
            self.validate_frame(frame, output_table=self.output_table)
        )
        if not candidate_keys:
            return {}

        candidate_key_set = set(candidate_keys)
        times = sorted({time_index for time_index, _ in candidate_key_set})
        asset_identifiers = sorted({asset_identifier for _, asset_identifier in candidate_key_set})

        AssetSnapshotsStorage._bind_meta_table(self.update_manager.output_metadata)
        context = MarketsRepositoryContext()
        statement = (
            select(
                AssetSnapshotsStorage.time_index.label("time_index"),
                AssetSnapshotsStorage.asset_identifier.label(ASSET_IDENTIFIER_DIMENSION),
                *(getattr(AssetSnapshotsStorage, name) for name in SNAPSHOT_VALUE_COLUMNS),
            )
            .where(
                AssetSnapshotsStorage.time_index >= times[0].to_pydatetime(),
                AssetSnapshotsStorage.time_index <= times[-1].to_pydatetime(),
                AssetSnapshotsStorage.asset_identifier.in_(asset_identifiers),
            )
        )
        operation = compile_markets_statement(
            statement,
            context=context,
            operation="select",
        )
        result = execute_markets_operation(operation, context=context)
        stored = {
            (
                normalize_timestamp_ns_utc(row["time_index"]),
                str(row[ASSET_IDENTIFIER_DIMENSION]),
            ): _snapshot_values(row)
            for row in _operation_result_rows(result)
            if row.get("time_index") is not None
            and row.get(ASSET_IDENTIFIER_DIMENSION) is not None
        }
        return {key: value for key, value in stored.items() if key in candidate_key_set}

    def _log_existing_asset_snapshot_key(
        self,
        *,
        time_index: pd.Timestamp,
        unique_identifier: str,
    ) -> None:
        try:
            logger = self.logger
        except Exception:
            return
        logger.info(
            "AssetSnapshot row already exists",
            time_index=time_index.isoformat(),
            unique_identifier=unique_identifier,
        )

    @classmethod
    def _required_output_table(cls) -> type[AssetSnapshotsStorage]:
        return AssetSnapshotsStorage


def changed_asset_snapshots(
    snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
    *,
    repository_context: MarketsOperationContext,
) -> list[AssetSnapshotInput]:
    """The snapshots that change their asset's snapshot, in input order (MainSequenceMarkets#62).

    Each row is compared, on ``SNAPSHOT_VALUE_COLUMNS``, with the snapshot in effect at
    its own ``time_index``: the asset's latest stored row at or before it, or the asset's
    previous row in ``snapshots`` when that one is later. A row equal to it changes
    nothing and is left out; so is a row that repeats a stored or an earlier
    ``(time_index, asset_identifier)`` with the same values. A repeated key with
    different values raises ``ValueError``. A backdated row is compared with the snapshot
    in effect at its date, not with the asset's latest one.
    """

    items = _snapshot_items(snapshots)
    rows = _first_of_each_key(
        [_snapshot_row(position, item) for position, item in enumerate(items)]
    )
    in_effect = _stored_snapshots_in_effect(rows, repository_context=repository_context)
    changed: list[int] = []
    conflicts: list[tuple[pd.Timestamp, str]] = []
    previous: _SnapshotRow | None = None
    for row in sorted(rows, key=lambda row: (row.asset_identifier, row.time_index)):
        if previous is not None and previous.asset_identifier != row.asset_identifier:
            previous = None
        stored = in_effect.get(row.position)
        if stored is not None and stored.at_row_time and stored.values != row.values:
            conflicts.append((row.time_index, row.asset_identifier))
        current = _later(previous, stored)
        if current is None or current.values != row.values:
            changed.append(row.position)
        previous = row
    if conflicts:
        raise ValueError(
            "AssetSnapshot rows already exist with different values for "
            f"(time_index, asset_identifier): {_format_snapshot_keys(sorted(conflicts))}."
        )
    return [items[position] for position in sorted(changed)]


@dataclass(frozen=True)
class _SnapshotRow:
    position: int
    time_index: pd.Timestamp
    asset_identifier: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class _StoredSnapshot:
    time_index: pd.Timestamp
    at_row_time: bool
    values: tuple[str, ...]


def _snapshot_row(position: int, snapshot: AssetSnapshotInput) -> _SnapshotRow:
    payload = _snapshot_payload(snapshot)
    return _SnapshotRow(
        position=position,
        time_index=_required_snapshot_time(payload),
        asset_identifier=_required_snapshot_string(payload, ASSET_IDENTIFIER_DIMENSION),
        values=tuple(_optional_snapshot_string(payload, name) for name in SNAPSHOT_VALUE_COLUMNS),
    )


def _first_of_each_key(rows: Sequence[_SnapshotRow]) -> list[_SnapshotRow]:
    """Drop rows that repeat an earlier row; a repeat with different values raises."""

    first: dict[tuple[pd.Timestamp, str], _SnapshotRow] = {}
    for row in rows:
        seen = first.setdefault((row.time_index, row.asset_identifier), row)
        if seen.values != row.values:
            raise ValueError(
                "Asset snapshots repeat (time_index, asset_identifier) with different values: "
                f"{_format_snapshot_keys([(row.time_index, row.asset_identifier)])}."
            )
    return list(first.values())


def _later(
    previous: _SnapshotRow | None, stored: _StoredSnapshot | None
) -> _SnapshotRow | _StoredSnapshot | None:
    if previous is None or stored is None:
        return previous or stored
    return stored if stored.time_index > previous.time_index else previous


def _stored_snapshots_in_effect(
    rows: Sequence[_SnapshotRow],
    *,
    repository_context: MarketsOperationContext,
) -> dict[int, _StoredSnapshot]:
    """Each row's position mapped to its asset's latest stored snapshot at or before it."""

    from msm.repositories.base import (
        compile_markets_statement,
        execute_markets_operation,
        resolve_markets_sql_target,
        values_parameter,
    )

    if not rows:
        return {}
    data_source_uid, dialect = resolve_markets_sql_target(repository_context)
    table = AssetSnapshotsStorage.__table__
    earlier = table.alias("earlier_snapshots")
    found: dict[int, _StoredSnapshot] = {}
    for start in range(0, len(rows), _SNAPSHOT_LOOKUP_BATCH):
        batch = rows[start : start + _SNAPSHOT_LOOKUP_BATCH]
        inputs = (
            values(
                column("position", Integer()),
                column(ASSET_IDENTIFIER_DIMENSION, String()),
                column("time_index", DateTime(timezone=True)),
                name="snapshot_input",
            )
            .data(
                [
                    (
                        values_parameter(row.position, Integer(), dialect=dialect),
                        values_parameter(row.asset_identifier, String(), dialect=dialect),
                        values_parameter(
                            row.time_index.to_pydatetime(), DateTime(timezone=True), dialect=dialect
                        ),
                    )
                    for row in batch
                ]
            )
            .cte("snapshot_input")
        )
        in_effect_time = (
            select(func.max(earlier.c.time_index))
            .where(
                earlier.c.asset_identifier == inputs.c[ASSET_IDENTIFIER_DIMENSION],
                earlier.c.time_index <= inputs.c.time_index,
            )
            .scalar_subquery()
        )
        statement = select(
            inputs.c.position,
            table.c.time_index,
            (table.c.time_index == inputs.c.time_index).label("at_row_time"),
            *(table.c[name] for name in SNAPSHOT_VALUE_COLUMNS),
        ).select_from(
            inputs.join(
                table,
                and_(
                    table.c.asset_identifier == inputs.c[ASSET_IDENTIFIER_DIMENSION],
                    table.c.time_index == in_effect_time,
                ),
            )
        )
        result = execute_markets_operation(
            compile_markets_statement(
                statement,
                context=repository_context,
                operation="select",
                dialect=dialect,
                data_source_uid=data_source_uid,
            ),
            context=repository_context,
        )
        for row in _operation_result_rows(result):
            found[int(row["position"])] = _StoredSnapshot(
                time_index=normalize_timestamp_ns_utc(row["time_index"]),
                at_row_time=bool(row["at_row_time"]),
                values=_snapshot_values(row),
            )
    return found


def _snapshot_values(row: Mapping[str, Any]) -> tuple[str, ...]:
    """A row's ``SNAPSHOT_VALUE_COLUMNS`` as strings; a missing value is ``""``."""

    return tuple(
        "" if row.get(name) is None or row.get(name) is pd.NA or _is_nan(row.get(name))
        else str(row.get(name))
        for name in SNAPSHOT_VALUE_COLUMNS
    )


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and value != value


def _format_snapshot_keys(keys: Sequence[tuple[pd.Timestamp, str]]) -> str:
    return ", ".join(f"({time_index.isoformat()}, {identifier})" for time_index, identifier in keys)


def _flat_snapshot_frame(frame: pd.DataFrame) -> pd.DataFrame:
    flat = reset_frame_index(
        frame.copy(),
        index_names=[
            "time_index",
            ASSET_IDENTIFIER_DIMENSION,
        ],
    )
    flat["time_index"] = normalize_datetime64_ns_utc(flat["time_index"])
    return flat


def _asset_snapshot_index_keys(frame: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    keys = _flat_snapshot_frame(frame)[
        [
            "time_index",
            ASSET_IDENTIFIER_DIMENSION,
        ]
    ].drop_duplicates()
    return [
        (
            normalize_timestamp_ns_utc(row["time_index"]),
            str(row[ASSET_IDENTIFIER_DIMENSION]),
        )
        for _, row in keys.iterrows()
    ]


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if not isinstance(result, Mapping):
        return []

    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            nested_rows = _operation_result_rows(value)
            if nested_rows:
                return nested_rows
            if key == "row":
                return [dict(value)]
            if "uid" in value:
                return [dict(value)]
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]

    if "uid" in result:
        return [dict(result)]
    return []


def _snapshot_items(
    snapshots: AssetSnapshotInput | Sequence[AssetSnapshotInput],
) -> list[AssetSnapshotInput]:
    if isinstance(snapshots, Mapping) or not isinstance(snapshots, Sequence):
        return [snapshots]
    if isinstance(snapshots, (str, bytes)):
        return [snapshots]
    return list(snapshots)


def _snapshot_payload(snapshot: AssetSnapshotInput) -> dict[str, Any]:
    if isinstance(snapshot, Mapping):
        return dict(snapshot)
    return {
        field_name: getattr(snapshot, field_name)
        for field_name in (
            "time_index",
            ASSET_IDENTIFIER_DIMENSION,
            "name",
            "ticker",
            "exchange_code",
            "asset_ticker_group_id",
        )
        if hasattr(snapshot, field_name)
    }


def _required_snapshot_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Asset snapshots require a non-empty {field_name}.")
    return value.strip()


def _required_snapshot_time(payload: Mapping[str, Any]) -> Any:
    value = payload.get("time_index")
    if value is None:
        raise ValueError("Asset snapshots require a per-row time_index.")
    try:
        return normalize_timestamp_ns_utc(value)
    except Exception as exc:
        raise ValueError(f"Invalid AssetSnapshot time_index: {value!r}.") from exc


def _optional_snapshot_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if value is None:
        return ""
    return str(value)


__all__ = [
    "AssetUpdaterConfiguration",
    "AssetSnapshot",
    "SNAPSHOT_VALUE_COLUMNS",
    "AssetSnapshotConfiguration",
    "AssetSnapshotInput",
    "AssetTimestampedUpdater",
    "AssetTimestampedFrameMixin",
    "changed_asset_snapshots",
]
