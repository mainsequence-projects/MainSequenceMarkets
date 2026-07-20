"""index_catalog_hardening

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-19 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    duplicate_active = op.get_bind().execute(
        sa.text(
            "SELECT index_uid, COUNT(*) AS active_count "
            "FROM ms_markets__indexcalculationdefinition "
            "WHERE status = 'active' GROUP BY index_uid HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate_active is not None:
        raise RuntimeError(
            "cannot add the one-active-definition invariant while an Index has "
            "multiple active methodology rows"
        )

    op.create_table(
        "ms_markets__indexdatasetavailability",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("index_uid", sa.Uuid(), nullable=False),
        sa.Column("meta_table_uid", sa.String(length=255), nullable=False),
        sa.Column("cadence", sa.String(length=32), nullable=False),
        sa.Column("population_state", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("earliest_time_index", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_time_index", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.CheckConstraint(
            "(population_state = 'populated' AND row_count > 0 "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(population_state = 'compatible_empty' AND row_count = 0 "
            "AND earliest_time_index IS NULL AND latest_time_index IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(population_state = 'unavailable' AND row_count IS NULL "
            "AND earliest_time_index IS NULL AND latest_time_index IS NULL)",
            name=op.f(
                "ck__ms_markets__indexdatasetavailability__dataset_po_13c13b29a7"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["index_uid"],
            ["ms_markets__index.uid"],
            name=op.f(
                "fk__ms_markets__indexdatasetavailability__index_uid_064eaeecbc"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "uid", name=op.f("pk__ms_markets__indexdatasetavailability")
        ),
        info={
            "namespace": "mainsequence.markets",
            "identifier": "IndexDatasetAvailability",
            "markets_storage_app": "ms_markets",
        },
    )
    op.create_index(
        op.f("uix__ms_markets__indexdatasetavailability__index_uid_d9e5880cd2"),
        "ms_markets__indexdatasetavailability",
        ["index_uid", "meta_table_uid"],
        unique=True,
    )
    op.create_index(
        op.f("ix__ms_markets__indexdatasetavailability__index_uid_3ff71269ef"),
        "ms_markets__indexdatasetavailability",
        ["index_uid", "population_state", "cadence"],
        unique=False,
    )
    op.create_index(
        op.f("ix__ms_markets__indexdatasetavailability__population_149bb7907d"),
        "ms_markets__indexdatasetavailability",
        ["population_state", "cadence", "index_uid"],
        unique=False,
    )
    op.create_index(
        op.f("uix__ms_markets__indexcalculationdefinition__index_uid"),
        "ms_markets__indexcalculationdefinition",
        ["index_uid"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        op.f("ix__ms_markets__indexvaluests__index_identifier__time_index"),
        "ms_markets__indexvaluests",
        ["index_identifier", "time_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix__ms_markets__indexvaluests__index_identifier__time_index"),
        table_name="ms_markets__indexvaluests",
    )
    op.drop_index(
        op.f("uix__ms_markets__indexcalculationdefinition__index_uid"),
        table_name="ms_markets__indexcalculationdefinition",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(
        op.f("ix__ms_markets__indexdatasetavailability__population_149bb7907d"),
        table_name="ms_markets__indexdatasetavailability",
    )
    op.drop_index(
        op.f("ix__ms_markets__indexdatasetavailability__index_uid_3ff71269ef"),
        table_name="ms_markets__indexdatasetavailability",
    )
    op.drop_index(
        op.f("uix__ms_markets__indexdatasetavailability__index_uid_d9e5880cd2"),
        table_name="ms_markets__indexdatasetavailability",
    )
    op.drop_table("ms_markets__indexdatasetavailability")
