"""Revision 0022 adds identity-named UID columns next to the pre-3.0 ones (ADR 0048)."""

from __future__ import annotations

import importlib
import uuid

import sqlalchemy as sa
from alembic import command

from tests.msm.maintenance.test_legacy_schema_migration import _config, _seed_every_table

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0022_identity_named_uid_columns"
)


def _seed_pre_3_0_values(connection) -> dict[tuple[str, str], str]:
    """Give every pre-3.0 UID column a distinct value and return them by (table, column)."""

    _seed_every_table(connection, expected_tables=63)
    expected = {}
    for table_name, columns in REVISION.RENAMED_COLUMNS.items():
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        # SQLite stores sa.Uuid as CHAR(32) hex, which reflection reports as CHAR.
        values = {
            previous: uuid.uuid5(uuid.NAMESPACE_URL, f"{table_name}.{previous}").hex
            for previous, _current in columns
        }
        connection.execute(table.update().values(**values))
        expected.update({(table_name, column): value for column, value in values.items()})
    connection.commit()
    return expected


def _row(connection, table_name: str) -> dict:
    table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
    return dict(connection.execute(sa.select(table)).mappings().one())


def _foreign_keys(connection) -> dict[str, list]:
    inspector = sa.inspect(connection)
    return {
        table_name: sorted(
            (fk["constrained_columns"], fk["referred_table"], fk["options"].get("ondelete"))
            for fk in inspector.get_foreign_keys(table_name)
        )
        for table_name in REVISION.RENAMED_COLUMNS
    }


def test_0022_copies_pre_3_0_values_and_downgrades_cleanly(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'uid-columns.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        command.upgrade(config, "0021")
        expected = _seed_pre_3_0_values(connection)
        foreign_keys = _foreign_keys(connection)

        command.upgrade(config, "0022")
        for table_name, columns in REVISION.RENAMED_COLUMNS.items():
            row = _row(connection, table_name)
            for previous, current in columns:
                assert row[current] == row[previous] == expected[(table_name, previous)]
        indexes = {
            index["name"]
            for index in sa.inspect(connection).get_indexes(REVISION.BINDING_TABLE)
        }
        assert REVISION.BINDING_INDEX in indexes
        assert _foreign_keys(connection) == foreign_keys

        command.downgrade(config, "0021")
        for table_name, columns in REVISION.RENAMED_COLUMNS.items():
            row = _row(connection, table_name)
            for previous, current in columns:
                assert current not in row
                assert row[previous] == expected[(table_name, previous)]
        assert _foreign_keys(connection) == foreign_keys

        command.upgrade(config, "head")
        row = _row(connection, REVISION.BINDING_TABLE)
        assert row["storage_table_uid"] == expected[(REVISION.BINDING_TABLE, "data_node_uid")]
    engine.dispose()
