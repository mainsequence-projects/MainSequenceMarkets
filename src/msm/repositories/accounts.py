from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    SmallInteger,
    String,
    Uuid,
    bindparam,
    cast,
    column,
    delete,
    false,
    func,
    insert,
    select,
    true,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as postgresql_insert

from mainsequence.client.metatables import MetaTableCompiledSQLOperation
from msm.data_nodes.accounts.storage import AccountHoldingsStorage
from msm.models import (
    AccountGroupTable,
    AccountHoldingsSetTable,
    AccountTable,
    AccountTargetAllocationTable,
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


def build_replace_account_holdings_snapshot_operation(
    context: MarketsRepositoryContext,
    *,
    holdings_set_uid: uuid.UUID | str,
    account_uid: uuid.UUID | str,
    holdings_date: dt.datetime | str,
    positions: Sequence[Mapping[str, Any]],
    overwrite: bool = False,
) -> MetaTableCompiledSQLOperation:
    if not positions:
        raise ValueError("Account holdings snapshot replacement requires positions.")

    normalized_holdings_date = _utc_timestamp(holdings_date, field_name="holdings_date")
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
        select(func.count().label("deleted_count"))
        .select_from(deleted)
        .cte("deleted_gate")
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
        models=[AccountHoldingsSetTable, AccountHoldingsStorage],
        access="write",
    )


def replace_account_holdings_snapshot(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_replace_account_holdings_snapshot_operation(context, **kwargs),
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


def _python_scalar(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return value


__all__ = [
    "build_replace_account_holdings_snapshot_operation",
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
    "search_account_target_allocations",
    "search_accounts",
    "search_position_sets",
    "update_account",
]
