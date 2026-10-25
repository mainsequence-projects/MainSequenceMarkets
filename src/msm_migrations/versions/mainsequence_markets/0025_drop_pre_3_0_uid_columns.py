"""Drop the pre-3.0 UID columns (ADR 0048).

ms-markets 4.0 stopped mapping, reading and writing the pre-3.0
``*_data_node_uid`` columns, but every 3.x process still selects and writes
them. ms-markets 4.1 ships this revision, so deploy it only once no process older
than 4.0 uses these tables.

The downgrade re-adds the columns, nullable as revision ``0024`` left them,
copies the current values into them and restores the ``data_node_uid`` index.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0025"
down_revision: str = "0024"
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
BINDING_INDEX = "ix__ms_markets__pricingmarketdatasetbinding__data_node_uid"


def upgrade() -> None:
    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.drop_index(batch_op.f(BINDING_INDEX))

    for table_name, columns in RENAMED_COLUMNS.items():
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            for previous, _current in columns:
                batch_op.drop_column(previous)


def downgrade() -> None:
    for table_name, columns in RENAMED_COLUMNS.items():
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            for previous, _current in columns:
                batch_op.add_column(sa.Column(previous, sa.Uuid(), nullable=True))
        assignments = ", ".join(f"{previous} = {current}" for previous, current in columns)
        op.execute(sa.text(f"UPDATE {table_name} SET {assignments}"))

    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.create_index(batch_op.f(BINDING_INDEX), ["data_node_uid"], unique=False)
