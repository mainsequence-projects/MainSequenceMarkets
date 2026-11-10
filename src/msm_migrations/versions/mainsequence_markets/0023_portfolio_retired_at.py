"""Add the portfolio retirement time (ADR 0049).

``Portfolio.retired_at`` is null while a portfolio is live and holds the UTC time
from which it is retired. Existing portfolios stay live. The column is nullable,
so the release that is still deployed keeps working during the rollout.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0023"
down_revision: str = "0022"
branch_labels = None
depends_on = None

TABLE = "ms_markets__portfolio"
COLUMN = "retired_at"


def upgrade() -> None:
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_column(COLUMN)
