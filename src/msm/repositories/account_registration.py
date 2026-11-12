"""Register an account and write its holdings snapshot in one transaction (ADR 0051).

The registration reads twice: the assets it names (``asset_reference_details``), and the
account by ``unique_identifier`` with its holdings at ``holdings_date``
(``build_account_registration_state_operation``). It then sends one ordered statement list
that MetaTables runs in one transaction on PostgreSQL and SQLite (MetaTables ADR 0026):

1. the missing asset types and assets, with ``ON CONFLICT DO NOTHING``;
2. asset snapshot rows, with plain SQL at ``holdings_date``;
3. the account, only when it is missing or differs;
4. the holdings set, the removal of its rows on overwrite, and its new rows;
5. a select that answers the account, every named asset and the holdings set.

The holdings statements look the account uid up by ``unique_identifier`` inside each
statement, so concurrent first registrations of one account reference the account that won.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

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
    delete,
    false,
    func,
    insert,
    select,
    values,
)
from sqlalchemy.dialects.postgresql import JSONB

from metatables import (
    MetaTableCompiledSQLDialect,
    MetaTableCompiledSQLOperation,
    MetaTableOperationLimits,
)
from metatables.compiled_sql.v1 import GuardedStatement
from msm.models import AccountHoldingsSetTable, AccountTable, AssetTable, AssetTypeTable
from msm.time_index.accounts.storage import AccountHoldingsStorage
from msm.time_index.assets.snapshots import SNAPSHOT_VALUE_COLUMNS
from msm.time_index.assets.storage import AssetSnapshotsStorage

from .accounts import HOLDINGS_SET_GUARD
from .asset_registration import (
    NewAsset,
    NewAssetType,
    dialect_insert,
    insert_missing_asset_types,
    insert_missing_assets,
)
from .base import (
    MarketsCompiledWrite,
    MarketsRepositoryContext,
    compile_markets_statement,
    compile_markets_statements,
    execute_markets_operation,
    execute_markets_write,
    resolve_markets_sql_target,
    values_parameter,
)

ACCOUNT_COLUMNS: tuple[str, ...] = tuple(column.name for column in AccountTable.__table__.columns)
"""The account row's columns, as the state read and the answer return them."""

ACCOUNT_INSERT_DEFAULTS: dict[str, bool] = {"is_paper": True, "account_is_active": False}
"""A new account's flags when the registration leaves them out, as ``AccountCreate``'s."""



@dataclass(frozen=True)
class SnapshotRow:
    """One asset snapshot row the registration writes at ``holdings_date``."""

    asset_identifier: str
    name: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None
    asset_ticker_group_id: str | None = None


@dataclass(frozen=True)
class AccountWrite:
    """The account fields to insert, or to update on an existing account.

    ``uid`` is used only when the account is inserted. A flag left as ``None`` takes the
    table default on insert and is not changed on update.
    """

    uid: uuid.UUID
    account_name: str
    is_paper: bool | None = None
    account_is_active: bool | None = None


@dataclass(frozen=True)
class HoldingPosition:
    """One holdings row: the asset, its positive quantity, its side and extra details."""

    asset_identifier: str
    quantity: float
    direction: int
    extra_details: Mapping[str, Any]


@dataclass(frozen=True)
class HoldingsWrite:
    """The holdings snapshot to write. ``holdings_set_uid`` is used only on insert."""

    holdings_set_uid: uuid.UUID
    positions: tuple[HoldingPosition, ...]
    overwrite: bool = False


@dataclass(frozen=True)
class AccountRegistrationWrites:
    """Everything one registration writes, and the assets its answer names."""

    account_identifier: str
    holdings_date: dt.datetime
    asset_identifiers: tuple[str, ...]
    asset_types: tuple[NewAssetType, ...] = ()
    assets: tuple[NewAsset, ...] = ()
    snapshots: tuple[SnapshotRow, ...] = ()
    account: AccountWrite | None = None
    holdings: HoldingsWrite | None = None

    @property
    def is_empty(self) -> bool:
        return not (
            self.asset_types or self.assets or self.snapshots or self.account or self.holdings
        )


