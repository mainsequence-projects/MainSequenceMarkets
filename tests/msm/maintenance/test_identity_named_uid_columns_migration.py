"""Revisions 0022 to 0024 move the UID columns to identity-named ones (ADR 0048)."""

from __future__ import annotations

import importlib
import uuid

import sqlalchemy as sa
from alembic import command

from tests.msm.maintenance.test_legacy_schema_migration import _config, _seed_every_table

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0022_identity_named_uid_columns"
)
FINAL_COPY = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0023_read_identity_named_uid_columns"
)
STOP_WRITING = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0024_stop_writing_pre_3_0_uid_columns"
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


def _indexes(connection) -> list:
    return sorted(
        (index["name"], tuple(index["column_names"]), bool(index["unique"]))
        for index in sa.inspect(connection).get_indexes(REVISION.BINDING_TABLE)
    )


def _nullable(connection, table_name: str, column: str) -> bool:
    columns = {item["name"]: item for item in sa.inspect(connection).get_columns(table_name)}
    return columns[column]["nullable"]


def _late_2_x_writes(connection) -> dict[tuple[str, str], str | None]:
    """Change the pre-3.0 columns as 2.x writers would after revision 0022, and return them."""

    written = {}
    for table_name, columns in FINAL_COPY.RENAMED_COLUMNS.items():
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        values = {
            previous: uuid.uuid5(uuid.NAMESPACE_URL, f"{table_name}.{previous}.late").hex
            for previous, _current in columns
        }
        connection.execute(table.update().values(**values))
        written.update({(table_name, column): value for column, value in values.items()})
    # A 2.x writer that cleared a pointer, and one that inserted a binding row.
    connection.execute(sa.text("UPDATE ms_markets__portfolio SET signal_weights_data_node_uid = NULL"))
    written[("ms_markets__portfolio", "signal_weights_data_node_uid")] = None
    connection.execute(sa.text(f"UPDATE {FINAL_COPY.BINDING_TABLE} SET storage_table_uid = NULL"))
    connection.commit()
    return written


def _writes_from_4_0(connection) -> dict[tuple[str, str], str]:
    """Write the current columns as ms-markets 4.0 does, leaving the pre-3.0 ones NULL."""

    written = {}
    for table_name, columns in STOP_WRITING.RENAMED_COLUMNS.items():
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        values = {
            current: uuid.uuid5(uuid.NAMESPACE_URL, f"{table_name}.{current}.4_0").hex
            for _previous, current in columns
        }
        values.update({previous: None for previous, _current in columns})
        connection.execute(table.update().values(**values))
        written.update({(table_name, column): value for column, value in values.items()})
    connection.commit()
    return written


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


def test_0023_copies_late_2_x_writes_and_requires_storage_table_uid(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'uid-columns.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        command.upgrade(config, "0021")
        _seed_pre_3_0_values(connection)
        command.upgrade(config, "0022")
        written = _late_2_x_writes(connection)
        foreign_keys = _foreign_keys(connection)
        indexes = _indexes(connection)

        command.upgrade(config, "0023")
        for table_name, columns in FINAL_COPY.RENAMED_COLUMNS.items():
            row = _row(connection, table_name)
            for previous, current in columns:
                assert row[current] == row[previous] == written[(table_name, previous)]
        assert not _nullable(connection, FINAL_COPY.BINDING_TABLE, "storage_table_uid")
        assert _foreign_keys(connection) == foreign_keys
        assert _indexes(connection) == indexes

        command.downgrade(config, "0022")
        assert _nullable(connection, FINAL_COPY.BINDING_TABLE, "storage_table_uid")
        row = _row(connection, FINAL_COPY.BINDING_TABLE)
        assert row["storage_table_uid"] == written[(FINAL_COPY.BINDING_TABLE, "data_node_uid")]
        assert _foreign_keys(connection) == foreign_keys
        assert _indexes(connection) == indexes
    engine.dispose()


def test_0024_lets_rows_omit_data_node_uid_and_downgrades_with_a_copy(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'uid-columns.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        command.upgrade(config, "0021")
        _seed_pre_3_0_values(connection)
        command.upgrade(config, "0023")
        foreign_keys = _foreign_keys(connection)
        indexes = _indexes(connection)

        command.upgrade(config, "0024")
        assert _nullable(connection, STOP_WRITING.BINDING_TABLE, "data_node_uid")
        assert _foreign_keys(connection) == foreign_keys
        assert _indexes(connection) == indexes
        written = _writes_from_4_0(connection)

        command.downgrade(config, "0023")
        assert not _nullable(connection, STOP_WRITING.BINDING_TABLE, "data_node_uid")
        for table_name, columns in STOP_WRITING.RENAMED_COLUMNS.items():
            row = _row(connection, table_name)
            for previous, current in columns:
                assert row[previous] == row[current] == written[(table_name, current)]
        assert _foreign_keys(connection) == foreign_keys
        assert _indexes(connection) == indexes
    engine.dispose()
