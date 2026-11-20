"""Record which principal manages each portfolio and signal (ADR 0060, decision 4).

``Portfolio`` and ``SignalMetadata`` gain ``managed_by``: the principal recorded from
the acting identity of the call that created the row. Only that principal publishes to
the row's series, restates them, or deletes the row. Rows that exist before this revision
keep a null ``managed_by`` and accept no publish until an Organization admin assigns a
manager (``msm registry assign-manager``). No row changes.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0032"
down_revision: str = "0031"
branch_labels = None
depends_on = None

TABLES = ("ms_markets__portfolio", "ms_markets__signalmetadata")
COLUMN = "managed_by"


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.String(length=255), nullable=True))


def downgrade() -> None:
    for table in reversed(TABLES):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column(COLUMN)
