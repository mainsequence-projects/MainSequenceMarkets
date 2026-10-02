"""migration

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-10 23:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PORTFOLIO_TABLE = "ms_markets__portfolio"
SIGNAL_METADATA_TABLE = "ms_markets__signalmetadata"
OLD_FK_NAME = "fk__ms_markets__portfolio__signal_uid__ms_markets__signalmetadata"
NEW_FK_NAME = "fk__ms_markets__portfolio__signal_uid__signalmetadata"


def upgrade() -> None:
    """Upgrade schema."""
    for constraint_name in _portfolio_signal_uid_fk_names():
        if constraint_name != NEW_FK_NAME:
            op.drop_constraint(constraint_name, PORTFOLIO_TABLE, type_="foreignkey")

    if NEW_FK_NAME not in _portfolio_signal_uid_fk_names():
        op.create_foreign_key(
            NEW_FK_NAME,
            PORTFOLIO_TABLE,
            SIGNAL_METADATA_TABLE,
            ["signal_uid"],
            ["signal_uid"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    """Downgrade schema."""
    for constraint_name in _portfolio_signal_uid_fk_names():
        op.drop_constraint(constraint_name, PORTFOLIO_TABLE, type_="foreignkey")

    op.create_foreign_key(
        op.f(OLD_FK_NAME),
        PORTFOLIO_TABLE,
        SIGNAL_METADATA_TABLE,
        ["signal_uid"],
        ["signal_uid"],
        ondelete="RESTRICT",
    )


def _portfolio_signal_uid_fk_names() -> list[str]:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    foreign_keys = inspector.get_foreign_keys(PORTFOLIO_TABLE)
    names = [
        str(foreign_key["name"])
        for foreign_key in foreign_keys
        if foreign_key.get("name")
        and list(foreign_key.get("constrained_columns") or []) == ["signal_uid"]
    ]
    return sorted(names)
