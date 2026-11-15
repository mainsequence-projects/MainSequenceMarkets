"""Restore account exposure and record the lines of each allocation (ADR 0054).

An account's exposure to a portfolio is a share of NAV or a notional amount, not
units, so ``TargetPositionsStorage`` returns to its shape before revision 0024.
A new table, ``AccountAllocationLinesStorage``, records each allocation of an
account holdings set: one row per owner and asset, with the sized target units
and the assigned units. The owner is a virtual fund or the account itself.

Targets written in units under revision 0024:

- an asset row becomes ``single_asset_quantity`` (quantity times direction);
- a position set with a portfolio row is deleted with its rows. Units per asset
  cannot be turned back into a share or an amount.

Targets deleted by revision 0024 are not restored. The downgrade puts back the
unit columns and deletes the target history, as revision 0024 does.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str = "0024"
branch_labels = None
depends_on = None

TABLE = "ms_markets__targetpositionsts"
POSITION_SET_TABLE = "ms_markets__positionset"
LINES_TABLE = "ms_markets__accountallocationlinests"

REFERENCE_CHECK = "ck__ms_markets__targetpositionsts__ck_target_positio_804f77878f"
SINGLE_EXPOSURE_CHECK = "ck__ms_markets__targetpositionsts__ck_target_positio_76b533764b"
QUANTITY_CHECK = "ck__ms_markets__targetpositionsts__ck_target_positio_b81cb75ad5"
DIRECTION_CHECK = "ck__ms_markets__targetpositionsts__ck_target_positio_93b1e77b25"
EXPOSURE_GRAIN_INDEX = "uix__ms_markets__targetpositionsts__time_index__posi_d64428cc34"
UNIT_GRAIN_INDEX = "uix__ms_markets__targetpositionsts__time_index__posi_493842b535"
LINES_GRAIN_INDEX = "uix__ms_markets__accountallocationlinests__time_inde_bcb64b5142"

EXPOSURE_GRAIN = ["time_index", "position_set_uid", "target_type", "target_uid"]
UNIT_GRAIN = [*EXPOSURE_GRAIN, "asset_uid"]

EXPOSURE_REFERENCE_SQL = (
    "(target_type = 'asset' AND asset_uid IS NOT NULL AND portfolio_uid IS NULL "
    "AND target_uid = asset_uid) OR (target_type = 'portfolio' AND portfolio_uid IS NOT NULL "
    "AND asset_uid IS NULL AND target_uid = portfolio_uid)"
)
UNIT_REFERENCE_SQL = (
    "(target_type = 'asset' AND portfolio_uid IS NULL AND target_uid = asset_uid) OR "
    "(target_type = 'portfolio' AND portfolio_uid IS NOT NULL AND target_uid = portfolio_uid)"
)
SINGLE_EXPOSURE_SQL = (
    "(CASE WHEN weight_notional_exposure IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN constant_notional_exposure IS NOT NULL THEN 1 ELSE 0 END) + "
    "(CASE WHEN single_asset_quantity IS NOT NULL THEN 1 ELSE 0 END) = 1"
)
LINES_GRAIN = [
    "time_index",
    "holdings_set_uid",
    "owner_type",
    "owner_uid",
    "asset_identifier",
]


def _create_allocation_lines() -> None:
    op.create_table(
        LINES_TABLE,
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("holdings_set_uid", sa.Uuid(), nullable=False),
        sa.Column("owner_type", sa.String(length=16), nullable=False),
        sa.Column("owner_uid", sa.Uuid(), nullable=False),
        sa.Column("asset_identifier", sa.String(length=255), nullable=False),
        sa.Column("account_uid", sa.Uuid(), nullable=False),
        sa.Column("virtual_fund_uid", sa.Uuid(), nullable=True),
        sa.Column("target_quantity", sa.Float(), nullable=False),
        sa.Column("target_direction", sa.SmallInteger(), nullable=False),
        sa.Column("assigned_quantity", sa.Float(), nullable=False),
        sa.Column("assigned_direction", sa.SmallInteger(), nullable=False),
        sa.Column("allocation_strategy", sa.String(length=64), nullable=False),
        sa.Column("extra_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "owner_type IN ('fund', 'direct')",
            name=op.f("ck__ms_markets__accountallocationlinests__ck_account_5635aeb4d2"),
        ),
        sa.CheckConstraint(
            "(owner_type = 'fund' AND virtual_fund_uid IS NOT NULL AND owner_uid = "
            "virtual_fund_uid) OR (owner_type = 'direct' AND virtual_fund_uid IS NULL AND "
            "owner_uid = account_uid)",
            name=op.f("ck__ms_markets__accountallocationlinests__ck_account_37385fa64b"),
        ),
        sa.CheckConstraint(
            "target_quantity >= 0 AND assigned_quantity >= 0",
            name=op.f("ck__ms_markets__accountallocationlinests__ck_account_3d777d8684"),
        ),
        sa.CheckConstraint(
            "target_direction IN (1, -1) AND assigned_direction IN (1, -1)",
            name=op.f("ck__ms_markets__accountallocationlinests__ck_account_6d1f6fba51"),
        ),
        sa.ForeignKeyConstraint(
            ["account_uid"],
            ["ms_markets__account.uid"],
            name=op.f("fk__ms_markets__accountallocationlinests__account_ui_e3ea4dfb8d"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_identifier"],
            ["ms_markets__asset.unique_identifier"],
            name=op.f("fk__ms_markets__accountallocationlinests__asset_iden_978d28d581"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["holdings_set_uid"],
            ["ms_markets__accountholdingsset.uid"],
            name=op.f("fk__ms_markets__accountallocationlinests__holdings_s_007384b6ef"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["virtual_fund_uid"],
            ["ms_markets__virtualfund.uid"],
            name=op.f("fk__ms_markets__accountallocationlinests__virtual_fu_55dd248d2d"),
            ondelete="CASCADE",
        ),
        info={
            "markets_storage_app": "ms_markets",
            "namespace": "mainsequence.markets",
            "identifier": "AccountAllocationLinesTS",
        },
    )
    with op.batch_alter_table(LINES_TABLE, schema=None) as batch_op:
        batch_op.create_index(LINES_GRAIN_INDEX, LINES_GRAIN, unique=True)


def _delete_unit_portfolio_targets() -> None:
    """Delete the position sets that hold a portfolio row in units, with their rows."""

    in_unit_sets = (
        f"position_set_uid IN (SELECT position_set_uid FROM {TABLE} "
        "WHERE target_type = 'portfolio')"
    )
    bind = op.get_bind()
    position_set_uids = [
        row[0]
        for row in bind.execute(
            sa.text(f"SELECT DISTINCT position_set_uid FROM {TABLE} WHERE target_type = 'portfolio'")
        )
    ]
    if not position_set_uids:
        return
    op.execute(sa.text(f"DELETE FROM {TABLE} WHERE {in_unit_sets}"))
    delete_position_set = sa.text(f"DELETE FROM {POSITION_SET_TABLE} WHERE uid = :uid")
    for uid in position_set_uids:
        bind.execute(delete_position_set, {"uid": uid})


def upgrade() -> None:
    _delete_unit_portfolio_targets()
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column("weight_notional_exposure", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("constant_notional_exposure", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("single_asset_quantity", sa.Float(), nullable=True))
    # Every remaining row is an asset row in units.
    op.execute(sa.text(f"UPDATE {TABLE} SET single_asset_quantity = quantity * direction"))
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_index(UNIT_GRAIN_INDEX)
        batch_op.drop_constraint(op.f(DIRECTION_CHECK), type_="check")
        batch_op.drop_constraint(op.f(QUANTITY_CHECK), type_="check")
        batch_op.drop_constraint(op.f(REFERENCE_CHECK), type_="check")
        batch_op.drop_column("direction")
        batch_op.drop_column("quantity")
        batch_op.alter_column("asset_uid", existing_type=sa.Uuid(), nullable=True)
        batch_op.create_check_constraint(op.f(REFERENCE_CHECK), EXPOSURE_REFERENCE_SQL)
        batch_op.create_check_constraint(op.f(SINGLE_EXPOSURE_CHECK), SINGLE_EXPOSURE_SQL)
        batch_op.create_index(EXPOSURE_GRAIN_INDEX, EXPOSURE_GRAIN, unique=True)
    _create_allocation_lines()


def downgrade() -> None:
    op.drop_table(LINES_TABLE)
    op.execute(sa.text(f"DELETE FROM {TABLE}"))
    op.execute(sa.text(f"DELETE FROM {POSITION_SET_TABLE}"))
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_index(EXPOSURE_GRAIN_INDEX)
        batch_op.drop_constraint(op.f(SINGLE_EXPOSURE_CHECK), type_="check")
        batch_op.drop_constraint(op.f(REFERENCE_CHECK), type_="check")
        batch_op.drop_column("weight_notional_exposure")
        batch_op.drop_column("constant_notional_exposure")
        batch_op.drop_column("single_asset_quantity")
        batch_op.add_column(sa.Column("quantity", sa.Float(), nullable=False))
        batch_op.add_column(sa.Column("direction", sa.SmallInteger(), nullable=False))
        batch_op.alter_column("asset_uid", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_check_constraint(op.f(REFERENCE_CHECK), UNIT_REFERENCE_SQL)
        batch_op.create_check_constraint(op.f(QUANTITY_CHECK), "quantity > 0")
        batch_op.create_check_constraint(op.f(DIRECTION_CHECK), "direction IN (1, -1)")
        batch_op.create_index(UNIT_GRAIN_INDEX, UNIT_GRAIN, unique=True)
