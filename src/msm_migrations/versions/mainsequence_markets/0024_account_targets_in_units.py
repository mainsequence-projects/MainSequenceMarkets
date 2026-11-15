"""Store account targets in units (ADR 0052).

Every account target row becomes a positive quantity of one asset with a
direction, like account holdings. A portfolio target is one row per asset of the
virtual fund's unit basket, so ``asset_uid`` is required on every row and joins
the storage index.

Existing position sets and their target rows are deleted first. They hold shares
of NAV and notional amounts, which cannot be turned into units without prices.
The account target allocations are kept. The downgrade restores the former
columns, not the deleted rows.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0024"
down_revision: str = "0023"
branch_labels = None
depends_on = None

TABLE = "ms_markets__targetpositionsts"
POSITION_SET_TABLE = "ms_markets__positionset"

REFERENCE_CHECK = "ck__ms_markets__targetpositionsts__ck_target_positio_804f77878f"
SINGLE_EXPOSURE_CHECK = "ck__ms_markets__targetpositionsts__ck_target_positio_76b533764b"
QUANTITY_CHECK = "ck__ms_markets__targetpositionsts__ck_target_positio_b81cb75ad5"
DIRECTION_CHECK = "ck__ms_markets__targetpositionsts__ck_target_positio_93b1e77b25"
FORMER_GRAIN_INDEX = "uix__ms_markets__targetpositionsts__time_index__posi_d64428cc34"
GRAIN_INDEX = "uix__ms_markets__targetpositionsts__time_index__posi_493842b535"

FORMER_GRAIN = ["time_index", "position_set_uid", "target_type", "target_uid"]
GRAIN = [*FORMER_GRAIN, "asset_uid"]

FORMER_REFERENCE_SQL = (
    "(target_type = 'asset' AND asset_uid IS NOT NULL AND portfolio_uid IS NULL "
    "AND target_uid = asset_uid) OR (target_type = 'portfolio' AND portfolio_uid IS NOT NULL "
    "AND asset_uid IS NULL AND target_uid = portfolio_uid)"
)
REFERENCE_SQL = (
    "(target_type = 'asset' AND portfolio_uid IS NULL AND target_uid = asset_uid) OR "
    "(target_type = 'portfolio' AND portfolio_uid IS NOT NULL AND target_uid = portfolio_uid)"
)
SINGLE_EXPOSURE_SQL = (
    "(CASE WHEN weight_notional_exposure IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN constant_notional_exposure IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN single_asset_quantity IS NOT NULL THEN 1 ELSE 0 END) = 1"
)


def _delete_target_history() -> None:
    op.execute(sa.text(f"DELETE FROM {TABLE}"))
    op.execute(sa.text(f"DELETE FROM {POSITION_SET_TABLE}"))


def upgrade() -> None:
    _delete_target_history()
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_index(FORMER_GRAIN_INDEX)
        batch_op.drop_constraint(op.f(SINGLE_EXPOSURE_CHECK), type_="check")
        batch_op.drop_constraint(op.f(REFERENCE_CHECK), type_="check")
        batch_op.drop_column("weight_notional_exposure")
        batch_op.drop_column("constant_notional_exposure")
        batch_op.drop_column("single_asset_quantity")
        batch_op.add_column(sa.Column("quantity", sa.Float(), nullable=False))
        batch_op.add_column(sa.Column("direction", sa.SmallInteger(), nullable=False))
        batch_op.alter_column("asset_uid", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_check_constraint(op.f(REFERENCE_CHECK), REFERENCE_SQL)
        batch_op.create_check_constraint(op.f(QUANTITY_CHECK), "quantity > 0")
        batch_op.create_check_constraint(op.f(DIRECTION_CHECK), "direction IN (1, -1)")
        batch_op.create_index(GRAIN_INDEX, GRAIN, unique=True)


def downgrade() -> None:
    _delete_target_history()
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_index(GRAIN_INDEX)
        batch_op.drop_constraint(op.f(DIRECTION_CHECK), type_="check")
        batch_op.drop_constraint(op.f(QUANTITY_CHECK), type_="check")
        batch_op.drop_constraint(op.f(REFERENCE_CHECK), type_="check")
        batch_op.drop_column("direction")
        batch_op.drop_column("quantity")
        batch_op.add_column(sa.Column("weight_notional_exposure", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("constant_notional_exposure", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("single_asset_quantity", sa.Float(), nullable=True))
        batch_op.alter_column("asset_uid", existing_type=sa.Uuid(), nullable=True)
        batch_op.create_check_constraint(op.f(REFERENCE_CHECK), FORMER_REFERENCE_SQL)
        batch_op.create_check_constraint(op.f(SINGLE_EXPOSURE_CHECK), SINGLE_EXPOSURE_SQL)
        batch_op.create_index(FORMER_GRAIN_INDEX, FORMER_GRAIN, unique=True)
