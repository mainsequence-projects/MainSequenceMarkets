from __future__ import annotations

import operator
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    Column,
    Integer,
    String,
    and_,
    bindparam,
    case,
    cast,
    column as sql_column,
    delete,
    exists,
    func,
    insert,
    inspect,
    literal,
    literal_column,
    or_,
    select,
    union_all,
    update,
    values as values_clause,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from metatables import (
    MetaTableCompiledSQLDialect,
    MetaTableCompiledSQLOperation,
    MetaTableTransactionGuardError,
)
from metatables.compiled_sql.v1 import GuardedStatement

from msm.base import MarketsBase

from .base import (
    MarketsCompiledWrite,
    MarketsOperationContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
    values_parameter,
)

_MISSING = object()


def mirror_renamed_columns(
    model: type[MarketsBase],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    """Return ``values`` with each renamed UID column also written under its pre-3.0 name.

    ms-markets 3.x keeps each pre-3.0 ``*_data_node_uid`` column next to the column
    that renamed it (``__renamed_columns__``, ADR 0048) and writes both, so readers
    and writers that still use the pre-3.0 column stay consistent. A value given
    under either name fills both columns.
    """

    payload = dict(values)
    for current, previous in getattr(model, "__renamed_columns__", {}).items():
        if current in payload and previous in payload:
            if not _same_value(payload[current], payload[previous]):
                raise ValueError(
                    f"{model.__name__} received different values for {current} and its "
                    f"pre-3.0 name {previous}."
                )
        elif current in payload:
            payload[previous] = payload[current]
        elif previous in payload:
            payload[current] = payload[previous]
    return payload


READ_PRE_3_0_COLUMNS = True
"""Read each renamed UID column under its pre-3.0 name (ADR 0048).

2.x writers update only the pre-3.0 column, so ms-markets 3.0 treats it as the
source of truth. ms-markets 3.1 reads the current column once every writer runs 3.x.
"""


def renamed_column_value(model: type[MarketsBase], row: Mapping[str, Any], current: str) -> Any:
    """Return the value of renamed UID column ``current`` from a row that may hold both names."""

    previous = model.__renamed_columns__[current]
    first, second = (previous, current) if READ_PRE_3_0_COLUMNS else (current, previous)
    if first in row:
        return row[first]
    return row.get(second)


def renamed_keyword(current_value: Any, previous_value: Any, *, current: str, previous: str) -> Any:
    """Return the value passed as ``current=``, or as pre-3.0 ``previous=`` with a warning."""

    if previous_value is None:
        return current_value
    from msm._deprecated_imports import warn_renamed

    warn_renamed(f"{previous}=", f"{current}=")
    if current_value is not None and not _same_value(current_value, previous_value):
        raise TypeError(f"Pass {current}= or its pre-3.0 name {previous}=, not both.")
    return previous_value


def _same_value(left: Any, right: Any) -> bool:
    return left == right or (left is not None and right is not None and str(left) == str(right))


def build_create_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Mapping[str, Any],
    returning: bool = True,
) -> MetaTableCompiledSQLOperation:
    """Build an insert operation for a markets MetaTable SQLAlchemy model."""

    statement = insert(model).values(
        _model_value_mapping(
            model, _model_insert_payload(model, mirror_renamed_columns(model, values))
        )
    )
    if returning:
        statement = statement.returning(model)
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
    )


UpsertStatus = Literal["inserted", "updated", "unchanged"]

UPSERT_STATUS_COLUMN = "upsert_status"
"""Key of each upserted row's status: ``inserted``, ``updated`` or ``unchanged``."""

UPSERT_STATUS_GUARD = "upsert_status"
"""Label of the SQLite statement that refuses an upsert whose rows changed after their
statuses were read; ``upsert_model`` and ``bulk_upsert_model`` then read them again."""

_UPSERT_INDEX_COLUMN = "upsert_index"
_EXPECTED_STATUS_COLUMN = "expected_status"
_UPSERT_ATTEMPTS = 3
_EXCLUDED = object()


