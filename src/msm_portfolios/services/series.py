"""Publish and read the three published series (ADR 0060, decision 3).

Signal weights, portfolio weights and portfolio values are stored once, in Markets'
own tables. An application sends their rows to ``publish`` and reads them with
``window``, ``last``, ``bounds`` and ``assets``; ``delete_after`` removes one key's rows
after a time so they can be restated. Every statement here names a table that
Markets' own migrations create, and nothing else.

``publish`` writes one key's rows in one transaction. A row equal to the stored row of
the same ``(time_index, key[, asset])`` is skipped; a different one refuses the call and
nothing is written, so publishing the same rows again writes nothing. Signal weights
keep the rules ``ApplicationWeights.publish`` had: times carry a timezone, weights are
finite numbers, assets are registered, an asset the signal held and an observation
leaves out is written at ``0``, and an observation at or before the signal's last
stored time is refused unless it equals what is stored. Only the row's manager may
publish or delete (decision 4).
"""

from __future__ import annotations

import datetime as dt
import math
import numbers
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, delete, func, insert, select

from metatables import dtype_codec as dc
from msm.api.managers import require_manager
from msm.models import AssetTable, PortfolioTable, SignalMetadataTable
from msm.repositories.base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
    with_max_rows,
)
from msm.time_index.utils.storage_schema import storage_column_dtypes_map
from msm_portfolios.time_index.portfolios.storage import PortfoliosStorage, PortfolioWeightsStorage
from msm_portfolios.time_index.signals.storage import SignalWeightsStorage

TIME_INDEX = "time_index"
ASSET = "asset_identifier"

PUBLISH_MAX_ROWS = 10_000
"""Rows one ``publish`` call takes. A longer history is published key by key, in calls."""

READ_MAX_ROWS = 9_000
"""Rows one read returns: a ``window`` page, or a whole ``last`` answer (MetaTables answers
at most 10,000 rows per statement)."""

DEFAULT_PAGE_ROWS = 5_000

_STATEMENT_PARAMETERS = 30_000
"""Values one insert statement binds, under SQLite's 32,766."""

_FLOAT_TOLERANCE = 1e-12


@dataclass(frozen=True)
class Series:
    """One published series: its storage table, key column and registry row."""

    resource: str
    model: type
    key: str
    asset: str | None
    registry: type
    registry_key: str
    label: str

    @property
    def table(self) -> Any:
        return self.model.__table__

    @property
    def dtypes(self) -> dict[str, str]:
        return storage_column_dtypes_map(self.model)

    @property
    def index_columns(self) -> list[str]:
        return [TIME_INDEX, self.key, *([self.asset] if self.asset else [])]

    @property
    def value_columns(self) -> list[str]:
        return [name for name in self.dtypes if name not in self.index_columns]

    def row_key(self, row: Mapping[str, Any]) -> tuple:
        return (row[TIME_INDEX], *((row[self.asset],) if self.asset else ()))

    def ordered(self) -> list[Any]:
        return [self.table.c[name] for name in self.index_columns]


SIGNAL_WEIGHTS = Series(
    resource="signal-weights",
    model=SignalWeightsStorage,
    key="signal_uid",
    asset=ASSET,
    registry=SignalMetadataTable,
    registry_key="signal_uid",
    label="Signal",
)
PORTFOLIO_WEIGHTS = Series(
    resource="portfolio-weights",
    model=PortfolioWeightsStorage,
    key="portfolio_identifier",
    asset=ASSET,
    registry=PortfolioTable,
    registry_key="unique_identifier",
    label="Portfolio",
)
PORTFOLIO_VALUES = Series(
    resource="portfolio-values",
    model=PortfoliosStorage,
    key="portfolio_identifier",
    asset=None,
    registry=PortfolioTable,
    registry_key="unique_identifier",
    label="Portfolio",
)
SERIES = {
    series.resource: series for series in (SIGNAL_WEIGHTS, PORTFOLIO_WEIGHTS, PORTFOLIO_VALUES)
}


