"""Write a calendar's header, rules and exceptions in one transaction (ADR 0055).

The header and its rows change together: a calendar never claims a range its
rows do not cover. The write is an ordered statement list that MetaTables runs
in one transaction on PostgreSQL and SQLite (MetaTables ADR 0026).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, insert, update

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLTransaction
from msm.base import new_markets_uid
from msm.models import CalendarExceptionTable, CalendarSessionRuleTable, CalendarTable
from msm.repositories.base import (
    MarketsRepositoryContext,
    compile_markets_statements,
    execute_markets_write,
    resolve_markets_sql_target,
)

MAX_STATEMENTS = 32
"""Statements MetaTables accepts in one transaction."""

EXCEPTION_ROWS_PER_STATEMENT = 500
MAX_EXCEPTION_ROWS_PER_STATEMENT = 2000
"""A statement's SQL text is limited to 1,000,000 characters; 2,000 rows stay well inside it."""

_CALENDAR_COLUMNS = (
    "unique_identifier",
    "display_name",
    "calendar_type",
    "timezone",
    "source",
    "source_identifier",
    "valid_from",
    "valid_to",
    "metadata_json",
)
_RULE_COLUMNS = (
    "session_label",
    "effective_from",
    "effective_to",
    "weekdays",
    "opens_at_local",
    "closes_at_local",
    "open_day_offset",
    "close_day_offset",
    "is_primary",
)
_EXCEPTION_COLUMNS = (
    "local_date",
    "session_label",
    "exception_type",
    "opens_at_local",
    "closes_at_local",
    "name",
    "source",
    "metadata_json",
)


def calendar_definition_statements(
    *,
    calendar_uid: uuid.UUID | str,
    calendar_values: Mapping[str, Any],
    calendar_exists: bool,
    rules: Sequence[Mapping[str, Any]] | None,
    delete_exception_uids: Sequence[uuid.UUID | str] = (),
    insert_exceptions: Sequence[Mapping[str, Any]] = (),
) -> list[Any]:
    """The ordered statements of one calendar write.

    ``rules`` replaces every session rule of the calendar; ``None`` leaves them.
    Exceptions change by difference: the named rows are deleted and the given
    rows inserted, so a row that did not change is not written.
    """

    header = {key: calendar_values.get(key) for key in _CALENDAR_COLUMNS}
    statements: list[Any] = []
    if calendar_exists:
        statements.append(
            update(CalendarTable).where(CalendarTable.uid == calendar_uid).values(**header)
        )
    else:
        statements.append(insert(CalendarTable).values(uid=calendar_uid, **header))

    if rules is not None:
        statements.append(
            delete(CalendarSessionRuleTable).where(
                CalendarSessionRuleTable.calendar_uid == calendar_uid
            )
        )
        if rules:
            statements.append(
                insert(CalendarSessionRuleTable).values(
                    [
                        {
                            "uid": new_markets_uid(),
                            "calendar_uid": calendar_uid,
                            **{key: rule.get(key) for key in _RULE_COLUMNS},
                        }
                        for rule in rules
                    ]
                )
            )

    budget = MAX_STATEMENTS - len(statements)
    largest = max(len(delete_exception_uids), len(insert_exceptions))
    per_statement = max(EXCEPTION_ROWS_PER_STATEMENT, math.ceil(2 * largest / max(budget, 1)))
    if per_statement > MAX_EXCEPTION_ROWS_PER_STATEMENT:
        raise ValueError(
            f"A calendar write of {len(insert_exceptions)} new and "
            f"{len(delete_exception_uids)} removed exceptions does not fit one transaction. "
            "Write a shorter range first."
        )
    for chunk in _chunks(list(delete_exception_uids), per_statement):
        statements.append(
            delete(CalendarExceptionTable).where(
                CalendarExceptionTable.calendar_uid == calendar_uid,
                CalendarExceptionTable.uid.in_(chunk),
            )
        )
    for chunk in _chunks(list(insert_exceptions), per_statement):
        statements.append(
            insert(CalendarExceptionTable).values(
                [
                    {
                        "uid": new_markets_uid(),
                        "calendar_uid": calendar_uid,
                        **{key: row.get(key) for key in _EXCEPTION_COLUMNS},
                    }
                    for row in chunk
                ]
            )
        )
    return statements


def build_write_calendar_definition_operation(
    context: MarketsRepositoryContext,
    *,
    dialect: MetaTableCompiledSQLDialect | None = None,
    **values: Any,
) -> MetaTableCompiledSQLTransaction:
    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        calendar_definition_statements(**values),
        context=context,
        operation="upsert",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def write_calendar_definition(
    context: MarketsRepositoryContext,
    **values: Any,
) -> dict[str, Any]:
    """Run one calendar write; see :func:`calendar_definition_statements`."""

    return execute_markets_write(
        build_write_calendar_definition_operation(context, **values),
        context=context,
    )


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


__all__ = [
    "EXCEPTION_ROWS_PER_STATEMENT",
    "MAX_STATEMENTS",
    "build_write_calendar_definition_operation",
    "calendar_definition_statements",
    "write_calendar_definition",
]
