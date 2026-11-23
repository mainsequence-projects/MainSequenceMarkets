"""Retire ``constant_notional_exposure`` from the account target (ADR 0061).

A row of ``ms_markets__targetpositionsts`` states ``weight_notional_exposure`` or
``single_asset_quantity``. This revision drops the check that requires exactly one
exposure, drops ``constant_notional_exposure``, and creates the check again for the two
fields left. The check keeps its name, because MetaTables builds the name from the table
and the constraint name, not from the SQL.

A row that still holds an amount holds neither field once the column is gone, so the new
check refuses it and the upgrade fails. Nothing is deleted: that account's target must
state a share before the upgrade. The upgrade runs in one transaction, so on PostgreSQL a
refused row leaves the database as it was.

SQLite cannot drop a column that a check names, so it rebuilds the table. A refused row
stops the copy into the new table, and SQLite keeps ``_alembic_tmp_ms_markets__targetpositionsts``;
drop it before upgrading again. The downgrade adds the column back, empty, with the
three-field check of revision ``0025``.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0036"
down_revision: str = "0035"
branch_labels = None
depends_on = None

TABLE = "ms_markets__targetpositionsts"
SINGLE_EXPOSURE_CHECK = "ck__ms_markets__targetpositionsts__ck_target_positio_76b533764b"

SINGLE_EXPOSURE_SQL = (
    "(CASE WHEN weight_notional_exposure IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN single_asset_quantity IS NOT NULL THEN 1 ELSE 0 END) = 1"
)
PREVIOUS_SINGLE_EXPOSURE_SQL = (
    "(CASE WHEN weight_notional_exposure IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN constant_notional_exposure IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN single_asset_quantity IS NOT NULL THEN 1 ELSE 0 END) = 1"
)
"""The check as revision ``0025`` created it."""


def upgrade() -> None:
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(op.f(SINGLE_EXPOSURE_CHECK), type_="check")
        batch_op.drop_column("constant_notional_exposure")
        batch_op.create_check_constraint(op.f(SINGLE_EXPOSURE_CHECK), SINGLE_EXPOSURE_SQL)


def downgrade() -> None:
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_constraint(op.f(SINGLE_EXPOSURE_CHECK), type_="check")
        batch_op.add_column(sa.Column("constant_notional_exposure", sa.Float(), nullable=True))
        batch_op.create_check_constraint(
            op.f(SINGLE_EXPOSURE_CHECK), PREVIOUS_SINGLE_EXPOSURE_SQL
        )