# Answers -------------------------------------------------------------------------------


class SeriesPublication(BaseModel):
    """What one ``publish`` call wrote, and the key's series after it."""

    model_config = ConfigDict(frozen=True)

    key: str
    written: int = Field(description="Rows inserted, including signal assets closed at 0.")
    skipped: int = Field(description="Rows equal to the stored row, not written again.")
    first_time: dt.datetime | None = None
    last_time: dt.datetime | None = None
    row_count: int = Field(0, description="The key's rows after the call.")


class SeriesBounds(BaseModel):
    """First and last time and row count of one key; times are ``None`` without rows."""

    model_config = ConfigDict(frozen=True)

    key: str
    first_time: dt.datetime | None = None
    last_time: dt.datetime | None = None
    row_count: int = 0


class SeriesDeletion(BaseModel):
    """The rows ``delete_after`` removed from one key's series."""

    model_config = ConfigDict(frozen=True)

    key: str
    after: dt.datetime
    deleted: int


class SeriesRows(BaseModel):
    """Rows of a series, typed by its columns; ``frame()`` gives them as a DataFrame.

    ``next_offset`` is set when a ``window`` page was full: pass it as ``offset`` for
    the next page.
    """

    model_config = ConfigDict(frozen=True)

    series: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    next_offset: int | None = None

    @model_validator(mode="after")
    def _typed_rows(self) -> SeriesRows:
        spec = SERIES.get(self.series)
        if spec is not None:
            object.__setattr__(self, "rows", [_typed_row(spec, row) for row in self.rows])
        return self

    def frame(self) -> pd.DataFrame:
        """The rows indexed by the series' index columns, times in UTC."""

        spec = SERIES[self.series]
        columns = list(dict.fromkeys(name for row in self.rows for name in row))
        if not columns:
            columns = list(spec.dtypes)
        flat = pd.DataFrame(self.rows, columns=columns)
        for name in columns:
            if spec.dtypes.get(name) == dc.TIMESTAMP_TZ:
                flat[name] = pd.to_datetime(flat[name], utc=True)
        return flat.set_index(spec.index_columns).sort_index()


# Publish -------------------------------------------------------------------------------


def publish_series(
    context: MarketsRepositoryContext,
    series: Series,
    *,
    key: str,
    rows: Sequence[Mapping[str, Any]],
) -> SeriesPublication:
    """Write one key's ``rows`` in one transaction; see the module docstring."""

    key = _required_key(series, key)
    if len(rows) > PUBLISH_MAX_ROWS:
        raise ValueError(
            f"publish takes at most {PUBLISH_MAX_ROWS} rows per call; got {len(rows)}. "
            "Publish a longer history in several calls, oldest first."
        )
    registry = _registry_row(context, series, key)
    require_manager(f"{series.label} {key!r}", registry.get("managed_by"))
    incoming = _validated_rows(series, key, rows)
    if series.registry is PortfolioTable:
        _refuse_rows_after_retirement(key, incoming, registry.get("retired_at"))
    before = series_bounds(context, series, keys=[key])[0]
    if not incoming:
        return SeriesPublication(
            key=key,
            written=0,
            skipped=0,
            first_time=before.first_time,
            last_time=before.last_time,
            row_count=before.row_count,
        )
    if series.asset:
        _require_registered_assets(context, {row[series.asset] for row in incoming})
    stored = _stored_rows(context, series, key=key, rows=incoming)
    new_rows: list[dict[str, Any]] = []
    skipped = 0
    conflicts: list[tuple] = []
    for row in incoming:
        existing = stored.get(series.row_key(row))
        if existing is None:
            new_rows.append(row)
        elif _same_values(series, row, existing):
            skipped += 1
        else:
            conflicts.append(series.row_key(row))
    if conflicts:
        raise ValueError(
            f"{series.label} {key!r} already has different {series.resource} rows at "
            f"{_format_keys(conflicts)}. Published rows are never rewritten; delete_after "
            "removes rows after a time so they can be published again."
        )
    if series is SIGNAL_WEIGHTS:
        new_rows = _signal_observations(context, key=key, new_rows=new_rows, last=before.last_time)
    if new_rows:
        _insert_rows(context, series, new_rows)
    times = [row[TIME_INDEX] for row in new_rows]
    first_time = min([t for t in (before.first_time, *times) if t is not None], default=None)
    last_time = max([t for t in (before.last_time, *times) if t is not None], default=None)
    return SeriesPublication(
        key=key,
        written=len(new_rows),
        skipped=skipped,
        first_time=first_time,
        last_time=last_time,
        row_count=before.row_count + len(new_rows),
    )


