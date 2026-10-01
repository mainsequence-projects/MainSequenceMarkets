"""create market tutorial tables

Revision ID: 0001
Revises: none
Create Date: 2026-09-28 11:46:11.200461

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "metatables_market_tutorial__asset",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__metatables_market_tutorial__asset")),
        sa.UniqueConstraint("symbol", name=op.f("uq__metatables_market_tutorial__asset__symbol")),
    )
    op.create_table(
        "metatables_market_tutorial__daily_close",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("adjusted_close", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["symbol"],
            ["metatables_market_tutorial__asset.symbol"],
            name=op.f("fk__metatables_market_tutorial__daily_close__symbol_13c68c75b3"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "uix__metatables_market_tutorial__daily_close__time_i_218669786c",
        "metatables_market_tutorial__daily_close",
        ["time_index", "symbol"],
        unique=True,
    )
    op.create_table(
        "metatables_market_tutorial__daily_return",
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("daily_return", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["symbol"],
            ["metatables_market_tutorial__asset.symbol"],
            name=op.f("fk__metatables_market_tutorial__daily_return__symbol_8076075a35"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "uix__metatables_market_tutorial__daily_return__time_0febe40688",
        "metatables_market_tutorial__daily_return",
        ["time_index", "symbol"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uix__metatables_market_tutorial__daily_return__time_0febe40688",
        table_name="metatables_market_tutorial__daily_return",
    )
    op.drop_table("metatables_market_tutorial__daily_return")
    op.drop_index(
        "uix__metatables_market_tutorial__daily_close__time_i_218669786c",
        table_name="metatables_market_tutorial__daily_close",
    )
    op.drop_table("metatables_market_tutorial__daily_close")
    op.drop_table("metatables_market_tutorial__asset")
