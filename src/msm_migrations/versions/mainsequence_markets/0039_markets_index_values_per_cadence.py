"""Markets' own Index-value tables at 1m, 1h and 1d (ADR 0066, decision 6).

Markets declares one Index-value table per cadence as a class statement:
``IndexValues1m``, ``IndexValues1h`` and ``IndexValues1d`` in
``msm.time_index.indices.storage``. The owner fixed the set on 2026-11-25. This revision
creates their tables, ``ms_markets__index_values__t_<cadence>``, with the columns, keys
and indexes of the ``IndexValuesTS`` contract. The migration provider lists the three
classes, so the deployment's migration registers them with the other Markets tables.

Before it, Markets built such a table's class the first time a cadence was asked for, and
no revision created the table, so a database can already hold one (issue 147). A table
that exists is taken as it is, rows included, when it has exactly the contract's columns,
types, nullability, keys and indexes. One that differs in any of them is refused, with
each difference named, before the revision changes anything.

The downgrade drops the three tables and their rows.
"""

import logging
import re

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

ON_DELETE = "RESTRICT"
"""What each key does when the row it points at is deleted."""


def _columns() -> list[sa.Column]:
    """The contract's columns, new objects for each table."""

    return [
        sa.Column("time_index", sa.DateTime(timezone=True), nullable=False),
        sa.Column("index_identifier", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("definition_uid", sa.Uuid(), nullable=True),
        sa.Column("observation_status", sa.String(length=32), nullable=True),
        sa.Column("source_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    ]


def _keys(names: dict[str, str]) -> dict[str, tuple[str, str, str]]:
    """Each foreign key by name: its column, and the table and column it points at."""

    return {
        names["index_key"]: ("index_identifier", INDEX_TABLE, "unique_identifier"),
        names["definition_key"]: ("definition_uid", DEFINITION_TABLE, "uid"),
    }


def _indexes(names: dict[str, str]) -> dict[str, tuple[tuple[str, ...], bool]]:
    """Each index by name: its columns, in order, and whether it is unique."""

    return {
        names["grain_index"]: (("time_index", "index_identifier"), True),
        names["series_index"]: (("index_identifier", "time_index"), False),
        names["definition_index"]: (("definition_uid",), False),
        names["status_index"]: (("observation_status",), False),
    }


def _arguments(type_: sa.types.TypeEngine, dialect) -> list[str]:
    return re.findall(r"\([^)]*\)", type_.compile(dialect=dialect))


def _key(inspector: sa.Inspector, key: dict) -> str:
    """A reflected foreign key in words: its columns, what they point at, its actions."""

    schema = key.get("referred_schema")
    target = key["referred_table"]
    if schema not in (None, inspector.default_schema_name):
        target = f"{schema}.{target}"
    options = key.get("options") or {}
    words = (
        f"({', '.join(key['constrained_columns'])}) -> {target} "
        f"({', '.join(key['referred_columns'])}) "
        f"ON DELETE {(options.get('ondelete') or 'NO ACTION').upper()}"
    )
    if options.get("onupdate"):
        words += f" ON UPDATE {options['onupdate'].upper()}"
    return words


def _index(columns, unique: bool) -> str:
    return f"{'unique ' if unique else ''}on ({', '.join(str(column) for column in columns)})"


def _differences(inspector: sa.Inspector, table: str, names: dict[str, str]) -> list[str]:
    """How the existing ``table`` differs from the contract; empty when it matches."""

    context = op.get_context()
    dialect = context.dialect
    found: list[str] = []

    columns = {column["name"]: column for column in inspector.get_columns(table)}
    for expected in _columns():
        column = columns.pop(expected.name, None)
        if column is None:
            found.append(f"column {expected.name} is missing")
            continue
        # Alembic's comparison knows the dialect's synonyms (PostgreSQL reports FLOAT as
        # DOUBLE PRECISION) but passes a length only one side states.
        if context.impl.compare_type(sa.Column(expected.name, column["type"]), expected) or (
            _arguments(column["type"], dialect) != _arguments(expected.type, dialect)
        ):
            found.append(
                f"column {expected.name} is {column['type'].compile(dialect=dialect)}, "
                f"the contract's is {expected.type.compile(dialect=dialect)}"
            )
        if column["nullable"] != expected.nullable:
            nullable = {True: "nullable", False: "NOT NULL"}
            found.append(
                f"column {expected.name} is {nullable[bool(column['nullable'])]}, "
                f"the contract's is {nullable[bool(expected.nullable)]}"
            )
    found += [f"column {name} is not in the contract" for name in columns]

    primary_key = inspector.get_pk_constraint(table)["constrained_columns"]
    if primary_key:
        found.append(f"primary key on ({', '.join(primary_key)}) is not in the contract")

    keys = inspector.get_foreign_keys(table)
    contract_keys = _keys(names)
    for name, (column, target, target_column) in contract_keys.items():
        key = next((key for key in keys if key["name"] == name), None)
        expected = _key(inspector, {
            "constrained_columns": [column], "referred_table": target,
            "referred_columns": [target_column], "options": {"ondelete": ON_DELETE},
        })
        if key is None:
            found.append(f"foreign key {name} is missing")
        elif _key(inspector, key) != expected:
            found.append(
                f"foreign key {name} is {_key(inspector, key)}, the contract's is {expected}"
            )
    found += [
        f"foreign key {key['name'] or 'without a name'} {_key(inspector, key)} "
        "is not in the contract"
        for key in keys
        if key["name"] not in contract_keys
    ]

    indexes = {index["name"]: index for index in inspector.get_indexes(table)}
    for name, (index_columns, unique) in _indexes(names).items():
        index = indexes.pop(name, None)
        if index is None:
            found.append(f"index {name} is missing")
        elif _index(index["column_names"], index["unique"]) != _index(index_columns, unique):
            found.append(
                f"index {name} is {_index(index['column_names'], index['unique'])}, "
                f"the contract's is {_index(index_columns, unique)}"
            )
    found += [f"index {name} is not in the contract" for name in indexes]
    return found


def _create(table: str, names: dict[str, str]) -> None:
    op.create_table(
        table,
        *_columns(),
        *(
            sa.ForeignKeyConstraint(
                [column], [f"{target}.{target_column}"], name=op.f(name), ondelete=ON_DELETE
            )
            for name, (column, target, target_column) in _keys(names).items()
        ),
    )
    with op.batch_alter_table(table, schema=None) as batch_op:
        for name, (columns, unique) in _indexes(names).items():
            batch_op.create_index(batch_op.f(name), list(columns), unique=unique)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = [table for table in TABLES if inspector.has_table(table)]
    # Every existing table is checked before any table is created, so a refusal leaves the
    # database as it was on SQLite too, where Alembic runs the DDL outside a transaction.
    refused = {
        table: differences
        for table in existing
        if (differences := _differences(inspector, table, TABLES[table]))
    }
    if refused:
        raise RuntimeError(
            "Revision 0039 refuses existing tables that differ from the IndexValuesTS contract: "
            + " ".join(
                f"{table}: {'; '.join(differences)}." for table, differences in refused.items()
            )
        )
    for table, names in TABLES.items():
        if table in existing:
            logging.getLogger(__name__).info(
                "Took the existing %s as it is, with its rows: it matches the IndexValuesTS "
                "contract",
                table,
            )
        else:
            _create(table, names)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