def _signal_observations(
    context: MarketsRepositoryContext,
    *,
    key: str,
    new_rows: list[dict[str, Any]],
    last: dt.datetime | None,
) -> list[dict[str, Any]]:
    """The new observations, each with the assets it drops closed at ``0``.

    An observation is every row at one time; it is the signal's whole set of weights
    then. A new observation must come after the signal's last stored time.
    """

    if not new_rows:
        return []
    first = min(row[TIME_INDEX] for row in new_rows)
    if last is not None and first <= last:
        raise ValueError(
            f"Observation at {first.isoformat()} is at or before this signal's last stored "
            f"observation ({last.isoformat()}). Published observations are never restated: "
            "portfolios that rebalanced on them would keep the old weights."
        )
    held: set[str] = set()
    if last is not None:
        latest = series_last(context, SIGNAL_WEIGHTS, keys=[key], at=last, by="asset")
        held = {
            str(row[ASSET]) for row in latest.rows if row.get("signal_weight") not in (None, 0.0)
        }
    by_time: dict[dt.datetime, list[dict[str, Any]]] = {}
    for row in new_rows:
        by_time.setdefault(row[TIME_INDEX], []).append(row)
    written: list[dict[str, Any]] = []
    for time in sorted(by_time):
        observation = by_time[time]
        present = {row[ASSET] for row in observation}
        written.extend(
            {TIME_INDEX: time, "signal_uid": key, ASSET: asset, "signal_weight": 0.0}
            for asset in sorted(held - present)
        )
        written.extend(observation)
        held = {row[ASSET] for row in observation if row["signal_weight"] != 0.0}
    return written


def _validated_rows(
    series: Series, key: str, rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    if isinstance(rows, (str, bytes, Mapping)) or not isinstance(rows, Iterable):
        raise TypeError("rows must be a list of mappings, one per row.")
    allowed = set(series.dtypes)
    validated: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for position, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"Row {position} is not a mapping: {row!r}.")
        unknown = sorted(set(row) - allowed)
        if unknown:
            raise ValueError(
                f"Row {position} has columns {series.resource} does not have: {unknown}."
            )
        given_key = row.get(series.key)
        if given_key not in (None, "") and str(given_key) != key:
            raise ValueError(
                f"Row {position} names {series.key} {given_key!r}; this call publishes {key!r}."
            )
        typed: dict[str, Any] = {TIME_INDEX: _publish_time(row.get(TIME_INDEX), position)}
        typed[series.key] = key
        if series.asset:
            asset = row.get(series.asset)
            if not isinstance(asset, str) or not asset.strip():
                raise ValueError(f"Row {position} has no {series.asset}: {asset!r}.")
            typed[series.asset] = asset
        for name in series.value_columns:
            typed[name] = _publish_value(series, name, row.get(name), position)
        token = series.row_key(typed)
        if token in seen:
            raise ValueError(f"Rows repeat {_format_keys([token])}.")
        seen.add(token)
        validated.append(typed)
    return validated


def _publish_time(value: Any, position: int) -> dt.datetime:
    if value in (None, ""):
        raise ValueError(f"Row {position} has no {TIME_INDEX}.")
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Row {position} {TIME_INDEX} {value!r} is not ISO 8601.") from exc
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is None:
            raise ValueError(f"Row {position} {TIME_INDEX} {value.isoformat()} has no timezone.")
        return _utc(value.floor("us").to_pydatetime())
    if not isinstance(value, dt.datetime):
        raise TypeError(f"Row {position} {TIME_INDEX} is not a datetime: {value!r}.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Row {position} {TIME_INDEX} {value.isoformat()} has no timezone.")
    return _utc(value)


