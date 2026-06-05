"""migration

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-05 10:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TARGET_POSITIONS_TABLE = "ms_markets__targetpositionsts__mainsequence_examples"
ASSET_TABLE = "ms_markets__asset__mainsequence_examples"


def _target_positions_table() -> sa.TableClause:
    return sa.table(
        TARGET_POSITIONS_TABLE,
        sa.column("asset_identifier", sa.String()),
        sa.column("target_type", sa.String()),
        sa.column("target_uid", sa.Uuid()),
        sa.column("asset_uid", sa.Uuid()),
        sa.column("portfolio_uid", sa.Uuid()),
    )


def _asset_table() -> sa.TableClause:
    return sa.table(
        ASSET_TABLE,
        sa.column("uid", sa.Uuid()),
        sa.column("unique_identifier", sa.String()),
    )


def _backfill_asset_targets() -> None:
    connection = op.get_bind()
    target_positions = _target_positions_table()
    assets = _asset_table()
    asset_uid_lookup = (
        sa.select(assets.c.uid)
        .where(assets.c.unique_identifier == target_positions.c.asset_identifier)
        .scalar_subquery()
    )

    connection.execute(
        target_positions.update().values(
            target_type="asset",
            target_uid=asset_uid_lookup,
            asset_uid=asset_uid_lookup,
        )
    )

    missing_count = connection.execute(
        sa.select(sa.func.count())
        .select_from(target_positions)
        .where(
            sa.or_(
                target_positions.c.target_type.is_(None),
                target_positions.c.target_uid.is_(None),
                target_positions.c.asset_uid.is_(None),
            )
        )
    ).scalar_one()
    if missing_count:
        raise RuntimeError(
            "Could not backfill TargetPositionsStorage target columns from "
            "asset_identifier. Existing rows must reference Asset.unique_identifier "
            "before applying migration 0007."
        )


def _backfill_asset_identifiers_for_downgrade() -> None:
    connection = op.get_bind()
    target_positions = _target_positions_table()
    assets = _asset_table()

    portfolio_target_count = connection.execute(
        sa.select(sa.func.count())
        .select_from(target_positions)
        .where(target_positions.c.target_type != "asset")
    ).scalar_one()
    if portfolio_target_count:
        raise RuntimeError(
            "Cannot downgrade TargetPositionsStorage migration 0007 while "
            "portfolio target rows exist."
        )

    asset_identifier_lookup = (
        sa.select(assets.c.unique_identifier)
        .where(assets.c.uid == target_positions.c.asset_uid)
        .scalar_subquery()
    )
    connection.execute(
        target_positions.update().values(asset_identifier=asset_identifier_lookup)
    )

    missing_count = connection.execute(
        sa.select(sa.func.count())
        .select_from(target_positions)
        .where(target_positions.c.asset_identifier.is_(None))
    ).scalar_one()
    if missing_count:
        raise RuntimeError(
            "Could not backfill TargetPositionsStorage.asset_identifier during "
            "migration 0007 downgrade."
        )


def upgrade() -> None:
    """Upgrade schema."""

    op.drop_index(
        "uix__ms_markets__targetpositionsts__mainsequence_exa_c53adaf81e",
        table_name=TARGET_POSITIONS_TABLE,
    )
    op.drop_constraint(
        "fk__ms_markets__targetpositionsts__mainsequence_exam_5ac73f7dc4",
        TARGET_POSITIONS_TABLE,
        type_="foreignkey",
    )
    op.add_column(
        TARGET_POSITIONS_TABLE,
        sa.Column("target_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        TARGET_POSITIONS_TABLE,
        sa.Column("target_uid", sa.Uuid(), nullable=True),
    )
    op.add_column(
        TARGET_POSITIONS_TABLE,
        sa.Column("asset_uid", sa.Uuid(), nullable=True),
    )
    op.add_column(
        TARGET_POSITIONS_TABLE,
        sa.Column("portfolio_uid", sa.Uuid(), nullable=True),
    )
    op.add_column(
        TARGET_POSITIONS_TABLE,
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    _backfill_asset_targets()
    op.alter_column(
        TARGET_POSITIONS_TABLE,
        "target_type",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.alter_column(
        TARGET_POSITIONS_TABLE,
        "target_uid",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk__ms_markets__targetpositionsts__mainsequence_exam_21645482de",
        TARGET_POSITIONS_TABLE,
        "ms_markets__asset__mainsequence_examples",
        ["asset_uid"],
        ["uid"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk__ms_markets__targetpositionsts__mainsequence_exam_41e34dab69",
        TARGET_POSITIONS_TABLE,
        "ms_markets__portfolio__mainsequence_examples",
        ["portfolio_uid"],
        ["uid"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck__ms_markets__targetpositionsts__mainsequence_exam_090467615c",
        TARGET_POSITIONS_TABLE,
        "target_type IN ('asset', 'portfolio')",
    )
    op.create_check_constraint(
        "ck__ms_markets__targetpositionsts__mainsequence_exam_8b7a5c5108",
        TARGET_POSITIONS_TABLE,
        "("
        "target_type = 'asset' AND asset_uid IS NOT NULL "
        "AND portfolio_uid IS NULL AND target_uid = asset_uid"
        ") OR ("
        "target_type = 'portfolio' AND portfolio_uid IS NOT NULL "
        "AND asset_uid IS NULL AND target_uid = portfolio_uid"
        ")",
    )
    op.create_check_constraint(
        "ck__ms_markets__targetpositionsts__mainsequence_exam_54d0ed828a",
        TARGET_POSITIONS_TABLE,
        "("
        "CASE WHEN weight_notional_exposure IS NOT NULL THEN 1 ELSE 0 END"
        ") + ("
        "CASE WHEN constant_notional_exposure IS NOT NULL THEN 1 ELSE 0 END"
        ") + ("
        "CASE WHEN single_asset_quantity IS NOT NULL THEN 1 ELSE 0 END"
        ") = 1",
    )
    op.create_index(
        "ix__ms_markets__targetpositionsts__mainsequence_exam_c5cb925c03",
        TARGET_POSITIONS_TABLE,
        ["asset_uid"],
        unique=False,
    )
    op.create_index(
        "ix__ms_markets__targetpositionsts__mainsequence_exam_4f286bcf1c",
        TARGET_POSITIONS_TABLE,
        ["portfolio_uid"],
        unique=False,
    )
    op.create_index(
        "ix__ms_markets__targetpositionsts__mainsequence_exam_782379de98",
        TARGET_POSITIONS_TABLE,
        ["position_set_uid", "target_type", "target_uid"],
        unique=False,
    )
    op.create_index(
        "uix__ms_markets__targetpositionsts__mainsequence_exa_9864e9a65f",
        TARGET_POSITIONS_TABLE,
        ["time_index", "position_set_uid", "target_type", "target_uid"],
        unique=True,
    )
    op.drop_column(TARGET_POSITIONS_TABLE, "asset_identifier")


def downgrade() -> None:
    """Downgrade schema."""

    op.add_column(
        TARGET_POSITIONS_TABLE,
        sa.Column("asset_identifier", sa.String(), nullable=True),
    )
    _backfill_asset_identifiers_for_downgrade()
    op.alter_column(
        TARGET_POSITIONS_TABLE,
        "asset_identifier",
        existing_type=sa.String(),
        nullable=False,
    )
    op.drop_index(
        "uix__ms_markets__targetpositionsts__mainsequence_exa_9864e9a65f",
        table_name=TARGET_POSITIONS_TABLE,
    )
    op.drop_index(
        "ix__ms_markets__targetpositionsts__mainsequence_exam_782379de98",
        table_name=TARGET_POSITIONS_TABLE,
    )
    op.drop_index(
        "ix__ms_markets__targetpositionsts__mainsequence_exam_4f286bcf1c",
        table_name=TARGET_POSITIONS_TABLE,
    )
    op.drop_index(
        "ix__ms_markets__targetpositionsts__mainsequence_exam_c5cb925c03",
        table_name=TARGET_POSITIONS_TABLE,
    )
    op.drop_constraint(
        "ck__ms_markets__targetpositionsts__mainsequence_exam_54d0ed828a",
        TARGET_POSITIONS_TABLE,
        type_="check",
    )
    op.drop_constraint(
        "ck__ms_markets__targetpositionsts__mainsequence_exam_8b7a5c5108",
        TARGET_POSITIONS_TABLE,
        type_="check",
    )
    op.drop_constraint(
        "ck__ms_markets__targetpositionsts__mainsequence_exam_090467615c",
        TARGET_POSITIONS_TABLE,
        type_="check",
    )
    op.drop_constraint(
        "fk__ms_markets__targetpositionsts__mainsequence_exam_41e34dab69",
        TARGET_POSITIONS_TABLE,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk__ms_markets__targetpositionsts__mainsequence_exam_21645482de",
        TARGET_POSITIONS_TABLE,
        type_="foreignkey",
    )
    op.drop_column(TARGET_POSITIONS_TABLE, "metadata_json")
    op.drop_column(TARGET_POSITIONS_TABLE, "portfolio_uid")
    op.drop_column(TARGET_POSITIONS_TABLE, "asset_uid")
    op.drop_column(TARGET_POSITIONS_TABLE, "target_uid")
    op.drop_column(TARGET_POSITIONS_TABLE, "target_type")
    op.create_foreign_key(
        "fk__ms_markets__targetpositionsts__mainsequence_exam_5ac73f7dc4",
        TARGET_POSITIONS_TABLE,
        "ms_markets__asset__mainsequence_examples",
        ["asset_identifier"],
        ["unique_identifier"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uix__ms_markets__targetpositionsts__mainsequence_exa_c53adaf81e",
        TARGET_POSITIONS_TABLE,
        ["time_index", "position_set_uid", "asset_identifier"],
        unique=True,
    )
