from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    JSON,
    SmallInteger,
    String,
    Uuid,
    bindparam,
    case,
    cast,
    column,
    delete,
    false,
    func,
    insert,
    literal,
    null,
    or_,
    select,
    true,
    union_all,
    update,
    values,
)
from sqlalchemy import and_
from sqlalchemy.dialects.postgresql import JSONB, insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import aliased

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from msm.time_index.accounts.constants import TARGET_TYPE_PORTFOLIO
from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm.models import (
    AccountHoldingsSetTable,
    AccountAllocationModelTable,
    AccountTable,
    AccountTargetAllocationTable,
    AssetTable,
    PortfolioTable,
    PositionSetTable,
)

from .base import (
    MarketsCompiledWrite,
    MarketsRepositoryContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
)
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_search_model_operation,
    mirror_renamed_columns,
    renamed_keyword,
)

# Guard labels of the SQLite statement lists. Each marks a write the single
# PostgreSQL statement would also have refused by writing nothing.
LIVE_PORTFOLIOS_GUARD = "live_portfolios"
POSITION_SET_GUARD = "position_set"
HOLDINGS_SET_GUARD = "holdings_set"


def build_create_account_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    account_name: str,
    is_paper: bool = True,
    account_is_active: bool = False,
    account_group_uid: uuid.UUID | str | None = None,
    holdings_storage_table_uid: uuid.UUID | str | None = None,
    metadata_json: MappingOrDict | None = None,
    holdings_data_node_uid: uuid.UUID | str | None = None,
) -> MetaTableCompiledSQLOperation:
    holdings_storage_table_uid = renamed_keyword(
        holdings_storage_table_uid,
        holdings_data_node_uid,
        current="holdings_storage_table_uid",
        previous="holdings_data_node_uid",
    )
    statement = (
        insert(AccountTable)
        .values(
            **mirror_renamed_columns(
                AccountTable,
                {
                    "unique_identifier": unique_identifier,
                    "account_name": account_name,
                    "is_paper": is_paper,
                    "account_is_active": account_is_active,
                    "account_group_uid": account_group_uid,
                    "holdings_storage_table_uid": holdings_storage_table_uid,
                    "metadata_json": metadata_json,
                },
            )
        )
        .returning(AccountTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
    )


def create_account(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_account_operation(context, **kwargs),
        context=context,
    )


def build_get_account_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(AccountTable).where(AccountTable.unique_identifier == unique_identifier).limit(1)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def get_account_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_account_by_unique_identifier_operation(
            context,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_get_account_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=AccountTable, uid=uid)


def get_account_by_uid(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_account_by_uid_operation(context, uid=uid),
        context=context,
    )


def build_search_accounts_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier_contains: str | None = None,
    account_name_contains: str | None = None,
    account_is_active: bool | None = None,
    account_group_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    statement = select(AccountTable).limit(limit)
    if unique_identifier_contains not in (None, ""):
        statement = statement.where(
            AccountTable.unique_identifier.contains(str(unique_identifier_contains))
        )
    if account_name_contains not in (None, ""):
        statement = statement.where(AccountTable.account_name.contains(str(account_name_contains)))
    if account_is_active is not None:
        statement = statement.where(AccountTable.account_is_active.is_(bool(account_is_active)))
    if account_group_uid is not None:
        statement = statement.where(AccountTable.account_group_uid == account_group_uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def search_accounts(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_accounts_operation(context, **kwargs),
        context=context,
    )


def build_update_account_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    account_name: str | None = None,
    is_paper: bool | None = None,
    account_is_active: bool | None = None,
    account_group_uid: uuid.UUID | str | None = None,
    holdings_storage_table_uid: uuid.UUID | str | None = None,
    metadata_json: MappingOrDict | None = None,
    holdings_data_node_uid: uuid.UUID | str | None = None,
) -> MetaTableCompiledSQLOperation:
    holdings_storage_table_uid = renamed_keyword(
        holdings_storage_table_uid,
        holdings_data_node_uid,
        current="holdings_storage_table_uid",
        previous="holdings_data_node_uid",
    )
    values = mirror_renamed_columns(
        AccountTable,
        {
            key: value
            for key, value in {
                "account_name": account_name,
                "is_paper": is_paper,
                "account_is_active": account_is_active,
                "account_group_uid": account_group_uid,
                "holdings_storage_table_uid": holdings_storage_table_uid,
                "metadata_json": metadata_json,
            }.items()
            if value is not None
        },
    )
    statement = (
        update(AccountTable).where(AccountTable.uid == uid).values(**values).returning(AccountTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
    )


def update_account(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_account_operation(context, **kwargs),
        context=context,
    )


def build_delete_account_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(AccountTable).where(AccountTable.uid == uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
    )


def delete_account(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_account_operation(context, uid=uid),
        context=context,
    )


def build_create_account_target_allocation_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    account_uid: uuid.UUID | str,
    account_allocation_model_uid: uuid.UUID | str,
    display_name: str | None = None,
    is_active: bool = True,
    source: str | None = None,
    metadata_json: MappingOrDict | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AccountTargetAllocationTable,
        values={
            "unique_identifier": unique_identifier,
            "account_uid": account_uid,
            "account_allocation_model_uid": account_allocation_model_uid,
            "display_name": display_name,
            "is_active": is_active,
            "source": source,
            "metadata_json": metadata_json,
        },
    )


def create_account_target_allocation(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_account_target_allocation_operation(context, **kwargs),
        context=context,
    )


def build_search_account_target_allocations_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str | None = None,
    account_uid: uuid.UUID | str | None = None,
    account_allocation_model_uid: uuid.UUID | str | None = None,
    is_active: bool | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "unique_identifier": unique_identifier,
        "account_uid": account_uid,
        "account_allocation_model_uid": account_allocation_model_uid,
        "is_active": is_active,
    }.items():
        if value is not None and value != "":
            filters[key] = value
    return build_search_model_operation(
        context,
        model=AccountTargetAllocationTable,
        filters=filters,
        limit=limit,
    )


def search_account_target_allocations(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_account_target_allocations_operation(context, **kwargs),
        context=context,
    )


