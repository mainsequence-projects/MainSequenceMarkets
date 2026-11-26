"""A virtual fund names its target allocation (ADR 0029, issue 157).

``ms_markets__virtualfund`` gains ``account_target_allocation_uid``, a key to
``ms_markets__accounttargetallocation.uid`` that deletes the fund with its allocation,
and a unique index on ``(account_target_allocation_uid, target_portfolio_uid)``. Until
now the allocation was only inside the fund's ``unique_identifier``, a hash of the
account, the portfolio and the allocation's uid, so finding an account's fund for a
portfolio took a read of the allocation first.

The upgrade fills the column from that hash: a fund's allocation is the allocation of
its account for which ``fund_unique_identifier(account, portfolio, allocation)`` is the
fund's ``unique_identifier``. The function is the key formula as ms-markets defines it
at 0040. Every fund belongs to an allocation, so the upgrade refuses, before it changes
anything, a database with a fund whose key matches no allocation of its account, and
names each such fund. It deletes and rewrites nothing. PostgreSQL then makes the column
NOT NULL.

The table has keys into it (virtual-fund holdings sets and holdings), so the column is
added in place and the table is never rebuilt on SQLite: a rebuilt table is created
last, and SQLite runs the actions of the keys into a deleted row in reverse creation
order (revision 0035). SQLite adds a column with a key only as ``ALTER TABLE ... ADD
COLUMN ... REFERENCES``, which Alembic does not emit, and only as a nullable column. Its
reflection does not read the name or the delete action of such a key, although SQLite
enforces both.

The downgrade drops the index, the key and the column, in place on SQLite too.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from alembic import op
import sqlalchemy as sa

revision: str = "0040"
down_revision: str = "0039"
branch_labels = None
depends_on = None

FUND = "ms_markets__virtualfund"
ALLOCATION = "ms_markets__accounttargetallocation"
COLUMN = "account_target_allocation_uid"
KEY = "fk__ms_markets__virtualfund__account_target_allocati_c12fa0428f"
INDEX = "uix__ms_markets__virtualfund__account_target_allocat_69d2a0b856"
ON_DELETE = "CASCADE"


def fund_unique_identifier(
    account_uid: Any, target_portfolio_uid: Any, account_target_allocation_uid: Any
) -> str:
    """A fund's ``unique_identifier``, as ms-markets builds it at 0040."""

    key = (
        "msm.account_virtual_fund:"
        f"account={_uid(account_uid)}:"
        f"portfolio={_uid(target_portfolio_uid)}:"
        f"target_allocation={_uid(account_target_allocation_uid)}"
    )
    return f"account-virtual-fund-{uuid.uuid5(uuid.NAMESPACE_URL, key)}"


def _uid(value: Any) -> str:
    """A uid as dashed text, or the stored text when it is not a uid."""

    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return str(value)


# The uids are read and written untyped, as the database stores them.
def _funds() -> sa.Table:
    return sa.table(
        FUND,
        sa.column("uid"),
        sa.column("unique_identifier", sa.String()),
        sa.column("account_uid"),
        sa.column(COLUMN),
        sa.column("target_portfolio_uid"),
    )


def _allocations() -> sa.Table:
    return sa.table(ALLOCATION, sa.column("uid"), sa.column("account_uid"))


# Upgrade ---------------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    matched, unmatched = _fund_allocations(bind)
    if unmatched:
        named = "; ".join(
            f"uid {_uid(fund['uid'])}, account {_uid(fund['account_uid'])}, "
            f"unique_identifier {fund['unique_identifier']!r}"
            for fund in unmatched[:20]
        )
        raise RuntimeError(
            f"Revision 0040 refuses to run: {len(unmatched)} virtual funds have a "
            "unique_identifier that matches no target allocation of their account, and every "
            f"fund belongs to one: {named}. Nothing was changed."
        )

    _add_column(bind)
    if matched:
        funds = _funds()
        bind.execute(
            funds.update()
            .where(funds.c.uid == sa.bindparam("fund_uid"))
            .values({COLUMN: sa.bindparam("allocation_uid")}),
            [
                {"fund_uid": fund_uid, "allocation_uid": allocation_uid}
                for fund_uid, allocation_uid in matched.items()
            ],
        )
    op.create_index(op.f(INDEX), FUND, [COLUMN, "target_portfolio_uid"], unique=True)
    if bind.dialect.name != "sqlite":
        # SQLite keeps the column nullable: NOT NULL needs a rebuild, and keys point into it.
        op.alter_column(FUND, COLUMN, existing_type=sa.Uuid(), nullable=False)


def _fund_allocations(bind: Any) -> tuple[dict[Any, Any], list[dict[str, Any]]]:
    """Each fund's allocation by fund uid, and the funds whose key matches none."""

    allocations: dict[str, list[Any]] = defaultdict(list)
    for row in bind.execute(sa.select(_allocations())).mappings():
        allocations[_uid(row["account_uid"])].append(row["uid"])
    funds = _funds()
    matched: dict[Any, Any] = {}
    unmatched: list[dict[str, Any]] = []
    for fund in bind.execute(
        sa.select(funds.c.uid, funds.c.unique_identifier, funds.c.account_uid,
                  funds.c.target_portfolio_uid)
    ).mappings():
        allocation_uid = next(
            (
                allocation_uid
                for allocation_uid in allocations.get(_uid(fund["account_uid"]), ())
                if fund_unique_identifier(
                    fund["account_uid"], fund["target_portfolio_uid"], allocation_uid
                )
                == fund["unique_identifier"]
            ),
            None,
        )
        if allocation_uid is None:
            unmatched.append(dict(fund))
        else:
            matched[fund["uid"]] = allocation_uid
    return matched, unmatched


def _add_column(bind: Any) -> None:
    if bind.dialect.name == "sqlite":
        # Alembic adds a key on SQLite only by rebuilding the table.
        op.execute(
            sa.text(
                f"ALTER TABLE {FUND} ADD COLUMN {COLUMN} CHAR(32) CONSTRAINT {KEY} "
                f"REFERENCES {ALLOCATION} (uid) ON DELETE {ON_DELETE}"
            )
        )
        return
    op.add_column(FUND, sa.Column(COLUMN, sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f(KEY), FUND, ALLOCATION, [COLUMN], ["uid"], ondelete=ON_DELETE)


# Downgrade -------------------------------------------------------------------------------


def downgrade() -> None:
    op.drop_index(op.f(INDEX), table_name=FUND)
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(op.f(KEY), FUND, type_="foreignkey")
    # SQLite drops the column and its key in place.
    with op.batch_alter_table(FUND, schema=None, recreate="never") as batch_op:
        batch_op.drop_column(COLUMN)
