"""Drop the pre-3.0 UID columns (ADR 0048, issue 107).

Revision ``0022`` gave each pre-3.0 ``*_data_node_uid`` column a successor named after
the identity it holds, and every release from 3.0.0 until 5.0.0 wrote both columns and
read the pre-3.0 one. This revision copies each pre-3.0 column into its successor, so
every row keeps the value those releases read, makes ``storage_table_uid`` NOT NULL on
pricing market-data bindings, as ``data_node_uid`` was, and drops the six pre-3.0
columns and the ``data_node_uid`` index. Those releases map the dropped columns, so they
fail on the account, account holdings set, portfolio and pricing market-data binding
tables once this revision runs. The downgrade adds the pre-3.0 columns back, copied
from their successors.

SQLite drops the columns in place (``recreate="never"``) instead of rebuilding the
tables. A rebuilt table is created last, and SQLite runs the actions of the keys into
a deleted row in reverse creation order: a rebuilt account holdings set table would let
an account delete cascade through it to holdings written after the delete's read, which
the holdings key refuses today (ADR 0050). Only the binding table is rebuilt, for the
NOT NULL constraint.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0035"
down_revision: str = "0034"
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
"""Table name to ``(pre-3.0 column, current column)`` pairs, as revision ``0022`` added them."""

BINDING_TABLE = "ms_markets__pricingmarketdatasetbinding"
BINDING_INDEX = "ix__ms_markets__pricingmarketdatasetbinding__data_node_uid"


def upgrade() -> None:
    for table_name, columns in RENAMED_COLUMNS.items():
        assignments = ", ".join(f"{current} = {previous}" for previous, current in columns)
        op.execute(sa.text(f"UPDATE {table_name} SET {assignments}"))

    op.drop_index(op.f(BINDING_INDEX), table_name=BINDING_TABLE)
    for table_name, columns in RENAMED_COLUMNS.items():
        with op.batch_alter_table(table_name, schema=None, recreate="never") as batch_op:
            for previous, _current in columns:
                batch_op.drop_column(previous)

    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.alter_column("storage_table_uid", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    for table_name, columns in RENAMED_COLUMNS.items():
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            for previous, _current in columns:
                batch_op.add_column(sa.Column(previous, sa.Uuid(), nullable=True))
        assignments = ", ".join(f"{previous} = {current}" for previous, current in columns)
        op.execute(sa.text(f"UPDATE {table_name} SET {assignments}"))

    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.alter_column("data_node_uid", existing_type=sa.Uuid(), nullable=False)
        batch_op.alter_column("storage_table_uid", existing_type=sa.Uuid(), nullable=True)
        batch_op.create_index(batch_op.f(BINDING_INDEX), ["data_node_uid"], unique=False)