def build_search_account_target_allocation_candidates_operation(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    target_type: str = "all",
    limit: int = 25,
    offset: int = 0,
    include_retired: bool = False,
) -> MetaTableCompiledSQLOperation:
    normalized_target_type = target_type.lower()
    if normalized_target_type not in {"all", "asset", "portfolio"}:
        raise ValueError("target_type must be one of: all, asset, portfolio.")
    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1.")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0.")

    branches = []
    if normalized_target_type in {"all", "asset"}:
        branches.append(_account_target_asset_candidate_select(search=search))
    if normalized_target_type in {"all", "portfolio"}:
        branches.append(
            _account_target_portfolio_candidate_select(
                search=search,
                include_retired=include_retired,
            )
        )

    if len(branches) == 1:
        candidates = branches[0].cte("account_target_allocation_candidates")
    else:
        candidates = union_all(*branches).cte("account_target_allocation_candidates")

    candidate_columns = [
        candidates.c.target_type,
        candidates.c.target_uid,
        candidates.c.asset_uid,
        candidates.c.portfolio_uid,
        candidates.c.identifier,
        candidates.c.display_label,
        candidates.c.secondary_label,
        candidates.c.snapshot_name,
        candidates.c.snapshot_ticker,
        candidates.c.asset_type,
        candidates.c.published_index_uid,
    ]
    paged_candidates = (
        select(*candidate_columns)
        .select_from(candidates)
        .order_by(
            candidates.c.target_type,
            candidates.c.display_label,
            candidates.c.identifier,
            candidates.c.target_uid,
        )
        .limit(limit)
        .offset(offset)
        .cte("paged_account_target_allocation_candidates")
    )
    count_branch = select(
        literal("__count__").label("row_kind"),
        cast(null(), String).label("target_type"),
        cast(null(), String).label("target_uid"),
        cast(null(), String).label("asset_uid"),
        cast(null(), String).label("portfolio_uid"),
        cast(null(), String).label("identifier"),
        cast(null(), String).label("display_label"),
        cast(null(), String).label("secondary_label"),
        cast(null(), String).label("snapshot_name"),
        cast(null(), String).label("snapshot_ticker"),
        cast(null(), String).label("asset_type"),
        cast(null(), String).label("published_index_uid"),
        func.count().label("total_count"),
    ).select_from(candidates)
    data_branch = select(
        literal("data").label("row_kind"),
        paged_candidates.c.target_type,
        paged_candidates.c.target_uid,
        paged_candidates.c.asset_uid,
        paged_candidates.c.portfolio_uid,
        paged_candidates.c.identifier,
        paged_candidates.c.display_label,
        paged_candidates.c.secondary_label,
        paged_candidates.c.snapshot_name,
        paged_candidates.c.snapshot_ticker,
        paged_candidates.c.asset_type,
        paged_candidates.c.published_index_uid,
        cast(null(), Integer).label("total_count"),
    ).select_from(paged_candidates)
    statement = union_all(count_branch, data_branch)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def search_account_target_allocation_candidates(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_account_target_allocation_candidates_operation(context, **kwargs),
        context=context,
    )


def _account_target_asset_candidate_select(*, search: str):
    latest_snapshots = _latest_asset_snapshots_subquery()
    statement = select(
        literal("asset").label("target_type"),
        cast(AssetTable.uid, String).label("target_uid"),
        cast(AssetTable.uid, String).label("asset_uid"),
        cast(null(), String).label("portfolio_uid"),
        AssetTable.unique_identifier.label("identifier"),
        func.coalesce(
            latest_snapshots.c.snapshot_name,
            AssetTable.unique_identifier,
        ).label("display_label"),
        latest_snapshots.c.snapshot_ticker.label("secondary_label"),
        latest_snapshots.c.snapshot_name.label("snapshot_name"),
        latest_snapshots.c.snapshot_ticker.label("snapshot_ticker"),
        AssetTable.asset_type.label("asset_type"),
        cast(null(), String).label("published_index_uid"),
    ).select_from(
        AssetTable.__table__.outerjoin(
            latest_snapshots,
            latest_snapshots.c.asset_identifier == AssetTable.unique_identifier,
        )
    )
    normalized_search = search.strip().lower()
    if normalized_search:
        needle = f"%{normalized_search}%"
        statement = statement.where(
            or_(
                func.lower(cast(AssetTable.uid, String)).like(needle),
                func.lower(AssetTable.unique_identifier).like(needle),
                func.lower(cast(AssetTable.asset_type, String)).like(needle),
                func.lower(cast(latest_snapshots.c.snapshot_name, String)).like(needle),
                func.lower(cast(latest_snapshots.c.snapshot_ticker, String)).like(needle),
            )
        )
    return statement


def _account_target_portfolio_candidate_select(*, search: str, include_retired: bool = False):
    statement = select(
        literal("portfolio").label("target_type"),
        cast(PortfolioTable.uid, String).label("target_uid"),
        cast(null(), String).label("asset_uid"),
        cast(PortfolioTable.uid, String).label("portfolio_uid"),
        PortfolioTable.unique_identifier.label("identifier"),
        PortfolioTable.unique_identifier.label("display_label"),
        cast(null(), String).label("secondary_label"),
        cast(null(), String).label("snapshot_name"),
        cast(null(), String).label("snapshot_ticker"),
        cast(null(), String).label("asset_type"),
        cast(PortfolioTable.published_index_uid, String).label("published_index_uid"),
    )
    if not include_retired:
        statement = statement.where(PortfolioTable.retired_at.is_(None))
    normalized_search = search.strip().lower()
    if normalized_search:
        needle = f"%{normalized_search}%"
        statement = statement.where(
            or_(
                func.lower(cast(PortfolioTable.uid, String)).like(needle),
                func.lower(PortfolioTable.unique_identifier).like(needle),
                func.lower(cast(PortfolioTable.published_index_uid, String)).like(needle),
            )
        )
    return statement


def _latest_asset_snapshots_subquery():
    ranked = (
        select(
            AssetSnapshotsStorage.asset_identifier.label("asset_identifier"),
            AssetSnapshotsStorage.name.label("snapshot_name"),
            AssetSnapshotsStorage.ticker.label("snapshot_ticker"),
            func.row_number()
            .over(
                partition_by=AssetSnapshotsStorage.asset_identifier,
                order_by=AssetSnapshotsStorage.time_index.desc(),
            )
            .label("snapshot_rank"),
        )
        .select_from(AssetSnapshotsStorage)
        .subquery("ranked_asset_snapshots")
    )
    return (
        select(
            ranked.c.asset_identifier,
            ranked.c.snapshot_name,
            ranked.c.snapshot_ticker,
        )
        .where(ranked.c.snapshot_rank == 1)
        .subquery("latest_asset_snapshots")
    )


def build_delete_account_target_allocation_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(
        context,
        model=AccountTargetAllocationTable,
        uid=uid,
    )


def delete_account_target_allocation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_account_target_allocation_operation(context, uid=uid),
        context=context,
    )


def build_create_position_set_operation(
    context: MarketsRepositoryContext,
    *,
    account_target_allocation_uid: uuid.UUID | str,
    position_set_time: dt.datetime | str,
    source: str | None = None,
    metadata_json: MappingOrDict | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=PositionSetTable,
        values={
            "account_target_allocation_uid": account_target_allocation_uid,
            "position_set_time": _utc_timestamp(
                position_set_time,
                field_name="position_set_time",
            ),
            "source": source,
            "metadata_json": metadata_json,
        },
    )


