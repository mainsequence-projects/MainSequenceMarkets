from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from metatables import MetaTableCompiledSQLOperation
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
    func,
    insert,
    select,
    true,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as postgresql_insert

from msm.repositories.base import (
    MarketsRepositoryContext,
    compile_markets_statement,
    execute_markets_operation,
)
from msm.models import VirtualFundHoldingsSetTable, VirtualFundTable
from msm.time_index.accounts.virtual_funds.storage import VirtualFundHoldingsStorage


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


def build_replace_account_virtual_fund_holdings_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    source_account_holdings_set_uid: uuid.UUID | str,
    allocation_time: dt.datetime,
    funds: Sequence[Mapping[str, Any]],
) -> MetaTableCompiledSQLOperation:
    """Replace an account's virtual-fund holdings for one source holdings set, in one statement.

    ``funds`` holds one entry per virtual fund: ``unique_identifier``,
    ``target_portfolio_uid`` and its ``holdings`` (``asset_identifier``,
    ``allocated_quantity``, ``allocation_strategy``, ``direction``,
    ``target_trade_time``, ``extra_details``). The statement upserts each
    ``VirtualFund`` by ``unique_identifier`` (a fund of another account is
    never taken over), upserts one ``VirtualFundHoldingsSet`` per fund for the
    source set, removes every holdings row the account's funds had for the
    source set, and the holdings sets of the account's funds that are no longer
    allocated, then inserts the new rows. It returns the inserted rows.
    """

    if not funds:
        raise ValueError("Virtual-fund holdings replacement requires at least one fund.")
    if allocation_time.tzinfo is None or allocation_time.utcoffset() is None:
        raise ValueError("allocation_time must be a timezone-aware UTC timestamp.")

    account_uid_param = bindparam(
        "account_uid", value=uuid.UUID(str(account_uid)), type_=Uuid(as_uuid=True)
    )
    source_param = bindparam(
        "source_account_holdings_set_uid",
        value=uuid.UUID(str(source_account_holdings_set_uid)),
        type_=Uuid(as_uuid=True),
    )
    time_param = bindparam(
        "allocation_time",
        value=allocation_time.astimezone(dt.UTC),
        type_=DateTime(timezone=True),
    )

    fund_rows = []
    holding_rows = []
    for fund_index, fund in enumerate(funds):
        unique_identifier = str(fund["unique_identifier"])
        holdings = list(fund.get("holdings") or [])
        if not holdings:
            raise ValueError(f"Virtual fund {unique_identifier!r} has no holdings to write.")
        fund_rows.append(
            (
                bindparam(
                    f"fund_unique_identifier_{fund_index}", value=unique_identifier, type_=String()
                ),
                _uuid_value(
                    f"fund_target_portfolio_uid_{fund_index}", fund["target_portfolio_uid"]
                ),
                _uuid_value(f"fund_candidate_uid_{fund_index}", uuid.uuid4()),
                _uuid_value(f"fund_candidate_holdings_set_uid_{fund_index}", uuid.uuid4()),
            )
        )
        for holding in holdings:
            index = len(holding_rows)
            holding_rows.append(
                (
                    bindparam(f"holding_fund_{index}", value=unique_identifier, type_=String()),
                    bindparam(
                        f"holding_asset_identifier_{index}",
                        value=str(holding["asset_identifier"]),
                        type_=String(),
                    ),
                    cast(
                        bindparam(
                            f"holding_allocated_quantity_{index}",
                            value=float(holding["allocated_quantity"]),
                            type_=Float(),
                        ),
                        Float(),
                    ),
                    bindparam(
                        f"holding_allocation_strategy_{index}",
                        value=str(holding.get("allocation_strategy") or "explicit"),
                        type_=String(),
                    ),
                    cast(
                        bindparam(
                            f"holding_direction_{index}",
                            value=int(holding.get("direction", 1)),
                            type_=SmallInteger(),
                        ),
                        SmallInteger(),
                    ),
                    cast(
                        bindparam(
                            f"holding_target_trade_time_{index}",
                            value=holding.get("target_trade_time"),
                            type_=DateTime(timezone=True),
                        ),
                        DateTime(timezone=True),
                    ),
                    cast(
                        bindparam(
                            f"holding_extra_details_{index}",
                            value=dict(holding.get("extra_details") or {}),
                            type_=JSONB(),
                        ),
                        JSONB(),
                    ),
                )
            )

    fund_inputs = (
        values(
            column("unique_identifier", String()),
            column("target_portfolio_uid", Uuid(as_uuid=True)),
            column("candidate_uid", Uuid(as_uuid=True)),
            column("candidate_holdings_set_uid", Uuid(as_uuid=True)),
            name="fund_inputs",
        )
        .data(fund_rows)
        .cte("fund_inputs")
    )
    holding_inputs = (
        values(
            column("fund_unique_identifier", String()),
            column("asset_identifier", String()),
            column("allocated_quantity", Float()),
            column("allocation_strategy", String()),
            column("direction", SmallInteger()),
            column("target_trade_time", DateTime(timezone=True)),
            column("extra_details", JSONB()),
            name="holding_inputs",
        )
        .data(holding_rows)
        .cte("holding_inputs")
    )

    funds_insert = postgresql_insert(VirtualFundTable).from_select(
        ["uid", "unique_identifier", "account_uid", "target_portfolio_uid"],
        select(
            fund_inputs.c.candidate_uid,
            fund_inputs.c.unique_identifier,
            cast(account_uid_param, Uuid(as_uuid=True)),
            fund_inputs.c.target_portfolio_uid,
        ),
    )
    upserted_funds = (
        funds_insert.on_conflict_do_update(
            index_elements=[VirtualFundTable.unique_identifier],
            set_={"target_portfolio_uid": funds_insert.excluded.target_portfolio_uid},
            where=VirtualFundTable.account_uid == funds_insert.excluded.account_uid,
        )
        .returning(VirtualFundTable.uid, VirtualFundTable.unique_identifier)
        .cte("upserted_funds")
    )
    account_funds = (
        select(VirtualFundTable.uid)
        .where(VirtualFundTable.account_uid == cast(account_uid_param, Uuid(as_uuid=True)))
        .cte("account_funds")
    )
    removed_rows = (
        delete(VirtualFundHoldingsStorage)
        .where(
            VirtualFundHoldingsStorage.source_account_holdings_set_uid
            == cast(source_param, Uuid(as_uuid=True))
        )
        .where(VirtualFundHoldingsStorage.virtual_fund_uid.in_(select(account_funds.c.uid)))
        .returning(true())
        .cte("removed_rows")
    )
    removed_sets = (
        delete(VirtualFundHoldingsSetTable)
        .where(
            VirtualFundHoldingsSetTable.source_account_holdings_set_uid
            == cast(source_param, Uuid(as_uuid=True))
        )
        .where(VirtualFundHoldingsSetTable.virtual_fund_uid.in_(select(account_funds.c.uid)))
        .where(VirtualFundHoldingsSetTable.virtual_fund_uid.not_in(select(upserted_funds.c.uid)))
        .returning(true())
        .cte("removed_sets")
    )
    sets_insert = postgresql_insert(VirtualFundHoldingsSetTable).from_select(
        ["uid", "virtual_fund_uid", "source_account_holdings_set_uid", "time_index"],
        select(
            fund_inputs.c.candidate_holdings_set_uid,
            upserted_funds.c.uid,
            cast(source_param, Uuid(as_uuid=True)),
            cast(time_param, DateTime(timezone=True)),
        ).select_from(
            fund_inputs.join(
                upserted_funds,
                upserted_funds.c.unique_identifier == fund_inputs.c.unique_identifier,
            )
        ),
    )
    holdings_sets = (
        sets_insert.on_conflict_do_update(
            index_elements=[
                VirtualFundHoldingsSetTable.virtual_fund_uid,
                VirtualFundHoldingsSetTable.source_account_holdings_set_uid,
            ],
            set_={"time_index": sets_insert.excluded.time_index},
        )
        .returning(VirtualFundHoldingsSetTable.uid, VirtualFundHoldingsSetTable.virtual_fund_uid)
        .cte("holdings_sets")
    )
    removed_gate = (
        select(func.count().label("removed_count")).select_from(removed_rows).cte("removed_gate")
    )
    statement = (
        insert(VirtualFundHoldingsStorage)
        .from_select(
            [
                "time_index",
                "virtual_fund_uid",
                "asset_identifier",
                "virtual_fund_holdings_set_uid",
                "source_account_holdings_set_uid",
                "allocated_quantity",
                "allocation_strategy",
                "direction",
                "target_trade_time",
                "extra_details",
            ],
            select(
                cast(time_param, DateTime(timezone=True)),
                upserted_funds.c.uid,
                holding_inputs.c.asset_identifier,
                holdings_sets.c.uid,
                cast(source_param, Uuid(as_uuid=True)),
                holding_inputs.c.allocated_quantity,
                holding_inputs.c.allocation_strategy,
                holding_inputs.c.direction,
                holding_inputs.c.target_trade_time,
                holding_inputs.c.extra_details,
            ).select_from(
                holding_inputs.join(
                    upserted_funds,
                    upserted_funds.c.unique_identifier == holding_inputs.c.fund_unique_identifier,
                )
                .join(holdings_sets, holdings_sets.c.virtual_fund_uid == upserted_funds.c.uid)
                .join(removed_gate, true())
            ),
        )
        .returning(VirtualFundHoldingsStorage)
        .add_cte(fund_inputs)
        .add_cte(holding_inputs)
        .add_cte(upserted_funds)
        .add_cte(account_funds)
        .add_cte(removed_rows)
        .add_cte(removed_sets)
        .add_cte(holdings_sets)
        .add_cte(removed_gate)
    )
    return compile_markets_statement(statement, context=context, operation="upsert")


def replace_account_virtual_fund_holdings(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_replace_account_virtual_fund_holdings_operation(context, **kwargs),
        context=context,
    )


def _uuid_value(name: str, value: uuid.UUID | str) -> Any:
    return cast(
        bindparam(name, value=uuid.UUID(str(value)), type_=Uuid(as_uuid=True)),
        Uuid(as_uuid=True),
    )


__all__ = [
    "build_create_virtual_fund_operation",
    "build_replace_account_virtual_fund_holdings_operation",
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
    "replace_account_virtual_fund_holdings",
    "update_virtual_fund",
]
