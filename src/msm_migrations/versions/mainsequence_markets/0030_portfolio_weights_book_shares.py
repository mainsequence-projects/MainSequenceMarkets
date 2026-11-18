"""Carry the rebalance book's shares and cash into the portfolio weights (ADR 0059).

A portfolio without a ledger is valued from the shares ``PortfolioRebalance``
records, so its weights drift with prices between rebalances. ``PortfolioWeights``
projects each row's shares and the book's cash into two nullable columns: rows
written before this revision, and rows of strategies that record no book, carry
none.

Only the Markets-owned table is migrated here. A provider adds the same columns to
its own ``PortfolioWeightsTS`` instances in a revision of its own.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0030"
down_revision: str = "0029"
branch_labels = None
depends_on = None

TABLE = "ms_markets__portfolioweightsts"
COLUMNS = ("held_shares", "book_cash")


def upgrade() -> None:
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        for column in COLUMNS:
            batch_op.add_column(sa.Column(column, sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        for column in reversed(COLUMNS):
            batch_op.drop_column(column)