def create_position_set(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_position_set_operation(context, **kwargs),
        context=context,
    )


def build_search_position_sets_operation(
    context: MarketsRepositoryContext,
    *,
    account_target_allocation_uid: uuid.UUID | str | None = None,
    position_set_time: dt.datetime | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "account_target_allocation_uid": account_target_allocation_uid,
        "position_set_time": (
            _utc_timestamp(position_set_time, field_name="position_set_time")
            if position_set_time is not None
            else None
        ),
    }.items():
        if value is not None and value != "":
            filters[key] = value
    return build_search_model_operation(
        context,
        model=PositionSetTable,
        filters=filters,
        limit=limit,
    )


def search_position_sets(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_position_sets_operation(context, **kwargs),
        context=context,
    )


def build_delete_position_set_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(
        context,
        model=PositionSetTable,
        uid=uid,
    )


def delete_position_set(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_position_set_operation(context, uid=uid),
        context=context,
    )


def current_portfolio_target_rows_select(*, portfolio_uid: Any):
    """Select the target rows that name a portfolio in each account's current target.

    An account's current target is the latest ``PositionSet`` across its active
    ``AccountTargetAllocation`` rows, ties broken by the higher ``PositionSet`` uid,
    which is what ``GET /api/v1/account/{account_uid}/target-positions/`` reads.
    An account that named the portfolio only in an earlier snapshot, or whose
    target was cleared, has no row. The scan starts from the ``portfolio_uid``
    index of ``TargetPositionsStorage``.

    ``portfolio_uid`` is a value or a SQL expression. Each result row carries
    ``account_uid``, ``account_target_allocation_uid``, ``position_set_uid``,
    ``target_positions_date`` and the row's exposure columns.
    """

    later_position_set = aliased(PositionSetTable, name="later_position_set")
    later_allocation = aliased(AccountTargetAllocationTable, name="later_allocation")
    later_snapshot = (
        select(later_position_set.uid)
        .join(
            later_allocation,
            later_position_set.account_target_allocation_uid == later_allocation.uid,
        )
        .where(later_allocation.account_uid == AccountTargetAllocationTable.account_uid)
        .where(later_allocation.is_active.is_(True))
        .where(
            or_(
                later_position_set.position_set_time > PositionSetTable.position_set_time,
                and_(
                    later_position_set.position_set_time == PositionSetTable.position_set_time,
                    later_position_set.uid > PositionSetTable.uid,
                ),
            )
        )
    )
    return (
        select(
            AccountTargetAllocationTable.account_uid.label("account_uid"),
            AccountTargetAllocationTable.uid.label("account_target_allocation_uid"),
            PositionSetTable.uid.label("position_set_uid"),
            PositionSetTable.position_set_time.label("target_positions_date"),
            TargetPositionsStorage.weight_notional_exposure.label("weight_notional_exposure"),
            TargetPositionsStorage.constant_notional_exposure.label(
                "constant_notional_exposure"
            ),
        )
        .select_from(TargetPositionsStorage)
        .join(PositionSetTable, PositionSetTable.uid == TargetPositionsStorage.position_set_uid)
        .join(
            AccountTargetAllocationTable,
            AccountTargetAllocationTable.uid == PositionSetTable.account_target_allocation_uid,
        )
        .where(TargetPositionsStorage.target_type == TARGET_TYPE_PORTFOLIO)
        .where(TargetPositionsStorage.portfolio_uid == portfolio_uid)
        .where(TargetPositionsStorage.time_index == PositionSetTable.position_set_time)
        .where(AccountTargetAllocationTable.is_active.is_(True))
        .where(~later_snapshot.exists())
    )


def _portfolio_uid_param(portfolio_uid: uuid.UUID | str):
    return bindparam(
        "portfolio_uid",
        value=uuid.UUID(str(portfolio_uid)),
        type_=Uuid(as_uuid=True),
    )


def build_search_portfolio_account_targets_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID | str,
    limit: int = 100,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """Page the accounts whose current target names a portfolio, ordered by account uid."""

    current = current_portfolio_target_rows_select(
        portfolio_uid=_portfolio_uid_param(portfolio_uid)
    ).subquery("current_portfolio_targets")
    statement = (
        select(current)
        .order_by(current.c.account_uid, current.c.position_set_uid)
        .limit(limit)
        .offset(offset)
    )
    return compile_markets_statement(statement, context=context, operation="select")


def build_count_portfolio_account_targets_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    """Count the accounts whose current target names a portfolio."""

    current = current_portfolio_target_rows_select(
        portfolio_uid=_portfolio_uid_param(portfolio_uid)
    ).subquery("current_portfolio_targets")
    statement = select(func.count().label("count")).select_from(current)
    return compile_markets_statement(statement, context=context, operation="select")


def search_portfolio_account_targets(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_portfolio_account_targets_operation(context, **kwargs),
        context=context,
    )


def count_portfolio_account_targets(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_count_portfolio_account_targets_operation(context, **kwargs),
        context=context,
    )