@dataclass(frozen=True)
class _Upsert:
    """One upsert: the rows to insert, their conflict key, and the update of a conflicting row.

    ``rows`` are the insert's ``VALUES``, bound parameters named after their columns;
    ``columns`` holds the same rows' plain values by table column. ``updates`` maps each
    column a conflicting row is updated on to a value, or to ``_EXCLUDED`` for the value
    the row would have been inserted with.
    """

    model: type[MarketsBase]
    rows: list[dict[Column, Any]]
    columns: list[dict[Column, Any]]
    keys: list[Column]
    updates: dict[Column, Any]
    single: bool

    @property
    def table(self) -> Any:
        return self.model.__table__

    @property
    def values(self) -> Any:
        """The ``VALUES`` of the insert: one mapping for a single-row upsert."""

        return self.rows[0] if self.single else self.rows

    @property
    def compared(self) -> dict[Column, Any]:
        """The update's columns a change is detected on: ``onupdate`` columns always change."""

        return {column: value for column, value in self.updates.items() if column.onupdate is None}


def build_upsert_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Mapping[str, Any],
    conflict_columns: Sequence[str],
    dialect: MetaTableCompiledSQLDialect | None = None,
    statuses: Sequence[UpsertStatus] | None = None,
) -> MarketsCompiledWrite:
    """Build the upsert of one row; see :func:`build_bulk_upsert_model_operation`."""

    upsert = _single_upsert(model, values, conflict_columns)
    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return _compile_upsert(
        context, upsert, data_source_uid=data_source_uid, dialect=dialect, statuses=statuses
    )


def build_bulk_upsert_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Sequence[Mapping[str, Any]],
    conflict_columns: Sequence[str],
    dialect: MetaTableCompiledSQLDialect | None = None,
    statuses: Sequence[UpsertStatus] | None = None,
) -> MarketsCompiledWrite:
    """Build one upsert of many rows that leaves unchanged rows alone (MainSequenceMarkets#62).

    A conflicting row is updated only when one of the updated columns, other than the
    conflict, primary-key and ``onupdate`` columns, differs from its new value. Every
    input row still comes back, in input order, with its ``upsert_status``:
    ``inserted``, ``updated`` or ``unchanged``.

    On PostgreSQL this is one statement: the unchanged rows, which the conditional
    update leaves out of ``RETURNING``, are read from the same snapshot. SQLite accepts
    only ``SELECT`` inside ``WITH`` and returns only a statement list's last rows, so
    there the rows' statuses are read first, and passed as ``statuses``; the write is a
    statement list that refuses, with the ``upsert_status`` guard, rows whose status
    changed since, then upserts and returns the rows. :func:`bulk_upsert_model` runs
    both and reads again when the guard refuses.
    """

    upsert = _bulk_upsert(model, values, conflict_columns)
    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return _compile_upsert(
        context, upsert, data_source_uid=data_source_uid, dialect=dialect, statuses=statuses
    )


def bulk_upsert_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Sequence[Mapping[str, Any]],
    conflict_columns: Sequence[str],
) -> dict[str, Any]:
    """Upsert many rows; each returned row carries its ``upsert_status``."""

    return _run_upsert(context, _bulk_upsert(model, values, conflict_columns))


def upsert_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Mapping[str, Any],
    conflict_columns: Sequence[str],
) -> dict[str, Any]:
    """Upsert one row; the returned row carries its ``upsert_status``."""

    return _run_upsert(context, _single_upsert(model, values, conflict_columns))


def _single_upsert(
    model: type[MarketsBase],
    values: Mapping[str, Any],
    conflict_columns: Sequence[str],
) -> _Upsert:
    payload = mirror_renamed_columns(model, values)
    insert_payload = _model_insert_payload(model, payload)
    update_payload = _model_update_payload(model, payload)

    def update_value(key: str, value: Any) -> Any:
        # The payload's own value is the one inserted; a default only fills a missing value.
        return _EXCLUDED if value is not None and insert_payload.get(key) is value else value

    return _upsert(
        model, [insert_payload], conflict_columns, update_payload, update_value, single=True
    )