def _publish_value(series: Series, name: str, value: Any, position: int) -> Any:
    dtype = series.dtypes[name]
    if dtype == dc.FLOAT64:
        if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA:
            if series is SIGNAL_WEIGHTS:
                raise ValueError(f"Row {position} has no signal_weight; weights are numbers.")
            return None
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            raise TypeError(f"Row {position} {name} is not a number: {value!r}.")
        if not math.isfinite(value):
            raise ValueError(f"Row {position} {name} is not finite: {value!r}.")
        return float(value)
    if dtype == dc.TIMESTAMP_TZ:
        return None if value in (None, "") or value is pd.NaT else _publish_time(value, position)
    if dtype == dc.BOOL:
        if value is None or value is pd.NA:
            return None
        if not isinstance(value, (bool,)) and not (
            isinstance(value, numbers.Integral) and value in (0, 1)
        ):
            raise TypeError(f"Row {position} {name} is not a boolean: {value!r}.")
        return bool(value)
    return None if value is None else str(value)


def _refuse_rows_after_retirement(
    key: str, rows: Sequence[Mapping[str, Any]], retired_at: Any
) -> None:
    if retired_at in (None, ""):
        return
    boundary = _utc(_as_datetime(retired_at))
    late = sorted({row[TIME_INDEX] for row in rows if row[TIME_INDEX] >= boundary})
    if late:
        raise ValueError(
            f"Portfolio {key!r} is retired from {boundary.isoformat()} (ADR 0049); rows at "
            f"or after it are refused: {', '.join(time.isoformat() for time in late[:5])}."
        )


def _same_values(series: Series, row: Mapping[str, Any], stored: Mapping[str, Any]) -> bool:
    for name in series.value_columns:
        left, right = row.get(name), stored.get(name)
        if left is None or right is None:
            if left is not right:
                return False
            continue
        if isinstance(left, float) or isinstance(right, float):
            if not math.isclose(float(left), float(right), rel_tol=_FLOAT_TOLERANCE, abs_tol=0.0):
                return False
        elif left != right:
            return False
    return True


