from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import DateTime, Uuid, bindparam, delete, func, insert, or_, select, update

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from msm.repositories.base import (
    MarketsCompiledWrite,
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)
from msm.models import PortfolioGroupMembershipTable, PortfolioGroupTable, PortfolioTable
from msm.repositories.crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_get_model_by_unique_identifier_operation,
    build_search_model_operation,
    build_update_model_operation,
    build_upsert_model_operation,
    mirror_renamed_columns,
    renamed_keyword,
    UpsertStatus,
    upsert_model,
)


def build_create_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    calendar_uid: uuid.UUID | str,
    published_index_uid: uuid.UUID | str | None = None,
    portfolio_weights_table_update_uid: uuid.UUID | str | None = None,
    signal_weights_table_update_uid: uuid.UUID | str | None = None,
    signal_uid: str | None = None,
    portfolio_table_update_uid: uuid.UUID | str | None = None,
    backtest_table_price_column_name: str = "close",
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None,
    signal_weights_data_node_uid: uuid.UUID | str | None = None,
    portfolio_data_node_uid: uuid.UUID | str | None = None,
) -> MetaTableCompiledSQLOperation:
    portfolio_weights_table_update_uid = renamed_keyword(
        portfolio_weights_table_update_uid,
        portfolio_weights_data_node_uid,
        current="portfolio_weights_table_update_uid",
        previous="portfolio_weights_data_node_uid",
    )
    signal_weights_table_update_uid = renamed_keyword(
        signal_weights_table_update_uid,
        signal_weights_data_node_uid,
        current="signal_weights_table_update_uid",
        previous="signal_weights_data_node_uid",
    )
    portfolio_table_update_uid = renamed_keyword(
        portfolio_table_update_uid,
        portfolio_data_node_uid,
        current="portfolio_table_update_uid",
        previous="portfolio_data_node_uid",
    )
    statement = (
        insert(PortfolioTable)
        .values(
            **mirror_renamed_columns(
                PortfolioTable,
                {
                    "unique_identifier": unique_identifier,
                    "calendar_uid": calendar_uid,
                    "published_index_uid": published_index_uid,
                    "portfolio_weights_table_update_uid": portfolio_weights_table_update_uid,
                    "signal_weights_table_update_uid": signal_weights_table_update_uid,
                    "signal_uid": signal_uid,
                    "portfolio_table_update_uid": portfolio_table_update_uid,
                    "backtest_table_price_column_name": backtest_table_price_column_name,
                },
            )
        )
        .returning(PortfolioTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
    )


def create_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_portfolio_operation(context, **kwargs),
        context=context,
    )


