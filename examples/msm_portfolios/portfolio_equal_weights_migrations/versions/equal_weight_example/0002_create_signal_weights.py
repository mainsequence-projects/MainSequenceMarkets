"""Create the equal-weight example's signal table.

The example's computed signal (`FixedWeights`) is its own node: it writes its rows to this
table and publishes the same rows to Markets' SignalWeightsTS (ADR 0060, amended on
2026-11-24). The table is the same in every database, keyed to Markets' signal metadata and
asset registry, and the revision changes no Markets table.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None

TABLE = "equal_weight_example__signalweightsts__signals"
TIME_INDEX = "uix__equal_weight_example__signalweightsts__signals_ed46ca479e"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_uid", sa.String(length=255), nullable=False),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("signal_weight", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__equal_weight_example__signalweightsts__signals_1e72e3d64f"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["signal_uid"],
            ["ms_markets__signalmetadata.signal_uid"],
            name=op.f("fk__equal_weight_example__signalweightsts__signals_29bd881dfb"),
            ondelete="RESTRICT",
        ),
        info={
            "namespace": "equal-weight-example",
            "identifier": "equal-weight-example.SignalWeightsTS.signals",
            "markets_storage_app": "equal_weight_example",
        },
    )
    op.create_index(
        TIME_INDEX, TABLE, ["time_index", "signal_uid", "asset_identifier"], unique=True
    )


def downgrade() -> None:
    op.drop_index(TIME_INDEX, table_name=TABLE)
    op.drop_table(TABLE)
