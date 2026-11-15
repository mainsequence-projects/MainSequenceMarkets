from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from metatables.compiled_sql.v1 import GuardedStatement
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    SmallInteger,
    String,
    Uuid,
    and_,
    bindparam,
    cast,
    column,
    func,
    insert,
    literal,
    select,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from msm.repositories.base import (
    MarketsCompiledWrite,
    MarketsRepositoryContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
)
from msm.models import VirtualFundHoldingsSetTable, VirtualFundTable
from msm.time_index.accounts.virtual_funds.storage import VirtualFundHoldingsStorage

# Guard label of the SQLite statement list. It stops the whole write when the
# snapshot is already allocated, or when a fund belongs to another account, as the
# single PostgreSQL statement then writes nothing.
ALLOCATION_WRITE_GUARD = "virtual_fund_allocation"


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


def build_search_account_virtual_fund_allocation_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    source_account_holdings_set_uid: uuid.UUID | str,
    limit: int = 5_000,
) -> MetaTableCompiledSQLOperation:
    """Select what the account's funds hold for one holdings snapshot.

    One row per holdings set and, when it has them, per holdings row: the fund,
    its holdings set, and the row's ``asset_identifier`` and ``extra_details``.
    """

    statement = (
        select(
            VirtualFundTable.uid.label("virtual_fund_uid"),
            VirtualFundTable.unique_identifier.label("unique_identifier"),
            VirtualFundTable.target_portfolio_uid.label("target_portfolio_uid"),
            VirtualFundHoldingsSetTable.uid.label("holdings_set_uid"),
            VirtualFundHoldingsStorage.asset_identifier.label("asset_identifier"),
            VirtualFundHoldingsStorage.extra_details.label("extra_details"),
        )
        .select_from(VirtualFundHoldingsSetTable)
        .join(
            VirtualFundTable,
            VirtualFundTable.uid == VirtualFundHoldingsSetTable.virtual_fund_uid,
        )
        .outerjoin(
            VirtualFundHoldingsStorage,
            VirtualFundHoldingsStorage.virtual_fund_holdings_set_uid
            == VirtualFundHoldingsSetTable.uid,
        )
        .where(VirtualFundTable.account_uid == uuid.UUID(str(account_uid)))
        .where(
            VirtualFundHoldingsSetTable.source_account_holdings_set_uid
            == uuid.UUID(str(source_account_holdings_set_uid))
        )
        .order_by(VirtualFundTable.unique_identifier)
        .limit(limit)
    )
    return compile_markets_statement(statement, context=context, operation="select")


def search_account_virtual_fund_allocation(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_account_virtual_fund_allocation_operation(context, **kwargs),
        context=context,
    )


def build_search_virtual_funds_by_unique_identifiers_operation(
    context: MarketsRepositoryContext,
    *,
    unique_identifiers: Sequence[str],
) -> MetaTableCompiledSQLOperation:
    statement = select(VirtualFundTable).where(
        VirtualFundTable.unique_identifier.in_([str(value) for value in unique_identifiers])
    )
    return compile_markets_statement(statement, context=context, operation="select")


def search_virtual_funds_by_unique_identifiers(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_virtual_funds_by_unique_identifiers_operation(context, **kwargs),
        context=context,
    )


def _snapshot_is_allocated(account_uid: Any, source: Any) -> Any:
    """True when one of the account's funds already holds a set for the snapshot."""

    existing_fund = VirtualFundTable.__table__.alias("existing_fund")
    existing_set = VirtualFundHoldingsSetTable.__table__.alias("existing_set")
    return (
        select(existing_set.c.uid)
        .join(existing_fund, existing_fund.c.uid == existing_set.c.virtual_fund_uid)
        .where(existing_fund.c.account_uid == account_uid)
        .where(existing_set.c.source_account_holdings_set_uid == source)
        .exists()
    )


