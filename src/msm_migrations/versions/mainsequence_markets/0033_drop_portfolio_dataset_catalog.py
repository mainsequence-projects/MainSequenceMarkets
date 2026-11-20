"""Drop the portfolio dataset catalog (ADR 0060, decision 8).

Revision 0021 added ``PortfolioDatasetAvailability``, which recorded the MetaTable uids of
the tables another application kept a portfolio's values, weights and signal weights in,
and ``SignalMetadata.meta_table_uid`` for a signal's table. Markets no longer reads any
table it does not own: those series are published to its own tables, so both go. Their
rows named tables, not series rows; no published row is lost. The downgrade restores the
empty table and the null column.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0033"
down_revision: str = "0032"
branch_labels = None
depends_on = None

CATALOG_TABLE = "ms_markets__portfoliodatasetavailability"
SIGNAL_TABLE = "ms_markets__signalmetadata"
SIGNAL_COLUMN = "meta_table_uid"
POPULATION_STATE_CHECK = (
    "(population_state = 'populated' AND row_count > 0 AND error_code IS NULL "
    "AND error_message IS NULL) OR (population_state = 'compatible_empty' AND row_count = 0 "
    "AND earliest_time_index IS NULL AND latest_time_index IS NULL AND error_code IS NULL "
    "AND error_message IS NULL) OR (population_state = 'unavailable' AND row_count IS NULL "
    "AND earliest_time_index IS NULL AND latest_time_index IS NULL)"
)


def upgrade() -> None:
    with op.batch_alter_table(SIGNAL_TABLE, schema=None) as batch_op:
        batch_op.drop_column(SIGNAL_COLUMN)

    with op.batch_alter_table(CATALOG_TABLE, schema=None) as batch_op:
        batch_op.drop_index(
            batch_op.f("uix__ms_markets__portfoliodatasetavailability__portfolio_uid")
        )
        batch_op.drop_index(
            batch_op.f("ix__ms_markets__portfoliodatasetavailability__values_d23ba027f2")
        )
        batch_op.drop_index(
            batch_op.f("ix__ms_markets__portfoliodatasetavailability__popula_5627783bed")
        )
    op.drop_table(CATALOG_TABLE)


def downgrade() -> None:
    op.create_table(
        CATALOG_TABLE,
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("portfolio_uid", sa.Uuid(), nullable=False),
        sa.Column("values_meta_table_uid", sa.String(length=255), nullable=False),
        sa.Column("weights_meta_table_uid", sa.String(length=255), nullable=True),
        sa.Column("signal_meta_table_uid", sa.String(length=255), nullable=True),
        sa.Column("population_state", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("earliest_time_index", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_time_index", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.CheckConstraint(
            POPULATION_STATE_CHECK,
            name=op.f("ck__ms_markets__portfoliodatasetavailability__portfo_80a9376603"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_uid"],
            ["ms_markets__portfolio.uid"],
            name=op.f("fk__ms_markets__portfoliodatasetavailability__portfo_5646f2dcfa"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__ms_markets__portfoliodatasetavailability")),
        info={
            "namespace": "mainsequence.markets",
            "identifier": "PortfolioDatasetAvailability",
            "markets_storage_app": "ms_markets",
        },
    )
    with op.batch_alter_table(CATALOG_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix__ms_markets__portfoliodatasetavailability__popula_5627783bed"),
            ["population_state", "portfolio_uid"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix__ms_markets__portfoliodatasetavailability__values_d23ba027f2"),
            ["values_meta_table_uid", "population_state"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("uix__ms_markets__portfoliodatasetavailability__portfolio_uid"),
            ["portfolio_uid"],
            unique=True,
        )

    with op.batch_alter_table(SIGNAL_TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column(SIGNAL_COLUMN, sa.String(length=255), nullable=True))