def _bulk_upsert(
    model: type[MarketsBase],
    values: Sequence[Mapping[str, Any]],
    conflict_columns: Sequence[str],
) -> _Upsert:
    if not values:
        raise ValueError("Bulk upsert operations require at least one values row.")
    payloads = [mirror_renamed_columns(model, row) for row in values]
    insert_payloads = [_model_insert_payload(model, payload) for payload in payloads]
    update_payload = _model_update_payload(model, payloads[0])

    def update_value(key: str, value: Any) -> Any:
        return _EXCLUDED if key in insert_payloads[0] else value

    return _upsert(
        model, insert_payloads, conflict_columns, update_payload, update_value, single=False
    )


def _upsert(
    model: type[MarketsBase],
    insert_payloads: Sequence[Mapping[str, Any]],
    conflict_columns: Sequence[str],
    update_payload: Mapping[str, Any],
    update_value: Any,
    *,
    single: bool,
) -> _Upsert:
    if not conflict_columns:
        raise ValueError("Upsert operations require at least one conflict column.")
    keys = [_model_column_property(model, name).columns[0] for name in conflict_columns]
    fixed = {*keys, *model.__table__.primary_key.columns}
    columns = [
        {_model_column_property(model, key).columns[0]: value for key, value in payload.items()}
        for payload in insert_payloads
    ]
    seen: set[tuple[str, ...]] = set()
    for row in columns:
        key = tuple(row.get(column) for column in keys)
        if any(value is None for value in key):
            raise ValueError(
                f"{model.__name__} upserts need a value for every conflict column "
                f"({', '.join(column.name for column in keys)}): a NULL never conflicts, so "
                "the row would be inserted again on every call."
            )
        token = tuple(str(value) for value in key)
        if token in seen:
            raise ValueError(
                f"{model.__name__} upsert received the conflict key {token} more than once."
            )
        seen.add(token)
    updates = {}
    for key, value in update_payload.items():
        target = _model_column_property(model, key).columns[0]
        if target not in fixed:
            updates[target] = update_value(key, value)
    return _Upsert(
        model=model,
        rows=[
            {
                target: bindparam(
                    target.key if single else f"{target.key}_m{index}", value, type_=target.type
                )
                for target, value in row.items()
            }
            for index, row in enumerate(columns)
        ],
        columns=columns,
        keys=keys,
        updates=updates,
        single=single,
    )


def _run_upsert(context: MarketsOperationContext, upsert: _Upsert) -> dict[str, Any]:
    data_source_uid, dialect = resolve_markets_sql_target(context)
    for attempt in range(1, _UPSERT_ATTEMPTS + 1):
        statuses = None
        if dialect == "sqlite":
            statuses = _read_upsert_statuses(
                context, upsert, data_source_uid=data_source_uid, dialect=dialect
            )
        write = _compile_upsert(
            context, upsert, data_source_uid=data_source_uid, dialect=dialect, statuses=statuses
        )
        try:
            result = execute_markets_write(write, context=context)
        except MetaTableTransactionGuardError as error:
            if error.label != UPSERT_STATUS_GUARD or attempt == _UPSERT_ATTEMPTS:
                raise
            continue
        return _upsert_result(
            context, upsert, result, data_source_uid=data_source_uid, dialect=dialect
        )
    raise AssertionError("unreachable")