def build_get_portfolio_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(PortfolioTable).where(PortfolioTable.unique_identifier == unique_identifier).limit(1)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def get_portfolio_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_portfolio_by_unique_identifier_operation(
            context,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_search_portfolios_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier_contains: str | None = None,
    calendar_uid: uuid.UUID | str | None = None,
    published_index_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    statement = select(PortfolioTable).limit(limit)
    if unique_identifier_contains not in (None, ""):
        statement = statement.where(
            PortfolioTable.unique_identifier.contains(str(unique_identifier_contains))
        )
    if calendar_uid not in (None, ""):
        statement = statement.where(PortfolioTable.calendar_uid == calendar_uid)
    if published_index_uid not in (None, ""):
        statement = statement.where(PortfolioTable.published_index_uid == published_index_uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def search_portfolios(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_portfolios_operation(context, **kwargs),
        context=context,
    )


def build_update_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    statement = (
        update(PortfolioTable)
        .where(PortfolioTable.uid == uid)
        .values(**{key: value for key, value in values.items() if value is not None})
        .returning(PortfolioTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
    )


def build_retire_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    retired_at: dt.datetime,
) -> MetaTableCompiledSQLOperation:
    """Set ``retired_at`` on a live portfolio that no account's current target names.

    Returns the updated row, or nothing when the portfolio is missing, already
    retired, or named by an account's current target (ADR 0049).
    """

    from msm.repositories.accounts import current_portfolio_target_rows_select

    uid_param = bindparam("uid", value=uuid.UUID(str(uid)), type_=Uuid(as_uuid=True))
    statement = (
        update(PortfolioTable)
        .where(PortfolioTable.uid == uid_param)
        .where(PortfolioTable.retired_at.is_(None))
        .where(~current_portfolio_target_rows_select(portfolio_uid=uid_param).exists())
        .values(
            retired_at=bindparam(
                "retired_at",
                value=retired_at,
                type_=DateTime(timezone=True),
            )
        )
        .returning(PortfolioTable)
    )
    return compile_markets_statement(statement, context=context, operation="update")


def build_clear_portfolio_retirement_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    retired_at: dt.datetime | None = None,
) -> MetaTableCompiledSQLOperation:
    """Clear ``retired_at``; with ``retired_at``, only when it still holds that value."""

    statement = update(PortfolioTable).where(
        PortfolioTable.uid
        == bindparam("uid", value=uuid.UUID(str(uid)), type_=Uuid(as_uuid=True))
    )
    if retired_at is not None:
        statement = statement.where(
            PortfolioTable.retired_at
            == bindparam(
                "expected_retired_at",
                value=retired_at,
                type_=DateTime(timezone=True),
            )
        )
    statement = statement.values(retired_at=None).returning(PortfolioTable)
    return compile_markets_statement(statement, context=context, operation="update")


def retire_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_retire_portfolio_operation(context, **kwargs),
        context=context,
    )


def clear_portfolio_retirement(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_clear_portfolio_retirement_operation(context, **kwargs),
        context=context,
    )


def update_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_portfolio_operation(context, **kwargs),
        context=context,
    )


def build_delete_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(PortfolioTable).where(PortfolioTable.uid == uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
    )


def delete_portfolio(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_portfolio_operation(context, uid=uid),
        context=context,
    )


def build_create_portfolio_group_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    display_name: str,
    description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=PortfolioGroupTable,
        values={
            "unique_identifier": unique_identifier,
            "display_name": display_name,
            "description": description,
            "metadata_json": metadata_json,
        },
    )


def create_portfolio_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_portfolio_group_operation(context, **kwargs),
        context=context,
    )


def build_upsert_portfolio_group_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    display_name: str,
    description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    dialect: MetaTableCompiledSQLDialect | None = None,
    statuses: Sequence[UpsertStatus] | None = None,
) -> MarketsCompiledWrite:
    return build_upsert_model_operation(
        context,
        model=PortfolioGroupTable,
        values=_portfolio_group_values(
            unique_identifier=unique_identifier,
            display_name=display_name,
            description=description,
            metadata_json=metadata_json,
        ),
        conflict_columns=("unique_identifier",),
        dialect=dialect,
        statuses=statuses,
    )


def upsert_portfolio_group(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    display_name: str,
    description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return upsert_model(
        context,
        model=PortfolioGroupTable,
        values=_portfolio_group_values(
            unique_identifier=unique_identifier,
            display_name=display_name,
            description=description,
            metadata_json=metadata_json,
        ),
        conflict_columns=("unique_identifier",),
    )


def _portfolio_group_values(
    *,
    unique_identifier: str,
    display_name: str,
    description: str | None,
    metadata_json: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "unique_identifier": unique_identifier,
        "display_name": display_name,
        "description": description,
        "metadata_json": metadata_json,
    }


def build_get_portfolio_group_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=PortfolioGroupTable, uid=uid)


def get_portfolio_group_by_uid(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_portfolio_group_by_uid_operation(context, uid=uid),
        context=context,
    )


def build_get_portfolio_group_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_unique_identifier_operation(
        context,
        model=PortfolioGroupTable,
        unique_identifier=unique_identifier,
    )


