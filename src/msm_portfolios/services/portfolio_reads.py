"""Reusable read services for portfolio output tables.

ADR 0047: portfolio values, weights and signal weights live in any number of
instances of the ``PortfoliosTS``, ``PortfolioWeightsTS`` and ``SignalWeightsTS``
contracts. The reads here resolve each portfolio's instance from the Markets
catalog (``PortfolioDatasetAvailabilityTable``, and ``SignalMetadataTable``
for signals) and read it by MetaTable uid through ``TimeIndexTableRef``,
filtered by ``portfolio_identifier`` or ``signal_uid``. A portfolio with no
catalog row reads the Markets-owned core tables through compiled SQL exactly
as before. A request for several portfolios groups them by table uid, reads
each table once and returns one list of rows.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from sqlalchemy import and_, func, select

from msm.models import PortfolioDatasetAvailabilityTable, PortfolioTable, SignalMetadataTable
from msm.repositories.base import (
    MarketsOperationContext,
    compile_markets_statement,
    execute_markets_operation,
)
from msm_portfolios.time_index.portfolios.storage import PortfolioWeightsStorage, PortfoliosStorage
from msm_portfolios.time_index.signals.storage import SignalWeightsStorage

PortfolioReadExecutor = Callable[
    [Any],
    Mapping[str, Any] | list[Any] | None,
]
DatasetReader = Callable[[str], Any]
"""Return a reader for one TimeIndexMetaTable uid.

