from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import delete, insert, select, update

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation
from msm.models import AccountTable, AccountTargetPositionAssignmentTable

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
            holdings_data_node_uid=holdings_data_node_uid,
            metadata_json=metadata_json,
        )
        .returning(AccountTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
        models=[AccountTable],
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
    statement = (
        update(AccountTable).where(AccountTable.uid == uid).values(**values).returning(AccountTable)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
        models=[AccountTable],
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


def build_create_account_target_position_assignment_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    target_positions_time: dt.datetime | str,
    position_set_uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=AccountTargetPositionAssignmentTable,
        values={
            "account_uid": account_uid,
            "target_positions_time": _utc_timestamp(
                target_positions_time,
                field_name="target_positions_time",
            ),
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
    target_positions_time: dt.datetime | str | None = None,
    position_set_uid: uuid.UUID | str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    for key, value in {
        "account_uid": account_uid,
        "target_positions_time": (
            _utc_timestamp(target_positions_time, field_name="target_positions_time")
            if target_positions_time is not None
            else None
        ),
        "position_set_uid": position_set_uid,
    }.items():
        if value not in (None, ""):
            filters[key] = value
    return build_search_model_operation(
        context,
        model=AccountTargetPositionAssignmentTable,
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
        model=AccountTargetPositionAssignmentTable,
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
    "build_create_account_target_position_assignment_operation",
    "build_create_account_operation",
    "build_delete_account_target_position_assignment_operation",
    "build_delete_account_operation",
    "build_get_account_by_uid_operation",
    "build_get_account_by_unique_identifier_operation",
    "build_search_accounts_operation",
    "build_search_account_target_position_assignments_operation",
    "build_update_account_operation",
    "create_account_target_position_assignment",
    "create_account",
    "delete_account_target_position_assignment",
    "delete_account",
    "get_account_by_uid",
    "get_account_by_unique_identifier",
    "search_account_target_position_assignments",
    "search_accounts",
    "update_account",
]