def get_portfolio_group_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_portfolio_group_by_unique_identifier_operation(
            context,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_search_portfolio_groups_operation(
    context: MarketsRepositoryContext,
    *,
    search: str | None = None,
    unique_identifier: str | None = None,
    unique_identifier_contains: str | None = None,
    display_name: str | None = None,
    display_name_contains: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    contains_filters: dict[str, str] = {}
    if unique_identifier not in (None, ""):
        filters["unique_identifier"] = unique_identifier
    if display_name not in (None, ""):
        filters["display_name"] = display_name
    if unique_identifier_contains not in (None, ""):
        contains_filters["unique_identifier"] = str(unique_identifier_contains)
    if display_name_contains not in (None, ""):
        contains_filters["display_name"] = str(display_name_contains)
    statement = select(PortfolioGroupTable)
    for field_name, value in filters.items():
        statement = statement.where(getattr(PortfolioGroupTable, field_name) == value)
    for field_name, value in contains_filters.items():
        statement = statement.where(
            func.lower(getattr(PortfolioGroupTable, field_name)).contains(str(value).lower())
        )
    if search not in (None, ""):
        normalized_search = str(search).lower()
        statement = statement.where(
            or_(
                func.lower(PortfolioGroupTable.unique_identifier).contains(normalized_search),
                func.lower(PortfolioGroupTable.display_name).contains(normalized_search),
            )
        )
    statement = statement.limit(limit)
    if offset:
        statement = statement.offset(offset)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def search_portfolio_groups(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_portfolio_groups_operation(context, **kwargs),
        context=context,
    )


def build_update_portfolio_group_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    display_name: str | None = None,
    description: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=PortfolioGroupTable,
        uid=uid,
        values={
            "display_name": display_name,
            "description": description,
            "metadata_json": metadata_json,
        },
    )


def update_portfolio_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_portfolio_group_operation(context, **kwargs),
        context=context,
    )


def build_delete_portfolio_group_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=PortfolioGroupTable, uid=uid)


def delete_portfolio_group(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_portfolio_group_operation(context, uid=uid),
        context=context,
    )


def build_upsert_portfolio_group_membership_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_group_uid: uuid.UUID | str,
    portfolio_uid: uuid.UUID | str,
    dialect: MetaTableCompiledSQLDialect | None = None,
    statuses: Sequence[UpsertStatus] | None = None,
) -> MarketsCompiledWrite:
    return build_upsert_model_operation(
        context,
        model=PortfolioGroupMembershipTable,
        values={"portfolio_group_uid": portfolio_group_uid, "portfolio_uid": portfolio_uid},
        conflict_columns=("portfolio_group_uid", "portfolio_uid"),
        dialect=dialect,
        statuses=statuses,
    )


def upsert_portfolio_group_membership(
    context: MarketsRepositoryContext,
    *,
    portfolio_group_uid: uuid.UUID | str,
    portfolio_uid: uuid.UUID | str,
) -> dict[str, Any]:
    return upsert_model(
        context,
        model=PortfolioGroupMembershipTable,
        values={"portfolio_group_uid": portfolio_group_uid, "portfolio_uid": portfolio_uid},
        conflict_columns=("portfolio_group_uid", "portfolio_uid"),
    )


def build_search_portfolio_group_memberships_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str | None = None,
    portfolio_group_uid: uuid.UUID | str | None = None,
    portfolio_uid: uuid.UUID | str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if uid not in (None, ""):
        filters["uid"] = uid
    if portfolio_group_uid not in (None, ""):
        filters["portfolio_group_uid"] = portfolio_group_uid
    if portfolio_uid not in (None, ""):
        filters["portfolio_uid"] = portfolio_uid
    return build_search_model_operation(
        context,
        model=PortfolioGroupMembershipTable,
        filters=filters,
        limit=limit,
        offset=offset,
    )


