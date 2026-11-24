"""Link many assets to their trading calendars in one transaction (ADR 0057).

``AssetCalendar`` is one row per asset. Linking by ``asset_uid`` one row at a
time needs the uids first; these statements link by ``unique_identifier`` with
an ``INSERT … SELECT`` over ``Asset``, so a caller names assets as it knows them
and an asset inserted earlier in the same transaction is linked too.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Uuid, func, literal, select

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from msm.models import AssetCalendarTable, AssetTable, CalendarTable
from msm.repositories.asset_registration import dialect_insert
from msm.repositories.base import (
    MarketsCompiledWrite,
    MarketsRepositoryContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
    values_parameter,
)

LINK_IDENTIFIERS_PER_STATEMENT = 2000
"""Asset identifiers one link statement names: inside a statement's parameter limit."""

LINK_STATEMENTS_PER_TRANSACTION = 32
"""Statements MetaTables accepts in one transaction."""

LINK_STATE_READ_SIZE = 1000
"""Asset identifiers per read of the current links; a governed read returns at most 1,000 rows."""


def link_assets_statements(
    links: Mapping[uuid.UUID | str, Sequence[str]],
    *,
    dialect: MetaTableCompiledSQLDialect,
    relink: bool,
) -> list[Any]:
    """The statements that link each calendar's assets, named by ``unique_identifier``.

    ``links`` maps a calendar uid to the identifiers of its assets. An identifier
    no asset has links nothing. With ``relink`` an asset linked to another
    calendar is moved; without it an asset that has a link keeps it. An asset
    already on the calendar is not rewritten.
    """

    statements: list[Any] = []
    for calendar_uid, identifiers in links.items():
        names = list(dict.fromkeys(str(identifier) for identifier in identifiers))
        calendar = values_parameter(
            uuid.UUID(str(calendar_uid)), Uuid(as_uuid=True), dialect=dialect
        )
        for index in range(0, len(names), LINK_IDENTIFIERS_PER_STATEMENT):
            chunk = names[index : index + LINK_IDENTIFIERS_PER_STATEMENT]
            insert = dialect_insert(AssetCalendarTable, dialect).from_select(
                ["asset_uid", "calendar_uid"],
                select(AssetTable.uid, calendar).where(AssetTable.unique_identifier.in_(chunk)),
            )
            if relink:
                statements.append(
                    insert.on_conflict_do_update(
                        index_elements=[AssetCalendarTable.asset_uid],
                        set_={"calendar_uid": insert.excluded.calendar_uid},
                        where=AssetCalendarTable.calendar_uid != insert.excluded.calendar_uid,
                    )
                )
            else:
                statements.append(
                    insert.on_conflict_do_nothing(index_elements=[AssetCalendarTable.asset_uid])
                )
    return statements