def _compile_upsert(
    context: MarketsOperationContext,
    upsert: _Upsert,
    *,
    data_source_uid: str,
    dialect: MetaTableCompiledSQLDialect,
    statuses: Sequence[UpsertStatus] | None,
) -> MarketsCompiledWrite:
    if dialect != "sqlite":
        if statuses is not None:
            raise ValueError("Upsert statuses are read first only on SQLite.")
        return compile_markets_statement(
            _postgresql_upsert(upsert),
            context=context,
            operation="upsert",
            dialect=dialect,
            data_source_uid=data_source_uid,
        )
    if statuses is None or len(statuses) != len(upsert.rows):
        raise ValueError(
            "A SQLite upsert needs the status of every row, read first; "
            "upsert_model and bulk_upsert_model read them."
        )
    return compile_markets_statements(
        _sqlite_upsert(upsert, statuses),
        context=context,
        operation="upsert",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def _postgresql_upsert(upsert: _Upsert) -> Any:
    """One statement whose CTEs share a snapshot, so ``existing`` is the rows before the write."""

    table = upsert.table
    inputs = _upsert_inputs(upsert, upsert.keys, dialect="postgresql")
    written = (
        _on_conflict(
            postgresql_insert(upsert.model).values(upsert.values), upsert, dialect="postgresql"
        )
        .returning(*table.c)
        .cte("upsert_written")
    )
    existing = (
        select(*table.c)
        .where(exists().where(_keys_match(upsert, table.c, inputs.c)))
        .cte("upsert_existing")
    )
    status = case(
        (exists().where(_keys_match(upsert, existing.c, written.c)), literal_column("'updated'")),
        else_=literal_column("'inserted'"),
    )
    result = union_all(
        select(*written.c, status.label(UPSERT_STATUS_COLUMN)),
        select(*existing.c, literal_column("'unchanged'").label(UPSERT_STATUS_COLUMN)).where(
            ~exists().where(_keys_match(upsert, written.c, existing.c))
        ),
    ).subquery("upsert_result")
    return (
        select(*result.c, inputs.c[_UPSERT_INDEX_COLUMN])
        .select_from(result.join(inputs, _keys_match(upsert, result.c, inputs.c)))
        .order_by(inputs.c[_UPSERT_INDEX_COLUMN])
    )


def _sqlite_upsert(upsert: _Upsert, statuses: Sequence[UpsertStatus]) -> list[Any]:
    """Refuse rows whose status changed since it was read, upsert, then return the rows."""

    table = upsert.table
    inputs = _upsert_inputs(upsert, _status_columns(upsert), dialect="sqlite", statuses=statuses)
    joined = inputs.outerjoin(table, _keys_match(upsert, table.c, inputs.c))
    changed_statuses = GuardedStatement(
        select(inputs.c[_UPSERT_INDEX_COLUMN])
        .select_from(joined)
        .where(_upsert_status(upsert, inputs) != inputs.c[_EXPECTED_STATUS_COLUMN]),
        expect_rows=0,
        label=UPSERT_STATUS_GUARD,
    )
    write = _on_conflict(
        sqlite_insert(upsert.model).values(upsert.values), upsert, dialect="sqlite"
    )
    rows = (
        select(
            *table.c,
            inputs.c[_EXPECTED_STATUS_COLUMN].label(UPSERT_STATUS_COLUMN),
            inputs.c[_UPSERT_INDEX_COLUMN],
        )
        .select_from(inputs.join(table, _keys_match(upsert, table.c, inputs.c)))
        .order_by(inputs.c[_UPSERT_INDEX_COLUMN])
    )
    return [changed_statuses, write, rows]


def _read_upsert_statuses(
    context: MarketsOperationContext,
    upsert: _Upsert,
    *,
    data_source_uid: str,
    dialect: MetaTableCompiledSQLDialect,
) -> list[UpsertStatus]:
    table = upsert.table
    inputs = _upsert_inputs(upsert, _status_columns(upsert), dialect=dialect)
    statement = (
        select(inputs.c[_UPSERT_INDEX_COLUMN], _upsert_status(upsert, inputs).label("status"))
        .select_from(inputs.outerjoin(table, _keys_match(upsert, table.c, inputs.c)))
        .order_by(inputs.c[_UPSERT_INDEX_COLUMN])
    )
    rows = _result_rows(
        execute_markets_operation(
            compile_markets_statement(
                statement,
                context=context,
                operation="select",
                dialect=dialect,
                data_source_uid=data_source_uid,
            ),
            context=context,
        )
    )
    statuses = {int(row[_UPSERT_INDEX_COLUMN]): row["status"] for row in rows}
    return [statuses[index] for index in range(len(upsert.rows))]


def _upsert_result(
    context: MarketsOperationContext,
    upsert: _Upsert,
    result: Mapping[str, Any],
    *,
    data_source_uid: str,
    dialect: MetaTableCompiledSQLDialect,
) -> dict[str, Any]:
    """Return the rows without their input index, completing rows a concurrent write hid.

    On PostgreSQL a row another transaction commits after this statement's snapshot, with
    the same values, is neither updated nor read as existing; it is read again here and
    reported ``unchanged``.
    """

    rows = _result_rows(result)
    returned = {row.get(_UPSERT_INDEX_COLUMN) for row in rows}
    missing = {index for index in range(len(upsert.rows)) if index not in returned}
    if missing and not result.get("truncated"):
        inputs = _upsert_inputs(upsert, upsert.keys, dialect=dialect, indexes=sorted(missing))
        statement = select(
            *upsert.table.c,
            literal_column("'unchanged'").label(UPSERT_STATUS_COLUMN),
            inputs.c[_UPSERT_INDEX_COLUMN],
        ).select_from(inputs.join(upsert.table, _keys_match(upsert, upsert.table.c, inputs.c)))
        reread = execute_markets_operation(
            compile_markets_statement(
                statement,
                context=context,
                operation="select",
                dialect=dialect,
                data_source_uid=data_source_uid,
            ),
            context=context,
        )
        rows = sorted(
            [*rows, *_result_rows(reread)], key=lambda row: int(row[_UPSERT_INDEX_COLUMN])
        )
    for row in rows:
        row.pop(_UPSERT_INDEX_COLUMN, None)
    return {**result, "rows": rows, "row_count": len(rows)}


def _on_conflict(
    statement: Any, upsert: _Upsert, *, dialect: MetaTableCompiledSQLDialect
) -> Any:
    index_elements = [upsert.table.c[key.name] for key in upsert.keys]
    changes = [
        _differs(target, value, statement.excluded, dialect=dialect)
        for target, value in upsert.compared.items()
    ]
    if not changes:
        return statement.on_conflict_do_nothing(index_elements=index_elements)
    return statement.on_conflict_do_update(
        index_elements=index_elements,
        set_={
            target: statement.excluded[target.name] if value is _EXCLUDED else value
            for target, value in upsert.updates.items()
        },
        where=or_(*changes),
    )


def _differs(
    target: Column, value: Any, source: Any, *, dialect: MetaTableCompiledSQLDialect
) -> Any:
    """Whether the stored ``target`` differs from the value the update would write.

    PostgreSQL has no equality for ``json``, which the Markets migrations create for
    most JSON columns, so JSON values compare as ``jsonb``: equal documents are equal
    whatever their key order. SQLite compares the stored text.
    """

    if value is None:
        return target.is_not(None)
    new = source[target.name] if value is _EXCLUDED else literal(value, target.type)
    if dialect == "postgresql" and isinstance(target.type, JSON):
        return cast(target, JSONB).is_distinct_from(cast(new, JSONB))
    return target.is_distinct_from(new)


def _status_columns(upsert: _Upsert) -> list[Column]:
    compared = [target for target, value in upsert.compared.items() if value is _EXCLUDED]
    return [*upsert.keys, *compared]


def _upsert_status(upsert: _Upsert, inputs: Any) -> Any:
    """SQLite: ``inserted``, ``updated`` or ``unchanged``, from ``inputs`` joined to the table."""

    whens = [(upsert.table.c[upsert.keys[0].name].is_(None), literal_column("'inserted'"))]
    changes = [
        _differs(target, value, inputs.c, dialect="sqlite")
        for target, value in upsert.compared.items()
    ]
    if changes:
        whens.append((or_(*changes), literal_column("'updated'")))
    return case(*whens, else_=literal_column("'unchanged'"))


def _upsert_inputs(
    upsert: _Upsert,
    columns: Sequence[Column],
    *,
    dialect: MetaTableCompiledSQLDialect,
    statuses: Sequence[UpsertStatus] | None = None,
    indexes: Sequence[int] | None = None,
) -> Any:
    """The input rows as a ``VALUES`` CTE: their index, then ``columns``, then ``statuses``."""

    def bound(value: Any, type_: Any) -> Any:
        return values_parameter(value, type_, dialect=dialect)

    names = [
        sql_column(_UPSERT_INDEX_COLUMN, Integer()),
        *(sql_column(c.name, c.type) for c in columns),
    ]
    if statuses is not None:
        names.append(sql_column(_EXPECTED_STATUS_COLUMN, String()))
    data = []
    for index in range(len(upsert.rows)) if indexes is None else indexes:
        row = [bound(index, Integer()), *(bound(upsert.columns[index].get(c), c.type) for c in columns)]
        if statuses is not None:
            row.append(bound(statuses[index], String()))
        data.append(tuple(row))
    return values_clause(*names, name="upsert_input").data(data).cte("upsert_input")


def _keys_match(upsert: _Upsert, left: Any, right: Any) -> Any:
    return and_(*(left[key.name] == right[key.name] for key in upsert.keys))


def _result_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("rows") if isinstance(result, Mapping) else None
    return [dict(row) for row in rows or [] if isinstance(row, Mapping)]


def create_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Mapping[str, Any],
    returning: bool = True,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_model_operation(
            context,
            model=model,
            values=values,
            returning=returning,
        ),
        context=context,
    )