def _insert_rows(
    context: MarketsRepositoryContext, series: Series, rows: Sequence[Mapping[str, Any]]
) -> None:
    columns = list(series.dtypes)
    per_statement = max(1, _STATEMENT_PARAMETERS // len(columns))
    statements = [
        insert(series.table).values(
            [
                {name: row.get(name) for name in columns}
                for row in rows[start : start + per_statement]
            ]
        )
        for start in range(0, len(rows), per_statement)
    ]
    data_source_uid, dialect = resolve_markets_sql_target(context)
    execute_markets_write(
        compile_markets_statements(
            statements,
            context=context,
            operation="insert",
            data_source_uid=data_source_uid,
            dialect=dialect,
        ),
        context=context,
    )


def _stored_rows(
    context: MarketsRepositoryContext,
    series: Series,
    *,
    key: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple, dict[str, Any]]:
    """The stored rows at the incoming rows' coordinates, by ``row_key``."""

    times = sorted({row[TIME_INDEX] for row in rows})
    wanted = {series.row_key(row) for row in rows}
    found: dict[tuple, dict[str, Any]] = {}
    offset = 0
    while True:
        page = series_window(
            context,
            series,
            keys=[key],
            start=times[0],
            end=times[-1],
            limit=READ_MAX_ROWS,
            offset=offset,
        )
        for row in page.rows:
            token = series.row_key(row)
            if token in wanted:
                found[token] = row
        if page.next_offset is None:
            return found
        offset = page.next_offset


# Reads ---------------------------------------------------------------------------------


def series_window(
    context: MarketsRepositoryContext,
    series: Series,
    *,
    keys: Sequence[str],
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    columns: Sequence[str] | None = None,
    assets: Sequence[str] | None = None,
    limit: int = DEFAULT_PAGE_ROWS,
    offset: int = 0,
    newest_first: bool = False,
) -> SeriesRows:
    """Rows of ``keys`` with ``start <= time_index <= end``, by time, key and asset; paged.

    ``newest_first`` orders by time descending (key and asset still ascending).
    """

    keys = _required_keys(series, keys)
    if not 1 <= limit <= READ_MAX_ROWS:
        raise ValueError(f"limit must be between 1 and {READ_MAX_ROWS}; got {limit}.")
    if offset < 0:
        raise ValueError(f"offset must be 0 or more; got {offset}.")
    table = series.table
    selected = [*series.index_columns, *_value_columns(series, columns)]
    statement = select(*(table.c[name] for name in selected)).where(table.c[series.key].in_(keys))
    statement = _time_filter(statement, table, start=start, end=end)
    statement = _asset_filter(statement, series, assets)
    order = series.ordered()
    if newest_first:
        order = [order[0].desc(), *order[1:]]
    statement = statement.order_by(*order).limit(limit + 1).offset(offset)
    rows = _select(context, statement, max_rows=limit + 1)
    next_offset = offset + limit if len(rows) > limit else None
    return SeriesRows(series=series.resource, rows=rows[:limit], next_offset=next_offset)


def series_last(
    context: MarketsRepositoryContext,
    series: Series,
    *,
    keys: Sequence[str],
    at: dt.datetime | None = None,
    by: Literal["key", "asset"] = "key",
    inclusive: bool = True,
    assets: Sequence[str] | None = None,
) -> SeriesRows:
    """The last rows at or before ``at`` (before it when ``inclusive`` is false).

    ``by="key"`` answers each key's rows at its last time: a portfolio's last value, or
    a signal's or portfolio's last whole set of weights. ``by="asset"`` answers each
    key's last row of each asset, whenever it was written.
    """

    keys = _required_keys(series, keys)
    if by not in ("key", "asset"):
        raise ValueError(f"by must be 'key' or 'asset'; got {by!r}.")
    if by == "asset" and not series.asset:
        raise ValueError(f"{series.resource} has no asset column; use by='key'.")
    table = series.table
    group = [table.c[series.key], *([table.c[series.asset]] if by == "asset" else [])]
    latest = select(*group, func.max(table.c[TIME_INDEX]).label("last_time")).where(
        table.c[series.key].in_(keys)
    )
    if at is not None:
        bound = _utc(_as_datetime(at))
        time = table.c[TIME_INDEX]
        latest = latest.where(time <= bound if inclusive else time < bound)
    latest = _asset_filter(latest, series, assets).group_by(*group).subquery("latest_rows")
    joined = and_(
        table.c[TIME_INDEX] == latest.c.last_time,
        *(column == latest.c[column.name] for column in group),
    )
    statement = select(*(table.c[name] for name in series.dtypes)).select_from(
        table.join(latest, joined)
    )
    statement = _asset_filter(statement, series, assets).order_by(*series.ordered())
    rows = _select(context, statement, max_rows=READ_MAX_ROWS + 1)
    if len(rows) > READ_MAX_ROWS:
        raise ValueError(
            f"last answers at most {READ_MAX_ROWS} rows; ask for fewer keys or assets."
        )
    return SeriesRows(series=series.resource, rows=rows)


def series_bounds(
    context: MarketsRepositoryContext,
    series: Series,
    *,
    keys: Sequence[str],
) -> list[SeriesBounds]:
    """First and last time and row count of each key, in the order of ``keys``."""

    keys = _required_keys(series, keys)
    table = series.table
    statement = (
        select(
            table.c[series.key].label("key"),
            func.min(table.c[TIME_INDEX]).label("first_time"),
            func.max(table.c[TIME_INDEX]).label("last_time"),
            func.count().label("row_count"),
        )
        .where(table.c[series.key].in_(keys))
        .group_by(table.c[series.key])
    )
    found = {str(row["key"]): row for row in _select(context, statement, max_rows=len(keys))}
    return [
        SeriesBounds(
            key=key,
            first_time=_optional_time(found.get(key, {}).get("first_time")),
            last_time=_optional_time(found.get(key, {}).get("last_time")),
            row_count=int(found.get(key, {}).get("row_count") or 0),
        )
        for key in keys
    ]


def series_assets(context: MarketsRepositoryContext, series: Series, *, key: str) -> list[str]:
    """Every asset ``key`` has a row for, sorted."""

    if not series.asset:
        raise ValueError(f"{series.resource} has no asset column.")
    key = _required_key(series, key)
    table = series.table
    statement = (
        select(table.c[series.asset].label("asset"))
        .where(table.c[series.key] == key)
        .distinct()
        .order_by(table.c[series.asset])
    )
    rows = _select(context, statement, max_rows=READ_MAX_ROWS + 1)
    if len(rows) > READ_MAX_ROWS:
        raise ValueError(f"{series.label} {key!r} has more than {READ_MAX_ROWS} assets.")
    return [str(row["asset"]) for row in rows]


def series_delete_after(
    context: MarketsRepositoryContext,
    series: Series,
    *,
    key: str,
    after: dt.datetime,
) -> SeriesDeletion:
    """Delete ``key``'s rows dated after ``after``, so they can be published again."""

    key = _required_key(series, key)
    registry = _registry_row(context, series, key)
    require_manager(f"{series.label} {key!r}", registry.get("managed_by"))
    if not isinstance(after, dt.datetime) or after.tzinfo is None:
        raise ValueError("delete_after needs a timezone-aware time.")
    bound = _utc(after)
    table = series.table
    counted = _count_after(context, series, key=key, after=bound)
    statement = delete(table).where(table.c[series.key] == key, table.c[TIME_INDEX] > bound)
    data_source_uid, dialect = resolve_markets_sql_target(context)
    execute_markets_write(
        compile_markets_statements(
            [statement],
            context=context,
            operation="delete",
            data_source_uid=data_source_uid,
            dialect=dialect,
        ),
        context=context,
    )
    return SeriesDeletion(key=key, after=bound, deleted=counted)


def _count_after(
    context: MarketsRepositoryContext, series: Series, *, key: str, after: dt.datetime
) -> int:
    table = series.table
    statement = select(func.count().label("row_count")).where(
        table.c[series.key] == key, table.c[TIME_INDEX] > after
    )
    rows = _select(context, statement, max_rows=1)
    return int(rows[0]["row_count"] or 0) if rows else 0


# Helpers -------------------------------------------------------------------------------


def _registry_row(context: MarketsRepositoryContext, series: Series, key: str) -> dict[str, Any]:
    registry = series.registry
    columns = [registry.uid, registry.managed_by]
    if registry is PortfolioTable:
        columns.append(registry.retired_at)
    statement = select(*columns).where(getattr(registry, series.registry_key) == key).limit(1)
    rows = _select(context, statement, max_rows=1)
    if not rows:
        what = "SignalMetadata row" if registry is SignalMetadataTable else "Portfolio"
        raise LookupError(f"No {what} has {series.registry_key} {key!r}.")
    return rows[0]


def _require_registered_assets(context: MarketsRepositoryContext, assets: set[str]) -> None:
    known: set[str] = set()
    ordered = sorted(assets)
    for start in range(0, len(ordered), READ_MAX_ROWS):
        batch = ordered[start : start + READ_MAX_ROWS]
        statement = select(AssetTable.unique_identifier.label("unique_identifier")).where(
            AssetTable.unique_identifier.in_(batch)
        )
        known.update(
            str(row["unique_identifier"])
            for row in _select(context, statement, max_rows=len(batch))
        )
    unknown = sorted(assets - known)
    if unknown:
        raise LookupError(f"Unknown asset unique identifiers: {unknown[:20]}.")


def _select(context: MarketsRepositoryContext, statement: Any, *, max_rows: int) -> list[dict]:
    result = execute_markets_operation(
        compile_markets_statement(
            statement, context=with_max_rows(context, max(max_rows, 1)), operation="select"
        ),
        context=context,
    )
    rows = result.get("rows") if isinstance(result, Mapping) else result
    return [dict(row) for row in rows or [] if isinstance(row, Mapping)]


def _time_filter(statement: Any, table: Any, *, start: Any, end: Any) -> Any:
    if start is not None:
        statement = statement.where(table.c[TIME_INDEX] >= _utc(_as_datetime(start)))
    if end is not None:
        statement = statement.where(table.c[TIME_INDEX] <= _utc(_as_datetime(end)))
    return statement


def _asset_filter(statement: Any, series: Series, assets: Sequence[str] | None) -> Any:
    if not assets:
        return statement
    if not series.asset:
        raise ValueError(f"{series.resource} has no asset column.")
    return statement.where(series.table.c[series.asset].in_([str(asset) for asset in assets]))


def _value_columns(series: Series, columns: Sequence[str] | None) -> list[str]:
    if columns is None:
        return series.value_columns
    unknown = sorted(set(columns) - set(series.value_columns))
    if unknown:
        raise ValueError(f"{series.resource} has no value columns {unknown}.")
    return [name for name in series.value_columns if name in set(columns)]


def _required_key(series: Series, key: Any) -> str:
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f"{series.resource} needs a {series.key} key; got {key!r}.")
    return key


