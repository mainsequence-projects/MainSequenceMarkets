from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, insert, select, update

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation
from msm.models import FundTable

from .base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)


def build_create_fund_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    target_account_uid: uuid.UUID | str,
    target_portfolio_uid: uuid.UUID | str,
    requires_nav_adjustment: bool = False,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    statement = (
        insert(FundTable)
        .values(
            unique_identifier=unique_identifier,
            target_account_uid=target_account_uid,
            target_portfolio_uid=target_portfolio_uid,
            requires_nav_adjustment=requires_nav_adjustment,
            metadata_json=metadata_json,
        )
        .returning(FundTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
        models=[FundTable],
        access="write",
    )


def create_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_fund_operation(context, **kwargs),
        context=context,
    )


def build_get_fund_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    statement = select(FundTable).where(FundTable.unique_identifier == unique_identifier).limit(1)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[FundTable],
        access="read",
    )


def get_fund_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_fund_by_unique_identifier_operation(
            context,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_get_funds_by_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    target_portfolio_uid: uuid.UUID | str,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(FundTable).where(FundTable.target_portfolio_uid == target_portfolio_uid).limit(limit)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[FundTable],
        access="read",
    )


def get_funds_by_portfolio(
    context: MarketsRepositoryContext,
    *,
    target_portfolio_uid: uuid.UUID | str,
    limit: int = 500,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_funds_by_portfolio_operation(
            context,
            target_portfolio_uid=target_portfolio_uid,
            limit=limit,
        ),
        context=context,
    )


def build_get_funds_by_account_operation(
    context: MarketsRepositoryContext,
    *,
    target_account_uid: uuid.UUID | str,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(FundTable).where(FundTable.target_account_uid == target_account_uid).limit(limit)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[FundTable],
        access="read",
    )


def get_funds_by_account(
    context: MarketsRepositoryContext,
    *,
    target_account_uid: uuid.UUID | str,
    limit: int = 500,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_funds_by_account_operation(
            context,
            target_account_uid=target_account_uid,
            limit=limit,
        ),
        context=context,
    )


def build_update_fund_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    statement = (
        update(FundTable)
        .where(FundTable.uid == uid)
        .values(**{key: value for key, value in values.items() if value is not None})
        .returning(FundTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
        models=[FundTable],
        access="write",
    )


def update_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_fund_operation(context, **kwargs),
        context=context,
    )


def build_delete_fund_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(FundTable).where(FundTable.uid == uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[FundTable],
        access="write",
    )


def delete_fund(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_fund_operation(context, uid=uid),
        context=context,
    )


__all__ = [
    "build_create_fund_operation",
    "build_delete_fund_operation",
    "build_get_fund_by_unique_identifier_operation",
    "build_get_funds_by_account_operation",
    "build_get_funds_by_portfolio_operation",
    "build_update_fund_operation",
    "create_fund",
    "delete_fund",
    "get_fund_by_unique_identifier",
    "get_funds_by_account",
    "get_funds_by_portfolio",
    "update_fund",
]
