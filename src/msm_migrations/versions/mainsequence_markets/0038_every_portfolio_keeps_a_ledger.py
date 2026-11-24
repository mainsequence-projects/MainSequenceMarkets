"""Every portfolio keeps a ledger (ADR 0065).

``ms_markets__portfolioweightsts`` loses ``held_shares`` and ``book_cash``, which revision
``0030`` added for the valuation of a portfolio without a ledger. Weights are now a
projection of the ledger, which holds the quantities. SQLite drops the columns in place
(``recreate="never"``) instead of rebuilding the table.

``ms_markets__assettype`` gains ``event_types``: the events an asset of the type can have.
On unadjusted prices a portfolio's ledger must book each of them. The upgrade sets the
events of the built-in types (ADR 0065, decision 12) on their rows; every other row lists
none. The downgrade drops the column, and adds the weights columns back, empty.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0038"
down_revision: str = "0037"
branch_labels = None
depends_on = None

WEIGHTS_TABLE = "ms_markets__portfolioweightsts"
WEIGHTS_COLUMNS = ("held_shares", "book_cash")
ASSET_TYPE_TABLE = "ms_markets__assettype"

BUILT_IN_EVENT_TYPES: dict[str, list[str]] = {
    "equity": ["dividend", "split"],
    "bond": ["coupon", "redemption"],
    "future": ["expiry"],
}
"""The events of the built-in asset types, as ``msm.constants`` defines them at 0038."""


def upgrade() -> None:
    with op.batch_alter_table(WEIGHTS_TABLE, schema=None, recreate="never") as batch_op:
        for column in WEIGHTS_COLUMNS:
            batch_op.drop_column(column)

    with op.batch_alter_table(ASSET_TYPE_TABLE, schema=None, recreate="never") as batch_op:
        batch_op.add_column(sa.Column("event_types", sa.JSON(), nullable=True))

    asset_types = sa.table(
        ASSET_TYPE_TABLE,
        sa.column("asset_type", sa.String()),
        sa.column("event_types", sa.JSON()),
    )
    op.execute(asset_types.update().values(event_types=[]))
    for asset_type, event_types in BUILT_IN_EVENT_TYPES.items():
        op.execute(
            asset_types.update()
            .where(asset_types.c.asset_type == asset_type)
            .values(event_types=event_types)
        )


def downgrade() -> None:
    with op.batch_alter_table(ASSET_TYPE_TABLE, schema=None, recreate="never") as batch_op:
        batch_op.drop_column("event_types")

    with op.batch_alter_table(WEIGHTS_TABLE, schema=None, recreate="never") as batch_op:
        for column in WEIGHTS_COLUMNS:
            batch_op.add_column(sa.Column(column, sa.Float(), nullable=True))
