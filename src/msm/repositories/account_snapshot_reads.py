"""One-statement reads of an account's target, holdings and holdings by fund.

Each MetaTables request is a round trip, so each read here joins in one statement what
the account services used to ask for one table at a time (issue 94). Columns of the
joined tables come back under a prefix: ``target__``, ``portfolio__``, ``holding__``,
``fund__``, ``fundset__``, ``allocation__`` and ``assetref__``; `prefixed_columns` takes
one table's columns out of a row.

Each read answers every row of its snapshot (`msm.repositories.complete_reads`): a
builder compiles the page at ``offset``, and the ``read_`` function reads them all.

``assetref__`` columns are the asset of a row (``uid``, ``identifier``) and its latest
snapshot's ``name`` and ``ticker``, the asset reference the services answer with; they
are null when the asset or its snapshot does not exist.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sqlalchemy import Text, and_, asc, cast, desc, func, or_, select, true
from sqlalchemy.orm import aliased

from metatables import MetaTableCompiledSQLOperation
from msm.models import (
    AccountHoldingsSetTable,
    AccountTable,
    AccountTargetAllocationTable,
    AssetTable,
    PortfolioTable,
    PositionSetTable,
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)
from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
from msm.time_index.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
from msm.time_index.assets.storage import AssetSnapshotsStorage

from .base import MarketsRepositoryContext, compile_markets_statement, execute_markets_operation
from .complete_reads import compile_page, key_order, page_select, read_every_row

SnapshotOrder = Literal["asc", "desc"]

TARGET = "target__"
PORTFOLIO = "portfolio__"
HOLDING = "holding__"
FUND = "fund__"
FUND_SET = "fundset__"
ALLOCATION = "allocation__"
ASSET_REFERENCE = "assetref__"


def prefixed_columns(row: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    """The columns of ``row`` under ``prefix``, without it."""

    return {key[len(prefix) :]: value for key, value in row.items() if key.startswith(prefix)}


def account_target_snapshot_select(
    *,
    account_uid: uuid.UUID | str,
    order: SnapshotOrder,
    target_positions_date: dt.datetime | None,
    include_asset_detail: bool,
    offset: int = 0,
) -> Any:
    """The select of `build_account_target_snapshot_operation`, not compiled.

    The target write also ends its transaction with it, at offset 0, to answer what it
    wrote (``msm.repositories.accounts``).
    """

    candidates = _account_position_sets(account_uid).where(
        AccountTargetAllocationTable.is_active == true()
    )
    if target_positions_date is not None:
        candidates = candidates.where(
            PositionSetTable.position_set_time == target_positions_date
        ).order_by(PositionSetTable.uid.asc())
    else:
        direction = _direction(order)
        candidates = candidates.order_by(
            direction(PositionSetTable.position_set_time),
            direction(PositionSetTable.uid),
        )
    return _target_rows_page(
        candidates.limit(1).subquery("target_snapshot"),
        account_uid=account_uid,
        key=(f"{TARGET}target_type", f"{TARGET}target_uid"),
        include_asset_detail=include_asset_detail,
        offset=offset,
    )


def build_account_target_snapshot_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    order: SnapshotOrder,
    target_positions_date: dt.datetime | None,
    include_asset_detail: bool,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """One read: the account, its target snapshot, the snapshot's rows and their labels.

    The snapshot is a position set of one of the account's active target allocations:
    the one at ``target_positions_date`` (the smallest uid when several are), else the
    latest (``order="desc"``) or the earliest, ties broken by uid. The statement answers
    no row when the account does not exist; one row with null ``position_set_uid`` when
    it has no such snapshot; otherwise one row per position (null ``target__`` columns
    when the snapshot has none) with its ``portfolio__`` row and, with
    ``include_asset_detail``, its asset reference.
    """

    statement = account_target_snapshot_select(
        account_uid=account_uid,
        order=order,
        target_positions_date=target_positions_date,
        include_asset_detail=include_asset_detail,
        offset=offset,
    )
    return compile_page(statement, context=context)


def read_account_target_snapshot(
    context: MarketsRepositoryContext, **kwargs: Any
) -> dict[str, Any]:
    return read_every_row(
        lambda offset: build_account_target_snapshot_operation(context, offset=offset, **kwargs),
        context=context,
    )


def build_account_target_history_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    order: SnapshotOrder,
    snapshots: int,
    skip: int,
    include_asset_detail: bool,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """One read: several of an account's target snapshots, with their rows and labels.

    The snapshots are the ``snapshots`` after the first ``skip`` of all the account's
    position sets, latest first (``order="desc"``) or earliest first, ties broken by uid.
    They are history, so unlike the current target they include those of an inactive
    allocation: a clear, and what came before it. Each row is as
    `build_account_target_snapshot_operation` answers it, with ``snapshot_count``, how
    many snapshots the account has. ``offset`` pages the rows, not the snapshots.
    """

    direction = _direction(order)
    position_sets = _account_position_sets(account_uid)
    count = (
        select(func.count())
        .select_from(position_sets.subquery("account_position_sets"))
        .scalar_subquery()
    )
    page = (
        position_sets.order_by(
            direction(PositionSetTable.position_set_time),
            direction(PositionSetTable.uid),
        )
        .limit(snapshots)
        .offset(skip)
        .subquery("target_snapshot")
    )
    sign = "-" if order == "desc" else ""
    statement = _target_rows_page(
        page,
        account_uid=account_uid,
        key=(
            f"{sign}position_set_time",
            f"{sign}position_set_uid",
            f"{TARGET}target_type",
            f"{TARGET}target_uid",
        ),
        include_asset_detail=include_asset_detail,
        offset=offset,
        extra=(count.label("snapshot_count"),),
    )
    return compile_page(statement, context=context)


def read_account_target_history(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return read_every_row(
        lambda offset: build_account_target_history_operation(context, offset=offset, **kwargs),
        context=context,
    )


def build_account_with_stored_target_allocation_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    """One read: the account row with ``stored_target_allocation_uid``.

    That is the uid of the account's stored target allocation, the one whose
    ``unique_identifier`` is the account uid (the key the target write upserts it by),
    or null. No row when the account does not exist.
    """

    stored_allocation = (
        select(AccountTargetAllocationTable.uid)
        .where(AccountTargetAllocationTable.unique_identifier == _uid_string(account_uid))
        .limit(1)
        .scalar_subquery()
    )
    statement = (
        select(
            *AccountTable.__table__.columns,
            stored_allocation.label("stored_target_allocation_uid"),
        )
        .where(AccountTable.uid == account_uid)
        .limit(1)
    )
    return _compile(statement, context)


def read_account_with_stored_target_allocation(
    context: MarketsRepositoryContext, **kwargs: Any
) -> dict[str, Any]:
    return execute_markets_operation(
        build_account_with_stored_target_allocation_operation(context, **kwargs),
        context=context,
    )


def build_account_holdings_snapshot_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    order: SnapshotOrder,
    holdings_date: dt.datetime | None,
    include_asset_detail: bool,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """One read: the account and its holdings at one time, with their asset references.

    The time is ``holdings_date``, else the account's latest (``order="desc"``) or
    earliest holdings time. The statement answers no row when the account does not
    exist, one row with null ``holding__`` columns when it holds nothing at that time,
    and otherwise one row per holding.
    """

    if holdings_date is not None:
        snapshot_time: Any = holdings_date
    else:
        times = aliased(AccountHoldingsStorage, name="holdings_times")
        aggregate = func.max if order == "desc" else func.min
        snapshot_time = (
            select(aggregate(times.time_index))
            .where(times.account_uid == account_uid)
            .scalar_subquery()
        )
    columns = [AccountTable.uid.label("account_uid"), *_labelled(AccountHoldingsStorage, HOLDING)]
    statement = (
        select(*columns)
        .select_from(AccountTable)
        .outerjoin(
            AccountHoldingsStorage,
            and_(
                AccountHoldingsStorage.account_uid == AccountTable.uid,
                AccountHoldingsStorage.time_index == snapshot_time,
            ),
        )
        .where(AccountTable.uid == account_uid)
    )
    key = (f"{HOLDING}asset_identifier",)
    statement = page_select(statement, key=key, offset=offset)
    if include_asset_detail:
        statement = _with_asset_references(
            statement,
            AssetTable.unique_identifier == AccountHoldingsStorage.asset_identifier,
            key=key,
        )
    return compile_page(statement, context=context)


def read_account_holdings_snapshot(
    context: MarketsRepositoryContext, **kwargs: Any
) -> dict[str, Any]:
    return read_every_row(
        lambda offset: build_account_holdings_snapshot_operation(context, offset=offset, **kwargs),
        context=context,
    )


def build_account_holdings_set_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    order: SnapshotOrder,
    holdings_date: dt.datetime | None,
    include_asset_detail: bool,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """One read: the account, one of its holdings sets and that set's rows.

    The set is the one at ``holdings_date``, else the latest (``order="desc"``) or the
    earliest, ties broken by uid. The statement answers no row when the account does
    not exist; one row with null ``holdings_set_uid`` when it has no such set; otherwise
    one row per holding of the set (null ``holding__`` columns when it has none), with
    its asset reference under ``include_asset_detail``.
    """

    direction = _direction(order)
    candidates = select(
        AccountHoldingsSetTable.uid.label("uid"),
        AccountHoldingsSetTable.time_index.label("time_index"),
    ).where(AccountHoldingsSetTable.account_uid == account_uid)
    if holdings_date is not None:
        candidates = candidates.where(AccountHoldingsSetTable.time_index == holdings_date)
    holdings_set = (
        candidates.order_by(
            direction(AccountHoldingsSetTable.time_index),
            direction(AccountHoldingsSetTable.uid),
        )
        .limit(1)
        .subquery("holdings_set")
    )
    columns = [
        AccountTable.uid.label("account_uid"),
        holdings_set.c.uid.label("holdings_set_uid"),
        holdings_set.c.time_index.label("holdings_set_time"),
        *_labelled(AccountHoldingsStorage, HOLDING),
    ]
    statement = (
        select(*columns)
        .select_from(AccountTable)
        .outerjoin(holdings_set, true())
        .outerjoin(
            AccountHoldingsStorage,
            and_(
                AccountHoldingsStorage.account_uid == AccountTable.uid,
                AccountHoldingsStorage.holdings_set_uid == holdings_set.c.uid,
            ),
        )
        .where(AccountTable.uid == account_uid)
    )
    key = (f"{HOLDING}time_index", f"{HOLDING}asset_identifier")
    statement = page_select(statement, key=key, offset=offset)
    if include_asset_detail:
        statement = _with_asset_references(
            statement,
            AssetTable.unique_identifier == AccountHoldingsStorage.asset_identifier,
            key=key,
        )
    return compile_page(statement, context=context)


def read_account_holdings_set(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return read_every_row(
        lambda offset: build_account_holdings_set_operation(context, offset=offset, **kwargs),
        context=context,
    )


def build_account_fund_holdings_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    source_account_holdings_set_uid: uuid.UUID | str,
    include_asset_detail: bool,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """One read: the account's virtual funds with what each holds from one holdings set.

    Each fund comes with its ``fundset__`` holdings set funded by
    ``source_account_holdings_set_uid`` (at most one: the pair is unique) and its
    ``allocation__`` rows from that set, one row each, or one row with null
    ``allocation__`` columns when it has the set alone; with ``include_asset_detail``,
    each row's asset reference. A fund with neither answers no row.
    """

    columns = [
        *_labelled(VirtualFundTable, FUND),
        *_labelled(VirtualFundHoldingsSetTable, FUND_SET),
        *_labelled(VirtualFundHoldingsStorage, ALLOCATION),
    ]
    statement = (
        select(*columns)
        .select_from(VirtualFundTable)
        .outerjoin(
            VirtualFundHoldingsSetTable,
            and_(
                VirtualFundHoldingsSetTable.virtual_fund_uid == VirtualFundTable.uid,
                VirtualFundHoldingsSetTable.source_account_holdings_set_uid
                == source_account_holdings_set_uid,
            ),
        )
        .outerjoin(
            VirtualFundHoldingsStorage,
            and_(
                VirtualFundHoldingsStorage.virtual_fund_uid == VirtualFundTable.uid,
                VirtualFundHoldingsStorage.source_account_holdings_set_uid
                == source_account_holdings_set_uid,
            ),
        )
        .where(
            VirtualFundTable.account_uid == account_uid,
            or_(
                VirtualFundHoldingsSetTable.uid.is_not(None),
                VirtualFundHoldingsStorage.time_index.is_not(None),
            ),
        )
    )
    key = (f"{FUND}uid", f"{ALLOCATION}time_index", f"{ALLOCATION}asset_identifier")
    statement = page_select(statement, key=key, offset=offset)
    if include_asset_detail:
        statement = _with_asset_references(
            statement,
            AssetTable.unique_identifier == VirtualFundHoldingsStorage.asset_identifier,
            key=key,
        )
    return compile_page(statement, context=context)


def read_account_fund_holdings(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return read_every_row(
        lambda offset: build_account_fund_holdings_operation(context, offset=offset, **kwargs),
        context=context,
    )


def build_account_holdings_snapshots_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    order: SnapshotOrder = "desc",
    holdings_dates: Sequence[dt.datetime] | None = None,
    snapshots: int = 1,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """One read: the holdings rows of several of an account's snapshots, ordered by time.

    The snapshots are those at ``holdings_dates``, else the latest (``order="desc"``) or
    earliest ``snapshots`` of them.
    """

    direction = _direction(order)
    if holdings_dates is not None:
        wanted: Any = list(holdings_dates)
    else:
        times = aliased(AccountHoldingsStorage, name="holdings_times")
        wanted = (
            select(times.time_index)
            .where(times.account_uid == account_uid)
            .distinct()
            .order_by(direction(times.time_index))
            .limit(snapshots)
        )
    statement = select(*AccountHoldingsStorage.__table__.columns).where(
        AccountHoldingsStorage.account_uid == account_uid,
        AccountHoldingsStorage.time_index.in_(wanted),
    )
    key = ("-time_index" if order == "desc" else "time_index", "asset_identifier")
    return compile_page(page_select(statement, key=key, offset=offset), context=context)


def read_account_holdings_snapshots(
    context: MarketsRepositoryContext, **kwargs: Any
) -> dict[str, Any]:
    return read_every_row(
        lambda offset: build_account_holdings_snapshots_operation(
            context, offset=offset, **kwargs
        ),
        context=context,
    )


def _account_position_sets(account_uid: uuid.UUID | str) -> Any:
    return (
        select(
            PositionSetTable.uid.label("uid"),
            PositionSetTable.position_set_time.label("position_set_time"),
        )
        .join(
            AccountTargetAllocationTable,
            PositionSetTable.account_target_allocation_uid == AccountTargetAllocationTable.uid,
        )
        .where(AccountTargetAllocationTable.account_uid == account_uid)
        .where(PositionSetTable.position_set_time.is_not(None))
    )


def _target_rows_page(
    snapshots: Any,
    *,
    account_uid: uuid.UUID | str,
    key: Sequence[str],
    include_asset_detail: bool,
    offset: int,
    extra: Sequence[Any] = (),
) -> Any:
    """One page of the account with ``snapshots``, their rows and the rows' labels."""

    statement = (
        select(
            AccountTable.uid.label("account_uid"),
            snapshots.c.uid.label("position_set_uid"),
            snapshots.c.position_set_time.label("position_set_time"),
            *extra,
            *_labelled(TargetPositionsStorage, TARGET),
            *_labelled(
                PortfolioTable, PORTFOLIO, names=("uid", "unique_identifier", "published_index_uid")
            ),
        )
        .select_from(AccountTable)
        .outerjoin(snapshots, true())
        .outerjoin(
            TargetPositionsStorage,
            and_(
                TargetPositionsStorage.position_set_uid == snapshots.c.uid,
                TargetPositionsStorage.time_index == snapshots.c.position_set_time,
            ),
        )
        .outerjoin(PortfolioTable, PortfolioTable.uid == TargetPositionsStorage.portfolio_uid)
        .where(AccountTable.uid == account_uid)
    )
    statement = page_select(statement, key=key, offset=offset)
    if include_asset_detail:
        statement = _with_asset_references(
            statement, AssetTable.uid == TargetPositionsStorage.asset_uid, key=key
        )
    return statement


