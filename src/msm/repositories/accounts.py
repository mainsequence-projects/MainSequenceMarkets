from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, insert, select, update

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation
from msm.models import Account, AccountTargetPositionAssignment

from .base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_search_model_operation,
)


def build_create_account_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
    account_name: str,
    is_paper: bool = True,
    account_is_active: bool = False,
    holdings_data_node_uid: uuid.UUID | str | None = None,
    metadata_json: MappingOrDict | None = None,
) -> MetaTableCompiledSQLOperation:
    statement = (
        insert(Account)
        .values(
            unique_identifier=unique_identifier,
            account_name=account_name,
            is_paper=is_paper,
            account_is_active=account_is_active,
            holdings_data_node_uid=holdings_data_node_uid,
            metadata_json=metadata_json,
        )
        .returning(Account)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
        models=[Account],
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
    statement = select(Account).where(Account.unique_identifier == unique_identifier).limit(1)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[Account],
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


def build_search_accounts_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifier_contains: str | None = None,
    account_name_contains: str | None = None,
    account_is_active: bool | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    statement = select(Account).limit(limit)
    if unique_identifier_contains not in (None, ""):
        statement = statement.where(
            Account.unique_identifier.contains(str(unique_identifier_contains))
        )
    if account_name_contains not in (None, ""):
        statement = statement.where(Account.account_name.contains(str(account_name_contains)))
    if account_is_active is not None:
        statement = statement.where(Account.account_is_active.is_(bool(account_is_active)))
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[Account],
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
    holdings_data_node_uid: uuid.UUID | str | None = None,
    metadata_json: MappingOrDict | None = None,
) -> MetaTableCompiledSQLOperation:
    values = {
        key: value
        for key, value in {
            "account_name": account_name,
            "is_paper": is_paper,
            "account_is_active": account_is_active,
            "holdings_data_node_uid": holdings_data_node_uid,
            "metadata_json": metadata_json,
        }.items()
        if value is not None
    }
    statement = update(Account).where(Account.uid == uid).values(**values).returning(Account)
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
        models=[Account],
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
    statement = delete(Account).where(Account.uid == uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[Account],
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


def build_create_account_target_position_assignment_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    target_positions_time: str,
    position_set_uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AccountTargetPositionAssignment,
        values={
            "account_uid": account_uid,
            "target_positions_time": target_positions_time,
            "position_set_uid": position_set_uid,
        },
    )


def create_account_target_position_assignment(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_account_target_position_assignment_operation(context, **kwargs),
        context=context,
    )


def build_search_account_target_position_assignments_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str | None = None,
    target_positions_time: str | None = None,
    position_set_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "account_uid": account_uid,
        "target_positions_time": target_positions_time,
        "position_set_uid": position_set_uid,
    }.items():
        if value not in (None, ""):
            filters[key] = value
    return build_search_model_operation(
        context,
        model=AccountTargetPositionAssignment,
        filters=filters,
        limit=limit,
    )


def search_account_target_position_assignments(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_account_target_position_assignments_operation(context, **kwargs),
        context=context,
    )


def build_delete_account_target_position_assignment_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(
        context,
        model=AccountTargetPositionAssignment,
        uid=uid,
    )


def delete_account_target_position_assignment(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_account_target_position_assignment_operation(context, uid=uid),
        context=context,
    )


MappingOrDict = dict[str, Any]


__all__ = [
    "build_create_account_target_position_assignment_operation",
    "build_create_account_operation",
    "build_delete_account_target_position_assignment_operation",
    "build_delete_account_operation",
    "build_get_account_by_unique_identifier_operation",
    "build_search_accounts_operation",
    "build_search_account_target_position_assignments_operation",
    "build_update_account_operation",
    "create_account_target_position_assignment",
    "create_account",
    "delete_account_target_position_assignment",
    "delete_account",
    "get_account_by_unique_identifier",
    "search_account_target_position_assignments",
    "search_accounts",
    "update_account",
]
