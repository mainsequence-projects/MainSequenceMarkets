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
    or_,
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
from msm.repositories.complete_reads import (
    compile_page,
    page_select,
    read_every_model_row,
    read_every_row,
)
from msm.models import VirtualFundHoldingsSetTable, VirtualFundTable
from msm.time_index.accounts.virtual_funds.storage import (
    AccountAllocationLinesStorage,
    VirtualFundHoldingsStorage,
)

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
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """Select a page of what the account's funds hold for one holdings snapshot.

    One row per holdings set and, when it has them, per holdings row: the fund,
    its holdings set, and the row's ``time_index``, ``asset_identifier`` and
    ``extra_details``.
    """

    statement = (
        select(
            VirtualFundTable.uid.label("virtual_fund_uid"),
            VirtualFundTable.unique_identifier.label("unique_identifier"),
            VirtualFundTable.target_portfolio_uid.label("target_portfolio_uid"),
            VirtualFundHoldingsSetTable.uid.label("holdings_set_uid"),
            VirtualFundHoldingsStorage.time_index.label("time_index"),
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
    )
    key = ("unique_identifier", "holdings_set_uid", "time_index", "asset_identifier")
    return compile_page(page_select(statement, key=key, offset=offset), context=context)


def search_account_virtual_fund_allocation(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    """Every row of what the account's funds hold for one holdings snapshot."""

    return read_every_row(
        lambda offset: build_search_account_virtual_fund_allocation_operation(
            context, offset=offset, **kwargs
        ),
        context=context,
    )


def search_virtual_funds_by_unique_identifiers(
    context: MarketsRepositoryContext,
    *,
    unique_identifiers: Sequence[str],
) -> dict[str, Any]:
    """Every virtual fund that has one of ``unique_identifiers``."""

    return read_every_model_row(
        context,
        model=VirtualFundTable,
        in_filters={"unique_identifier": [str(value) for value in unique_identifiers]},
    )


def _snapshot_is_allocated(account_uid: Any, source: Any) -> Any:
    """True when the account's holdings snapshot already has an allocation.

    An allocation leaves its lines, and a holdings set per fund. Either marks the
    snapshot: an allocation written before the lines were recorded has only sets.
    """

    existing_fund = VirtualFundTable.__table__.alias("existing_fund")
    existing_set = VirtualFundHoldingsSetTable.__table__.alias("existing_set")
    existing_line = AccountAllocationLinesStorage.__table__.alias("existing_line")
    return or_(
        select(existing_set.c.uid)
        .join(existing_fund, existing_fund.c.uid == existing_set.c.virtual_fund_uid)
        .where(existing_fund.c.account_uid == account_uid)
        .where(existing_set.c.source_account_holdings_set_uid == source)
        .exists(),
        select(existing_line.c.owner_uid)
        .where(existing_line.c.account_uid == account_uid)
        .where(existing_line.c.holdings_set_uid == source)
        .exists(),
    )


def build_search_account_allocation_lines_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    source_account_holdings_set_uid: uuid.UUID | str | None = None,
    time_index: dt.datetime | None = None,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    """Select a page of the lines of one allocation of an account's holdings.

    The allocation is the one of ``source_account_holdings_set_uid``, or the one
    at ``time_index``, or with neither the account's latest. One row per owner
    and asset, with the fund's key and portfolio on a fund line.
    """

    lines = AccountAllocationLinesStorage
    account = uuid.UUID(str(account_uid))
    if source_account_holdings_set_uid is not None:
        which = lines.holdings_set_uid == uuid.UUID(
            str(source_account_holdings_set_uid)
        )
    elif time_index is not None:
        which = lines.time_index == time_index
    else:
        latest = AccountAllocationLinesStorage.__table__.alias("latest_line")
        which = (
            lines.time_index
            == select(func.max(latest.c.time_index))
            .where(latest.c.account_uid == account)
            .scalar_subquery()
        )
    statement = (
        select(
            lines.time_index,
            lines.holdings_set_uid,
            lines.owner_type,
            lines.owner_uid,
            lines.asset_identifier,
            lines.account_uid,
            lines.virtual_fund_uid,
            lines.target_quantity,
            lines.target_direction,
            lines.assigned_quantity,
            lines.assigned_direction,
            lines.allocation_strategy,
            lines.extra_details,
            VirtualFundTable.unique_identifier.label("virtual_fund_unique_identifier"),
            VirtualFundTable.target_portfolio_uid.label("target_portfolio_uid"),
        )
        .select_from(lines)
        .outerjoin(VirtualFundTable, VirtualFundTable.uid == lines.virtual_fund_uid)
        .where(lines.account_uid == account)
        .where(which)
    )
    key = ("-owner_type", "owner_uid", "asset_identifier", "holdings_set_uid")
    return compile_page(page_select(statement, key=key, offset=offset), context=context)


def search_account_allocation_lines(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return read_every_row(
        lambda offset: build_search_account_allocation_lines_operation(
            context, offset=offset, **kwargs
        ),
        context=context,
    )


_FUND_INPUT_COLUMNS = (
    ("unique_identifier", String),
    ("target_portfolio_uid", Uuid),
    ("virtual_fund_uid", Uuid),
    ("holdings_set_uid", Uuid),
)
_HOLDING_INPUT_COLUMNS = (
    ("fund_unique_identifier", String),
    ("asset_identifier", String),
    ("allocated_quantity", Float),
    ("allocation_strategy", String),
    ("direction", SmallInteger),
    ("extra_details", None),
)
_LINE_INPUT_COLUMNS = (
    ("owner_type", String),
    ("fund_unique_identifier", String),
    ("asset_identifier", String),
    ("target_quantity", Float),
    ("target_direction", SmallInteger),
    ("assigned_quantity", Float),
    ("assigned_direction", SmallInteger),
    ("allocation_strategy", String),
    ("extra_details", None),
)
_HOLDING_COLUMNS = [
    "time_index",
    "virtual_fund_uid",
    "asset_identifier",
    "virtual_fund_holdings_set_uid",
    "source_account_holdings_set_uid",
    "allocated_quantity",
    "allocation_strategy",
    "direction",
    "extra_details",
]
_LINE_COLUMNS = [
    "time_index",
    "holdings_set_uid",
    "owner_type",
    "owner_uid",
    "asset_identifier",
    "account_uid",
    "virtual_fund_uid",
    "target_quantity",
    "target_direction",
    "assigned_quantity",
    "assigned_direction",
    "allocation_strategy",
    "extra_details",
]


def _input_values(
    name: str,
    columns: Sequence[tuple[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    *,
    postgresql: bool,
) -> Any:
    """The rows of one write input, as a CTE.

    On PostgreSQL they are one JSONB parameter, read as a typed recordset: a value bound
    for each column of each row passed MetaTables' 1,000,000 characters of SQL at about
    2,000 rows, and PostgreSQL's 65,535 parameters after it. On SQLite they are a
    ``VALUES`` list, bound without casts: it casts ``DATETIME`` and ``JSON`` to numbers.
    """

    json_type = JSONB if postgresql else JSON

    def type_of(kind: Any) -> Any:
        if kind is None:
            return json_type()
        return Uuid(as_uuid=True) if kind is Uuid else kind()

    def value(key: str, kind: Any, row: Mapping[str, Any]) -> Any:
        raw = row.get(key)
        if kind is Uuid:
            raw = uuid.UUID(str(raw))
            return str(raw) if postgresql else raw
        if kind is Float:
            return float(raw)
        if kind is SmallInteger:
            return int(raw)
        if kind is None:
            return dict(raw or {})
        return None if raw is None else str(raw)

    typed = [column(key, type_of(kind)) for key, kind in columns]
    if postgresql:
        payload = [{key: value(key, kind, row) for key, kind in columns} for row in rows]
        parameter = cast(bindparam(f"{name}_rows", value=payload, type_=JSONB()), JSONB())
        recordset = (
            func.jsonb_to_recordset(parameter)
            .table_valued(*typed)
            .render_derived(name=f"{name}_recordset", with_types=True)
        )
        return select(*recordset.c).cte(name)

    return (
        values(*typed, name=name)
        .data(
            [
                tuple(
                    bindparam(
                        f"{name}_{key}_{index}", value=value(key, kind, row), type_=type_of(kind)
                    )
                    for key, kind in columns
                )
                for index, row in enumerate(rows)
            ]
        )
        .cte(name)
    )


def _allocation_inputs(
    funds: Sequence[Mapping[str, Any]],
    lines: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Flatten the write's funds, their holdings rows and the lines into input rows."""

    fund_rows = [
        {
            "unique_identifier": fund["unique_identifier"],
            "target_portfolio_uid": fund["target_portfolio_uid"],
            "virtual_fund_uid": fund["virtual_fund_uid"],
            "holdings_set_uid": fund["holdings_set_uid"],
        }
        for fund in funds
    ]
    holding_rows = [
        {
            "fund_unique_identifier": fund["unique_identifier"],
            "asset_identifier": holding["asset_identifier"],
            "allocated_quantity": holding["allocated_quantity"],
            "allocation_strategy": holding["allocation_strategy"],
            "direction": holding.get("direction", 1),
            "extra_details": holding.get("extra_details"),
        }
        for fund in funds
        for holding in fund.get("holdings") or ()
    ]
    return fund_rows, holding_rows, [dict(line) for line in lines]


def build_write_account_virtual_fund_allocation_operation(
    context: MarketsRepositoryContext,
    *,
    account_uid: uuid.UUID | str,
    source_account_holdings_set_uid: uuid.UUID | str,
    allocation_time: dt.datetime,
    funds: Sequence[Mapping[str, Any]],
    lines: Sequence[Mapping[str, Any]] = (),
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Write the allocation of one account holdings snapshot atomically (ADR 0054).

    ``funds`` are the virtual funds of the account's target. Each gives
    ``unique_identifier``, ``target_portfolio_uid``, a ``virtual_fund_uid`` to use
    when the fund is new, a ``holdings_set_uid`` and its ``holdings`` rows: what
    the fund was assigned, which may be nothing.

    ``lines`` are the allocation's record: one per owner and asset, with the sized
    target and the assigned units. A line names its fund by
    ``fund_unique_identifier``; a direct line leaves it null.

    The write upserts the funds, inserts one holdings set per fund, the holdings
    rows and the lines. It returns the last rows it inserted: the lines, else the
    holdings rows, else the holdings sets.

    An applied allocation is account history, so nothing is replaced. The write
    does nothing, and returns no rows, when the snapshot already has an
    allocation, or when a fund belongs to another account.

    On PostgreSQL this is one statement. SQLite accepts only ``SELECT`` inside
    ``WITH``, so there the same steps run as a statement list in one transaction
    (MetaTables ADR 0026).
    """

    if not funds and not lines:
        raise ValueError("An allocation write requires at least one fund or one line.")
    if allocation_time.tzinfo is None or allocation_time.utcoffset() is None:
        raise ValueError("allocation_time must be a timezone-aware UTC timestamp.")

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    normalized_time = allocation_time.astimezone(dt.UTC)
    if dialect == "sqlite":
        return compile_markets_statements(
            _virtual_fund_allocation_statement_list(
                account_uid=account_uid,
                source_account_holdings_set_uid=source_account_holdings_set_uid,
                allocation_time=normalized_time,
                funds=funds,
                lines=lines,
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
    fund_rows, holding_rows, line_rows = _allocation_inputs(funds, lines)
    not_allocated = ~_snapshot_is_allocated(account_uid_param, source_param)

    # Each step is an INSERT. The last one that has rows is the statement; the
    # earlier ones are data-modifying CTEs, which PostgreSQL runs to completion
    # whether or not the statement reads them.
    steps: list[Any] = []
    ctes: list[Any] = []
    upserted_funds = None
    gate = not_allocated
    if fund_rows:
        fund_inputs = _input_values("fund_inputs", _FUND_INPUT_COLUMNS, fund_rows, postgresql=True)
        funds_insert = postgresql_insert(VirtualFundTable).from_select(
            ["uid", "unique_identifier", "account_uid", "target_portfolio_uid"],
            select(
                fund_inputs.c.virtual_fund_uid,
                fund_inputs.c.unique_identifier,
                account_uid_param,
                fund_inputs.c.target_portfolio_uid,
            ).where(not_allocated),
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
        ctes += [fund_inputs, upserted_funds]
        # Every fund must have been written; a fund of another account is not taken over.
        gate = select(func.count()).select_from(upserted_funds).scalar_subquery() == literal(
            len(fund_rows)
        )
        steps.append(
            (
                "holdings_sets",
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
                    .where(gate),
                )
                .returning(
                    VirtualFundHoldingsSetTable.uid, VirtualFundHoldingsSetTable.virtual_fund_uid
                ),
            )
        )
    if holding_rows:
        holding_inputs = _input_values(
            "holding_inputs", _HOLDING_INPUT_COLUMNS, holding_rows, postgresql=True
        )
        fund_set_uids = fund_inputs.alias("fund_set_uids")
        ctes.append(holding_inputs)
        steps.append(
            (
                "inserted_holdings",
                insert(VirtualFundHoldingsStorage)
                .from_select(
                    _HOLDING_COLUMNS,
                    select(
                        time_param,
                        upserted_funds.c.uid,
                        holding_inputs.c.asset_identifier,
                        fund_set_uids.c.holdings_set_uid,
                        source_param,
                        holding_inputs.c.allocated_quantity,
                        holding_inputs.c.allocation_strategy,
                        holding_inputs.c.direction,
                        holding_inputs.c.extra_details,
                    )
                    .select_from(
                        holding_inputs.join(
                            upserted_funds,
                            upserted_funds.c.unique_identifier
                            == holding_inputs.c.fund_unique_identifier,
                        ).join(
                            fund_set_uids,
                            fund_set_uids.c.unique_identifier
                            == holding_inputs.c.fund_unique_identifier,
                        )
                    )
                    .where(gate),
                )
                .returning(VirtualFundHoldingsStorage),
            )
        )
    if line_rows:
        line_inputs = _input_values("line_inputs", _LINE_INPUT_COLUMNS, line_rows, postgresql=True)
        ctes.append(line_inputs)
        if upserted_funds is None:
            line_source = line_inputs
            fund_uid: Any = cast(literal(None), Uuid(as_uuid=True))
        else:
            line_source = line_inputs.outerjoin(
                upserted_funds,
                upserted_funds.c.unique_identifier == line_inputs.c.fund_unique_identifier,
            )
            fund_uid = upserted_funds.c.uid
        steps.append(
            (
                "inserted_lines",
                insert(AccountAllocationLinesStorage)
                .from_select(
                    _LINE_COLUMNS,
                    select(
                        time_param,
                        source_param,
                        line_inputs.c.owner_type,
                        func.coalesce(fund_uid, account_uid_param),
                        line_inputs.c.asset_identifier,
                        account_uid_param,
                        fund_uid,
                        line_inputs.c.target_quantity,
                        line_inputs.c.target_direction,
                        line_inputs.c.assigned_quantity,
                        line_inputs.c.assigned_direction,
                        line_inputs.c.allocation_strategy,
                        line_inputs.c.extra_details,
                    )
                    .select_from(line_source)
                    .where(gate),
                )
                .returning(AccountAllocationLinesStorage),
            )
        )

    *earlier, (_, statement) = steps
    for cte in ctes:
        statement = statement.add_cte(cte)
    for name, step in earlier:
        statement = statement.add_cte(step.cte(name))
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
    lines: Sequence[Mapping[str, Any]] = (),
) -> list[GuardedStatement | Any]:
    """The allocation write as ordered statements for one transaction.

    The first statement is the guard: it writes nothing when the snapshot already
    has an allocation, and with funds it requires every one of them to be
    upserted, so a fund of another account is not taken over. Then one holdings
    set per fund, the holdings rows and the lines. Later statements find funds
    and sets by key. The last statement answers its rows.
    """

    account = uuid.UUID(str(account_uid))
    source = uuid.UUID(str(source_account_holdings_set_uid))

    def account_param() -> Any:
        return bindparam("account_uid", value=account, type_=Uuid(as_uuid=True))

    def source_param() -> Any:
        return bindparam("source_account_holdings_set_uid", value=source, type_=Uuid(as_uuid=True))

    def time_param() -> Any:
        return bindparam("allocation_time", value=allocation_time, type_=DateTime(timezone=True))

    fund_rows, holding_rows, line_rows = _allocation_inputs(funds, lines)

    def fund_inputs() -> Any:
        return _input_values("fund_inputs", _FUND_INPUT_COLUMNS, fund_rows, postgresql=False)

    not_allocated = ~_snapshot_is_allocated(account_param(), source_param())
    statements: list[GuardedStatement | Any] = []
    if not fund_rows:
        statements.append(
            GuardedStatement(
                select(literal(1)).where(not_allocated),
                expect_rows=1,
                label=ALLOCATION_WRITE_GUARD,
            )
        )
    else:
        new_funds = fund_inputs()
        funds_insert = sqlite_insert(VirtualFundTable).from_select(
            ["uid", "unique_identifier", "account_uid", "target_portfolio_uid"],
            select(
                new_funds.c.virtual_fund_uid,
                new_funds.c.unique_identifier,
                account_param(),
                new_funds.c.target_portfolio_uid,
            )
            .select_from(new_funds)
            .where(not_allocated),
        )
        statements.append(
            GuardedStatement(
                funds_insert.on_conflict_do_update(
                    index_elements=[VirtualFundTable.unique_identifier],
                    set_={"target_portfolio_uid": funds_insert.excluded.target_portfolio_uid},
                    where=VirtualFundTable.account_uid == funds_insert.excluded.account_uid,
                ).returning(VirtualFundTable.uid),
                expect_rows=len(fund_rows),
                label=ALLOCATION_WRITE_GUARD,
            )
        )
        set_rows = fund_inputs()
        statements.append(
            insert(VirtualFundHoldingsSetTable)
            .from_select(
                ["uid", "virtual_fund_uid", "source_account_holdings_set_uid", "time_index"],
                select(
                    set_rows.c.holdings_set_uid,
                    VirtualFundTable.uid,
                    source_param(),
                    time_param(),
                )
                .select_from(
                    set_rows.join(
                        VirtualFundTable,
                        VirtualFundTable.unique_identifier == set_rows.c.unique_identifier,
                    )
                )
                .where(VirtualFundTable.account_uid == account_param()),
            )
            .returning(
                VirtualFundHoldingsSetTable.uid, VirtualFundHoldingsSetTable.virtual_fund_uid
            )
        )
    if holding_rows:
        holding_inputs = _input_values(
            "holding_inputs", _HOLDING_INPUT_COLUMNS, holding_rows, postgresql=False
        )
        statements.append(
            insert(VirtualFundHoldingsStorage)
            .from_select(
                _HOLDING_COLUMNS,
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
                        VirtualFundTable.unique_identifier
                        == holding_inputs.c.fund_unique_identifier,
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
    if line_rows:
        line_inputs = _input_values(
            "line_inputs", _LINE_INPUT_COLUMNS, line_rows, postgresql=False
        )
        statements.append(
            insert(AccountAllocationLinesStorage)
            .from_select(
                _LINE_COLUMNS,
                select(
                    time_param(),
                    source_param(),
                    line_inputs.c.owner_type,
                    func.coalesce(VirtualFundTable.uid, account_param()),
                    line_inputs.c.asset_identifier,
                    account_param(),
                    VirtualFundTable.uid,
                    line_inputs.c.target_quantity,
                    line_inputs.c.target_direction,
                    line_inputs.c.assigned_quantity,
                    line_inputs.c.assigned_direction,
                    line_inputs.c.allocation_strategy,
                    line_inputs.c.extra_details,
                ).select_from(
                    line_inputs.outerjoin(
                        VirtualFundTable,
                        and_(
                            VirtualFundTable.unique_identifier
                            == line_inputs.c.fund_unique_identifier,
                            VirtualFundTable.account_uid == account_param(),
                        ),
                    )
                ),
            )
            .returning(AccountAllocationLinesStorage)
        )
    return statements


def write_account_virtual_fund_allocation(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_write(
        build_write_account_virtual_fund_allocation_operation(context, **kwargs),
        context=context,
        refused_by=(ALLOCATION_WRITE_GUARD,),
    )


__all__ = [
    "ALLOCATION_WRITE_GUARD",
    "build_search_account_allocation_lines_operation",
    "build_search_account_virtual_fund_allocation_operation",
    "build_write_account_virtual_fund_allocation_operation",
    "search_account_allocation_lines",
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