def _labelled(model: Any, prefix: str, *, names: tuple[str, ...] | None = None) -> list[Any]:
    columns = model.__table__.columns
    return [
        column.label(f"{prefix}{column.name}")
        for column in columns
        if names is None or column.name in names
    ]


def _with_asset_references(statement: Any, asset_onclause: Any, *, key: Sequence[str]) -> Any:
    """``statement``'s rows, each with its asset and that asset's latest snapshot.

    The latest snapshot times are found in one pass over the snapshots, for all the rows'
    assets, and that pass is skipped when no row names an asset. The names at those times
    are then read by key or, as PostgreSQL chooses, in a second pass. No index of the
    snapshots leads with the asset, so a lookup per asset reads a whole index, or every
    chunk's, for each. PostgreSQL turns a join or a plain ``IN`` into that when it expects
    few assets, as without statistics: ``IS true`` keeps the membership test a filter of
    the one pass, and ``MATERIALIZED`` keeps the pass from running again for each row.
    The identifiers are cast to ``TEXT`` there: PostgreSQL hashes the test only when it
    expects them to fit ``work_mem``, and it counts about 500 bytes for a ``VARCHAR(255)``,
    so a whole page would be compared row by row.

    The rows are a `page_select`, whose order ``key`` names; the join keeps that order.
    """

    identifier_label = f"{ASSET_REFERENCE}identifier"
    rows = (
        statement.add_columns(
            AssetTable.uid.label(f"{ASSET_REFERENCE}uid"),
            AssetTable.unique_identifier.label(identifier_label),
        )
        .outerjoin(AssetTable, asset_onclause)
        .cte("read_rows")
    )
    identifier = rows.c[identifier_label]
    latest = (
        select(
            AssetSnapshotsStorage.asset_identifier.label("asset_identifier"),
            func.max(AssetSnapshotsStorage.time_index).label("time_index"),
        )
        .where(
            select(identifier).where(identifier.is_not(None)).exists(),
            AssetSnapshotsStorage.asset_identifier.in_(select(cast(identifier, Text))).is_(true()),
        )
        .group_by(AssetSnapshotsStorage.asset_identifier)
        .cte("latest_asset_snapshots")
        .prefix_with("MATERIALIZED")
    )
    return (
        select(
            *rows.c,
            AssetSnapshotsStorage.name.label(f"{ASSET_REFERENCE}name"),
            AssetSnapshotsStorage.ticker.label(f"{ASSET_REFERENCE}ticker"),
        )
        .select_from(rows)
        .outerjoin(latest, latest.c.asset_identifier == identifier)
        .outerjoin(
            AssetSnapshotsStorage,
            and_(
                AssetSnapshotsStorage.asset_identifier == latest.c.asset_identifier,
                AssetSnapshotsStorage.time_index == latest.c.time_index,
            ),
        )
        .order_by(*key_order(rows.c, key))
    )


