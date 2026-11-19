"""Mark portfolio values that used a stale price (ADR 0058).

A held asset is valued at its last observed price, however old. When that price
is older than ``ValuationAlignmentPolicy.maximum_staleness``, the portfolio value
row has ``valuation_stale`` set. The column is nullable: rows written before this
revision, and by a release still deployed during the rollout, carry no marking.

Only the Markets-owned table is migrated here. A provider adds the same column to
its own ``PortfoliosTS`` instances in a revision of its own.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0029"
down_revision: str = "0028"
branch_labels = None
depends_on = None

TABLE = "ms_markets__portfoliosts"
COLUMN = "valuation_stale"


def upgrade() -> None:
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column(COLUMN, sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_column(COLUMN)
