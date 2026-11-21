"""One-statement reads of an account's target, holdings and holdings by fund.

Each MetaTables request is a round trip, so each read here joins in one statement what
the account services used to ask for one table at a time (issue 94). Columns of the
joined tables come back under a prefix: ``target__``, ``portfolio__``, ``holding__``,
``fund__``, ``fundset__``, ``allocation__`` and ``assetref__``; `prefixed_columns` takes
one table's columns out of a row.

``assetref__`` columns are the asset of a row (``uid``, ``identifier``) and its latest
snapshot's ``name`` and ``ticker``, the asset reference the services answer with; they
are null when the asset or its snapshot does not exist.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any, Literal

from sqlalchemy import and_, asc, desc, func, select, true
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


def build_account_target_snapshot_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    order: SnapshotOrder,
    target_positions_date: dt.datetime | None,
    include_asset_detail: bool,
    limit: int,
) -> MetaTableCompiledSQLOperation:
    """One read: the account, its target snapshot, the snapshot's rows and their labels.

    The snapshot is a position set of one of the account's active target allocations:
    the one at ``target_positions_date`` (the smallest uid when several are), else the
    latest (``order="desc"``) or the earliest, ties broken by uid. The statement answers
    no row when the account does not exist; one row with null ``position_set_uid`` when
    it has no such snapshot; otherwise one row per position (null ``target__`` columns
    when the snapshot has none) with its ``portfolio__`` row and, with
    ``include_asset_detail``, its asset reference. ``limit`` bounds the rows.
    """

    candidates = (
        select(
            PositionSetTable.uid.label("uid"),
            PositionSetTable.position_set_time.label("position_set_time"),
        )
        .join(
            AccountTargetAllocationTable,
            PositionSetTable.account_target_allocation_uid == AccountTargetAllocationTable.uid,
        )
        .where(AccountTargetAllocationTable.account_uid == account_uid)
        .where(AccountTargetAllocationTable.is_active == true())
        .where(PositionSetTable.position_set_time.is_not(None))
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
    snapshot = candidates.limit(1).subquery("target_snapshot")

    columns = [
        AccountTable.uid.label("account_uid"),
        snapshot.c.uid.label("position_set_uid"),
        snapshot.c.position_set_time.label("position_set_time"),
        *_labelled(TargetPositionsStorage, TARGET),
        *_labelled(
            PortfolioTable, PORTFOLIO, names=("uid", "unique_identifier", "published_index_uid")
        ),
    ]
    if include_asset_detail:
        columns.extend(_asset_reference_columns())
    statement = (
        select(*columns)
        .select_from(AccountTable)
        .outerjoin(snapshot, true())
        .outerjoin(
            TargetPositionsStorage,
            and_(
                TargetPositionsStorage.position_set_uid == snapshot.c.uid,
                TargetPositionsStorage.time_index == snapshot.c.position_set_time,
            ),
        )
        .outerjoin(PortfolioTable, PortfolioTable.uid == TargetPositionsStorage.portfolio_uid)
    )
    if include_asset_detail:
        statement = _join_asset_references(
            statement, AssetTable.uid == TargetPositionsStorage.asset_uid
        )
    return _compile(statement.where(AccountTable.uid == account_uid).limit(limit), context)


def read_account_target_snapshot(
    context: MarketsRepositoryContext, **kwargs: Any
) -> dict[str, Any]:
    return execute_markets_operation(
        build_account_target_snapshot_operation(context, **kwargs),
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
    limit: int,
) -> MetaTableCompiledSQLOperation:
    """One read: the account and its holdings at one time, with their asset references.

    The time is ``holdings_date``, else the account's latest (``order="desc"``) or
    earliest holdings time. The statement answers no row when the account does not
    exist, one row with null ``holding__`` columns when it holds nothing at that time,
    and otherwise one row per holding. ``limit`` bounds the rows.
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
    if include_asset_detail:
        columns.extend(_asset_reference_columns())
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
    )
    if include_asset_detail:
        statement = _join_asset_references(
            statement, AssetTable.unique_identifier == AccountHoldingsStorage.asset_identifier
        )
    return _compile(statement.where(AccountTable.uid == account_uid).limit(limit), context)


def read_account_holdings_snapshot(
    context: MarketsRepositoryContext, **kwargs: Any
) -> dict[str, Any]:
    return execute_markets_operation(
        build_account_holdings_snapshot_operation(context, **kwargs),
        context=context,
    )


