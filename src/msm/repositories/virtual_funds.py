from __future__ import annotations

import uuid
from typing import Any

from mainsequence.client.metatables import MetaTableCompiledSQLOperation
from sqlalchemy import delete, insert, select, update

from msm.repositories.base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)
from msm.models import VirtualFundTable


def build_create_virtual_fund_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    account_uid: uuid.UUID | str,
    target_portfolio_uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = (
        insert(VirtualFundTable)
        .values(
            unique_identifier=unique_identifier,
            account_uid=account_uid,
            target_portfolio_uid=target_portfolio_uid,
        )
        .returning(VirtualFundTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
        models=[VirtualFundTable],
        access="write",
    )


def create_virtual_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_virtual_fund_operation(context, **kwargs),
        context=context,
    )


def build_get_virtual_fund_by_unique_identifier_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(VirtualFundTable)
        .where(VirtualFundTable.unique_identifier == unique_identifier)
        .limit(1)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[VirtualFundTable],
        access="read",
    )


def get_virtual_fund_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_virtual_fund_by_unique_identifier_operation(
            context,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_get_virtual_funds_by_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    target_portfolio_uid: uuid.UUID | str,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(VirtualFundTable)
        .where(VirtualFundTable.target_portfolio_uid == target_portfolio_uid)
        .limit(limit)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[VirtualFundTable],
        access="read",
    )


def get_virtual_funds_by_portfolio(
    context: MarketsRepositoryContext,
    *,
    target_portfolio_uid: uuid.UUID | str,
    limit: int = 500,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_virtual_funds_by_portfolio_operation(
            context,
            target_portfolio_uid=target_portfolio_uid,
            limit=limit,
        ),
        context=context,
    )


def build_get_virtual_funds_by_account_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(VirtualFundTable).where(VirtualFundTable.account_uid == account_uid).limit(limit)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[VirtualFundTable],
        access="read",
    )


def get_virtual_funds_by_account(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    limit: int = 500,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_virtual_funds_by_account_operation(
            context,
            account_uid=account_uid,
            limit=limit,
        ),
        context=context,
    )


def build_update_virtual_fund_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    **values: Any,
) -> MetaTableCompiledSQLOperation:
    statement = (
        update(VirtualFundTable)
        .where(VirtualFundTable.uid == uid)
        .values(**{key: value for key, value in values.items() if value is not None})
        .returning(VirtualFundTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
        models=[VirtualFundTable],
        access="write",
    )


def update_virtual_fund(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_virtual_fund_operation(context, **kwargs),
        context=context,
    )


def build_delete_virtual_fund_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(VirtualFundTable).where(VirtualFundTable.uid == uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[VirtualFundTable],
        access="write",
    )


def delete_virtual_fund(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_virtual_fund_operation(context, uid=uid),
        context=context,
    )


__all__ = [
    "build_create_virtual_fund_operation",
    "build_delete_virtual_fund_operation",
    "build_get_virtual_fund_by_unique_identifier_operation",
    "build_get_virtual_funds_by_account_operation",
    "build_get_virtual_funds_by_portfolio_operation",
    "build_update_virtual_fund_operation",
    "create_virtual_fund",
    "delete_virtual_fund",
    "get_virtual_fund_by_unique_identifier",
    "get_virtual_funds_by_account",
    "get_virtual_funds_by_portfolio",
    "update_virtual_fund",
]