class _Params:
    """Bound parameters shared by the statements; each call is a new bind of the same name."""

    def __init__(
        self,
        *,
        account_identifier: str,
        holdings_date: dt.datetime,
        dialect: MetaTableCompiledSQLDialect | None = None,
    ) -> None:
        self.identifier = account_identifier
        self.holdings_date = holdings_date
        self.dialect = dialect

    def account_identifier(self) -> Any:
        return bindparam("account_identifier", value=self.identifier, type_=String())

    def date(self) -> Any:
        """``holdings_date``, cast on PostgreSQL, which cannot type a bare select-list value."""

        type_ = DateTime(timezone=True)
        parameter = bindparam("holdings_date", value=self.holdings_date, type_=type_)
        return cast(parameter, type_) if self.dialect == "postgresql" else parameter

    def account_uid(self) -> Any:
        """The account's uid, looked up by ``unique_identifier`` inside the statement."""

        return (
            select(AccountTable.uid)
            .where(AccountTable.unique_identifier == self.account_identifier())
            .scalar_subquery()
        )

    def holdings_set_uid(self) -> Any:
        return (
            select(AccountHoldingsSetTable.uid)
            .where(AccountHoldingsSetTable.account_uid == self.account_uid())
            .where(AccountHoldingsSetTable.time_index == self.date())
            .scalar_subquery()
        )


def build_account_registration_state_operation(
    context: MarketsRepositoryContext,
    *,
    account_identifier: str,
    holdings_date: dt.datetime,
    max_rows: int,
) -> MetaTableCompiledSQLOperation:
    """One read: the account by ``unique_identifier`` with its holdings at ``holdings_date``.

    The account left-joins its holdings set at ``holdings_date`` and that set's rows, so it
    answers one row per stored holding, or one row with null holding columns, or no row
    when the account does not exist. ``max_rows`` bounds the rows returned.
    """

    params = _Params(account_identifier=account_identifier, holdings_date=holdings_date)
    statement = (
        select(
            *AccountTable.__table__.columns,
            AccountHoldingsSetTable.uid.label("holdings_set_uid"),
            AccountHoldingsStorage.asset_identifier.label("holding_asset_identifier"),
            AccountHoldingsStorage.quantity.label("holding_quantity"),
            AccountHoldingsStorage.direction.label("holding_direction"),
            AccountHoldingsStorage.target_trade_time.label("holding_target_trade_time"),
            AccountHoldingsStorage.extra_details.label("holding_extra_details"),
        )
        .select_from(AccountTable)
        .outerjoin(
            AccountHoldingsSetTable,
            and_(
                AccountHoldingsSetTable.account_uid == AccountTable.uid,
                AccountHoldingsSetTable.time_index == params.date(),
            ),
        )
        .outerjoin(
            AccountHoldingsStorage,
            AccountHoldingsStorage.holdings_set_uid == AccountHoldingsSetTable.uid,
        )
        .where(AccountTable.unique_identifier == params.account_identifier())
        .order_by(AccountHoldingsStorage.asset_identifier)
    )
    return compile_markets_statement(
        statement,
        context=with_max_rows(context, max_rows),
        operation="select",
    )


def read_account_registration_state(
    context: MarketsRepositoryContext,
    *,
    account_identifier: str,
    holdings_date: dt.datetime,
    max_rows: int,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_account_registration_state_operation(
            context,
            account_identifier=account_identifier,
            holdings_date=holdings_date,
            max_rows=max_rows,
        ),
        context=context,
    )


