"""migration

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-10 22:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "ms_markets__portfolio",
        sa.Column("signal_uid", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix__ms_markets__portfolio__signal_uid"),
        "ms_markets__portfolio",
        ["signal_uid"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk__ms_markets__portfolio__signal_uid__ms_markets__signalmetadata"),
        "ms_markets__portfolio",
        "ms_markets__signalmetadata",
        ["signal_uid"],
        ["signal_uid"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk__ms_markets__portfolio__signal_uid__ms_markets__signalmetadata"),
        "ms_markets__portfolio",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix__ms_markets__portfolio__signal_uid"), table_name="ms_markets__portfolio")
    op.drop_column("ms_markets__portfolio", "signal_uid")
