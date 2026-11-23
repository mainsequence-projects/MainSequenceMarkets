"""Write execution rows in one transaction, without an updater run (ADR 0064, issue 131).

An application creates a batch's orders with ``OrderManager.create_batch`` (one Markets
call: the ``OrderManager`` row and the ``Order`` rows). It then writes what happens to
them with :func:`write_execution`: each order's state rows (``OrdersTS``), its events
(``OrderEventsTS``) and its trades (``TradesTS``), written under the order, in one
MetaTables statement transaction on its own runtime. Trades of an order written by an
earlier call go in ``trades``, with their ``order_uid``.

The call writes every row it may and answers what it did not (issue 128): a row that
fails validation, or whose key repeats in the call, is left out and listed in
``failed``. When the database refuses the transaction (an order that does not exist, an
unknown asset), nothing in it was written; each order is then written in its own
transaction, so only the refused orders stay out.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, Float, String, Uuid
from sqlalchemy.types import JSON

from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage

ORDER_STATES = "order_states"
ORDER_EVENTS = "order_events"
TRADES = "trades"

MAX_TRANSACTION_STATEMENTS = 32
"""Statements MetaTables runs in one transaction (MetaTables ADR 0026)."""

MAX_REQUEST_BYTES = 12_100_000
"""Bytes of one request MetaTables accepts."""

_CONFLICT_MARKERS = ("foreign key", "violates", "referenced", "restrict", "constraint")


class ExecutionOrder(BaseModel):
    """The order rows are written under: an ``Order`` row, or its uid, account and asset."""

    model_config = ConfigDict(extra="ignore", from_attributes=True, frozen=True)

    uid: uuid.UUID
    account_identifier: str = Field(min_length=1)
    asset_identifier: str = Field(min_length=1)


class OrderExecution(BaseModel):
    """One order with the rows written under it.

    ``states`` are ``OrdersTS`` rows, ``events`` ``OrderEventsTS`` rows and ``trades``
    ``TradesTS`` rows. Each takes the order's uid; a trade also its account and asset. A
    row may leave them out, and one that states a different value is refused.
    """

    model_config = ConfigDict(extra="forbid")

    order: ExecutionOrder
    states: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionRefusal(BaseModel):
    """A row the call did not write: its table, its key, and why."""

    table: str
    key: dict[str, Any]
    detail: str


class ExecutionWrite(BaseModel):
    """What :func:`write_execution` wrote, per table, and what it did not."""

    order_states: list[dict[str, Any]] = Field(default_factory=list)
    order_events: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    failed: list[ExecutionRefusal] = Field(default_factory=list)


@dataclass
class _Group:
    """Rows written together: one order's, or one trade written on its own."""

    order: ExecutionOrder | None
    rows: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {ORDER_STATES: [], ORDER_EVENTS: [], TRADES: []}
    )

    def is_empty(self) -> bool:
        return not any(self.rows.values())


def write_execution(
    orders: Sequence[OrderExecution | Mapping[str, Any]] = (),
    *,
    trades: Sequence[Mapping[str, Any]] = (),
    orders_table: type[OrdersStorage] = OrdersStorage,
    order_events_table: type[OrderEventsStorage] = OrderEventsStorage,
    trades_table: type[TradesStorage] = TradesStorage,
) -> ExecutionWrite:
    """Write ``orders`` with their state rows, events and trades, and ``trades``, in one
    transaction; answer the rows written per table and the rows refused.

    The tables are the application's instances of ``OrdersTS``, ``OrderEventsTS`` and
    ``TradesTS`` (``msm.storage_instances``), on its own runtime; the defaults are the
    Markets tables. Rows are upserted on each table's key. A call that does not fit one
    MetaTables transaction (32 statements, 12,100,000 bytes) raises ``ValueError`` before
    anything is sent.
    """

    tables = {
        ORDER_STATES: orders_table,
        ORDER_EVENTS: order_events_table,
        TRADES: trades_table,
    }
    groups, failed = _validated_groups(orders, trades, tables=tables)
    written = _write_groups(groups, tables=tables, failed=failed)
    return ExecutionWrite(
        order_states=written[ORDER_STATES],
        order_events=written[ORDER_EVENTS],
        trades=written[TRADES],
        failed=failed,
    )


# Validation ------------------------------------------------------------------------------