def account_registration_statements(
    writes: AccountRegistrationWrites,
    *,
    dialect: MetaTableCompiledSQLDialect,
) -> list[GuardedStatement | Any]:
    """The registration as ordered statements for one transaction (ADR 0051, decision 3).

    Each statement is present only when it writes something. The last one answers the
    account row, every named asset with its type's uid, the holdings set uid and its row
    count. When the holdings set exists and ``overwrite`` is false, its insert is refused
    by the ``holdings_set`` guard and the whole transaction rolls back.
    """

    if not writes.asset_identifiers:
        raise ValueError("An account registration names at least one asset.")
    params = _Params(
        account_identifier=writes.account_identifier,
        holdings_date=writes.holdings_date,
        dialect=dialect,
    )
    statements: list[GuardedStatement | Any] = []
    if writes.asset_types:
        statements.append(insert_missing_asset_types(writes.asset_types, dialect=dialect))
    if writes.assets:
        statements.append(insert_missing_assets(writes.assets, dialect=dialect))
    if writes.snapshots:
        statements.append(_insert_snapshots(writes.snapshots, params=params, dialect=dialect))
    if writes.account is not None:
        statements.append(_upsert_account(writes.account, params=params, dialect=dialect))
    if writes.holdings is not None:
        statements.extend(_holdings_statements(writes.holdings, params=params, dialect=dialect))
    statements.append(_answer(writes.asset_identifiers, params=params))
    return statements


