"""Markets' own Index-value tables at 1m, 1h and 1d (ADR 0066, decision 6).

Markets declares one Index-value table per cadence as a class statement:
``IndexValues1m``, ``IndexValues1h`` and ``IndexValues1d`` in
``msm.time_index.indices.storage``. The owner fixed the set on 2026-11-25. This revision
creates their tables, ``ms_markets__index_values__t_<cadence>``, with the columns, keys
and indexes of the ``IndexValuesTS`` contract. The migration provider lists the three
classes, so the deployment's migration registers them with the other Markets tables.

Before it, Markets built such a table's class the first time a cadence was asked for, and
no revision created the table. The downgrade drops the three tables and their rows.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "0039"
down_revision: str = "0038"
branch_labels = None
depends_on = None

INDEX_TABLE = "ms_markets__index"
DEFINITION_TABLE = "ms_markets__indexformuladefinition"

TABLES: dict[str, dict[str, str]] = {
    "ms_markets__index_values__t_1m": {
        "index_key": "fk__ms_markets__index_values__t_1m__index_identifier_24953d78bc",
        "definition_key": "fk__ms_markets__index_values__t_1m__definition_uid_0e8277cd2a",
        "grain_index": "uix__ms_markets__index_values__t_1m__time_index__ind_e7ed797d86",
        "series_index": "ix__ms_markets__index_values__t_1m__index_identifier_dda9d66c29",
        "definition_index": "ix__ms_markets__index_values__t_1m__definition_uid",
        "status_index": "ix__ms_markets__index_values__t_1m__observation_status",
    },
    "ms_markets__index_values__t_1h": {
        "index_key": "fk__ms_markets__index_values__t_1h__index_identifier_2290c7f7d7",
        "definition_key": "fk__ms_markets__index_values__t_1h__definition_uid_b1cc6654de",
        "grain_index": "uix__ms_markets__index_values__t_1h__time_index__ind_d40651044f",
        "series_index": "ix__ms_markets__index_values__t_1h__index_identifier_d50e47f45a",
        "definition_index": "ix__ms_markets__index_values__t_1h__definition_uid",
        "status_index": "ix__ms_markets__index_values__t_1h__observation_status",
    },
    "ms_markets__index_values__t_1d": {
        "index_key": "fk__ms_markets__index_values__t_1d__index_identifier_1fe142575d",
        "definition_key": "fk__ms_markets__index_values__t_1d__definition_uid_72895f3c43",
        "grain_index": "uix__ms_markets__index_values__t_1d__time_index__ind_88c17df072",
        "series_index": "ix__ms_markets__index_values__t_1d__index_identifier_e673aae886",
        "definition_index": "ix__ms_markets__index_values__t_1d__definition_uid",
        "status_index": "ix__ms_markets__index_values__t_1d__observation_status",
    },
}
"""Each table's key and index names, as the ``IndexValuesTS`` contract names them."""


def upgrade() -> None:
    for table, names in TABLES.items():
        op.create_table(
            table,
            sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
            sa.Column("index_identifier", sa.String(length=255), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column("definition_uid", sa.Uuid(), nullable=True),
            sa.Column("observation_status", sa.String(length=32), nullable=True),
            sa.Column("source_as_of", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(
                ["index_identifier"],
                [f"{INDEX_TABLE}.unique_identifier"],
                name=op.f(names["index_key"]),
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["definition_uid"],
                [f"{DEFINITION_TABLE}.uid"],
                name=op.f(names["definition_key"]),
                ondelete="RESTRICT",
            ),
        )
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_index(
                names["grain_index"], ["time_index", "index_identifier"], unique=True
            )
            batch_op.create_index(
                batch_op.f(names["series_index"]),
                ["index_identifier", "time_index"],
                unique=False,
            )
            batch_op.create_index(
                batch_op.f(names["definition_index"]), ["definition_uid"], unique=False
            )
            batch_op.create_index(
                batch_op.f(names["status_index"]), ["observation_status"], unique=False
            )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
