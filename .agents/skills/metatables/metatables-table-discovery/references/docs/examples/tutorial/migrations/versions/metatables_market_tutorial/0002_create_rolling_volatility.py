"""Add the third time-index stage without changing existing tutorial tables.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metatables_market_tutorial__rolling_volatility",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("annualized_volatility", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["symbol"],
            ["metatables_market_tutorial__asset.symbol"],
            name=op.f("fk__metatables_market_tutorial__rolling_volatility_e55b523baa"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "uix__metatables_market_tutorial__rolling_volatility_ca36d330d7",
        "metatables_market_tutorial__rolling_volatility",
        ["time_index", "symbol"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uix__metatables_market_tutorial__rolling_volatility_ca36d330d7",
        table_name="metatables_market_tutorial__rolling_volatility",
    )
    op.drop_table("metatables_market_tutorial__rolling_volatility")