def build_register_account_operation(
    context: MarketsRepositoryContext,
    writes: AccountRegistrationWrites,
    *,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the registration's writes as one transaction for the context's DataSource."""

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        account_registration_statements(writes, dialect=dialect),
        context=with_max_rows(context, len(writes.asset_identifiers)),
        operation="upsert",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def register_account(
    context: MarketsRepositoryContext,
    writes: AccountRegistrationWrites,
) -> dict[str, Any]:
    """Run the registration's writes; no rows when the holdings set guard refuses them."""

    return execute_markets_write(
        build_register_account_operation(context, writes),
        context=context,
        refused_by=(HOLDINGS_SET_GUARD,),
    )


def with_max_rows(context: MarketsRepositoryContext, max_rows: int) -> MarketsRepositoryContext:
    """``context`` whose operations return at least ``max_rows`` rows."""

    limits = MetaTableOperationLimits.model_validate(context.limits or {})
    if limits.max_rows >= max_rows:
        return context
    return MarketsRepositoryContext(
        limits=limits.model_copy(update={"max_rows": max_rows}),
        data_source_uid=context.data_source_uid,
        timeout=context.timeout,
        namespace=context.namespace,
    )


def _insert_snapshots(
    snapshots: Sequence[SnapshotRow],
    *,
    params: _Params,
    dialect: MetaTableCompiledSQLDialect,
) -> Any:
    """Snapshot rows at ``holdings_date``; a row already at that key is left as it is."""

    return (
        dialect_insert(AssetSnapshotsStorage, dialect)
        .values(
            [
                {
                    "time_index": params.holdings_date,
                    "asset_identifier": row.asset_identifier,
                    # A missing value is written as an empty string, as the updater does.
                    **{name: getattr(row, name) or "" for name in SNAPSHOT_VALUE_COLUMNS},
                }
                for row in snapshots
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[AssetSnapshotsStorage.time_index, AssetSnapshotsStorage.asset_identifier]
        )
    )


def _upsert_account(
    account: AccountWrite,
    *,
    params: _Params,
    dialect: MetaTableCompiledSQLDialect,
) -> Any:
    supplied = {
        "account_name": account.account_name,
        "is_paper": account.is_paper,
        "account_is_active": account.account_is_active,
    }
    supplied = {key: value for key, value in supplied.items() if value is not None}
    # The inserted row needs every NOT NULL column even when it then conflicts.
    statement = dialect_insert(AccountTable, dialect).values(
        uid=account.uid,
        unique_identifier=params.identifier,
        **{**ACCOUNT_INSERT_DEFAULTS, **supplied},
    )
    return statement.on_conflict_do_update(
        index_elements=[AccountTable.unique_identifier],
        set_={key: statement.excluded[key] for key in supplied},
    )


def _holdings_statements(
    holdings: HoldingsWrite,
    *,
    params: _Params,
    dialect: MetaTableCompiledSQLDialect,
) -> list[GuardedStatement | Any]:
    """Upsert the holdings set, remove its rows on overwrite, insert the new rows.

    As ``replace_account_holdings_snapshot``'s statement list, with the account uid looked
    up by ``unique_identifier``. Without ``overwrite`` an existing set is not touched and
    its guard refuses the transaction.
    """

    set_insert = dialect_insert(AccountHoldingsSetTable, dialect).values(
        uid=bindparam("holdings_set_uid", value=holdings.holdings_set_uid, type_=Uuid(as_uuid=True)),
        account_uid=params.account_uid(),
        time_index=params.date(),
    )
    conflict_keys = [AccountHoldingsSetTable.account_uid, AccountHoldingsSetTable.time_index]
    set_statement = (
        set_insert.on_conflict_do_update(
            index_elements=conflict_keys,
            set_={"time_index": set_insert.excluded.time_index},
        )
        if holdings.overwrite
        else set_insert.on_conflict_do_nothing(index_elements=conflict_keys)
    )
    statements: list[GuardedStatement | Any] = [
        GuardedStatement(
            set_statement.returning(AccountHoldingsSetTable.uid),
            expect_rows=1,
            label=HOLDINGS_SET_GUARD,
        )
    ]
    if holdings.overwrite:
        statements.append(
            delete(AccountHoldingsStorage).where(
                AccountHoldingsStorage.holdings_set_uid == params.holdings_set_uid()
            )
        )

    input_rows = _input_rows(holdings.positions, dialect=dialect)
    statements.append(
        insert(AccountHoldingsStorage).from_select(
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
                params.date(),
                params.account_uid(),
                input_rows.c.asset_identifier,
                params.holdings_set_uid(),
                false(),
                input_rows.c.quantity,
                input_rows.c.direction,
                params.date(),
                input_rows.c.extra_details,
            ).select_from(input_rows),
        )
    )
    return statements


def _input_rows(
    positions: Sequence[HoldingPosition],
    *,
    dialect: MetaTableCompiledSQLDialect,
) -> Any:
    """The positions as a ``VALUES`` list, typed by ``values_parameter`` for the dialect."""

    json_type = JSONB() if dialect == "postgresql" else JSON()

    def typed(value: Any, type_: Any) -> Any:
        return values_parameter(value, type_, dialect=dialect)

    return (
        values(
            column("asset_identifier", String()),
            column("quantity", Float()),
            column("direction", SmallInteger()),
            column("extra_details", json_type),
            name="input_rows",
        )
        .data(
            [
                (
                    typed(position.asset_identifier, String()),
                    typed(position.quantity, Float()),
                    typed(position.direction, SmallInteger()),
                    typed(dict(position.extra_details), json_type),
                )
                for position in positions
            ]
        )
        .cte("input_rows")
    )


def _answer(asset_identifiers: Sequence[str], *, params: _Params) -> Any:
    """The account row and every named asset, one row per asset, with the holdings set."""

    asset_type_uid = (
        select(AssetTypeTable.uid)
        .where(AssetTypeTable.asset_type == AssetTable.asset_type)
        .scalar_subquery()
    )
    holdings_row_count = (
        select(func.count())
        .select_from(AccountHoldingsStorage)
        .where(AccountHoldingsStorage.holdings_set_uid == params.holdings_set_uid())
        .scalar_subquery()
    )
    return (
        select(
            *AccountTable.__table__.columns,
            AssetTable.unique_identifier.label("asset_identifier"),
            AssetTable.uid.label("asset_uid"),
            AssetTable.asset_type.label("asset_type"),
            asset_type_uid.label("asset_type_uid"),
            params.holdings_set_uid().label("holdings_set_uid"),
            holdings_row_count.label("holdings_row_count"),
        )
        .select_from(AssetTable)
        .join(AccountTable, AccountTable.unique_identifier == params.account_identifier())
        .where(AssetTable.unique_identifier.in_(list(asset_identifiers)))
        .order_by(AssetTable.unique_identifier)
    )


__all__ = [
    "ACCOUNT_COLUMNS",
    "AccountRegistrationWrites",
    "AccountWrite",
    "HoldingPosition",
    "HoldingsWrite",
    "SnapshotRow",
    "account_registration_statements",
    "build_account_registration_state_operation",
    "build_register_account_operation",
    "read_account_registration_state",
    "register_account",
    "with_max_rows",
]