The reader exposes ``get_df_between_dates(...)`` and ``get_last_observation(...)``
as ``metatables.TimeIndexTableRef`` does. The default is
``TimeIndexTableRef.from_uid``; tests inject a fake.
"""

PORTFOLIO_VALUES_COLUMNS: tuple[str, ...] = (
    "time_index",
    "portfolio_identifier",
    "close",
    "return",
    "calculated_close",
    "close_time",
)
PORTFOLIO_WEIGHTS_COLUMNS: tuple[str, ...] = (
    "time_index",
    "portfolio_identifier",
    "asset_identifier",
    "weight",
    "weight_before",
    "price_current",
    "price_before",
    "volume_current",
    "volume_before",
)
SIGNAL_WEIGHTS_COLUMNS: tuple[str, ...] = (
    "time_index",
    "signal_uid",
    "asset_identifier",
    "signal_weight",
)


@dataclass(frozen=True)
class PortfolioDatasetTables:
    """The instance tables that hold one portfolio's datasets, as the catalog records them.

    A ``None`` table uid means the Markets-owned core table.
    """

    portfolio_uid: uuid.UUID
    portfolio_identifier: str
    signal_uid: str | None = None
    values_meta_table_uid: str | None = None
    weights_meta_table_uid: str | None = None
    signal_meta_table_uid: str | None = None


def default_dataset_reader(meta_table_uid: str) -> Any:
    """Return the read-only ``TimeIndexTableRef`` for one registered table uid."""

    from metatables import TimeIndexTableRef

    return TimeIndexTableRef.from_uid(str(meta_table_uid))


def resolve_portfolio_dataset_tables(
    portfolio_identifiers: str | Sequence[str],
    *,
    repository_context: MarketsOperationContext | None = None,
    executor: PortfolioReadExecutor | None = None,
) -> dict[str, PortfolioDatasetTables]:
    """Return, per portfolio identifier, the catalogued instance tables.

    One statement joins ``PortfolioTable`` to its catalog row and to its signal
    metadata. Identifiers that are not portfolios are absent from the result.
    The signal table is the catalog's ``signal_meta_table_uid`` when present,
    else ``SignalMetadata.meta_table_uid``, else the core table.
    """

    identifiers = _normalize_identifiers(
        portfolio_identifiers,
        field_name="portfolio_identifiers",
    )
    if not identifiers:
        return {}
    statement = (
        select(
            PortfolioTable.uid.label("portfolio_uid"),
            PortfolioTable.unique_identifier.label("portfolio_identifier"),
            PortfolioTable.signal_uid.label("signal_uid"),
            PortfolioDatasetAvailabilityTable.values_meta_table_uid.label("values_meta_table_uid"),
            PortfolioDatasetAvailabilityTable.weights_meta_table_uid.label(
                "weights_meta_table_uid"
            ),
            PortfolioDatasetAvailabilityTable.signal_meta_table_uid.label("signal_meta_table_uid"),
            SignalMetadataTable.meta_table_uid.label("signal_metadata_meta_table_uid"),
        )
        .select_from(PortfolioTable)
        .outerjoin(
            PortfolioDatasetAvailabilityTable,
            PortfolioDatasetAvailabilityTable.portfolio_uid == PortfolioTable.uid,
        )
        .outerjoin(
            SignalMetadataTable,
            SignalMetadataTable.signal_uid == PortfolioTable.signal_uid,
        )
        .where(PortfolioTable.unique_identifier.in_(identifiers))
    )
    rows = _execute_statement(
        repository_context=repository_context,
        statement=statement,
        executor=executor,
    )
    resolved: dict[str, PortfolioDatasetTables] = {}
    for row in rows:
        identifier = str(row["portfolio_identifier"])
        resolved[identifier] = PortfolioDatasetTables(
            portfolio_uid=uuid.UUID(str(row["portfolio_uid"])),
            portfolio_identifier=identifier,
            signal_uid=_string_or_none(row.get("signal_uid")),
            values_meta_table_uid=_string_or_none(row.get("values_meta_table_uid")),
            weights_meta_table_uid=_string_or_none(row.get("weights_meta_table_uid")),
            signal_meta_table_uid=(
                _string_or_none(row.get("signal_meta_table_uid"))
                or _string_or_none(row.get("signal_metadata_meta_table_uid"))
            ),
        )
    return resolved


def latest_portfolio_weights(
    portfolio_identifiers: str | Sequence[str],
    *,
    weights_date: dt.datetime | dt.date | str | None = None,
    as_of: bool = True,
    order: Literal["asc", "desc"] = "desc",
    repository_context: MarketsOperationContext | None = None,
    executor: PortfolioReadExecutor | None = None,
    dataset_reader: DatasetReader | None = None,
) -> list[dict[str, Any]]:
    """Return portfolio weight rows for each requested portfolio snapshot.

    ``portfolio_identifiers`` are ``PortfolioTable.unique_identifier`` values,
    which are also the storage-facing ``portfolio_identifier`` dimension of the
    ``PortfolioWeightsTS`` contract. When ``weights_date`` is provided and
    ``as_of=True``, each portfolio resolves to its latest snapshot at or before
    that timestamp. When ``as_of=False``, rows must match ``weights_date``
    exactly. With no ``weights_date``, the latest snapshot for each portfolio is
    returned, or the earliest with ``order="asc"``.

    Each portfolio's table comes from the Markets catalog; portfolios without a
    catalog row read the core ``PortfolioWeightsStorage`` table.
    """

    identifiers = _normalize_identifiers(
        portfolio_identifiers,
        field_name="portfolio_identifiers",
    )
    if not identifiers:
        return []
    if order not in ("asc", "desc"):
        raise ValueError("order must be 'asc' or 'desc'.")

    snapshot_time = _coerce_datetime(weights_date, field_name="weights_date")
    tables = resolve_portfolio_dataset_tables(
        identifiers,
        repository_context=repository_context,
        executor=executor,
    )
    rows: list[dict[str, Any]] = []
    for meta_table_uid, group in _group_by_table(
        identifiers, tables, attribute="weights_meta_table_uid"
    ).items():
        if meta_table_uid is None:
            rows.extend(
                _execute_statement(
                    repository_context=repository_context,
                    statement=_core_weights_statement(
                        group,
                        snapshot_time=snapshot_time,
                        as_of=as_of,
                        order=order,
                    ),
                    executor=executor,
                )
            )
            continue
        reader = (dataset_reader or default_dataset_reader)(meta_table_uid)
        rows.extend(
            _dataset_weight_rows(
                reader,
                group,
                tables=tables,
                snapshot_time=snapshot_time,
                as_of=as_of,
                order=order,
            )
        )
    rows.sort(
        key=lambda row: (
            str(row.get("portfolio_identifier", "")),
            _sort_time(row.get("time_index")),
            str(row.get("asset_identifier", "")),
        )
    )
    return rows


def portfolio_values(
    portfolio_identifiers: str | Sequence[str],
    *,
    start: dt.datetime | dt.date | str | None = None,
    end: dt.datetime | dt.date | str | None = None,
    latest_only: bool = False,
    limit: int | None = None,
    repository_context: MarketsOperationContext | None = None,
    executor: PortfolioReadExecutor | None = None,
    dataset_reader: DatasetReader | None = None,
) -> list[dict[str, Any]]:
    """Return portfolio value rows for the requested portfolios.

    Portfolios are grouped by the ``PortfoliosTS`` instance the catalog records
    for them; each instance is read once by uid through ``TimeIndexTableRef``
    with a ``portfolio_identifier`` filter, and portfolios without a catalog row
    read the core ``PortfoliosStorage`` table. The result is one list ordered by
    portfolio identifier and time index.
    """

    identifiers = _normalize_identifiers(
        portfolio_identifiers,
        field_name="portfolio_identifiers",
    )
    if not identifiers:
        return []

    start_time = _coerce_datetime(start, field_name="start")
    end_time = _coerce_datetime(end, field_name="end")
    if start_time is not None and end_time is not None and start_time > end_time:
        raise ValueError("start must be before or equal to end.")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be a positive integer.")

    tables = resolve_portfolio_dataset_tables(
        identifiers,
        repository_context=repository_context,
        executor=executor,
    )
    rows: list[dict[str, Any]] = []
    for meta_table_uid, group in _group_by_table(
        identifiers, tables, attribute="values_meta_table_uid"
    ).items():
        if meta_table_uid is None:
            rows.extend(
                _execute_statement(
                    repository_context=repository_context,
                    statement=_core_values_statement(
                        group,
                        start_time=start_time,
                        end_time=end_time,
                        latest_only=latest_only,
                        limit=limit,
                    ),
                    executor=executor,
                )
            )
            continue
        reader = (dataset_reader or default_dataset_reader)(meta_table_uid)
        rows.extend(
            _dataset_value_rows(
                reader,
                group,
                tables=tables,
                start_time=start_time,
                end_time=end_time,
                latest_only=latest_only,
            )
        )
    rows.sort(
        key=lambda row: (
            str(row.get("portfolio_identifier", "")),
            _sort_time(row.get("time_index")),
        )
    )
    if limit is not None:
        rows = rows[:limit]
    return rows


def signal_weights(
    signal_uid: str,
    *,
    start: dt.datetime | dt.date | str | None = None,
    end: dt.datetime | dt.date | str | None = None,
    order: Literal["asc", "desc"] = "desc",
    limit: int | None = None,
    meta_table_uid: str | None = None,
    repository_context: MarketsOperationContext | None = None,
    executor: PortfolioReadExecutor | None = None,
    dataset_reader: DatasetReader | None = None,
) -> list[dict[str, Any]]:
    """Return raw signal weight rows for one signal.

    The ``SignalWeightsTS`` instance is ``meta_table_uid`` when the caller
    resolved it from the portfolio's catalog row, else
    ``SignalMetadata.meta_table_uid`` for the signal, else the core
    ``SignalWeightsStorage`` table.
    """

    signal = str(signal_uid).strip()
    if not signal:
        raise ValueError("signal_uid must be a non-empty string.")
    if order not in ("asc", "desc"):
        raise ValueError("order must be 'asc' or 'desc'.")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be a positive integer.")
    start_time = _coerce_datetime(start, field_name="start")
    end_time = _coerce_datetime(end, field_name="end")
    if start_time is not None and end_time is not None and start_time > end_time:
        raise ValueError("start must be before or equal to end.")

    table_uid = _string_or_none(meta_table_uid)
    if table_uid is None:
        metadata_rows = _execute_statement(
            repository_context=repository_context,
            statement=select(SignalMetadataTable.meta_table_uid.label("meta_table_uid"))
            .where(SignalMetadataTable.signal_uid == signal)
            .limit(1),
            executor=executor,
        )
        if metadata_rows:
            table_uid = _string_or_none(metadata_rows[0].get("meta_table_uid"))

    if table_uid is None:
        statement = select(SignalWeightsStorage).where(SignalWeightsStorage.signal_uid == signal)
        statement = _apply_time_range(
            statement, column=SignalWeightsStorage.time_index, start=start_time, end=end_time
        )
        statement = statement.order_by(
            SignalWeightsStorage.time_index.asc()
            if order == "asc"
            else SignalWeightsStorage.time_index.desc(),
            SignalWeightsStorage.asset_identifier.asc(),
        )
        if limit is not None:
            statement = statement.limit(limit)
        return _execute_statement(
            repository_context=repository_context,
            statement=statement,
            executor=executor,
        )

    reader = (dataset_reader or default_dataset_reader)(table_uid)
    frame = reader.get_df_between_dates(
        start_date=start_time,
        end_date=end_time,
        dimension_filters={"signal_uid": [signal]},
        columns=list(SIGNAL_WEIGHTS_COLUMNS),
    )
    rows = _frame_rows(frame, columns=SIGNAL_WEIGHTS_COLUMNS)
    rows.sort(
        key=lambda row: (_sort_time(row.get("time_index")), str(row.get("asset_identifier", ""))),
        reverse=order == "desc",
    )
    if limit is not None:
        rows = rows[:limit]
    return rows


def _group_by_table(
    identifiers: Sequence[str],
    tables: Mapping[str, PortfolioDatasetTables],
    *,
    attribute: str,
) -> dict[str | None, list[str]]:
    groups: dict[str | None, list[str]] = {}
    for identifier in identifiers:
        resolved = tables.get(identifier)
        meta_table_uid = getattr(resolved, attribute, None) if resolved is not None else None
        groups.setdefault(meta_table_uid, []).append(identifier)
    return groups


def _dataset_value_rows(
    reader: Any,
    identifiers: Sequence[str],
    *,
    tables: Mapping[str, PortfolioDatasetTables],
    start_time: dt.datetime | None,
    end_time: dt.datetime | None,
    latest_only: bool,
) -> list[dict[str, Any]]:
    frame = reader.get_df_between_dates(
        start_date=start_time,
        end_date=end_time,
        dimension_filters={"portfolio_identifier": list(identifiers)},
        columns=list(PORTFOLIO_VALUES_COLUMNS),
    )
    rows = _frame_rows(frame, columns=PORTFOLIO_VALUES_COLUMNS)
    if latest_only:
        rows = _latest_per_portfolio(rows)
    return _with_portfolio_uid(rows, tables)


def _dataset_weight_rows(
    reader: Any,
    identifiers: Sequence[str],
    *,
    tables: Mapping[str, PortfolioDatasetTables],
    snapshot_time: dt.datetime | None,
    as_of: bool,
    order: str,
) -> list[dict[str, Any]]:
    dimension_filters = {"portfolio_identifier": list(identifiers)}
    columns = list(PORTFOLIO_WEIGHTS_COLUMNS)
    if snapshot_time is not None and not as_of:
        frame = reader.get_df_between_dates(
            start_date=snapshot_time,
            end_date=snapshot_time,
            dimension_filters=dimension_filters,
            columns=columns,
        )
        return _with_portfolio_uid(_frame_rows(frame, columns=PORTFOLIO_WEIGHTS_COLUMNS), tables)

    if snapshot_time is None and order == "desc":
        # The last observation names each portfolio's latest snapshot time; the
        # snapshot rows are then read in one bounded request.
        last = _frame_rows(
            reader.get_last_observation(dimension_filters=dimension_filters),
            columns=PORTFOLIO_WEIGHTS_COLUMNS,
        )
        snapshot_times = _max_time_per_portfolio(last)
        covered = [item for item in identifiers if item in snapshot_times]
        rows: list[dict[str, Any]] = []
        if covered:
            times = [snapshot_times[item] for item in covered]
            frame = reader.get_df_between_dates(
                start_date=min(times),
                end_date=max(times),
                dimension_filters={"portfolio_identifier": covered},
                columns=columns,
            )
            rows = [
                row
                for row in _frame_rows(frame, columns=PORTFOLIO_WEIGHTS_COLUMNS)
                if _sort_time(row.get("time_index"))
                == _sort_time(snapshot_times.get(str(row.get("portfolio_identifier"))))
            ]
        remaining = [item for item in identifiers if item not in snapshot_times]
        if remaining:
            frame = reader.get_df_between_dates(
                dimension_filters={"portfolio_identifier": remaining},
                columns=columns,
            )
            rows.extend(_latest_per_portfolio(_frame_rows(frame, columns=PORTFOLIO_WEIGHTS_COLUMNS)))
        return _with_portfolio_uid(rows, tables)

    frame = reader.get_df_between_dates(
        end_date=snapshot_time if order == "desc" else None,
        dimension_filters=dimension_filters,
        columns=columns,
    )
    rows = _frame_rows(frame, columns=PORTFOLIO_WEIGHTS_COLUMNS)
    rows = _latest_per_portfolio(rows) if order == "desc" else _earliest_per_portfolio(rows)
    return _with_portfolio_uid(rows, tables)


def _core_weights_statement(
    identifiers: Sequence[str],
    *,
    snapshot_time: dt.datetime | None,
    as_of: bool,
    order: str,
):
    statement = _portfolio_weights_select()
    statement = statement.where(PortfolioWeightsStorage.portfolio_identifier.in_(list(identifiers)))

    if snapshot_time is not None and not as_of:
        statement = statement.where(PortfolioWeightsStorage.time_index == snapshot_time)
    else:
        boundary = (
            func.max(PortfolioWeightsStorage.time_index)
            if order == "desc"
            else func.min(PortfolioWeightsStorage.time_index)
        )
        snapshot_times = (
            select(
                PortfolioWeightsStorage.portfolio_identifier.label("portfolio_identifier"),
                boundary.label("time_index"),
            )
            .where(PortfolioWeightsStorage.portfolio_identifier.in_(list(identifiers)))
            .group_by(PortfolioWeightsStorage.portfolio_identifier)
        )
        if snapshot_time is not None:
            snapshot_times = snapshot_times.where(
                PortfolioWeightsStorage.time_index <= snapshot_time
                if order == "desc"
                else PortfolioWeightsStorage.time_index >= snapshot_time
            )

        snapshot_subquery = snapshot_times.subquery()
        statement = statement.join(
            snapshot_subquery,
            and_(
                PortfolioWeightsStorage.portfolio_identifier
                == snapshot_subquery.c.portfolio_identifier,
                PortfolioWeightsStorage.time_index == snapshot_subquery.c.time_index,
            ),
        )

    return statement.order_by(
        PortfolioWeightsStorage.portfolio_identifier.asc(),
        PortfolioWeightsStorage.time_index.asc(),
        PortfolioWeightsStorage.asset_identifier.asc(),
    )


def _core_values_statement(
    identifiers: Sequence[str],
    *,
    start_time: dt.datetime | None,
    end_time: dt.datetime | None,
    latest_only: bool,
    limit: int | None,
):
    statement = _portfolio_values_select()
    statement = statement.where(PortfoliosStorage.portfolio_identifier.in_(list(identifiers)))
    statement = _apply_time_range(
        statement, column=PortfoliosStorage.time_index, start=start_time, end=end_time
    )

    if latest_only:
        latest_times = (
            select(
                PortfoliosStorage.portfolio_identifier.label("portfolio_identifier"),
                func.max(PortfoliosStorage.time_index).label("time_index"),
            )
            .where(PortfoliosStorage.portfolio_identifier.in_(list(identifiers)))
            .group_by(PortfoliosStorage.portfolio_identifier)
        )
        latest_times = _apply_time_range(
            latest_times,
            column=PortfoliosStorage.time_index,
            start=start_time,
            end=end_time,
        )
        latest_times_subquery = latest_times.subquery()
        statement = statement.join(
            latest_times_subquery,
            and_(
                PortfoliosStorage.portfolio_identifier
                == latest_times_subquery.c.portfolio_identifier,
                PortfoliosStorage.time_index == latest_times_subquery.c.time_index,
            ),
        )

    statement = statement.order_by(
        PortfoliosStorage.portfolio_identifier.asc(),
        PortfoliosStorage.time_index.asc(),
    )
    if limit is not None:
        statement = statement.limit(limit)
    return statement


def _portfolio_weights_select():
    return (
        select(
            PortfolioTable.uid.label("portfolio_uid"),
            PortfolioWeightsStorage.portfolio_identifier.label("portfolio_identifier"),
            PortfolioWeightsStorage.time_index.label("time_index"),
            PortfolioWeightsStorage.asset_identifier.label("asset_identifier"),
            PortfolioWeightsStorage.weight.label("weight"),
            PortfolioWeightsStorage.weight_before.label("weight_before"),
            PortfolioWeightsStorage.price_current.label("price_current"),
            PortfolioWeightsStorage.price_before.label("price_before"),
            PortfolioWeightsStorage.volume_current.label("volume_current"),
            PortfolioWeightsStorage.volume_before.label("volume_before"),
        )
        .select_from(PortfolioWeightsStorage)
        .join(
            PortfolioTable,
            PortfolioTable.unique_identifier == PortfolioWeightsStorage.portfolio_identifier,
        )
    )


def _portfolio_values_select():
    return (
        select(
            PortfolioTable.uid.label("portfolio_uid"),
            PortfoliosStorage.portfolio_identifier.label("portfolio_identifier"),
            PortfoliosStorage.time_index.label("time_index"),
            PortfoliosStorage.close.label("close"),
            PortfoliosStorage.return_.label("return"),
            PortfoliosStorage.calculated_close.label("calculated_close"),
            PortfoliosStorage.close_time.label("close_time"),
        )
        .select_from(PortfoliosStorage)
        .join(
            PortfolioTable,
            PortfolioTable.unique_identifier == PortfoliosStorage.portfolio_identifier,
        )
    )


def _frame_rows(frame: Any, *, columns: Sequence[str]) -> list[dict[str, Any]]:
    """Flatten a ``TimeIndexTableRef`` frame into contract-column row dictionaries."""

    if frame is None:
        return []
    if not isinstance(frame, pd.DataFrame):
        return [dict(row) for row in frame if isinstance(row, Mapping)]
    if frame.empty:
        return []
    flat = frame.reset_index() if any(name is not None for name in frame.index.names) else frame
    flat = flat.loc[:, [name for name in columns if name in flat.columns]]
    rows: list[dict[str, Any]] = []
    for record in flat.to_dict("records"):
        row: dict[str, Any] = {}
        for key, value in record.items():
            row[str(key)] = _python_value(value)
        rows.append(row)
    return rows


def _python_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.to_pydatetime()
    if value is pd.NaT:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (ValueError, TypeError):
            return value
    return value


def _with_portfolio_uid(
    rows: Iterable[Mapping[str, Any]],
    tables: Mapping[str, PortfolioDatasetTables],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        resolved = tables.get(str(payload.get("portfolio_identifier")))
        payload.setdefault("portfolio_uid", resolved.portfolio_uid if resolved else None)
        result.append(payload)
    return result


def _max_time_per_portfolio(rows: Iterable[Mapping[str, Any]]) -> dict[str, dt.datetime]:
    times: dict[str, dt.datetime] = {}
    for row in rows:
        identifier = str(row.get("portfolio_identifier"))
        moment = row.get("time_index")
        if moment is None:
            continue
        if identifier not in times or _sort_time(moment) > _sort_time(times[identifier]):
            times[identifier] = moment
    return times


def _latest_per_portfolio(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    times = _max_time_per_portfolio(rows)
    return [
        row
        for row in rows
        if _sort_time(row.get("time_index"))
        == _sort_time(times.get(str(row.get("portfolio_identifier"))))
    ]


def _earliest_per_portfolio(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    times: dict[str, dt.datetime] = {}
    for row in rows:
        identifier = str(row.get("portfolio_identifier"))
        moment = row.get("time_index")
        if moment is None:
            continue
        if identifier not in times or _sort_time(moment) < _sort_time(times[identifier]):
            times[identifier] = moment
    return [
        row
        for row in rows
        if _sort_time(row.get("time_index"))
        == _sort_time(times.get(str(row.get("portfolio_identifier"))))
    ]


def _sort_time(value: Any) -> float:
    if value is None:
        return float("-inf")
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value.timestamp()
    if isinstance(value, str):
        return _sort_time(_coerce_datetime(value, field_name="time_index"))
    return float(value)


def _execute_statement(
    *,
    repository_context: MarketsOperationContext | None,
    statement: Any,
    executor: PortfolioReadExecutor | None,
) -> list[dict[str, Any]]:
    if executor is not None:
        return _operation_result_rows(executor(statement))
    if repository_context is None:
        raise ValueError("repository_context is required when executor is not provided.")

    return _operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                statement,
                context=repository_context,
                operation="select",
            ),
            context=repository_context,
        )
    )


def _apply_time_range(
    statement: Any, *, column: Any, start: dt.datetime | None, end: dt.datetime | None
):
    if start is not None:
        statement = statement.where(column >= start)
    if end is not None:
        statement = statement.where(column <= end)
    return statement


def _normalize_identifiers(
    identifiers: str | Sequence[str],
    *,
    field_name: str,
) -> tuple[str, ...]:
    raw_values: Sequence[str]
    if isinstance(identifiers, str):
        raw_values = [identifiers]
    else:
        raw_values = identifiers

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        value = str(raw_value).strip()
        if not value:
            raise ValueError(f"{field_name} entries must be non-empty strings.")
        if value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return tuple(normalized)


def _coerce_datetime(
    value: dt.datetime | dt.date | str | None,
    *,
    field_name: str,
) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"{field_name} must be a datetime, date, or ISO datetime string."
            ) from exc
    raise TypeError(f"{field_name} must be a datetime, date, or ISO datetime string.")


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [dict(row) for row in result if isinstance(row, Mapping)]
    if not isinstance(result, Mapping):
        return []
    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]
    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            return [dict(value)]
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


__all__ = [
    "DatasetReader",
    "PORTFOLIO_VALUES_COLUMNS",
    "PORTFOLIO_WEIGHTS_COLUMNS",
    "PortfolioDatasetTables",
    "PortfolioReadExecutor",
    "SIGNAL_WEIGHTS_COLUMNS",
    "default_dataset_reader",
    "latest_portfolio_weights",
    "portfolio_values",
    "resolve_portfolio_dataset_tables",
    "signal_weights",
]