def build_link_assets_operation(
    context: MarketsRepositoryContext,
    *,
    links: Mapping[uuid.UUID | str, Sequence[str]],
    relink: bool,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the links as one transaction for the context's DataSource."""

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    statements = link_assets_statements(links, dialect=dialect, relink=relink)
    if not statements:
        raise ValueError("Linking assets to a calendar names at least one asset.")
    if len(statements) > LINK_STATEMENTS_PER_TRANSACTION:
        limit = LINK_STATEMENTS_PER_TRANSACTION * LINK_IDENTIFIERS_PER_STATEMENT
        raise ValueError(
            f"One call links at most about {limit:,} assets; this one needs "
            f"{len(statements)} statements. Link the assets in several calls."
        )
    return compile_markets_statements(
        statements,
        context=context,
        operation="upsert",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def link_assets(
    context: MarketsRepositoryContext,
    *,
    links: Mapping[uuid.UUID | str, Sequence[str]],
    relink: bool,
) -> dict[str, Any]:
    """Run the links; see :func:`link_assets_statements`."""

    return execute_markets_write(
        build_link_assets_operation(context, links=links, relink=relink),
        context=context,
    )


def build_asset_link_state_operation(
    context: MarketsRepositoryContext,
    *,
    asset_identifiers: Sequence[str],
) -> MetaTableCompiledSQLOperation:
    """One read of the named assets with the calendar each is linked to, if any."""

    statement = (
        select(
            AssetTable.unique_identifier.label("asset_identifier"),
            AssetTable.uid.label("asset_uid"),
            AssetCalendarTable.calendar_uid.label("calendar_uid"),
        )
        .select_from(AssetTable)
        .outerjoin(AssetCalendarTable, AssetCalendarTable.asset_uid == AssetTable.uid)
        .where(AssetTable.unique_identifier.in_(list(asset_identifiers)))
        .order_by(AssetTable.unique_identifier)
        .limit(LINK_STATE_READ_SIZE)
    )
    return compile_markets_statement(statement, context=context, operation="select")


def read_asset_link_state(
    context: MarketsRepositoryContext,
    *,
    asset_identifiers: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Each existing asset among ``asset_identifiers`` with its link, by identifier.

    An identifier that is missing from the answer names no asset. ``calendar_uid``
    is None for an asset that has no trading calendar.
    """

    names = list(dict.fromkeys(str(identifier) for identifier in asset_identifiers))
    state: dict[str, dict[str, Any]] = {}
    for index in range(0, len(names), LINK_STATE_READ_SIZE):
        result = execute_markets_operation(
            build_asset_link_state_operation(
                context,
                asset_identifiers=names[index : index + LINK_STATE_READ_SIZE],
            ),
            context=context,
        )
        for row in result.get("rows") or []:
            state[str(row["asset_identifier"])] = dict(row)
    return state


def build_asset_trading_calendars_operation(
    context: MarketsRepositoryContext,
    *,
    asset_identifiers: Sequence[str],
) -> MetaTableCompiledSQLOperation:
    """One read of the named assets with the row of the calendar each is linked to."""

    statement = (
        select(AssetTable.unique_identifier.label("asset_identifier"), *CalendarTable.__table__.c)
        .select_from(AssetTable)
        .outerjoin(AssetCalendarTable, AssetCalendarTable.asset_uid == AssetTable.uid)
        .outerjoin(CalendarTable, CalendarTable.uid == AssetCalendarTable.calendar_uid)
        .where(AssetTable.unique_identifier.in_(list(asset_identifiers)))
        .order_by(AssetTable.unique_identifier)
        .limit(LINK_STATE_READ_SIZE)
    )
    return compile_markets_statement(statement, context=context, operation="select")


def read_asset_trading_calendars(
    context: MarketsRepositoryContext,
    *,
    asset_identifiers: Sequence[str],
) -> dict[str, dict[str, Any] | None]:
    """Each existing asset's calendar row, by identifier, in one read per 1,000 assets.

    An identifier missing from the answer names no asset; an asset with no trading
    calendar answers ``None``.
    """

    names = list(dict.fromkeys(str(identifier) for identifier in asset_identifiers))
    calendars: dict[str, dict[str, Any] | None] = {}
    for index in range(0, len(names), LINK_STATE_READ_SIZE):
        result = execute_markets_operation(
            build_asset_trading_calendars_operation(
                context,
                asset_identifiers=names[index : index + LINK_STATE_READ_SIZE],
            ),
            context=context,
        )
        for row in result.get("rows") or []:
            calendar = {key: value for key, value in row.items() if key != "asset_identifier"}
            calendars[str(row["asset_identifier"])] = (
                None if calendar.get("uid") is None else calendar
            )
    return calendars


def build_unlinked_assets_operation(
    context: MarketsRepositoryContext,
    *,
    asset_type: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """Assets that have no trading calendar, by ``unique_identifier``."""

    statement = (
        select(AssetTable)
        .outerjoin(AssetCalendarTable, AssetCalendarTable.asset_uid == AssetTable.uid)
        .where(AssetCalendarTable.asset_uid.is_(None))
    )
    if asset_type not in (None, ""):
        statement = statement.where(AssetTable.asset_type == asset_type)
    statement = statement.order_by(AssetTable.unique_identifier).limit(limit)
    if offset:
        statement = statement.offset(offset)
    return compile_markets_statement(statement, context=context, operation="select")


def read_unlinked_assets(
    context: MarketsRepositoryContext,
    **filters: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_unlinked_assets_operation(context, **filters),
        context=context,
    )


def count_assets_on_calendar(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: uuid.UUID | str,
) -> int:
    """How many assets have ``calendar_uid`` as their trading calendar."""

    statement = (
        select(func.count().label("count"))
        .select_from(AssetCalendarTable)
        .where(
            AssetCalendarTable.calendar_uid
            == literal(uuid.UUID(str(calendar_uid)), Uuid(as_uuid=True))
        )
    )
    result = execute_markets_operation(
        compile_markets_statement(statement, context=context, operation="select"),
        context=context,
    )
    rows = result.get("rows") or []
    return int(rows[0]["count"]) if rows else 0


__all__ = [
    "LINK_IDENTIFIERS_PER_STATEMENT",
    "LINK_STATEMENTS_PER_TRANSACTION",
    "build_asset_link_state_operation",
    "build_asset_trading_calendars_operation",
    "build_link_assets_operation",
    "build_unlinked_assets_operation",
    "count_assets_on_calendar",
    "link_assets",
    "link_assets_statements",
    "read_asset_link_state",
    "read_asset_trading_calendars",
    "read_unlinked_assets",
]