def build_get_model_by_uid_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = select(model).where(_model_identity_attribute(model) == uid).limit(1)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def get_model_by_uid(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_model_by_uid_operation(context, model=model, uid=uid),
        context=context,
    )


def build_get_model_by_unique_identifier_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(model)
        .where(_model_attribute(model, "unique_identifier") == unique_identifier)
        .limit(1)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def get_model_by_unique_identifier(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_model_by_unique_identifier_operation(
            context,
            model=model,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_search_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
    range_filters: Mapping[str, Mapping[str, Any]] | None = None,
    limit: int = 500,
    offset: int = 0,
    order_by: Sequence[str] | None = None,
) -> MetaTableCompiledSQLOperation:
    statement = _filtered_model_select(
        model,
        filters=filters,
        in_filters=in_filters,
        contains_filters=contains_filters,
        range_filters=range_filters,
    )
    for column_name in order_by or ():
        descending = str(column_name).startswith("-")
        name = str(column_name).removeprefix("-")
        if name not in model.__table__.c:
            raise ValueError(f"{model.__name__} cannot order by unknown column {name!r}.")
        column = model.__table__.c[name]
        statement = statement.order_by(column.desc() if descending else column.asc())
    statement = statement.limit(limit)
    if offset:
        statement = statement.offset(offset)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def search_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
    range_filters: Mapping[str, Mapping[str, Any]] | None = None,
    limit: int = 500,
    offset: int = 0,
    order_by: Sequence[str] | None = None,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_model_operation(
            context,
            model=model,
            filters=filters,
            in_filters=in_filters,
            contains_filters=contains_filters,
            range_filters=range_filters,
            order_by=order_by,
            limit=limit,
            offset=offset,
        ),
        context=context,
    )


