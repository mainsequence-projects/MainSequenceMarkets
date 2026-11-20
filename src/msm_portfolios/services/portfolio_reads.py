"""Reusable read services for the published portfolio series (ADR 0060).

Portfolio values, portfolio weights and signal weights are stored once, in the
Markets-owned ``PortfoliosTS``, ``PortfolioWeightsTS`` and ``SignalWeightsTS``
tables. The reads here run compiled SQL on those tables only; Markets reads no
other application's table.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

import pandas as pd
from sqlalchemy import and_, func, select

from msm.models import PortfolioTable
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


def latest_portfolio_weights(
    portfolio_identifiers: str | Sequence[str],
    *,
    weights_date: dt.datetime | dt.date | str | None = None,
    as_of: bool = True,
    order: Literal["asc", "desc"] = "desc",
    repository_context: MarketsOperationContext | None = None,
    executor: PortfolioReadExecutor | None = None,
) -> list[dict[str, Any]]:
    """Return portfolio weight rows for each requested portfolio snapshot.

    ``portfolio_identifiers`` are ``PortfolioTable.unique_identifier`` values,
    which are also the storage-facing ``portfolio_identifier`` dimension of the
    ``PortfolioWeightsTS`` contract. When ``weights_date`` is provided and
    ``as_of=True``, each portfolio resolves to its latest snapshot at or before
    that timestamp. When ``as_of=False``, rows must match ``weights_date``
    exactly. With no ``weights_date``, the latest snapshot for each portfolio is
    returned, or the earliest with ``order="asc"``.
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
    rows = _execute_statement(
        repository_context=repository_context,
        statement=_core_weights_statement(
            identifiers,
            snapshot_time=snapshot_time,
            as_of=as_of,
            order=order,
        ),
        executor=executor,
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
) -> list[dict[str, Any]]:
    """Return portfolio value rows for the requested portfolios.

    The result is one list ordered by portfolio identifier and time index.
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

    return _execute_statement(
        repository_context=repository_context,
        statement=_core_values_statement(
            identifiers,
            start_time=start_time,
            end_time=end_time,
            latest_only=latest_only,
            limit=limit,
        ),
        executor=executor,
    )


def signal_weights(
    signal_uid: str,
    *,
    start: dt.datetime | dt.date | str | None = None,
    end: dt.datetime | dt.date | str | None = None,
    order: Literal["asc", "desc"] = "desc",
    limit: int | None = None,
    repository_context: MarketsOperationContext | None = None,
    executor: PortfolioReadExecutor | None = None,
) -> list[dict[str, Any]]:
    """Return raw signal weight rows for one signal, newest first by default."""

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
    "PORTFOLIO_VALUES_COLUMNS",
    "PORTFOLIO_WEIGHTS_COLUMNS",
    "PortfolioReadExecutor",
    "SIGNAL_WEIGHTS_COLUMNS",
    "latest_portfolio_weights",
    "portfolio_values",
    "signal_weights",
]