def _direction(order: SnapshotOrder) -> Any:
    if order not in {"asc", "desc"}:
        raise ValueError("order must be 'asc' or 'desc'.")
    return desc if order == "desc" else asc


def _uid_string(value: uuid.UUID | str) -> str:
    """The canonical text of a uid, as the target write keys an allocation by it."""

    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return str(value)


def _compile(statement: Any, context: MarketsRepositoryContext) -> MetaTableCompiledSQLOperation:
    return compile_markets_statement(statement, context=context, operation="select")


__all__ = [
    "ALLOCATION",
    "ASSET_REFERENCE",
    "FUND",
    "FUND_SET",
    "HOLDING",
    "PORTFOLIO",
    "TARGET",
    "account_target_snapshot_select",
    "build_account_fund_holdings_operation",
    "build_account_holdings_set_operation",
    "build_account_holdings_snapshot_operation",
    "build_account_holdings_snapshots_operation",
    "build_account_target_history_operation",
    "build_account_target_snapshot_operation",
    "build_account_with_stored_target_allocation_operation",
    "prefixed_columns",
    "read_account_fund_holdings",
    "read_account_holdings_set",
    "read_account_holdings_snapshot",
    "read_account_holdings_snapshots",
    "read_account_target_history",
    "read_account_target_snapshot",
    "read_account_with_stored_target_allocation",
]