def _required_keys(series: Series, keys: Sequence[str]) -> list[str]:
    if isinstance(keys, str):
        keys = [keys]
    unique = list(dict.fromkeys(_required_key(series, key) for key in keys))
    if not unique:
        raise ValueError(f"{series.resource} reads need at least one key.")
    if len(unique) > READ_MAX_ROWS:
        raise ValueError(f"{series.resource} reads take at most {READ_MAX_ROWS} keys.")
    return unique


def _typed_row(series: Series, row: Mapping[str, Any]) -> dict[str, Any]:
    typed: dict[str, Any] = {}
    for name, value in row.items():
        dtype = series.dtypes.get(name)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            typed[name] = None
        elif dtype == dc.TIMESTAMP_TZ:
            typed[name] = _utc(_as_datetime(value))
        elif dtype == dc.FLOAT64:
            typed[name] = float(value)
        elif dtype == dc.BOOL:
            typed[name] = bool(value)
        elif dtype == dc.STRING:
            typed[name] = str(value)
        else:
            typed[name] = value
    return typed


def _as_datetime(value: Any) -> dt.datetime:
    if isinstance(value, pd.Timestamp):
        timestamp = value
    elif isinstance(value, dt.datetime):
        return value
    else:
        timestamp = pd.Timestamp(value)
    return timestamp.to_pydatetime()


def _utc(value: dt.datetime) -> dt.datetime:
    """``value`` in UTC; a naive stored time is UTC already (SQLite stores it so)."""

    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _optional_time(value: Any) -> dt.datetime | None:
    return None if value in (None, "") else _utc(_as_datetime(value))


def _format_keys(keys: Sequence[tuple]) -> str:
    shown = [
        "("
        + ", ".join(
            part.isoformat() if isinstance(part, dt.datetime) else str(part) for part in key
        )
        + ")"
        for key in list(keys)[:5]
    ]
    more = f" and {len(keys) - 5} more" if len(keys) > 5 else ""
    return ", ".join(shown) + more


__all__ = [
    "PORTFOLIO_VALUES",
    "PORTFOLIO_WEIGHTS",
    "PUBLISH_MAX_ROWS",
    "READ_MAX_ROWS",
    "SERIES",
    "SIGNAL_WEIGHTS",
    "Series",
    "SeriesBounds",
    "SeriesDeletion",
    "SeriesPublication",
    "SeriesRows",
    "publish_series",
    "series_assets",
    "series_bounds",
    "series_delete_after",
    "series_last",
    "series_window",
]
