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
    insert,
    select,
    true,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as postgresql_insert

from mainsequence.client.metatables import MetaTableCompiledSQLOperation
from msm.data_nodes.storage import AccountHoldingsStorage
from msm.models import (
    AccountGroupTable,
    AccountHoldingsSetTable,
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
    parameters: dict[str, Any] = {
        "holdings_set_uid": str(uuid.UUID(str(holdings_set_uid))),
        "account_uid": str(uuid.UUID(str(account_uid))),
        "holdings_date": normalized_holdings_date,
        "overwrite": bool(overwrite),
    }
    parameter_types = {"holdings_date": TIMESTAMP_TZ}
    values_sql: list[str] = []
    for index, position in enumerate(positions):
        target_trade_time = _utc_timestamp(
            position.get("target_trade_time") or normalized_holdings_date,
            field_name=f"positions[{index}].target_trade_time",
        )
        parameters.update(
            {
                f"asset_identifier_{index}": str(position["asset_identifier"]),
                f"quantity_{index}": _python_scalar(position.get("quantity")),
                f"direction_{index}": int(position.get("direction", 1)),
                f"target_trade_time_{index}": target_trade_time,
                f"extra_details_{index}": json.dumps(
                    position.get("extra_details") or {},
                    sort_keys=True,
                ),
            }
        )
        parameter_types[f"target_trade_time_{index}"] = TIMESTAMP_TZ
        values_sql.append(
            "("
            f"%(asset_identifier_{index})s, "
            f"CAST(%(quantity_{index})s AS double precision), "
            f"CAST(%(direction_{index})s AS smallint), "
            f"CAST(%(target_trade_time_{index})s AS timestamptz), "
            f"CAST(%(extra_details_{index})s AS jsonb)"
            ")"
        )

    holdings_set_table = _qualified_table_name(AccountHoldingsSetTable)
    storage_table = _qualified_table_name(AccountHoldingsStorage)
    sql = f"""
WITH holdings_set AS (
    INSERT INTO {holdings_set_table} (
        uid,
        account_uid,
        time_index
    )
    VALUES (
        CAST(%(holdings_set_uid)s AS uuid),
        CAST(%(account_uid)s AS uuid),
        CAST(%(holdings_date)s AS timestamptz)
    )
    ON CONFLICT (account_uid, time_index)
    DO UPDATE SET time_index = EXCLUDED.time_index
    WHERE %(overwrite)s
    RETURNING uid
),
deleted AS (
    DELETE FROM {storage_table} AS storage
    USING holdings_set AS hs
    WHERE %(overwrite)s
        AND storage.holdings_set_uid = hs.uid
    RETURNING 1
),
input_rows (
    asset_identifier,
    quantity,
    direction,
    target_trade_time,
    extra_details
) AS (
    VALUES
        {", ".join(values_sql)}
),
inserted AS (
    INSERT INTO {storage_table} (
        time_index,
        account_uid,
        asset_identifier,
        holdings_set_uid,
        is_trade_snapshot,
        quantity,
        direction,
        target_trade_time,
        extra_details
    )
    SELECT
        CAST(%(holdings_date)s AS timestamptz),
        CAST(%(account_uid)s AS uuid),
        input_rows.asset_identifier,
        holdings_set.uid,
        FALSE,
        input_rows.quantity,
        input_rows.direction,
        input_rows.target_trade_time,
        input_rows.extra_details
    FROM input_rows
    CROSS JOIN holdings_set
    RETURNING
        time_index,
        account_uid,
        asset_identifier,
        holdings_set_uid,
        is_trade_snapshot,
        quantity,
        direction,
        target_trade_time,
        extra_details
)
SELECT
    time_index,
    account_uid,
    asset_identifier,
    holdings_set_uid,
    is_trade_snapshot,
    quantity,
    direction,
    target_trade_time,
    extra_details
FROM inserted
"""
    return build_operation(
        operation="upsert",
        sql=sql,
        parameters=parameters,
        parameter_types=parameter_types,
        scope=MetaTableOperationScope(
            tables=[
                context.scope_table(AccountHoldingsSetTable, access="write"),
                context.scope_table(AccountHoldingsStorage, access="write"),
            ]
        ),
        limits=context.limits,
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


def _qualified_table_name(model: Any) -> str:
    preparer = postgresql.dialect().identifier_preparer
    return preparer.format_table(model.__table__)


def _python_scalar(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return value


__all__ = [
    "build_replace_account_holdings_snapshot_operation",
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
    "replace_account_holdings_snapshot",
    "search_account_target_portfolios",
    "search_accounts",
    "search_position_sets",
    "update_account",
]
