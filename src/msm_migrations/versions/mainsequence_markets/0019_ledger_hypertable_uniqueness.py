"""Remove ledger uniqueness that excludes the TimescaleDB partition key.

0018 may already be committed even when catalog finalization failed. Preserve
that history and every ledger row; the existing full-grain unique index remains.
Economic identities across timestamps are validated by msm_portfolios.
"""

from alembic import op

revision: str = "0019"
down_revision: str = "0018"
branch_labels = None
depends_on = None

TABLE_NAME = "ms_markets__portfolioeventledgerts"
CONSTRAINT_NAME = "uq__ms_markets__portfolioeventledgerts__portfolio_id_256b1e63f2"


def upgrade() -> None:
    with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
        batch_op.drop_constraint(op.f(CONSTRAINT_NAME), type_="unique")


def downgrade() -> None:
    # Restores the former schema on ordinary PostgreSQL/SQLite tables. TimescaleDB
    # rejects this constraint once the table is a hypertable; use a forward fix
    # there rather than removing partitioning or data to permit a downgrade.
    with op.batch_alter_table(TABLE_NAME, schema=None) as batch_op:
        batch_op.create_unique_constraint(
            op.f(CONSTRAINT_NAME),
            ["portfolio_identifier", "event_identifier", "event_revision", "record_identifier"],
        )