def build_count_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
    range_filters: Mapping[str, Mapping[str, Any]] | None = None,
) -> MetaTableCompiledSQLOperation:
    filtered = _filtered_model_select(
        model,
        filters=filters,
        in_filters=in_filters,
        contains_filters=contains_filters,
        range_filters=range_filters,
    ).subquery()
    statement = select(func.count().label("count")).select_from(filtered)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def count_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
    range_filters: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_count_model_operation(
            context,
            model=model,
            filters=filters,
            in_filters=in_filters,
            contains_filters=contains_filters,
            range_filters=range_filters,
        ),
        context=context,
    )


def build_update_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
    values: Mapping[str, Any],
    returning: bool = True,
) -> MetaTableCompiledSQLOperation:
    statement = (
        update(model)
        .where(_model_identity_attribute(model) == uid)
        .values(
            _model_value_mapping(
                model,
                mirror_renamed_columns(model, values),
                include_none=False,
            )
        )
    )
    if returning:
        statement = statement.returning(model)
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
    )


def update_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
    values: Mapping[str, Any],
    returning: bool = True,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_model_operation(
            context,
            model=model,
            uid=uid,
            values=values,
            returning=returning,
        ),
        context=context,
    )


def build_delete_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(model).where(_model_identity_attribute(model) == uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
    )


def delete_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_model_operation(context, model=model, uid=uid),
        context=context,
    )


