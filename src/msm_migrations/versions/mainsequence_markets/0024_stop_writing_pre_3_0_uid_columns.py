"""Let rows omit the pre-3.0 UID columns that ms-markets 4.0 stops writing (ADR 0048).

ms-markets 4.0 no longer maps, reads or writes the pre-3.0 ``*_data_node_uid``
columns, so the rows it inserts leave them NULL. This revision makes
``data_node_uid``, the only one of them that is NOT NULL, nullable. The columns
stay until revision ``0025`` in ms-markets 4.1, because every 3.x process still
selects and writes them. ms-markets 4.0 ships this revision, so deploy it only
once no reader older than 3.1 remains: 3.0 reads the pre-3.0 columns.

The downgrade copies every current value that differs, NULL included, back into
its pre-3.0 column, so 3.x reads the rows 4.0 wrote, and restores NOT NULL on
``data_node_uid``.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0024"
down_revision: str = "0023"
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


def _differs(previous: str, current: str) -> str:
    # SQLite before 3.39 has no IS DISTINCT FROM; this works on SQLite and PostgreSQL.
    return (
        f"{current} <> {previous} "
        f"OR ({current} IS NULL AND {previous} IS NOT NULL) "
        f"OR ({current} IS NOT NULL AND {previous} IS NULL)"
    )


def upgrade() -> None:
    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.alter_column("data_node_uid", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    for table_name, columns in RENAMED_COLUMNS.items():
        for previous, current in columns:
            op.execute(
                sa.text(
                    f"UPDATE {table_name} SET {previous} = {current} "
                    f"WHERE {_differs(previous, current)}"
                )
            )

    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.alter_column("data_node_uid", existing_type=sa.Uuid(), nullable=False)