def build_account_holdings_set_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    order: SnapshotOrder,
    holdings_date: dt.datetime | None,
    include_asset_detail: bool,
    limit: int,
) -> MetaTableCompiledSQLOperation:
    """One read: the account, one of its holdings sets and that set's rows.

    The set is the one at ``holdings_date``, else the latest (``order="desc"``) or the
    earliest, ties broken by uid. The statement answers no row when the account does
    not exist; one row with null ``holdings_set_uid`` when it has no such set; otherwise
    one row per holding of the set (null ``holding__`` columns when it has none), with
    its asset reference under ``include_asset_detail``. ``limit`` bounds the rows.
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
    if include_asset_detail:
        columns.extend(_asset_reference_columns())
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
    )
    if include_asset_detail:
        statement = _join_asset_references(
            statement, AssetTable.unique_identifier == AccountHoldingsStorage.asset_identifier
        )
    return _compile(statement.where(AccountTable.uid == account_uid).limit(limit), context)


def read_account_holdings_set(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_account_holdings_set_operation(context, **kwargs),
        context=context,
    )


def build_account_fund_holdings_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    source_account_holdings_set_uid: uuid.UUID | str,
    include_asset_detail: bool,
    limit: int,
) -> MetaTableCompiledSQLOperation:
    """One read: the account's virtual funds with what each holds from one holdings set.

    Each fund comes with its ``fundset__`` holdings set funded by
    ``source_account_holdings_set_uid`` (at most one: the pair is unique) and its
    ``allocation__`` rows from that set, one row each, or one row with null
    ``allocation__`` columns when it has none; with ``include_asset_detail``, each row's
    asset reference. ``limit`` bounds the rows.
    """

    columns = [
        *_labelled(VirtualFundTable, FUND),
        *_labelled(VirtualFundHoldingsSetTable, FUND_SET),
        *_labelled(VirtualFundHoldingsStorage, ALLOCATION),
    ]
    if include_asset_detail:
        columns.extend(_asset_reference_columns())
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
    )
    if include_asset_detail:
        statement = _join_asset_references(
            statement,
            AssetTable.unique_identifier == VirtualFundHoldingsStorage.asset_identifier,
        )
    return _compile(
        statement.where(VirtualFundTable.account_uid == account_uid).limit(limit), context
    )


def read_account_fund_holdings(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_account_fund_holdings_operation(context, **kwargs),
        context=context,
    )


def _labelled(model: Any, prefix: str, *, names: tuple[str, ...] | None = None) -> list[Any]:
    columns = model.__table__.columns
    return [
        column.label(f"{prefix}{column.name}")
        for column in columns
        if names is None or column.name in names
    ]


def _asset_reference_columns() -> list[Any]:
    return [
        AssetTable.uid.label(f"{ASSET_REFERENCE}uid"),
        AssetTable.unique_identifier.label(f"{ASSET_REFERENCE}identifier"),
        AssetSnapshotsStorage.name.label(f"{ASSET_REFERENCE}name"),
        AssetSnapshotsStorage.ticker.label(f"{ASSET_REFERENCE}ticker"),
    ]


def _join_asset_references(statement: Any, asset_onclause: Any) -> Any:
    """Left-join each row's asset (``asset_onclause``) and the asset's latest snapshot."""

    snapshots = aliased(AssetSnapshotsStorage, name="asset_snapshot_times")
    latest_snapshot_time = (
        select(func.max(snapshots.time_index))
        .where(snapshots.asset_identifier == AssetTable.unique_identifier)
        .scalar_subquery()
    )
    return statement.outerjoin(AssetTable, asset_onclause).outerjoin(
        AssetSnapshotsStorage,
        and_(
            AssetSnapshotsStorage.asset_identifier == AssetTable.unique_identifier,
            AssetSnapshotsStorage.time_index == latest_snapshot_time,
        ),
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
    "build_account_fund_holdings_operation",
    "build_account_holdings_set_operation",
    "build_account_holdings_snapshot_operation",
    "build_account_target_snapshot_operation",
    "build_account_with_stored_target_allocation_operation",
    "prefixed_columns",
    "read_account_fund_holdings",
    "read_account_holdings_set",
    "read_account_holdings_snapshot",
    "read_account_target_snapshot",
    "read_account_with_stored_target_allocation",
]
