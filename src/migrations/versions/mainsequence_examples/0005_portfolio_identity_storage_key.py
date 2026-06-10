"""portfolio_identity_storage_key

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-10 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PORTFOLIO_TABLE = "ms_markets__portfolio__mainsequence_examples"
INDEX_TABLE = "ms_markets__index__mainsequence_examples"
WEIGHTS_TABLE = "ms_markets__portfolioweightsts__mainsequence_examples"

OLD_PORTFOLIO_INDEX = "ix__ms_markets__portfolio__mainsequence_examples__po_be638370d3"
OLD_PORTFOLIO_FK = "fk__ms_markets__portfolio__mainsequence_examples__po_55ef2ceb40"
OLD_WEIGHTS_INDEX = "uix__ms_markets__portfolioweightsts__mainsequence_ex_c1365e7560"

NEW_PORTFOLIO_INDEX = "ix__msm_portfolio_examples__published_index_uid"
NEW_PORTFOLIO_FK = "fk__msm_portfolio_examples__published_index_uid__index_uid"
NEW_WEIGHTS_INDEX = "uix__msm_portfolio_weights_examples__portfolio_asset_time"


def upgrade() -> None:
    """Upgrade schema."""

    op.drop_index(OLD_WEIGHTS_INDEX, table_name=WEIGHTS_TABLE)
    op.alter_column(
        WEIGHTS_TABLE,
        "portfolio_index_identifier",
        new_column_name="portfolio_identifier",
        existing_type=sa.String(),
        existing_nullable=False,
    )

    op.drop_index(OLD_PORTFOLIO_INDEX, table_name=PORTFOLIO_TABLE)
    op.drop_constraint(OLD_PORTFOLIO_FK, PORTFOLIO_TABLE, type_="foreignkey")
    op.alter_column(
        PORTFOLIO_TABLE,
        "portfolio_index_uid",
        new_column_name="published_index_uid",
        existing_type=sa.Uuid(),
        existing_nullable=True,
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {WEIGHTS_TABLE} AS weights
            SET portfolio_identifier = portfolio.unique_identifier
            FROM {PORTFOLIO_TABLE} AS portfolio
            JOIN {INDEX_TABLE} AS published_index
              ON portfolio.published_index_uid = published_index.uid
            WHERE weights.portfolio_identifier = published_index.unique_identifier
            """
        )
    )

    op.create_foreign_key(
        NEW_PORTFOLIO_FK,
        PORTFOLIO_TABLE,
        INDEX_TABLE,
        ["published_index_uid"],
        ["uid"],
        ondelete="SET NULL",
    )
    op.create_index(
        NEW_PORTFOLIO_INDEX,
        PORTFOLIO_TABLE,
        ["published_index_uid"],
        unique=False,
    )
    op.create_index(
        NEW_WEIGHTS_INDEX,
        WEIGHTS_TABLE,
        ["time_index", "portfolio_identifier", "asset_identifier"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(NEW_WEIGHTS_INDEX, table_name=WEIGHTS_TABLE)

    op.execute(
        sa.text(
            f"""
            UPDATE {WEIGHTS_TABLE} AS weights
            SET portfolio_identifier = published_index.unique_identifier
            FROM {PORTFOLIO_TABLE} AS portfolio
            JOIN {INDEX_TABLE} AS published_index
              ON portfolio.published_index_uid = published_index.uid
            WHERE weights.portfolio_identifier = portfolio.unique_identifier
            """
        )
    )

    op.alter_column(
        WEIGHTS_TABLE,
        "portfolio_identifier",
        new_column_name="portfolio_index_identifier",
        existing_type=sa.String(),
        existing_nullable=False,
    )

    op.drop_index(NEW_PORTFOLIO_INDEX, table_name=PORTFOLIO_TABLE)
    op.drop_constraint(NEW_PORTFOLIO_FK, PORTFOLIO_TABLE, type_="foreignkey")
    op.alter_column(
        PORTFOLIO_TABLE,
        "published_index_uid",
        new_column_name="portfolio_index_uid",
        existing_type=sa.Uuid(),
        existing_nullable=True,
    )
    op.create_foreign_key(
        OLD_PORTFOLIO_FK,
        PORTFOLIO_TABLE,
        INDEX_TABLE,
        ["portfolio_index_uid"],
        ["uid"],
        ondelete="SET NULL",
    )
    op.create_index(
        OLD_PORTFOLIO_INDEX,
        PORTFOLIO_TABLE,
        ["portfolio_index_uid"],
        unique=False,
    )
    op.create_index(
        OLD_WEIGHTS_INDEX,
        WEIGHTS_TABLE,
        ["time_index", "portfolio_index_identifier", "asset_identifier"],
        unique=True,
    )
