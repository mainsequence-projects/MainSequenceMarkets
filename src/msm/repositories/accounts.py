from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import delete, insert, select, update

from mainsequence.client.metatables import MetaTableCompiledSQLOperation
from msm.models import (
    AccountGroupTable,
    AccountTable,
    AccountTargetPortfolioTable,
    PositionSetTable,
)

from .base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_search_model_operation,
)


def build_create_account_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    account_name: str,
    is_paper: bool = True,
    account_is_active: bool = False,
    account_group_uid: uuid.UUID | str | None = None,
    holdings_data_node_uid: uuid.UUID | str | None = None,
    metadata_json: MappingOrDict | None = None,
) -> MetaTableCompiledSQLOperation:
    statement = (
        insert(AccountTable)
        .values(
            unique_identifier=unique_identifier,
            account_name=account_name,
            is_paper=is_paper,
            account_is_active=account_is_active,
            account_group_uid=account_group_uid,
            holdings_data_node_uid=holdings_data_node_uid,
            metadata_json=metadata_json,
        )
        .returning(AccountTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
        models=[AccountGroupTable, AccountTable],
        access="write",
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
        models=[AccountTable],
        access="read",
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
        models=[AccountTable],
        access="read",
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
    holdings_data_node_uid: uuid.UUID | str | None = None,
    metadata_json: MappingOrDict | None = None,
) -> MetaTableCompiledSQLOperation:
    values = {
        key: value
        for key, value in {
            "account_name": account_name,
            "is_paper": is_paper,
            "account_is_active": account_is_active,
            "account_group_uid": account_group_uid,
            "holdings_data_node_uid": holdings_data_node_uid,
            "metadata_json": metadata_json,
        }.items()
        if value is not None
    }
    statement = (
        update(AccountTable).where(AccountTable.uid == uid).values(**values).returning(AccountTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
        models=[AccountGroupTable, AccountTable],
        access="write",
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
        models=[AccountTable],
        access="write",
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


def build_create_account_target_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    account_uid: uuid.UUID | str,
    account_model_portfolio_uid: uuid.UUID | str,
    display_name: str | None = None,
    is_active: bool = True,
    source: str | None = None,
    metadata_json: MappingOrDict | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AccountTargetPortfolioTable,
        values={
            "unique_identifier": unique_identifier,
            "account_uid": account_uid,
            "account_model_portfolio_uid": account_model_portfolio_uid,
            "display_name": display_name,
            "is_active": is_active,
            "source": source,
            "metadata_json": metadata_json,
        },
    )


def create_account_target_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_account_target_portfolio_operation(context, **kwargs),
        context=context,
    )


def build_search_account_target_portfolios_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str | None = None,
    account_uid: uuid.UUID | str | None = None,
    account_model_portfolio_uid: uuid.UUID | str | None = None,
    is_active: bool | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "unique_identifier": unique_identifier,
        "account_uid": account_uid,
        "account_model_portfolio_uid": account_model_portfolio_uid,
        "is_active": is_active,
    }.items():
        if value is not None and value != "":
            filters[key] = value
    return build_search_model_operation(
        context,
        model=AccountTargetPortfolioTable,
        filters=filters,
        limit=limit,
    )


def search_account_target_portfolios(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_account_target_portfolios_operation(context, **kwargs),
        context=context,
    )


def build_delete_account_target_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(
        context,
        model=AccountTargetPortfolioTable,
        uid=uid,
    )


def delete_account_target_portfolio(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_account_target_portfolio_operation(context, uid=uid),
        context=context,
    )


def build_create_position_set_operation(
    context: MarketsRepositoryContext,
    *,
    account_target_portfolio_uid: uuid.UUID | str,
    position_set_time: dt.datetime | str,
    source: str | None = None,
    metadata_json: MappingOrDict | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=PositionSetTable,
        values={
            "account_target_portfolio_uid": account_target_portfolio_uid,
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
    account_target_portfolio_uid: uuid.UUID | str | None = None,
    position_set_time: dt.datetime | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "account_target_portfolio_uid": account_target_portfolio_uid,
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


__all__ = [
    "build_create_account_target_portfolio_operation",
    "build_create_account_operation",
    "build_create_position_set_operation",
    "build_delete_account_target_portfolio_operation",
    "build_delete_account_operation",
    "build_delete_position_set_operation",
    "build_get_account_by_uid_operation",
    "build_get_account_by_unique_identifier_operation",
    "build_search_accounts_operation",
    "build_search_account_target_portfolios_operation",
    "build_search_position_sets_operation",
    "build_update_account_operation",
    "create_account_target_portfolio",
    "create_account",
    "create_position_set",
    "delete_account_target_portfolio",
    "delete_account",
    "delete_position_set",
    "get_account_by_uid",
    "get_account_by_unique_identifier",
    "search_account_target_portfolios",
    "search_accounts",
    "search_position_sets",
    "update_account",
]
