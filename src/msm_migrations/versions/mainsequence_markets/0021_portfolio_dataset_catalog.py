"""Catalog the time-series instances that hold each portfolio's datasets (ADR 0047).

``PortfoliosTS``, ``PortfolioWeightsTS`` and ``SignalWeightsTS`` become contracts
with provider-owned instances. ``PortfolioDatasetAvailability`` records, per
portfolio, the MetaTable uid of the values, weights and signal instance plus the
reconciled population state of the values instance, mirroring
``IndexDatasetAvailability``. ``SignalMetadata`` gains the uid of the instance
holding its weight rows. No existing table, column or row changes; a portfolio
without a catalog row keeps reading the core tables.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0021"
down_revision: str = "0020"
branch_labels = None
depends_on = None

CATALOG_TABLE = "ms_markets__portfoliodatasetavailability"
SIGNAL_TABLE = "ms_markets__signalmetadata"
POPULATION_STATE_CHECK = (
    "(population_state = 'populated' AND row_count > 0 AND error_code IS NULL "
    "AND error_message IS NULL) OR (population_state = 'compatible_empty' AND row_count = 0 "
    "AND earliest_time_index IS NULL AND latest_time_index IS NULL AND error_code IS NULL "
    "AND error_message IS NULL) OR (population_state = 'unavailable' AND row_count IS NULL "
    "AND earliest_time_index IS NULL AND latest_time_index IS NULL)"
)


def upgrade() -> None:
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
        batch_op.add_column(sa.Column("meta_table_uid", sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(SIGNAL_TABLE, schema=None) as batch_op:
        batch_op.drop_column("meta_table_uid")

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