def build_replace_account_holdings_snapshot_operation(
    context: MarketsRepositoryContext,
    *,
    holdings_set_uid: uuid.UUID | str,
    account_uid: uuid.UUID | str,
    holdings_date: dt.datetime | str,
    positions: Sequence[Mapping[str, Any]],
    overwrite: bool = False,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Write one account holdings snapshot atomically.

    On PostgreSQL this is one statement. SQLite accepts only `SELECT` inside
    `WITH`, so there the same steps run as a statement list in one transaction
    (MetaTables ADR 0026). Either way the write returns the inserted rows, and
    nothing when the snapshot exists and `overwrite` is false.
    """

    if not positions:
        raise ValueError("Account holdings snapshot replacement requires positions.")

    normalized_holdings_date = _utc_timestamp(holdings_date, field_name="holdings_date")
    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    if dialect == "sqlite":
        return compile_markets_statements(
            _holdings_snapshot_statement_list(
                holdings_set_uid=holdings_set_uid,
                account_uid=account_uid,
                holdings_date=normalized_holdings_date,
                positions=positions,
                overwrite=overwrite,
            ),
            context=context,
            operation="upsert",
            data_source_uid=data_source_uid,
            dialect=dialect,
        )
    holdings_set_uid_param = bindparam(
        "holdings_set_uid",
        value=uuid.UUID(str(holdings_set_uid)),
        type_=Uuid(as_uuid=True),
    )
    account_uid_param = bindparam(
        "account_uid",
        value=uuid.UUID(str(account_uid)),
        type_=Uuid(as_uuid=True),
    )
    holdings_date_param = bindparam(
        "holdings_date",
        value=normalized_holdings_date,
        type_=DateTime(timezone=True),
    )
    overwrite_param = bindparam("overwrite", value=bool(overwrite))

    holdings_set = (
        postgresql_insert(AccountHoldingsSetTable)
        .values(
            uid=cast(holdings_set_uid_param, Uuid(as_uuid=True)),
            account_uid=cast(account_uid_param, Uuid(as_uuid=True)),
            time_index=cast(holdings_date_param, DateTime(timezone=True)),
        )
        .on_conflict_do_update(
            index_elements=[
                AccountHoldingsSetTable.account_uid,
                AccountHoldingsSetTable.time_index,
            ],
            set_={
                "time_index": cast(
                    bindparam(
                        "holdings_date",
                        value=normalized_holdings_date,
                        type_=DateTime(timezone=True),
                    ),
                    DateTime(timezone=True),
                )
            },
            where=overwrite_param,
        )
        .returning(AccountHoldingsSetTable.uid)
        .cte("holdings_set")
    )

    input_row_values = []
    for index, position in enumerate(positions):
        target_trade_time = _utc_timestamp(
            position.get("target_trade_time") or normalized_holdings_date,
            field_name=f"positions[{index}].target_trade_time",
        )
        input_row_values.append(
            (
                bindparam(
                    f"asset_identifier_{index}",
                    value=str(position["asset_identifier"]),
                    type_=String(),
                ),
                cast(
                    bindparam(
                        f"quantity_{index}",
                        value=_python_scalar(position.get("quantity")),
                        type_=Float(),
                    ),
                    Float(),
                ),
                cast(
                    bindparam(
                        f"direction_{index}",
                        value=int(position.get("direction", 1)),
                        type_=SmallInteger(),
                    ),
                    SmallInteger(),
                ),
                cast(
                    bindparam(
                        f"target_trade_time_{index}",
                        value=target_trade_time,
                        type_=DateTime(timezone=True),
                    ),
                    DateTime(timezone=True),
                ),
                cast(
                    bindparam(
                        f"extra_details_{index}",
                        value=position.get("extra_details") or {},
                        type_=JSONB(),
                    ),
                    JSONB(),
                ),
            )
        )

    input_rows = (
        values(
            column("asset_identifier", String()),
            column("quantity", Float()),
            column("direction", SmallInteger()),
            column("target_trade_time", DateTime(timezone=True)),
            column("extra_details", JSONB()),
            name="input_rows",
        )
        .data(input_row_values)
        .cte("input_rows")
    )
    deleted = (
        delete(AccountHoldingsStorage)
        .where(overwrite_param)
        .where(AccountHoldingsStorage.holdings_set_uid == holdings_set.c.uid)
        .returning(true())
        .cte("deleted")
    )
    deleted_gate = (
        select(func.count().label("deleted_count")).select_from(deleted).cte("deleted_gate")
    )
    statement = (
        insert(AccountHoldingsStorage)
        .from_select(
            [
                "time_index",
                "account_uid",
                "asset_identifier",
                "holdings_set_uid",
                "is_trade_snapshot",
                "quantity",
                "direction",
                "target_trade_time",
                "extra_details",
            ],
            select(
                cast(holdings_date_param, DateTime(timezone=True)),
                cast(account_uid_param, Uuid(as_uuid=True)),
                input_rows.c.asset_identifier,
                holdings_set.c.uid,
                false(),
                input_rows.c.quantity,
                input_rows.c.direction,
                input_rows.c.target_trade_time,
                input_rows.c.extra_details,
            ).select_from(input_rows.join(holdings_set, true()).join(deleted_gate, true())),
        )
        .returning(AccountHoldingsStorage)
        .add_cte(holdings_set)
        .add_cte(deleted)
        .add_cte(deleted_gate)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="upsert",
        dialect=dialect,
        data_source_uid=data_source_uid,
    )


def _holdings_snapshot_statement_list(
    *,
    holdings_set_uid: uuid.UUID | str,
    account_uid: uuid.UUID | str,
    holdings_date: dt.datetime,
    positions: Sequence[Mapping[str, Any]],
    overwrite: bool,
) -> list[GuardedStatement | Any]:
    """The holdings snapshot write as ordered statements for one transaction.

    Upsert the holdings set, refused by the `holdings_set` guard when it exists
    and `overwrite` is false; with `overwrite`, delete its rows; insert the new
    rows. Later statements find the set by its key. Values bind without casts:
    SQLite casts `DATETIME` and `JSON` to numbers.
    """

    account = uuid.UUID(str(account_uid))

    def account_param() -> Any:
        return bindparam("account_uid", value=account, type_=Uuid(as_uuid=True))

    def holdings_date_param() -> Any:
        return bindparam("holdings_date", value=holdings_date, type_=DateTime(timezone=True))

    def overwrite_param() -> Any:
        return bindparam("overwrite", value=bool(overwrite), type_=Boolean())

    def holdings_set_lookup() -> Any:
        return (
            select(AccountHoldingsSetTable.uid)
            .where(AccountHoldingsSetTable.account_uid == account_param())
            .where(AccountHoldingsSetTable.time_index == holdings_date_param())
            .scalar_subquery()
        )

    holdings_set_insert = sqlite_insert(AccountHoldingsSetTable).values(
        uid=bindparam(
            "holdings_set_uid", value=uuid.UUID(str(holdings_set_uid)), type_=Uuid(as_uuid=True)
        ),
        account_uid=account_param(),
        time_index=holdings_date_param(),
    )
    upsert_holdings_set = GuardedStatement(
        holdings_set_insert.on_conflict_do_update(
            index_elements=[AccountHoldingsSetTable.account_uid, AccountHoldingsSetTable.time_index],
            set_={"time_index": holdings_set_insert.excluded.time_index},
            where=overwrite_param(),
        ).returning(AccountHoldingsSetTable.uid),
        expect_rows=1,
        label=HOLDINGS_SET_GUARD,
    )
    remove_rows = (
        delete(AccountHoldingsStorage)
        .where(overwrite_param())
        .where(AccountHoldingsStorage.holdings_set_uid == holdings_set_lookup())
    )

    input_rows = (
        values(
            column("asset_identifier", String()),
            column("quantity", Float()),
            column("direction", SmallInteger()),
            column("target_trade_time", DateTime(timezone=True)),
            column("extra_details", JSON()),
            name="input_rows",
        )
        .data(
            [
                (
                    bindparam(
                        f"asset_identifier_{index}",
                        value=str(position["asset_identifier"]),
                        type_=String(),
                    ),
                    bindparam(
                        f"quantity_{index}",
                        value=_python_scalar(position.get("quantity")),
                        type_=Float(),
                    ),
                    bindparam(
                        f"direction_{index}",
                        value=int(position.get("direction", 1)),
                        type_=SmallInteger(),
                    ),
                    bindparam(
                        f"target_trade_time_{index}",
                        value=_utc_timestamp(
                            position.get("target_trade_time") or holdings_date,
                            field_name=f"positions[{index}].target_trade_time",
                        ),
                        type_=DateTime(timezone=True),
                    ),
                    bindparam(
                        f"extra_details_{index}",
                        value=position.get("extra_details") or {},
                        type_=JSON(),
                    ),
                )
                for index, position in enumerate(positions)
            ]
        )
        .cte("input_rows")
    )
    insert_rows = (
        insert(AccountHoldingsStorage)
        .from_select(
            [
                "time_index",
                "account_uid",
                "asset_identifier",
                "holdings_set_uid",
                "is_trade_snapshot",
                "quantity",
                "direction",
                "target_trade_time",
                "extra_details",
            ],
            select(
                holdings_date_param(),
                account_param(),
                input_rows.c.asset_identifier,
                holdings_set_lookup(),
                false(),
                input_rows.c.quantity,
                input_rows.c.direction,
                input_rows.c.target_trade_time,
                input_rows.c.extra_details,
            ).select_from(input_rows),
        )
        .returning(AccountHoldingsStorage)
    )
    return [upsert_holdings_set, remove_rows, insert_rows]


def replace_account_holdings_snapshot(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_write(
        build_replace_account_holdings_snapshot_operation(context, **kwargs),
        context=context,
        refused_by=(HOLDINGS_SET_GUARD,),
    )


def build_replace_account_target_positions_snapshot_operation(
    context: MarketsRepositoryContext,
    *,
    account_allocation_model_uid: uuid.UUID | str,
    account_target_allocation_uid: uuid.UUID | str,
    position_set_uid: uuid.UUID | str,
    account_uid: uuid.UUID | str,
    account_name: str,
    target_positions_date: dt.datetime | str,
    positions: Sequence[Mapping[str, Any]],
    overwrite: bool = False,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Write one account target-position snapshot atomically.

    On PostgreSQL this is one statement. SQLite accepts only `SELECT` inside
    `WITH`, so there the same steps run as a statement list in one transaction
    (MetaTables ADR 0026), and a refused write changes nothing at all.

    With positions, the account's target allocation becomes active and the
    snapshot's rows replace any rows at ``target_positions_date``. With no
    positions, the target is cleared: an empty ``PositionSet`` is written at
    ``target_positions_date`` and the target allocation becomes inactive, so
    the target's history records when it was cleared.

    The allocation's ``is_active`` changes only when the snapshot write goes
    through; a refused write (the snapshot exists and ``overwrite`` is false)
    leaves it as it was. The statement returns the inserted target rows, or
    the cleared ``PositionSet`` uid, and nothing when the write was refused.

    A snapshot that names a retired portfolio is refused whatever its date
    (ADR 0049): the statement locks the named ``Portfolio`` rows ``FOR SHARE``
    and writes nothing unless every one is live, so it cannot interleave with a
    retirement of one of them. On SQLite the transaction holds the database's
    write lock instead, and the ``live_portfolios`` guard refuses the write.
    """

    clearing = not positions
    normalized_target_positions_date = _utc_timestamp(
        target_positions_date,
        field_name="target_positions_date",
    )
    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    if dialect == "sqlite":
        return compile_markets_statements(
            _target_positions_snapshot_statement_list(
                account_allocation_model_uid=account_allocation_model_uid,
                account_target_allocation_uid=account_target_allocation_uid,
                position_set_uid=position_set_uid,
                account_uid=account_uid,
                account_name=account_name,
                target_positions_date=normalized_target_positions_date,
                positions=positions,
                overwrite=overwrite,
            ),
            context=context,
            operation="upsert",
            data_source_uid=data_source_uid,
            dialect=dialect,
        )
    account_uid_param = bindparam(
        "account_uid",
        value=uuid.UUID(str(account_uid)),
        type_=Uuid(as_uuid=True),
    )
    account_name_param = bindparam("account_name", value=str(account_name), type_=String())
    target_positions_date_param = bindparam(
        "target_positions_date",
        value=normalized_target_positions_date,
        type_=DateTime(timezone=True),
    )
    overwrite_param = bindparam("overwrite", value=bool(overwrite))
    is_active_param = bindparam("is_active", value=not clearing, type_=Boolean())
    existing_allocation = AccountTargetAllocationTable.__table__.alias("existing_allocation")
    existing_position_set = PositionSetTable.__table__.alias("existing_position_set")
    snapshot_exists = (
        select(existing_position_set.c.uid)
        .join(
            existing_allocation,
            existing_position_set.c.account_target_allocation_uid == existing_allocation.c.uid,
        )
        .where(existing_allocation.c.unique_identifier == cast(account_uid_param, String()))
        .where(
            existing_position_set.c.position_set_time
            == cast(target_positions_date_param, DateTime(timezone=True))
        )
        .exists()
    )

    account_allocation_model = (
        postgresql_insert(AccountAllocationModelTable)
        .values(
            uid=cast(
                bindparam(
                    "account_allocation_model_uid",
                    value=uuid.UUID(str(account_allocation_model_uid)),
                    type_=Uuid(as_uuid=True),
                ),
                Uuid(as_uuid=True),
            ),
            allocation_model_name=cast(account_uid_param, String()),
            allocation_model_description=(
                f"Default target allocation model for account {uuid.UUID(str(account_uid))!s}"
            ),
            metadata_json=cast(
                bindparam(
                    "account_allocation_model_metadata_json",
                    value={"source": "apps.v1"},
                    type_=JSON(),
                ),
                JSON(),
            ),
        )
        .on_conflict_do_update(
            index_elements=[AccountAllocationModelTable.allocation_model_name],
            set_={
                "allocation_model_description": (
                    f"Default target allocation model for account {uuid.UUID(str(account_uid))!s}"
                ),
                "metadata_json": cast(
                    bindparam(
                        "account_allocation_model_metadata_json",
                        value={"source": "apps.v1"},
                        type_=JSON(),
                    ),
                    JSON(),
                ),
            },
        )
        .returning(AccountAllocationModelTable.uid)
        .cte("account_allocation_model")
    )
    named_portfolio_uids = sorted(
        {
            uuid.UUID(str(position["portfolio_uid"]))
            for position in positions
            if position.get("portfolio_uid") not in (None, "")
        }
    )
    live_portfolio_gate = None
    if named_portfolio_uids:
        live_portfolios = (
            select(PortfolioTable.uid)
            .where(PortfolioTable.uid.in_(named_portfolio_uids))
            .where(PortfolioTable.retired_at.is_(None))
            .with_for_update(read=True)
            .cte("live_portfolios")
        )
        live_portfolio_gate = select(func.count()).select_from(
            live_portfolios
        ).scalar_subquery() == literal(len(named_portfolio_uids))
    account_target_allocation_values = select(
        cast(
            bindparam(
                "account_target_allocation_uid",
                value=uuid.UUID(str(account_target_allocation_uid)),
                type_=Uuid(as_uuid=True),
            ),
            Uuid(as_uuid=True),
        ),
        cast(account_uid_param, String()),
        cast(account_uid_param, Uuid(as_uuid=True)),
        account_allocation_model.c.uid,
        account_name_param,
        is_active_param,
        literal("apps.v1"),
        cast(
            bindparam(
                "account_target_allocation_metadata_json",
                value={},
                type_=JSON(),
            ),
            JSON(),
        ),
    ).select_from(account_allocation_model)
    if live_portfolio_gate is not None:
        account_target_allocation_values = account_target_allocation_values.where(
            live_portfolio_gate
        )
    account_target_allocation_insert = postgresql_insert(AccountTargetAllocationTable).from_select(
        [
            "uid",
            "unique_identifier",
            "account_uid",
            "account_allocation_model_uid",
            "display_name",
            "is_active",
            "source",
            "metadata_json",
        ],
        account_target_allocation_values,
    )
    account_target_allocation = (
        account_target_allocation_insert.on_conflict_do_update(
            index_elements=[AccountTargetAllocationTable.unique_identifier],
            set_={
                "account_uid": account_target_allocation_insert.excluded.account_uid,
                "account_allocation_model_uid": (
                    account_target_allocation_insert.excluded.account_allocation_model_uid
                ),
                "display_name": account_target_allocation_insert.excluded.display_name,
                "is_active": case(
                    (
                        or_(overwrite_param, ~snapshot_exists),
                        account_target_allocation_insert.excluded.is_active,
                    ),
                    else_=AccountTargetAllocationTable.is_active,
                ),
                "source": account_target_allocation_insert.excluded.source,
                "metadata_json": account_target_allocation_insert.excluded.metadata_json,
            },
        )
        .returning(AccountTargetAllocationTable.uid)
        .cte("account_target_allocation")
    )
    position_set_insert = postgresql_insert(PositionSetTable).from_select(
        [
            "uid",
            "account_target_allocation_uid",
            "position_set_time",
            "source",
            "metadata_json",
        ],
        select(
            cast(
                bindparam(
                    "position_set_uid",
                    value=uuid.UUID(str(position_set_uid)),
                    type_=Uuid(as_uuid=True),
                ),
                Uuid(as_uuid=True),
            ),
            account_target_allocation.c.uid,
            cast(target_positions_date_param, DateTime(timezone=True)),
            literal("apps.v1"),
            cast(
                bindparam(
                    "position_set_metadata_json",
                    value={"account_uid": str(account_uid)},
                    type_=JSON(),
                ),
                JSON(),
            ),
        ).select_from(account_target_allocation),
    )
    position_set_upsert = position_set_insert.on_conflict_do_update(
        index_elements=[
            PositionSetTable.account_target_allocation_uid,
            PositionSetTable.position_set_time,
        ],
        set_={
            "source": position_set_insert.excluded.source,
            "metadata_json": position_set_insert.excluded.metadata_json,
        },
        where=overwrite_param,
    ).returning(PositionSetTable.uid)

    if clearing:
        cleared_rows = (
            delete(TargetPositionsStorage)
            .where(overwrite_param)
            .where(
                TargetPositionsStorage.position_set_uid.in_(
                    select(existing_position_set.c.uid)
                    .where(
                        existing_position_set.c.account_target_allocation_uid.in_(
                            select(account_target_allocation.c.uid)
                        )
                    )
                    .where(
                        existing_position_set.c.position_set_time
                        == cast(target_positions_date_param, DateTime(timezone=True))
                    )
                )
            )
            .returning(true())
            .cte("cleared_rows")
        )
        return compile_markets_statement(
            position_set_upsert.add_cte(account_allocation_model)
            .add_cte(account_target_allocation)
            .add_cte(cleared_rows),
            context=context,
            operation="upsert",
            dialect=dialect,
            data_source_uid=data_source_uid,
        )

    position_set = position_set_upsert.cte("position_set")

    input_row_values = []
    for index, position in enumerate(positions):
        input_row_values.append(
            (
                bindparam(
                    f"target_type_{index}",
                    value=str(position["target_type"]),
                    type_=String(),
                ),
                cast(
                    bindparam(
                        f"target_uid_{index}",
                        value=uuid.UUID(str(position["target_uid"])),
                        type_=Uuid(as_uuid=True),
                    ),
                    Uuid(as_uuid=True),
                ),
                cast(
                    bindparam(
                        f"asset_uid_{index}",
                        value=(
                            uuid.UUID(str(position["asset_uid"]))
                            if position.get("asset_uid") not in (None, "")
                            else None
                        ),
                        type_=Uuid(as_uuid=True),
                    ),
                    Uuid(as_uuid=True),
                ),
                cast(
                    bindparam(
                        f"portfolio_uid_{index}",
                        value=(
                            uuid.UUID(str(position["portfolio_uid"]))
                            if position.get("portfolio_uid") not in (None, "")
                            else None
                        ),
                        type_=Uuid(as_uuid=True),
                    ),
                    Uuid(as_uuid=True),
                ),
                cast(
                    bindparam(
                        f"weight_notional_exposure_{index}",
                        value=_python_scalar(position.get("weight_notional_exposure")),
                        type_=Float(),
                    ),
                    Float(),
                ),
                cast(
                    bindparam(
                        f"constant_notional_exposure_{index}",
                        value=_python_scalar(position.get("constant_notional_exposure")),
                        type_=Float(),
                    ),
                    Float(),
                ),
                cast(
                    bindparam(
                        f"single_asset_quantity_{index}",
                        value=_python_scalar(position.get("single_asset_quantity")),
                        type_=Float(),
                    ),
                    Float(),
                ),
                cast(
                    bindparam(
                        f"metadata_json_{index}",
                        value=position.get("metadata_json") or {},
                        type_=JSONB(),
                    ),
                    JSONB(),
                ),
            )
        )

    input_rows = (
        values(
            column("target_type", String()),
            column("target_uid", Uuid(as_uuid=True)),
            column("asset_uid", Uuid(as_uuid=True)),
            column("portfolio_uid", Uuid(as_uuid=True)),
            column("weight_notional_exposure", Float()),
            column("constant_notional_exposure", Float()),
            column("single_asset_quantity", Float()),
            column("metadata_json", JSONB()),
            name="input_rows",
        )
        .data(input_row_values)
        .cte("input_rows")
    )
    deleted = (
        delete(TargetPositionsStorage)
        .where(overwrite_param)
        .where(TargetPositionsStorage.position_set_uid == position_set.c.uid)
        .returning(true())
        .cte("deleted")
    )
    deleted_gate = (
        select(func.count().label("deleted_count")).select_from(deleted).cte("deleted_gate")
    )
    statement = (
        insert(TargetPositionsStorage)
        .from_select(
            [
                "time_index",
                "position_set_uid",
                "target_type",
                "target_uid",
                "asset_uid",
                "portfolio_uid",
                "weight_notional_exposure",
                "constant_notional_exposure",
                "single_asset_quantity",
                "metadata_json",
            ],
            select(
                cast(target_positions_date_param, DateTime(timezone=True)),
                position_set.c.uid,
                input_rows.c.target_type,
                input_rows.c.target_uid,
                input_rows.c.asset_uid,
                input_rows.c.portfolio_uid,
                input_rows.c.weight_notional_exposure,
                input_rows.c.constant_notional_exposure,
                input_rows.c.single_asset_quantity,
                input_rows.c.metadata_json,
            ).select_from(input_rows.join(position_set, true()).join(deleted_gate, true())),
        )
        .returning(TargetPositionsStorage)
        .add_cte(account_allocation_model)
        .add_cte(account_target_allocation)
        .add_cte(position_set)
        .add_cte(deleted)
        .add_cte(deleted_gate)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="upsert",
        dialect=dialect,
        data_source_uid=data_source_uid,
    )


def _target_positions_snapshot_statement_list(
    *,
    account_allocation_model_uid: uuid.UUID | str,
    account_target_allocation_uid: uuid.UUID | str,
    position_set_uid: uuid.UUID | str,
    account_uid: uuid.UUID | str,
    account_name: str,
    target_positions_date: dt.datetime,
    positions: Sequence[Mapping[str, Any]],
    overwrite: bool,
) -> list[GuardedStatement | Any]:
    """The target-position snapshot write as ordered statements for one transaction.

    The same steps as the single PostgreSQL statement:

    1. With portfolio positions, the `live_portfolios` guard: every named
       portfolio exists and is not retired (ADR 0049).
    2. Upsert the account's allocation model, then its target allocation, whose
       `is_active` changes only when the snapshot write goes through.
    3. Upsert the `PositionSet`, refused by the `position_set` guard when it
       exists and `overwrite` is false.
    4. With `overwrite`, delete the snapshot's earlier rows; then insert the new
       rows. A clear inserts none and returns the `PositionSet` uid instead.

    Later statements find what earlier ones wrote by key. Values bind without
    casts: SQLite casts `DATETIME` and `JSON` to numbers, and a `Uuid` cast to
    text would drop the dashes `unique_identifier` keeps.
    """

    clearing = not positions
    account = uuid.UUID(str(account_uid))
    account_key = str(account)

    def account_key_param() -> Any:
        return bindparam("account_key", value=account_key, type_=String())

    def account_uid_param() -> Any:
        return bindparam("account_uid", value=account, type_=Uuid(as_uuid=True))

    def target_positions_date_param() -> Any:
        return bindparam(
            "target_positions_date", value=target_positions_date, type_=DateTime(timezone=True)
        )

    def overwrite_param() -> Any:
        return bindparam("overwrite", value=bool(overwrite), type_=Boolean())

    def allocation_lookup() -> Any:
        return (
            select(AccountTargetAllocationTable.uid)
            .where(AccountTargetAllocationTable.unique_identifier == account_key_param())
            .scalar_subquery()
        )

    def position_set_lookup() -> Any:
        return (
            select(PositionSetTable.uid)
            .where(PositionSetTable.account_target_allocation_uid == allocation_lookup())
            .where(PositionSetTable.position_set_time == target_positions_date_param())
            .scalar_subquery()
        )

    statements: list[GuardedStatement | Any] = []
    named_portfolio_uids = sorted(
        {
            uuid.UUID(str(position["portfolio_uid"]))
            for position in positions
            if position.get("portfolio_uid") not in (None, "")
        }
    )
    if named_portfolio_uids:
        statements.append(
            GuardedStatement(
                select(PortfolioTable.uid)
                .where(PortfolioTable.uid.in_(named_portfolio_uids))
                .where(PortfolioTable.retired_at.is_(None)),
                expect_rows=len(named_portfolio_uids),
                label=LIVE_PORTFOLIOS_GUARD,
            )
        )

    model_description = f"Default target allocation model for account {account!s}"
    model_insert = sqlite_insert(AccountAllocationModelTable).values(
        uid=bindparam(
            "account_allocation_model_uid",
            value=uuid.UUID(str(account_allocation_model_uid)),
            type_=Uuid(as_uuid=True),
        ),
        allocation_model_name=account_key_param(),
        allocation_model_description=model_description,
        metadata_json=bindparam(
            "account_allocation_model_metadata_json", value={"source": "apps.v1"}, type_=JSON()
        ),
    )
    statements.append(
        model_insert.on_conflict_do_update(
            index_elements=[AccountAllocationModelTable.allocation_model_name],
            set_={
                "allocation_model_description": model_insert.excluded.allocation_model_description,
                "metadata_json": model_insert.excluded.metadata_json,
            },
        )
    )

    existing_allocation = AccountTargetAllocationTable.__table__.alias("existing_allocation")
    existing_position_set = PositionSetTable.__table__.alias("existing_position_set")
    snapshot_exists = (
        select(existing_position_set.c.uid)
        .join(
            existing_allocation,
            existing_position_set.c.account_target_allocation_uid == existing_allocation.c.uid,
        )
        .where(existing_allocation.c.unique_identifier == account_key_param())
        .where(existing_position_set.c.position_set_time == target_positions_date_param())
        .exists()
    )
    allocation_insert = sqlite_insert(AccountTargetAllocationTable).from_select(
        [
            "uid",
            "unique_identifier",
            "account_uid",
            "account_allocation_model_uid",
            "display_name",
            "is_active",
            "source",
            "metadata_json",
        ],
        select(
            bindparam(
                "account_target_allocation_uid",
                value=uuid.UUID(str(account_target_allocation_uid)),
                type_=Uuid(as_uuid=True),
            ),
            account_key_param(),
            account_uid_param(),
            select(AccountAllocationModelTable.uid)
            .where(AccountAllocationModelTable.allocation_model_name == account_key_param())
            .scalar_subquery(),
            bindparam("account_name", value=str(account_name), type_=String()),
            bindparam("is_active", value=not clearing, type_=Boolean()),
            literal("apps.v1"),
            bindparam("account_target_allocation_metadata_json", value={}, type_=JSON()),
        ).where(true()),  # SQLite needs a WHERE before ON CONFLICT in INSERT ... SELECT.
    )
    statements.append(
        allocation_insert.on_conflict_do_update(
            index_elements=[AccountTargetAllocationTable.unique_identifier],
            set_={
                "account_uid": allocation_insert.excluded.account_uid,
                "account_allocation_model_uid": allocation_insert.excluded.account_allocation_model_uid,
                "display_name": allocation_insert.excluded.display_name,
                "is_active": case(
                    (or_(overwrite_param(), ~snapshot_exists), allocation_insert.excluded.is_active),
                    else_=AccountTargetAllocationTable.is_active,
                ),
                "source": allocation_insert.excluded.source,
                "metadata_json": allocation_insert.excluded.metadata_json,
            },
        )
    )

    position_set_insert = sqlite_insert(PositionSetTable).from_select(
        ["uid", "account_target_allocation_uid", "position_set_time", "source", "metadata_json"],
        select(
            bindparam(
                "position_set_uid", value=uuid.UUID(str(position_set_uid)), type_=Uuid(as_uuid=True)
            ),
            allocation_lookup(),
            target_positions_date_param(),
            literal("apps.v1"),
            bindparam(
                "position_set_metadata_json", value={"account_uid": str(account_uid)}, type_=JSON()
            ),
        ).where(true()),
    )
    upsert_position_set = GuardedStatement(
        position_set_insert.on_conflict_do_update(
            index_elements=[
                PositionSetTable.account_target_allocation_uid,
                PositionSetTable.position_set_time,
            ],
            set_={
                "source": position_set_insert.excluded.source,
                "metadata_json": position_set_insert.excluded.metadata_json,
            },
            where=overwrite_param(),
        ).returning(PositionSetTable.uid),
        expect_rows=1,
        label=POSITION_SET_GUARD,
    )
    remove_rows = (
        delete(TargetPositionsStorage)
        .where(overwrite_param())
        .where(TargetPositionsStorage.position_set_uid == position_set_lookup())
    )
    if clearing:
        # The clear answers with the PositionSet uid, as the PostgreSQL statement does.
        return [*statements, remove_rows, upsert_position_set]

    input_rows = (
        values(
            column("target_type", String()),
            column("target_uid", Uuid(as_uuid=True)),
            column("asset_uid", Uuid(as_uuid=True)),
            column("portfolio_uid", Uuid(as_uuid=True)),
            column("weight_notional_exposure", Float()),
            column("constant_notional_exposure", Float()),
            column("single_asset_quantity", Float()),
            column("metadata_json", JSON()),
            name="input_rows",
        )
        .data(
            [
                (
                    bindparam(
                        f"target_type_{index}", value=str(position["target_type"]), type_=String()
                    ),
                    bindparam(
                        f"target_uid_{index}",
                        value=uuid.UUID(str(position["target_uid"])),
                        type_=Uuid(as_uuid=True),
                    ),
                    bindparam(
                        f"asset_uid_{index}",
                        value=_optional_uuid(position.get("asset_uid")),
                        type_=Uuid(as_uuid=True),
                    ),
                    bindparam(
                        f"portfolio_uid_{index}",
                        value=_optional_uuid(position.get("portfolio_uid")),
                        type_=Uuid(as_uuid=True),
                    ),
                    bindparam(
                        f"weight_notional_exposure_{index}",
                        value=_python_scalar(position.get("weight_notional_exposure")),
                        type_=Float(),
                    ),
                    bindparam(
                        f"constant_notional_exposure_{index}",
                        value=_python_scalar(position.get("constant_notional_exposure")),
                        type_=Float(),
                    ),
                    bindparam(
                        f"single_asset_quantity_{index}",
                        value=_python_scalar(position.get("single_asset_quantity")),
                        type_=Float(),
                    ),
                    bindparam(
                        f"metadata_json_{index}",
                        value=position.get("metadata_json") or {},
                        type_=JSON(),
                    ),
                )
                for index, position in enumerate(positions)
            ]
        )
        .cte("input_rows")
    )
    insert_rows = (
        insert(TargetPositionsStorage)
        .from_select(
            [
                "time_index",
                "position_set_uid",
                "target_type",
                "target_uid",
                "asset_uid",
                "portfolio_uid",
                "weight_notional_exposure",
                "constant_notional_exposure",
                "single_asset_quantity",
                "metadata_json",
            ],
            select(
                target_positions_date_param(),
                position_set_lookup(),
                input_rows.c.target_type,
                input_rows.c.target_uid,
                input_rows.c.asset_uid,
                input_rows.c.portfolio_uid,
                input_rows.c.weight_notional_exposure,
                input_rows.c.constant_notional_exposure,
                input_rows.c.single_asset_quantity,
                input_rows.c.metadata_json,
            ).select_from(input_rows),
        )
        .returning(TargetPositionsStorage)
    )
    return [*statements, upsert_position_set, remove_rows, insert_rows]


def replace_account_target_positions_snapshot(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_write(
        build_replace_account_target_positions_snapshot_operation(context, **kwargs),
        context=context,
        refused_by=(LIVE_PORTFOLIOS_GUARD, POSITION_SET_GUARD),
    )


MappingOrDict = dict[str, Any]


def _utc_timestamp(value: dt.datetime | str, *, field_name: str) -> dt.datetime:
    if isinstance(value, str):
        try:
            value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 UTC timestamp.") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware UTC timestamp.")
    return value.astimezone(dt.UTC)


def _python_scalar(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return value


def _optional_uuid(value: Any) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value not in (None, "") else None


__all__ = [
    "build_replace_account_holdings_snapshot_operation",
    "build_replace_account_target_positions_snapshot_operation",
    "build_create_account_target_allocation_operation",
    "build_create_account_operation",
    "build_create_position_set_operation",
    "build_delete_account_target_allocation_operation",
    "build_delete_account_operation",
    "build_delete_position_set_operation",
    "build_get_account_by_uid_operation",
    "build_get_account_by_unique_identifier_operation",
    "build_search_accounts_operation",
    "build_search_account_target_allocations_operation",
    "build_search_account_target_allocation_candidates_operation",
    "build_search_position_sets_operation",
    "build_update_account_operation",
    "create_account_target_allocation",
    "create_account",
    "create_position_set",
    "delete_account_target_allocation",
    "delete_account",
    "delete_position_set",
    "get_account_by_uid",
    "get_account_by_unique_identifier",
    "replace_account_holdings_snapshot",
    "replace_account_target_positions_snapshot",
    "search_account_target_allocations",
    "search_account_target_allocation_candidates",
    "search_accounts",
    "search_position_sets",
    "update_account",
]
