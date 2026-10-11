"""Join the populated 0017 schema and the 0019 development schema without resets.

Only the ten identifiers left unbounded by the old schema may differ from the
frozen 0018 column baseline. No table, column, or row is removed. PostgreSQL
applies checked identifier limits in place; SQLite needs no physical change.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision: str = "0020"
down_revision = ("0017", "0019")
branch_labels = None
depends_on = None

LEGACY_IDENTIFIERS = {
    "ms_markets__signalweightsts": ("asset_identifier",),
    "ms_markets__portfolioweightsts": ("portfolio_identifier", "asset_identifier"),
    "ms_markets__tradests": (
        "account_identifier", "asset_identifier", "commission_asset_identifier",
        "settlement_asset_identifier",
    ),
    "ms_markets__ordersts": (
        "account_identifier", "order_manager_identifier", "asset_identifier",
    ),
}


def _fingerprint(connection, table_name):
    name = connection.dialect.identifier_preparer.quote(table_name)
    # A bounded-size aggregate verifies the row multiset without returning data
    # or building an unbounded string of every row. Identifier limits do not
    # change the JSON representation of any stored value.
    return tuple(connection.exec_driver_sql(
        f"SELECT count(*), sum(('x'||substr(md5(row_to_json(t)::text),1,16))::bit(64)::bigint), "
        f"sum(('x'||substr(md5(row_to_json(t)::text),17,16))::bit(64)::bigint) FROM {name} t"
    ).one())


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    expected = json.loads(Path(__file__).with_name("0020_expected_columns.json").read_text())
    tables = set(inspector.get_table_names())
    missing = sorted(set(expected) - tables)
    if missing:
        raise RuntimeError(f"Legacy schema is missing application tables: {missing}")
    changes = []
    for table_name, columns in expected.items():
        actual = {column["name"]: column for column in inspector.get_columns(table_name)}
        for name, contract in columns.items():
            column = actual.get(name)
            if column is None or column["nullable"] != contract["nullable"]:
                raise RuntimeError(f"Legacy schema column contract differs: {table_name}.{name}")
            expected_type = contract["type"]
            actual_type = str(column["type"])
            if connection.dialect.name == "sqlite":
                # SQLite stores JSONB as JSON and all date-times without a zone.
                expected_type = expected_type.replace("JSONB", "JSON").replace("TIMESTAMP", "DATETIME")
                expected_type = expected_type.replace("DOUBLE PRECISION", "FLOAT").replace("UUID", "CHAR(32)")
            if actual_type == expected_type:
                continue
            if (
                name in LEGACY_IDENTIFIERS.get(table_name, ())
                and isinstance(column["type"], sa.String)
                and column["type"].length is None
                and expected_type == "VARCHAR(255)"
            ):
                table = sa.table(table_name, sa.column(name, sa.String()))
                maximum = connection.execute(sa.select(sa.func.max(sa.func.length(table.c[name])))).scalar()
                if maximum is not None and maximum > 255:
                    raise RuntimeError(f"Cannot bound {table_name}.{name}: existing value exceeds 255 characters")
                changes.append((table_name, name, column))
                continue
            raise RuntimeError(
                f"Legacy schema type differs: {table_name}.{name}: {actual_type} != {expected_type}"
            )
    if connection.dialect.name == "postgresql":
        changed_tables = sorted({table for table, _, _ in changes})
        before = {}
        if changed_tables:
            # Block competing writes only on tables whose column limits change.
            # Already-current development has no changes and takes no locks.
            names = ", ".join(connection.dialect.identifier_preparer.quote(name) for name in changed_tables)
            connection.exec_driver_sql(f"LOCK TABLE {names} IN SHARE ROW EXCLUSIVE MODE")
            # Recheck lengths under the lock, since a writer could have
            # committed between the initial validation and acquiring it.
            for table_name, name, _ in changes:
                table = sa.table(table_name, sa.column(name, sa.String()))
                maximum = connection.execute(sa.select(sa.func.max(sa.func.length(table.c[name])))).scalar()
                if maximum is not None and maximum > 255:
                    raise RuntimeError(f"Cannot bound {table_name}.{name}: existing value exceeds 255 characters")
            before = {name: _fingerprint(connection, name) for name in changed_tables}
        for table_name, name, column in changes:
            op.alter_column(
                table_name, name, existing_type=column["type"], type_=sa.String(255),
                existing_nullable=column["nullable"],
            )
        for table_name, fingerprint in before.items():
            if _fingerprint(connection, table_name) != fingerprint:
                raise RuntimeError(f"Row contents changed during legacy reconciliation: {table_name}")
            logging.getLogger(__name__).info(
                "Preserved all %d rows in %s (row multiset checksum unchanged)",
                fingerprint[0], table_name,
            )
    elif connection.dialect.name != "sqlite" and changes:
        raise RuntimeError("Legacy identifier reconciliation supports PostgreSQL and SQLite")
    logging.getLogger(__name__).info(
        "Verified %d application tables; reconciled %d legacy identifier limits without replacing tables",
        len(expected), len(changes),
    )


def downgrade() -> None:
    raise RuntimeError("Legacy schema reconciliation is forward-only; use a new migration.")
