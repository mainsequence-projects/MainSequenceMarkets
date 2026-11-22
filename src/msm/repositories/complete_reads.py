"""Reads that answer every row their select matches, or raise; never a part.

MetaTables answers at most 10,000 rows a statement and cuts an answer at 8 MiB. A select
read here has a total order and carries two columns of its own: how many rows it matches
in all, counted before the page is cut, and a value every row of one statement shares.
`read_every_row` takes both off the rows. With them it reads until it has every row, and
it knows when the rows came from more than one statement, which a write can fall between:
it then reads again until two reads agree, and raises `IncompleteReadError` when none do.
A select that fits one statement costs one request.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import func, select

from metatables import MetaTableCompiledSQLOperation
from msm.base import MarketsBase

from .base import (
    MarketsOperationContext,
    compile_markets_statement,
    execute_markets_operation,
    with_max_rows,
)
from .crud import MAX_STATEMENT_ROWS, _filtered_model_select, _result_rows

READ_PAGE_ROWS = MAX_STATEMENT_ROWS
READ_ATTEMPTS = 4
IN_FILTER_VALUES = 5_000
"""The most values of one ``IN`` list: inside both dialects' parameter limits."""

_MATCHED = "read__matched_rows"
_STATEMENT = "read__statement"


class IncompleteReadError(RuntimeError):
    """A read could not answer every row of one state of its tables."""


def page_select(statement: Any, *, key: Sequence[str], offset: int) -> Any:
    """One page of ``statement``, ordered by ``key``, with the two columns of a complete read.

    ``key`` names selected columns that make each row unique; ``-`` before a name orders
    it descending.
    """

    order = key_order(statement.selected_columns, key)
    return (
        statement.add_columns(
            func.count().over().label(_MATCHED),
            # A scalar subquery runs once, so a statement's rows share its value.
            select(func.random()).scalar_subquery().label(_STATEMENT),
        )
        .order_by(*order)
        .limit(READ_PAGE_ROWS)
        .offset(offset)
    )


def key_order(columns: Any, key: Sequence[str]) -> list[Any]:
    """The order ``key`` names among ``columns``: ``-`` before a name orders it descending."""

    return [
        columns[name[1:]].desc() if name.startswith("-") else columns[name].asc() for name in key
    ]


def compile_page(
    statement: Any, *, context: MarketsOperationContext
) -> MetaTableCompiledSQLOperation:
    """Compile a `page_select` so that MetaTables returns the whole page."""

    return compile_markets_statement(statement, context=page_context(context), operation="select")


def page_context(context: MarketsOperationContext) -> MarketsOperationContext:
    """``context`` whose answers hold a whole page."""

    return with_max_rows(context, READ_PAGE_ROWS)


def whole_page(page: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]] | None:
    """The rows of a `page_select` at offset 0 that another operation answered, if they are all.

    A write whose transaction ends in that select has its answer here. ``None`` when the
    select matched more rows than it answered: they are then read with `read_every_row`.
    """

    rows = [dict(row) for row in page]
    matched = {int(row.pop(_MATCHED)) for row in rows}
    for row in rows:
        row.pop(_STATEMENT)
    return rows if matched == {len(rows)} else None


def read_every_row(
    build_page: Callable[[int], MetaTableCompiledSQLOperation],
    *,
    context: MarketsOperationContext,
) -> dict[str, Any]:
    """Every row of the select whose page at an offset ``build_page`` compiles."""

    previous: list[dict[str, Any]] | None = None
    for _attempt in range(READ_ATTEMPTS):
        rows, one_statement = _read_pages(build_page, context=context)
        if rows is not None and (one_statement or rows == previous):
            return {"rows": rows, "row_count": len(rows)}
        previous = rows
    raise IncompleteReadError(
        f"The rows changed or were cut in each of {READ_ATTEMPTS} reads, so none is returned: "
        "a part would look like the whole. Try again."
    )


def read_every_model_row(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
) -> dict[str, Any]:
    """Every row of ``model`` the filters match, with no limit.

    The filters are `search_model`'s, except that an empty ``IN`` list matches no row:
    `search_model` drops it, which here would be every row of the table. A list over
    `IN_FILTER_VALUES` values is read in batches.
    """

    if any(not values for values in (in_filters or {}).values()):
        return {"rows": [], "row_count": 0}

    key = getattr(model, "__index_names__", None) or [
        column.name for column in model.__table__.primary_key.columns
    ]
    selections = [dict(in_filters or {})]
    for name, values in (in_filters or {}).items():
        listed = list(dict.fromkeys(values))
        selections = [
            {**selection, name: listed[start : start + IN_FILTER_VALUES]}
            for selection in selections
            for start in range(0, len(listed), IN_FILTER_VALUES)
        ]
    rows: list[dict[str, Any]] = []
    for selection in selections:
        statement = _filtered_model_select(model, filters=filters, in_filters=selection)
        result = read_every_row(
            lambda offset: compile_page(
                page_select(statement, key=key, offset=offset), context=context
            ),
            context=context,
        )
        rows.extend(result["rows"])
    return {"rows": rows, "row_count": len(rows)}


def _read_pages(
    build_page: Callable[[int], MetaTableCompiledSQLOperation],
    *,
    context: MarketsOperationContext,
) -> tuple[list[dict[str, Any]] | None, bool]:
    """The rows, or ``None`` when they are not all there; and whether one statement read them."""

    rows: list[dict[str, Any]] = []
    matched: set[int] = set()
    statements: set[Any] = set()
    while True:
        page = _result_rows(execute_markets_operation(build_page(len(rows)), context=context))
        for row in page:
            matched.add(int(row.pop(_MATCHED)))
            statements.add(row.pop(_STATEMENT))
        rows.extend(page)
        if not page or len(rows) >= max(matched):
            break
    whole = not matched or matched == {len(rows)}
    return (rows if whole else None), len(statements) <= 1


__all__ = [
    "IN_FILTER_VALUES",
    "IncompleteReadError",
    "READ_ATTEMPTS",
    "READ_PAGE_ROWS",
    "compile_page",
    "key_order",
    "page_context",
    "page_select",
    "read_every_model_row",
    "read_every_row",
    "whole_page",
]
