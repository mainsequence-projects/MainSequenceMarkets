"""An order has its own row (ADR 0064).

``ms_markets__order`` holds one row per order: its uid, account, asset, order manager and
the terms it was created with. The execution tables reference it:

- ``ms_markets__ordersts`` keeps an order's state, keyed by ``(order_time, order_uid)``;
  the order's account, asset, manager and terms move to its ``Order`` row.
- ``ms_markets__ordereventsts`` is keyed by ``(event_time, order_uid)``.
- ``ms_markets__tradests`` is keyed by ``(trade_time, trade_identifier)``; a trade of an
  order references ``(order_uid, account_identifier, asset_identifier)`` of its order.

Each ``order_identifier`` becomes an ``order_uid``: the identifier itself when it is a
UUID, else ``uuid5(ORDER_UID_NAMESPACE, identifier)``, so an order's state rows, events
and trades keep naming the same order. An order's ``Order`` row takes its account, asset,
manager and terms from its earliest state row; an empty string there becomes null.

The upgrade refuses, before it changes anything, a database where an order cannot get
one row: an identifier with state rows of two accounts or assets, a trade or an event
that names an order with no state row, or two trades with the same time and identifier.
Those rows are to be corrected first.

Only the Markets-owned tables are migrated here. An application's instances of these
tables are migrated by the application's own migrations.

SQLite rebuilds the three execution tables to drop columns that hold foreign keys. No
key points into them, so the rebuild does not change how SQLite orders the actions of
the keys into a deleted account row (revision 0035).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from alembic import op
import sqlalchemy as sa

revision: str = "0037"
down_revision: str = "0036"
branch_labels = None
depends_on = None

ORDER_UID_NAMESPACE = uuid.UUID("0b8f1c52-4a77-5c7e-9d2e-6a3f0c1e8b64")
"""Namespace of the uids given to order identifiers that are not UUIDs."""

ORDER = "ms_markets__order"
ORDERS = "ms_markets__ordersts"
EVENTS = "ms_markets__ordereventsts"
TRADES = "ms_markets__tradests"
UID_MAP = "_ms_markets_0037_order_uids"

ORDER_TERMS = (
    "order_side",
    "order_type",
    "quantity",
    "limit_price",
    "time_in_force",
    "expires_time",
    "client_order_id",
)
MOVED_COLUMNS = (
    "order_identifier",
    "account_identifier",
    "order_manager_identifier",
    "asset_identifier",
    *ORDER_TERMS,
)

ORDERS_GRAIN_INDEX = "uix__ms_markets__ordersts__order_time__order_uid"
ORDERS_ORDER_INDEX = "ix__ms_markets__ordersts__order_uid__order_time"
ORDERS_ORDER_KEY = "fk__ms_markets__ordersts__order_uid__ms_markets__order__uid"
FORMER_ORDERS_GRAIN_INDEX = "uix__ms_markets__ordersts__order_time__order_identif_20c686be5c"
FORMER_ORDERS_INDEXES = (
    ("ix__ms_markets__ordersts__account_identifier__order_time", ("account_identifier", "order_time")),
    ("ix__ms_markets__ordersts__order_manager_identifier", ("order_manager_identifier",)),
    ("ix__ms_markets__ordersts__order_identifier", ("order_identifier",)),
)
FORMER_ORDERS_KEYS = (
    (
        "fk__ms_markets__ordersts__account_identifier__ms_mar_dc1a18e044",
        "account_identifier",
        "ms_markets__account",
    ),
    (
        "fk__ms_markets__ordersts__asset_identifier__ms_marke_e41085088a",
        "asset_identifier",
        "ms_markets__asset",
    ),
    (
        "fk__ms_markets__ordersts__order_manager_identifier_b80dd3d684",
        "order_manager_identifier",
        "ms_markets__ordermanager",
    ),
)

EVENTS_GRAIN_INDEX = "uix__ms_markets__ordereventsts__event_time__order_uid"
EVENTS_ORDER_INDEX = "ix__ms_markets__ordereventsts__order_uid__event_time"
EVENTS_ORDER_KEY = "fk__ms_markets__ordereventsts__order_uid__ms_markets_75a00bd0fe"
FORMER_EVENTS_GRAIN_INDEX = "uix__ms_markets__ordereventsts__event_time__order_identifier"
FORMER_EVENTS_INDEX = "ix__ms_markets__ordereventsts__order_identifier__event_time"

TRADES_GRAIN_INDEX = "uix__ms_markets__tradests__trade_time__trade_identifier"
TRADES_ORDER_INDEX = "ix__ms_markets__tradests__order_uid"
TRADES_ORDER_KEY = "fk__ms_markets__tradests__order_uid__account_identif_cde226899a"
FORMER_TRADES_GRAIN_INDEX = "uix__ms_markets__tradests__trade_time__trade_identif_4ad9fea888"
FORMER_TRADES_GRAIN = ["trade_time", "trade_identifier", "account_identifier", "asset_identifier"]


def order_uid(identifier: str) -> uuid.UUID:
    """The uid an order identifier becomes."""

    try:
        return uuid.UUID(identifier)
    except ValueError:
        return uuid.uuid5(ORDER_UID_NAMESPACE, identifier)


# Upgrade ---------------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    orders, uids = _orders(bind)
    _refuse_unknown_orders(bind, uids)
    _refuse_repeated_trades(bind)

    _create_order_table()
    if orders:
        bind.execute(_order_table().insert(), list(orders.values()))
    _create_uid_map(bind, uids)

    for table in (ORDERS, EVENTS):
        with op.batch_alter_table(table, schema=None, recreate="never") as batch_op:
            batch_op.add_column(sa.Column("order_uid", sa.Uuid(), nullable=True))
    with op.batch_alter_table(TRADES, schema=None, recreate="never") as batch_op:
        batch_op.add_column(sa.Column("order_uid", sa.Uuid(), nullable=True))
    for table in (ORDERS, EVENTS, TRADES):
        op.execute(
            sa.text(
                f"UPDATE {table} SET order_uid = (SELECT {UID_MAP}.order_uid FROM {UID_MAP} "
                f"WHERE {UID_MAP}.order_identifier = {table}.order_identifier)"
            )
        )
    op.drop_table(UID_MAP)

    with op.batch_alter_table(ORDERS, schema=None) as batch_op:
        batch_op.drop_index(FORMER_ORDERS_GRAIN_INDEX)
        for index, _columns in FORMER_ORDERS_INDEXES:
            batch_op.drop_index(index)
        for key, _column, _target in FORMER_ORDERS_KEYS:
            batch_op.drop_constraint(key, type_="foreignkey")
        for column in MOVED_COLUMNS:
            batch_op.drop_column(column)
        batch_op.alter_column("order_uid", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_foreign_key(
            op.f(ORDERS_ORDER_KEY), ORDER, ["order_uid"], ["uid"], ondelete="RESTRICT"
        )
        batch_op.create_index(ORDERS_GRAIN_INDEX, ["order_time", "order_uid"], unique=True)
        batch_op.create_index(ORDERS_ORDER_INDEX, ["order_uid", "order_time"], unique=False)

    with op.batch_alter_table(EVENTS, schema=None) as batch_op:
        batch_op.drop_index(FORMER_EVENTS_GRAIN_INDEX)
        batch_op.drop_index(FORMER_EVENTS_INDEX)
        batch_op.drop_column("order_identifier")
        batch_op.alter_column("order_uid", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_foreign_key(
            op.f(EVENTS_ORDER_KEY), ORDER, ["order_uid"], ["uid"], ondelete="RESTRICT"
        )
        batch_op.create_index(EVENTS_GRAIN_INDEX, ["event_time", "order_uid"], unique=True)
        batch_op.create_index(EVENTS_ORDER_INDEX, ["order_uid", "event_time"], unique=False)

    with op.batch_alter_table(TRADES, schema=None) as batch_op:
        batch_op.drop_index(FORMER_TRADES_GRAIN_INDEX)
        batch_op.drop_column("order_identifier")
        batch_op.create_foreign_key(
            op.f(TRADES_ORDER_KEY),
            ORDER,
            ["order_uid", "account_identifier", "asset_identifier"],
            ["uid", "account_identifier", "asset_identifier"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(TRADES_GRAIN_INDEX, ["trade_time", "trade_identifier"], unique=True)
        batch_op.create_index(TRADES_ORDER_INDEX, ["order_uid"], unique=False)


def _orders(bind: Any) -> tuple[dict[uuid.UUID, dict[str, Any]], dict[str, uuid.UUID]]:
    """Each order's ``Order`` row, from its earliest state row, and each identifier's uid."""

    columns = ", ".join(("order_identifier", "account_identifier", "asset_identifier",
                         "order_manager_identifier", *ORDER_TERMS))
    rows = bind.execute(
        sa.text(f"SELECT {columns} FROM {ORDERS} ORDER BY order_time, order_identifier")
    ).mappings()
    orders: dict[uuid.UUID, dict[str, Any]] = {}
    uids: dict[str, uuid.UUID] = {}
    conflicts: list[str] = []
    for row in rows:
        identifier = str(row["order_identifier"])
        uid = uids.setdefault(identifier, order_uid(identifier))
        order = orders.get(uid)
        if order is None:
            orders[uid] = {
                "uid": uid,
                "account_identifier": row["account_identifier"],
                "asset_identifier": row["asset_identifier"],
                "order_manager_identifier": row["order_manager_identifier"] or None,
                **{term: _blank_to_none(row[term]) for term in ORDER_TERMS},
            }
        elif (order["account_identifier"], order["asset_identifier"]) != (
            row["account_identifier"],
            row["asset_identifier"],
        ):
            conflicts.append(identifier)
    if conflicts:
        raise RuntimeError(
            "Revision 0037 refuses to run: these order identifiers have state rows of more "
            "than one account or asset, so they cannot be one order: "
            f"{', '.join(sorted(set(conflicts))[:20])}. Give each order its own identifier "
            f"in {ORDERS} first."
        )
    return orders, uids


def _refuse_unknown_orders(bind: Any, uids: Mapping[str, uuid.UUID]) -> None:
    unknown: list[str] = []
    for table in (EVENTS, TRADES):
        identifiers = bind.execute(
            sa.text(
                f"SELECT DISTINCT order_identifier FROM {table} "
                "WHERE order_identifier IS NOT NULL AND order_identifier <> ''"
            )
        ).scalars()
        unknown.extend(
            f"{table}: {identifier}" for identifier in identifiers if identifier not in uids
        )
    if unknown:
        raise RuntimeError(
            "Revision 0037 refuses to run: these events and trades name an order with no "
            f"state row in {ORDERS}: {', '.join(unknown[:20])}. Write the orders' state rows "
            "or correct the identifiers first."
        )


def _refuse_repeated_trades(bind: Any) -> None:
    repeated = bind.execute(
        sa.text(
            f"SELECT trade_identifier FROM {TRADES} GROUP BY trade_time, trade_identifier "
            "HAVING count(*) > 1"
        )
    ).scalars().all()
    if repeated:
        raise RuntimeError(
            "Revision 0037 refuses to run: these trade identifiers have more than one trade at "
            f"the same time: {', '.join(sorted(set(repeated))[:20])}. A trade is keyed by its "
            "time and identifier; give each trade its own identifier first."
        )


def _blank_to_none(value: Any) -> Any:
    return None if value == "" else value


def _create_order_table() -> None:
    op.create_table(
        ORDER,
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("account_identifier", sa.String(length=255), nullable=False),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("order_manager_identifier", sa.String(length=255), nullable=True),
        sa.Column("replaces_order_uid", sa.Uuid(), nullable=True),
        sa.Column("order_side", sa.BigInteger(), nullable=True),
        sa.Column("order_type", sa.String(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("limit_price", sa.Float(), nullable=True),
        sa.Column("time_in_force", sa.String(), nullable=True),
        sa.Column("expires_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_order_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_identifier"],
            ["ms_markets__account.unique_identifier"],
            name=op.f("fk__ms_markets__order__account_identifier__ms_market_241038d166"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__ms_markets__order__asset_identifier__ms_markets_e417791fa6"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_manager_identifier"],
            ["ms_markets__ordermanager.unique_identifier"],
            name=op.f("fk__ms_markets__order__order_manager_identifier__ms_ebed6ae83f"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__ms_markets__order")),
        info={"markets_storage_app": "ms_markets", "namespace": "mainsequence.markets", "identifier": "Order"},
    )
    with op.batch_alter_table(ORDER, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("uix__ms_markets__order__uid__account_identifier__ass_8848164e20"),
            ["uid", "account_identifier", "asset_identifier"],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f("ix__ms_markets__order__account_identifier"), ["account_identifier"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix__ms_markets__order__order_manager_identifier"),
            ["order_manager_identifier"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix__ms_markets__order__replaces_order_uid"), ["replaces_order_uid"], unique=False
        )
    # The replaced order's key targets the unique index above, which must exist first.
    with op.batch_alter_table(ORDER, schema=None) as batch_op:
        batch_op.create_foreign_key(
            op.f("fk__ms_markets__order__replaces_order_uid__account_i_3d288c7530"),
            ORDER,
            ["replaces_order_uid", "account_identifier", "asset_identifier"],
            ["uid", "account_identifier", "asset_identifier"],
        )


def _order_table() -> sa.Table:
    return sa.Table(
        ORDER,
        sa.MetaData(),
        sa.Column("uid", sa.Uuid()),
        sa.Column("account_identifier", sa.String()),
        sa.Column("asset_identifier", sa.String()),
        sa.Column("order_manager_identifier", sa.String()),
        sa.Column("order_side", sa.BigInteger()),
        sa.Column("order_type", sa.String()),
        sa.Column("quantity", sa.Float()),
        sa.Column("limit_price", sa.Float()),
        sa.Column("time_in_force", sa.String()),
        sa.Column("expires_time", sa.DateTime(timezone=True)),
        sa.Column("client_order_id", sa.String()),
    )


def _uid_map() -> sa.Table:
    return sa.Table(
        UID_MAP,
        sa.MetaData(),
        sa.Column("order_identifier", sa.String(), primary_key=True),
        sa.Column("order_uid", sa.Uuid(), nullable=False),
    )


def _create_uid_map(bind: Any, uids: Mapping[str, uuid.UUID]) -> None:
    table = _uid_map()
    table.create(bind)
    if uids:
        bind.execute(
            table.insert(),
            [{"order_identifier": identifier, "order_uid": uid} for identifier, uid in uids.items()],
        )


# Downgrade -------------------------------------------------------------------------------


def downgrade() -> None:
    """Put the order identifiers back as the uids' text, and the orders' columns back on
    their state rows; trades of an order get the order's identifier again."""

    bind = op.get_bind()
    orders = list(bind.execute(sa.select(_order_table())).mappings())
    table = _uid_map()
    table.create(bind)
    if orders:
        bind.execute(
            table.insert(),
            [{"order_identifier": str(order["uid"]), "order_uid": order["uid"]} for order in orders],
        )

    with op.batch_alter_table(ORDERS, schema=None, recreate="never") as batch_op:
        batch_op.add_column(sa.Column("order_identifier", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("account_identifier", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("order_manager_identifier", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("asset_identifier", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("client_order_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("order_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("order_side", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("quantity", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("expires_time", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("limit_price", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("time_in_force", sa.String(), nullable=True))
    for events_or_trades in (EVENTS, TRADES):
        with op.batch_alter_table(events_or_trades, schema=None, recreate="never") as batch_op:
            batch_op.add_column(sa.Column("order_identifier", sa.String(), nullable=True))

    moved = ", ".join(
        f"{column} = (SELECT {ORDER}.{column} FROM {ORDER} WHERE {ORDER}.uid = {ORDERS}.order_uid)"
        for column in ("account_identifier", "order_manager_identifier", "asset_identifier", *ORDER_TERMS)
    )
    op.execute(sa.text(f"UPDATE {ORDERS} SET {moved}"))
    for target in (ORDERS, EVENTS, TRADES):
        op.execute(
            sa.text(
                f"UPDATE {target} SET order_identifier = (SELECT {UID_MAP}.order_identifier "
                f"FROM {UID_MAP} WHERE {UID_MAP}.order_uid = {target}.order_uid)"
            )
        )
    op.drop_table(UID_MAP)

    with op.batch_alter_table(TRADES, schema=None) as batch_op:
        batch_op.drop_index(TRADES_ORDER_INDEX)
        batch_op.drop_index(TRADES_GRAIN_INDEX)
        batch_op.drop_constraint(TRADES_ORDER_KEY, type_="foreignkey")
        batch_op.drop_column("order_uid")
        batch_op.create_index(FORMER_TRADES_GRAIN_INDEX, FORMER_TRADES_GRAIN, unique=True)

    with op.batch_alter_table(EVENTS, schema=None) as batch_op:
        batch_op.drop_index(EVENTS_ORDER_INDEX)
        batch_op.drop_index(EVENTS_GRAIN_INDEX)
        batch_op.drop_constraint(EVENTS_ORDER_KEY, type_="foreignkey")
        batch_op.drop_column("order_uid")
        batch_op.alter_column("order_identifier", existing_type=sa.String(), nullable=False)
        batch_op.create_index(FORMER_EVENTS_GRAIN_INDEX, ["event_time", "order_identifier"], unique=True)
        batch_op.create_index(FORMER_EVENTS_INDEX, ["order_identifier", "event_time"], unique=False)

    with op.batch_alter_table(ORDERS, schema=None) as batch_op:
        batch_op.drop_index(ORDERS_ORDER_INDEX)
        batch_op.drop_index(ORDERS_GRAIN_INDEX)
        batch_op.drop_constraint(ORDERS_ORDER_KEY, type_="foreignkey")
        batch_op.drop_column("order_uid")
        for column in ("order_identifier", "account_identifier", "asset_identifier"):
            batch_op.alter_column(column, existing_type=sa.String(), nullable=False)
        for key, column, target in FORMER_ORDERS_KEYS:
            batch_op.create_foreign_key(
                op.f(key), target, [column], ["unique_identifier"], ondelete="RESTRICT"
            )
        batch_op.create_index(
            FORMER_ORDERS_GRAIN_INDEX,
            ["order_time", "order_identifier", "account_identifier", "asset_identifier"],
            unique=True,
        )
        for index, columns in FORMER_ORDERS_INDEXES:
            batch_op.create_index(index, list(columns), unique=False)

    op.drop_table(ORDER)