def _validated_groups(
    orders: Sequence[OrderExecution | Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    *,
    tables: Mapping[str, type[Any]],
) -> tuple[list[_Group], list[ExecutionRefusal]]:
    failed: list[ExecutionRefusal] = []
    seen: dict[str, set[tuple[Any, ...]]] = {name: set() for name in tables}
    groups: list[_Group] = []

    for position, entry in enumerate(orders):
        try:
            execution = (
                entry if isinstance(entry, OrderExecution) else OrderExecution.model_validate(entry)
            )
        except ValueError as exc:
            failed.append(
                ExecutionRefusal(
                    table="order", key=_entry_key(entry, position), detail=_detail(exc)
                )
            )
            continue
        group = _Group(order=execution.order)
        inherited = {
            ORDER_STATES: {"order_uid": execution.order.uid},
            ORDER_EVENTS: {"order_uid": execution.order.uid},
            TRADES: {
                "order_uid": execution.order.uid,
                "account_identifier": execution.order.account_identifier,
                "asset_identifier": execution.order.asset_identifier,
            },
        }
        for name, rows in (
            (ORDER_STATES, execution.states),
            (ORDER_EVENTS, execution.events),
            (TRADES, execution.trades),
        ):
            for row in rows:
                normalized = _accepted_row(
                    name, row, tables[name], seen=seen[name], failed=failed, inherited=inherited[name]
                )
                if normalized is not None:
                    group.rows[name].append(normalized)
        if not group.is_empty():
            groups.append(group)

    for row in trades:
        normalized = _accepted_row(TRADES, row, tables[TRADES], seen=seen[TRADES], failed=failed)
        if normalized is not None:
            group = _Group(order=None)
            group.rows[TRADES].append(normalized)
            groups.append(group)
    return groups, failed


def _accepted_row(
    name: str,
    row: Mapping[str, Any],
    table: type[Any],
    *,
    seen: set[tuple[Any, ...]],
    failed: list[ExecutionRefusal],
    inherited: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    key_columns = list(table.__index_names__)
    try:
        normalized = normalize_execution_row(table, row, inherited=inherited)
    except ValueError as exc:
        failed.append(ExecutionRefusal(table=name, key=_row_key(row, key_columns), detail=str(exc)))
        return None
    key = tuple(normalized[column] for column in key_columns)
    if key in seen:
        failed.append(
            ExecutionRefusal(
                table=name,
                key=_row_key(normalized, key_columns),
                detail=f"Its key {key_columns} repeats an earlier row of this call.",
            )
        )
        return None
    seen.add(key)
    return normalized


def normalize_execution_row(
    table: type[Any],
    row: Mapping[str, Any],
    *,
    inherited: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One row of an execution table, every column typed; ``ValueError`` names the problem.

    ``inherited`` are the values a row written under an order takes from it: the row may
    leave them out, and a row that states another value is refused.
    """

    columns = {column.name: column for column in table.__table__.columns}
    unknown = sorted(set(row) - set(columns))
    if unknown:
        raise ValueError(f"Unknown columns: {', '.join(unknown)}.")
    values = dict(row)
    for name, value in (inherited or {}).items():
        stated = values.get(name)
        if stated is not None and _typed(columns[name], stated, name) != value:
            raise ValueError(f"{name} {stated!r} is not its order's {value!r}.")
        values[name] = value
    normalized: dict[str, Any] = {}
    for name, column in columns.items():
        value = _typed(column, values.get(name), name)
        if value is None and not column.nullable:
            raise ValueError(f"{name} is required.")
        normalized[name] = value
    return normalized


def _typed(column: Any, value: Any, name: str) -> Any:
    if _missing(value):
        return None
    column_type = column.type
    if isinstance(column_type, DateTime):
        return _timestamp(value, name)
    try:
        if isinstance(column_type, Uuid):
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if isinstance(column_type, BigInteger):
            if isinstance(value, bool) or float(value) != int(float(value)):
                raise ValueError
            return int(float(value))
        if isinstance(column_type, Float):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError
            return number
        if isinstance(column_type, String):
            return str(value)
        if isinstance(column_type, JSON):
            if not isinstance(value, (dict, list)):
                raise ValueError
            return value
    except (TypeError, ValueError):
        raise ValueError(f"{name} {value!r} is not a valid {column_type}.") from None
    raise ValueError(f"{name} has an unsupported type {column_type}.")


def _timestamp(value: Any, name: str) -> dt.datetime:
    original = value
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{name} {original!r} is not a timestamp.") from None
    to_pydatetime = getattr(value, "to_pydatetime", None)
    if to_pydatetime is not None:
        value = to_pydatetime()
    if not isinstance(value, dt.datetime):
        raise ValueError(f"{name} {original!r} is not a timestamp.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} {value.isoformat()} has no timezone.")
    return value.astimezone(dt.UTC)


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return type(value).__name__ in {"NaTType", "NAType"}


def _row_key(row: Mapping[str, Any], key_columns: Sequence[str]) -> dict[str, Any]:
    return {column: _jsonable(row.get(column)) for column in key_columns}


def _entry_key(entry: Any, position: int) -> dict[str, Any]:
    order = entry.get("order") if isinstance(entry, Mapping) else None
    uid = order.get("uid") if isinstance(order, Mapping) else getattr(order, "uid", None)
    return {"uid": _jsonable(uid)} if uid is not None else {"position": position}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (uuid.UUID, dt.datetime)):
        return value.isoformat() if isinstance(value, dt.datetime) else str(value)
    return value


def _detail(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in errors()
        )
    return str(exc)


# The write -------------------------------------------------------------------------------


def _write_groups(
    groups: list[_Group],
    *,
    tables: Mapping[str, type[Any]],
    failed: list[ExecutionRefusal],
) -> dict[str, list[dict[str, Any]]]:
    written: dict[str, list[dict[str, Any]]] = {name: [] for name in tables}
    if not groups:
        return written
    context = _context(tables)
    _check_size(groups, tables=tables)
    try:
        _write(context, groups, tables=tables)
    except Exception as exc:
        if not _is_refusal(exc):
            raise
        if len(groups) == 1:
            _refuse(groups[0], str(exc), tables=tables, failed=failed)
            return written
        # Nothing was written. Each order on its own: only the refused ones stay out.
        for group in groups:
            try:
                _write(context, [group], tables=tables)
            except Exception as group_exc:
                if not _is_refusal(group_exc):
                    raise
                _refuse(group, str(group_exc), tables=tables, failed=failed)
                continue
            _collect(group, written)
        return written
    for group in groups:
        _collect(group, written)
    return written


def _write(context: Any, groups: Sequence[_Group], *, tables: Mapping[str, type[Any]]) -> None:
    from msm.repositories.execution import write_execution_rows

    rows = {name: [row for group in groups for row in group.rows[name]] for name in tables}
    write_execution_rows(
        context,
        [(tables[name], rows[name]) for name in (ORDER_STATES, ORDER_EVENTS, TRADES)],
    )


def _check_size(groups: Sequence[_Group], *, tables: Mapping[str, type[Any]]) -> None:
    from msm.repositories.execution import execution_rows_per_statement

    statements = 0
    for name, table in tables.items():
        count = sum(len(group.rows[name]) for group in groups)
        if count:
            statements += math.ceil(count / execution_rows_per_statement(table))
    if statements > MAX_TRANSACTION_STATEMENTS:
        raise ValueError(
            f"The call needs {statements} statements; one MetaTables transaction runs at most "
            f"{MAX_TRANSACTION_STATEMENTS}. Nothing was written."
        )
    size = len(
        json.dumps(
            [group.rows for group in groups], default=_jsonable, separators=(",", ":")
        ).encode()
    )
    if size > MAX_REQUEST_BYTES:
        raise ValueError(
            f"The call's rows take about {size} bytes; one MetaTables request takes at most "
            f"{MAX_REQUEST_BYTES}. Nothing was written."
        )


def _context(tables: Mapping[str, type[Any]]) -> Any:
    from msm.bootstrap import resolve_runtime

    return resolve_runtime(models=list(tables.values()), row_model_name="write_execution").context


def _is_refusal(exc: Exception) -> bool:
    if isinstance(exc, PermissionError):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _CONFLICT_MARKERS)


def _refuse(
    group: _Group,
    detail: str,
    *,
    tables: Mapping[str, type[Any]],
    failed: list[ExecutionRefusal],
) -> None:
    for name, rows in group.rows.items():
        key_columns = list(tables[name].__index_names__)
        for row in rows:
            failed.append(ExecutionRefusal(table=name, key=_row_key(row, key_columns), detail=detail))


def _collect(group: _Group, written: dict[str, list[dict[str, Any]]]) -> None:
    for name, rows in group.rows.items():
        written[name].extend(rows)


__all__ = [
    "ExecutionOrder",
    "ExecutionRefusal",
    "ExecutionWrite",
    "MAX_REQUEST_BYTES",
    "MAX_TRANSACTION_STATEMENTS",
    "OrderExecution",
    "normalize_execution_row",
    "write_execution",
]
