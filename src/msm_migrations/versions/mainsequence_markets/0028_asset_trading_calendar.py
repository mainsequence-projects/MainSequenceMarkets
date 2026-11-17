"""Link an asset to its trading calendar (ADR 0056).

``AssetCalendar`` is a one-to-one detail table of ``Asset``. It names the stored
``Calendar`` whose sessions decide which price bars the asset has.

The revision creates the table and writes no rows. Nothing stored says which
calendar an asset trades on, so there is nothing to convert, and an asset is not
linked to a calendar nobody chose. A price update refuses an asset without a
link until its owner links it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str = "0027"
branch_labels = None
depends_on = None

ASSET_TABLE = "ms_markets__asset"
CALENDAR_TABLE = "ms_markets__calendar"
ASSET_CALENDAR_TABLE = "ms_markets__assetcalendar"

ASSET_KEY = "fk__ms_markets__assetcalendar__asset_uid__ms_markets_56374c2770"
CALENDAR_KEY = "fk__ms_markets__assetcalendar__calendar_uid__ms_mark_7713a9c8e4"
CALENDAR_INDEX = "ix__ms_markets__assetcalendar__calendar_uid"

NAMESPACE = "mainsequence.markets"


def upgrade() -> None:
    op.create_table(
        ASSET_CALENDAR_TABLE,
        sa.Column("asset_uid", sa.Uuid(), nullable=False),
        sa.Column("calendar_uid", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_uid"],
            [f"{ASSET_TABLE}.uid"],
            name=op.f(ASSET_KEY),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["calendar_uid"],
            [f"{CALENDAR_TABLE}.uid"],
            name=op.f(CALENDAR_KEY),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("asset_uid", name=op.f("pk__ms_markets__assetcalendar")),
        info={
            "namespace": NAMESPACE,
            "identifier": "AssetCalendar",
            "markets_storage_app": "ms_markets",
        },
    )
    with op.batch_alter_table(ASSET_CALENDAR_TABLE, schema=None) as batch_op:
        batch_op.create_index(batch_op.f(CALENDAR_INDEX), ["calendar_uid"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table(ASSET_CALENDAR_TABLE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(CALENDAR_INDEX))
    op.drop_table(ASSET_CALENDAR_TABLE)