def search_portfolio_group_memberships(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_portfolio_group_memberships_operation(context, **kwargs),
        context=context,
    )


def build_delete_portfolio_group_membership_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=PortfolioGroupMembershipTable, uid=uid)


def delete_portfolio_group_membership(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_portfolio_group_membership_operation(context, uid=uid),
        context=context,
    )


def build_delete_portfolio_group_membership_by_pair_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_group_uid: uuid.UUID | str,
    portfolio_uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(PortfolioGroupMembershipTable).where(
        PortfolioGroupMembershipTable.portfolio_group_uid == portfolio_group_uid,
        PortfolioGroupMembershipTable.portfolio_uid == portfolio_uid,
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
    )


def delete_portfolio_group_membership_by_pair(
    context: MarketsRepositoryContext,
    *,
    portfolio_group_uid: uuid.UUID | str,
    portfolio_uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_portfolio_group_membership_by_pair_operation(
            context,
            portfolio_group_uid=portfolio_group_uid,
            portfolio_uid=portfolio_uid,
        ),
        context=context,
    )


def build_list_portfolios_for_group_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_group_uid: uuid.UUID | str,
    limit: int = 500,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(PortfolioTable)
        .select_from(PortfolioTable)
        .join(
            PortfolioGroupMembershipTable,
            PortfolioGroupMembershipTable.portfolio_uid == PortfolioTable.uid,
        )
        .where(PortfolioGroupMembershipTable.portfolio_group_uid == portfolio_group_uid)
        .limit(limit)
    )
    if offset:
        statement = statement.offset(offset)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def list_portfolios_for_group(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_list_portfolios_for_group_operation(context, **kwargs),
        context=context,
    )


def build_list_portfolio_groups_for_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID | str,
    limit: int = 500,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(PortfolioGroupTable)
        .select_from(PortfolioGroupTable)
        .join(
            PortfolioGroupMembershipTable,
            PortfolioGroupMembershipTable.portfolio_group_uid == PortfolioGroupTable.uid,
        )
        .where(PortfolioGroupMembershipTable.portfolio_uid == portfolio_uid)
        .limit(limit)
    )
    if offset:
        statement = statement.offset(offset)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
    )


def list_portfolio_groups_for_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_list_portfolio_groups_for_portfolio_operation(context, **kwargs),
        context=context,
    )


__all__ = [
    "build_create_portfolio_operation",
    "build_create_portfolio_group_operation",
    "build_delete_portfolio_operation",
    "build_delete_portfolio_group_membership_by_pair_operation",
    "build_delete_portfolio_group_membership_operation",
    "build_delete_portfolio_group_operation",
    "build_get_portfolio_by_unique_identifier_operation",
    "build_get_portfolio_group_by_uid_operation",
    "build_get_portfolio_group_by_unique_identifier_operation",
    "build_list_portfolio_groups_for_portfolio_operation",
    "build_list_portfolios_for_group_operation",
    "build_search_portfolio_group_memberships_operation",
    "build_search_portfolio_groups_operation",
    "build_search_portfolios_operation",
    "build_update_portfolio_operation",
    "build_update_portfolio_group_operation",
    "build_upsert_portfolio_group_membership_operation",
    "build_upsert_portfolio_group_operation",
    "create_portfolio",
    "create_portfolio_group",
    "delete_portfolio",
    "delete_portfolio_group",
    "delete_portfolio_group_membership",
    "delete_portfolio_group_membership_by_pair",
    "get_portfolio_by_unique_identifier",
    "get_portfolio_group_by_uid",
    "get_portfolio_group_by_unique_identifier",
    "list_portfolio_groups_for_portfolio",
    "list_portfolios_for_group",
    "search_portfolio_group_memberships",
    "search_portfolio_groups",
    "search_portfolios",
    "update_portfolio",
    "update_portfolio_group",
    "upsert_portfolio_group",
    "upsert_portfolio_group_membership",
]