def _model_value_mapping(
    model: type[MarketsBase],
    values: Mapping[str, Any],
    *,
    include_none: bool = True,
) -> dict[Any, Any]:
    return {
        _model_attribute(model, key): value
        for key, value in values.items()
        if include_none or value is not None
    }


def _filtered_model_select(
    model: type[MarketsBase],
    *,
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
    range_filters: Mapping[str, Mapping[str, Any]] | None = None,
):
    statement = select(model)

    for field_name, value in (filters or {}).items():
        if value is not None:
            statement = statement.where(_model_attribute(model, field_name) == value)

    for field_name, values in (in_filters or {}).items():
        if values:
            statement = statement.where(_model_attribute(model, field_name).in_(list(values)))

    for field_name, value in (contains_filters or {}).items():
        if value not in (None, ""):
            statement = statement.where(
                func.lower(_model_attribute(model, field_name)).contains(str(value).lower())
            )

    for field_name, bounds in (range_filters or {}).items():
        attribute = _model_attribute(model, field_name)
        for lookup, value in bounds.items():
            if value is None:
                continue
            if lookup not in _RANGE_LOOKUPS:
                raise ValueError(f"Unknown range lookup {lookup!r}; use one of {sorted(_RANGE_LOOKUPS)}.")
            statement = statement.where(_RANGE_LOOKUPS[lookup](attribute, value))

    return statement


_RANGE_LOOKUPS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}


def _model_insert_payload(
    model: type[MarketsBase],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(values)
    for column_property in inspect(model).column_attrs:
        column = column_property.columns[0]
        if column_property.key in payload and payload[column_property.key] is not None:
            continue
        default_value = _column_default_value(column.default)
        if default_value is not _MISSING:
            payload[column_property.key] = default_value
    return payload


def _model_update_payload(
    model: type[MarketsBase],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(values)
    for column_property in inspect(model).column_attrs:
        column = column_property.columns[0]
        if column_property.key in payload and payload[column_property.key] is not None:
            continue
        default_value = _column_default_value(column.onupdate)
        if default_value is not _MISSING:
            payload[column_property.key] = default_value
    return payload


def _column_default_value(default: Any) -> Any:
    if default is None or getattr(default, "is_clause_element", False):
        return _MISSING

    value = getattr(default, "arg", default)
    if callable(value):
        try:
            return value(None)
        except TypeError:
            return value()
    return value


def _model_identity_attribute(model: type[MarketsBase]) -> Any:
    if "uid" in model.__table__.c:
        return _model_attribute(model, "uid")

    primary_key_columns = list(model.__table__.primary_key.columns)
    if len(primary_key_columns) != 1:
        raise ValueError(
            f"{model.__name__} must define a `uid` column or exactly one primary key column."
        )
    primary_key_property = inspect(model).get_property_by_column(primary_key_columns[0])
    return _model_attribute(model, primary_key_property.key)


def _model_column_property(model: type[MarketsBase], field_name: str) -> Any:
    matches = []
    for column_property in inspect(model).column_attrs:
        names = {column_property.key}
        for column in column_property.columns:
            names.add(str(column.key))
            names.add(str(column.name))
        if field_name in names:
            matches.append(column_property)

    if not matches:
        raise ValueError(f"{model.__name__} has no SQLAlchemy column {field_name!r}.")
    if len(matches) > 1:
        raise ValueError(f"{model.__name__} column reference {field_name!r} is ambiguous.")
    return matches[0]


def _model_attribute(model: type[MarketsBase], field_name: str) -> Any:
    return getattr(model, _model_column_property(model, field_name).key)


__all__ = [
    "build_bulk_upsert_model_operation",
    "build_count_model_operation",
    "build_create_model_operation",
    "build_delete_model_operation",
    "build_get_model_by_uid_operation",
    "build_get_model_by_unique_identifier_operation",
    "build_search_model_operation",
    "build_upsert_model_operation",
    "build_update_model_operation",
    "bulk_upsert_model",
    "count_model",
    "create_model",
    "delete_model",
    "get_model_by_uid",
    "get_model_by_unique_identifier",
    "search_model",
    "upsert_model",
    "update_model",
]
