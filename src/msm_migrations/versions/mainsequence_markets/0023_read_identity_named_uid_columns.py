"""Copy late 2.x writes into the identity-named UID columns (ADR 0048).

Revision ``0022`` copied every pre-3.0 ``*_data_node_uid`` value into its
identity-named column, but 2.x writers that ran after it updated only the pre-3.0
columns. ms-markets 3.1 ships this revision, so deploy it only once no writer
older than 3.0 remains. It copies every pre-3.0 value that differs, NULL
included, so each identity-named column holds what ms-markets 3.0 read, and makes
``storage_table_uid`` NOT NULL like the ``data_node_uid`` column it replaces.
ms-markets 3.1 reads the identity-named columns and still writes both, so 3.0
readers stay correct. ms-markets 4.0 stops writing the pre-3.0 columns and 4.1
drops them.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0023"
down_revision: str = "0022"
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
    for table_name, columns in RENAMED_COLUMNS.items():
        for previous, current in columns:
            op.execute(
                sa.text(
                    f"UPDATE {table_name} SET {current} = {previous} "
                    f"WHERE {_differs(previous, current)}"
                )
            )

    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.alter_column("storage_table_uid", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    # 3.0 reads the pre-3.0 columns, which 3.1 kept writing, so the copy stays.
    with op.batch_alter_table(BINDING_TABLE, schema=None) as batch_op:
        batch_op.alter_column("storage_table_uid", existing_type=sa.Uuid(), nullable=True)
