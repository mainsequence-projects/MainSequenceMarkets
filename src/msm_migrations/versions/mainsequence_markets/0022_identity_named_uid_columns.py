"""Add UID columns named after the identity they hold (ADR 0048).

Each pre-3.0 ``*_data_node_uid`` column gets a successor that names the identity
it holds: ``*_table_update_uid`` for a TimeIndexTableUpdate uid and
``*storage_table_uid`` for a TimeIndexMetaTable uid. This revision only adds the
columns and copies the existing values, so the release that is still deployed
keeps working during the rollout. ms-markets 3.0 writes both columns and reads the
pre-3.0 ones, because 2.x writers update only those. Revision ``0023`` copies any
late 2.x writes and switches reads to the new columns; revision ``0024`` drops the
pre-3.0 columns in ms-markets 4.0.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0022"
down_revision: str = "0021"
branch_labels = None
depends_on = None

RENAMED_COLUMNS = {
    "ms_markets__account": (("holdings_data_node_uid", "holdings_storage_table_uid"),),
    "ms_markets__accountholdingsset": (("source_data_node_uid", "source_storage_table_uid"),),
    "ms_markets__portfolio": (
        ("portfolio_weights_data_node_uid", "portfolio_weights_table_update_uid"),
        ("signal_weights_data_node_uid", "signal_weights_table_update_uid"),
        ("portfolio_data_node_uid", "portfolio_table_update_uid"),
    ),
    "ms_markets__pricingmarketdatasetbinding": (("data_node_uid", "storage_table_uid"),),
}
"""Table name to ``(pre-3.0 column, current column)`` pairs."""

BINDING_TABLE = "ms_markets__pricingmarketdatasetbinding"
BINDING_INDEX = "ix__ms_markets__pricingmarketdatasetbinding__storage_table_uid"


def upgrade() -> None:
    for table_name, columns in RENAMED_COLUMNS.items():
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            for _previous, current in columns:
                batch_op.add_column(sa.Column(current, sa.Uuid(), nullable=True))
        assignments = ", ".join(f"{current} = {previous}" for previous, current in columns)
        op.execute(sa.text(f"UPDATE {table_name} SET {assignments}"))

    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.create_index(batch_op.f(BINDING_INDEX), ["storage_table_uid"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(BINDING_INDEX))

    for table_name, columns in reversed(RENAMED_COLUMNS.items()):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            for _previous, current in reversed(columns):
                batch_op.drop_column(current)