def build_write_account_virtual_fund_allocation_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    source_account_holdings_set_uid: uuid.UUID | str,
    allocation_time: dt.datetime,
    funds: Sequence[Mapping[str, Any]],
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Write the virtual-fund allocation of one holdings snapshot atomically (ADR 0053).

    Each fund gives ``unique_identifier``, ``target_portfolio_uid``, a
    ``virtual_fund_uid`` to use when the fund is new, a ``holdings_set_uid`` and
    its ``holdings`` rows. The write upserts the funds, inserts one holdings set
    per fund and inserts the holdings rows. It returns the inserted rows.

    An applied allocation is account history, so nothing is replaced. The write
    does nothing, and returns no rows, when one of the account's funds already
    holds a set for the snapshot, or when a fund belongs to another account.

    On PostgreSQL this is one statement. SQLite accepts only ``SELECT`` inside
    ``WITH``, so there the same steps run as a statement list in one transaction
    (MetaTables ADR 0026).
    """

    if not funds:
        raise ValueError("A virtual-fund allocation write requires at least one fund.")
    if allocation_time.tzinfo is None or allocation_time.utcoffset() is None:
        raise ValueError("allocation_time must be a timezone-aware UTC timestamp.")
    for fund in funds:
        if not fund.get("holdings"):
            raise ValueError(
                f"Virtual fund {fund['unique_identifier']!r} has no holdings to write."
            )

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    normalized_time = allocation_time.astimezone(dt.UTC)
    if dialect == "sqlite":
        return compile_markets_statements(
            _virtual_fund_allocation_statement_list(
                account_uid=account_uid,
                source_account_holdings_set_uid=source_account_holdings_set_uid,
                allocation_time=normalized_time,
                funds=funds,
            ),
            context=context,
            operation="upsert",
            data_source_uid=data_source_uid,
            dialect=dialect,
        )

    account_uid_param = cast(
        bindparam("account_uid", value=uuid.UUID(str(account_uid)), type_=Uuid(as_uuid=True)),
        Uuid(as_uuid=True),
    )
    source_param = cast(
        bindparam(
            "source_account_holdings_set_uid",
            value=uuid.UUID(str(source_account_holdings_set_uid)),
            type_=Uuid(as_uuid=True),
        ),
        Uuid(as_uuid=True),
    )
    time_param = cast(
        bindparam("allocation_time", value=normalized_time, type_=DateTime(timezone=True)),
        DateTime(timezone=True),
    )

    fund_rows = []
    holding_rows = []
    for fund_index, fund in enumerate(funds):
        unique_identifier = str(fund["unique_identifier"])
        fund_rows.append(
            (
                bindparam(
                    f"fund_unique_identifier_{fund_index}", value=unique_identifier, type_=String()
                ),
                _uuid_value(
                    f"fund_target_portfolio_uid_{fund_index}", fund["target_portfolio_uid"]
                ),
                _uuid_value(f"fund_uid_{fund_index}", fund["virtual_fund_uid"]),
                _uuid_value(f"fund_holdings_set_uid_{fund_index}", fund["holdings_set_uid"]),
            )
        )
        for holding in fund["holdings"]:
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
                        value=str(holding["allocation_strategy"]),
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
            column("virtual_fund_uid", Uuid(as_uuid=True)),
            column("holdings_set_uid", Uuid(as_uuid=True)),
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
            column("extra_details", JSONB()),
            name="holding_inputs",
        )
        .data(holding_rows)
        .cte("holding_inputs")
    )

    funds_insert = postgresql_insert(VirtualFundTable).from_select(
        ["uid", "unique_identifier", "account_uid", "target_portfolio_uid"],
        select(
            fund_inputs.c.virtual_fund_uid,
            fund_inputs.c.unique_identifier,
            account_uid_param,
            fund_inputs.c.target_portfolio_uid,
        ).where(~_snapshot_is_allocated(account_uid_param, source_param)),
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
    # Every fund must have been written; a fund of another account is not taken over.
    all_funds_written = select(func.count()).select_from(
        upserted_funds
    ).scalar_subquery() == literal(len(funds))
    holdings_sets = (
        insert(VirtualFundHoldingsSetTable)
        .from_select(
            ["uid", "virtual_fund_uid", "source_account_holdings_set_uid", "time_index"],
            select(
                fund_inputs.c.holdings_set_uid,
                upserted_funds.c.uid,
                source_param,
                time_param,
            )
            .select_from(
                fund_inputs.join(
                    upserted_funds,
                    upserted_funds.c.unique_identifier == fund_inputs.c.unique_identifier,
                )
            )
            .where(all_funds_written),
        )
        .returning(VirtualFundHoldingsSetTable.uid, VirtualFundHoldingsSetTable.virtual_fund_uid)
        .cte("holdings_sets")
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
                "extra_details",
            ],
            select(
                time_param,
                upserted_funds.c.uid,
                holding_inputs.c.asset_identifier,
                holdings_sets.c.uid,
                source_param,
                holding_inputs.c.allocated_quantity,
                holding_inputs.c.allocation_strategy,
                holding_inputs.c.direction,
                holding_inputs.c.extra_details,
            ).select_from(
                holding_inputs.join(
                    upserted_funds,
                    upserted_funds.c.unique_identifier == holding_inputs.c.fund_unique_identifier,
                ).join(holdings_sets, holdings_sets.c.virtual_fund_uid == upserted_funds.c.uid)
            ),
        )
        .returning(VirtualFundHoldingsStorage)
        .add_cte(fund_inputs)
        .add_cte(holding_inputs)
        .add_cte(upserted_funds)
        .add_cte(holdings_sets)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="upsert",
        dialect=dialect,
        data_source_uid=data_source_uid,
    )


def _virtual_fund_allocation_statement_list(
    *,
    account_uid: uuid.UUID | str,
    source_account_holdings_set_uid: uuid.UUID | str,
    allocation_time: dt.datetime,
    funds: Sequence[Mapping[str, Any]],
) -> list[GuardedStatement | Any]:
    """The allocation write as ordered statements for one transaction.

    Upsert the funds, which the guard requires to be every one of them: it
    writes none when the snapshot is already allocated, and it does not take
    over a fund of another account. Then insert one holdings set per fund, and
    the holdings rows. Later statements find funds and sets by key. Values bind
    without casts: SQLite casts ``DATETIME`` and ``JSON`` to numbers.
    """

    account = uuid.UUID(str(account_uid))
    source = uuid.UUID(str(source_account_holdings_set_uid))

    def account_param() -> Any:
        return bindparam("account_uid", value=account, type_=Uuid(as_uuid=True))

    def source_param() -> Any:
        return bindparam("source_account_holdings_set_uid", value=source, type_=Uuid(as_uuid=True))

    def time_param() -> Any:
        return bindparam("allocation_time", value=allocation_time, type_=DateTime(timezone=True))

    def fund_inputs() -> Any:
        return (
            values(
                column("unique_identifier", String()),
                column("target_portfolio_uid", Uuid(as_uuid=True)),
                column("virtual_fund_uid", Uuid(as_uuid=True)),
                column("holdings_set_uid", Uuid(as_uuid=True)),
                name="fund_inputs",
            )
            .data(
                [
                    (
                        bindparam(
                            f"fund_unique_identifier_{index}",
                            value=str(fund["unique_identifier"]),
                            type_=String(),
                        ),
                        bindparam(
                            f"fund_target_portfolio_uid_{index}",
                            value=uuid.UUID(str(fund["target_portfolio_uid"])),
                            type_=Uuid(as_uuid=True),
                        ),
                        bindparam(
                            f"fund_uid_{index}",
                            value=uuid.UUID(str(fund["virtual_fund_uid"])),
                            type_=Uuid(as_uuid=True),
                        ),
                        bindparam(
                            f"fund_holdings_set_uid_{index}",
                            value=uuid.UUID(str(fund["holdings_set_uid"])),
                            type_=Uuid(as_uuid=True),
                        ),
                    )
                    for index, fund in enumerate(funds)
                ]
            )
            .cte("fund_inputs")
        )

    fund_rows = fund_inputs()
    funds_insert = sqlite_insert(VirtualFundTable).from_select(
        ["uid", "unique_identifier", "account_uid", "target_portfolio_uid"],
        select(
            fund_rows.c.virtual_fund_uid,
            fund_rows.c.unique_identifier,
            account_param(),
            fund_rows.c.target_portfolio_uid,
        )
        .select_from(fund_rows)
        .where(~_snapshot_is_allocated(account_param(), source_param())),
    )
    upsert_funds = GuardedStatement(
        funds_insert.on_conflict_do_update(
            index_elements=[VirtualFundTable.unique_identifier],
            set_={"target_portfolio_uid": funds_insert.excluded.target_portfolio_uid},
            where=VirtualFundTable.account_uid == funds_insert.excluded.account_uid,
        ).returning(VirtualFundTable.uid),
        expect_rows=len(funds),
        label=ALLOCATION_WRITE_GUARD,
    )

    set_rows = fund_inputs()
    insert_sets = insert(VirtualFundHoldingsSetTable).from_select(
        ["uid", "virtual_fund_uid", "source_account_holdings_set_uid", "time_index"],
        select(
            set_rows.c.holdings_set_uid,
            VirtualFundTable.uid,
            source_param(),
            time_param(),
        )
        .select_from(
            set_rows.join(
                VirtualFundTable, VirtualFundTable.unique_identifier == set_rows.c.unique_identifier
            )
        )
        .where(VirtualFundTable.account_uid == account_param()),
    )

    holding_rows = []
    for fund in funds:
        for holding in fund["holdings"]:
            index = len(holding_rows)
            holding_rows.append(
                (
                    bindparam(
                        f"holding_fund_{index}",
                        value=str(fund["unique_identifier"]),
                        type_=String(),
                    ),
                    bindparam(
                        f"holding_asset_identifier_{index}",
                        value=str(holding["asset_identifier"]),
                        type_=String(),
                    ),
                    bindparam(
                        f"holding_allocated_quantity_{index}",
                        value=float(holding["allocated_quantity"]),
                        type_=Float(),
                    ),
                    bindparam(
                        f"holding_allocation_strategy_{index}",
                        value=str(holding["allocation_strategy"]),
                        type_=String(),
                    ),
                    bindparam(
                        f"holding_direction_{index}",
                        value=int(holding.get("direction", 1)),
                        type_=SmallInteger(),
                    ),
                    bindparam(
                        f"holding_extra_details_{index}",
                        value=dict(holding.get("extra_details") or {}),
                        type_=JSON(),
                    ),
                )
            )
    holding_inputs = (
        values(
            column("fund_unique_identifier", String()),
            column("asset_identifier", String()),
            column("allocated_quantity", Float()),
            column("allocation_strategy", String()),
            column("direction", SmallInteger()),
            column("extra_details", JSON()),
            name="holding_inputs",
        )
        .data(holding_rows)
        .cte("holding_inputs")
    )
    insert_rows = (
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
                "extra_details",
            ],
            select(
                time_param(),
                VirtualFundTable.uid,
                holding_inputs.c.asset_identifier,
                VirtualFundHoldingsSetTable.uid,
                source_param(),
                holding_inputs.c.allocated_quantity,
                holding_inputs.c.allocation_strategy,
                holding_inputs.c.direction,
                holding_inputs.c.extra_details,
            )
            .select_from(
                holding_inputs.join(
                    VirtualFundTable,
                    VirtualFundTable.unique_identifier == holding_inputs.c.fund_unique_identifier,
                ).join(
                    VirtualFundHoldingsSetTable,
                    and_(
                        VirtualFundHoldingsSetTable.virtual_fund_uid == VirtualFundTable.uid,
                        VirtualFundHoldingsSetTable.source_account_holdings_set_uid
                        == source_param(),
                    ),
                )
            )
            .where(VirtualFundTable.account_uid == account_param()),
        )
        .returning(VirtualFundHoldingsStorage)
    )
    return [upsert_funds, insert_sets, insert_rows]


def write_account_virtual_fund_allocation(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_write(
        build_write_account_virtual_fund_allocation_operation(context, **kwargs),
        context=context,
        refused_by=(ALLOCATION_WRITE_GUARD,),
    )


def _uuid_value(name: str, value: uuid.UUID | str) -> Any:
    return cast(
        bindparam(name, value=uuid.UUID(str(value)), type_=Uuid(as_uuid=True)),
        Uuid(as_uuid=True),
    )


__all__ = [
    "ALLOCATION_WRITE_GUARD",
    "build_search_account_virtual_fund_allocation_operation",
    "build_search_virtual_funds_by_unique_identifiers_operation",
    "build_write_account_virtual_fund_allocation_operation",
    "search_account_virtual_fund_allocation",
    "search_virtual_funds_by_unique_identifiers",
    "write_account_virtual_fund_allocation",
    "build_create_virtual_fund_operation",
    "build_get_virtual_fund_by_unique_identifier_operation",
    "build_get_virtual_funds_by_account_operation",
    "build_get_virtual_funds_by_portfolio_operation",
    "build_update_virtual_fund_operation",
    "create_virtual_fund",
    "get_virtual_fund_by_unique_identifier",
    "get_virtual_funds_by_account",
    "get_virtual_funds_by_portfolio",
    "update_virtual_fund",
]
