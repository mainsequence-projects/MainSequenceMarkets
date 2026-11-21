"""Revision 0035 drops the pre-3.0 UID columns (ADR 0048, issue 107)."""

from __future__ import annotations

import importlib
import uuid

import sqlalchemy as sa
from alembic import command

from tests.support.migrations import _config
from tests.support.sqlite_markets import _insert

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0035_drop_pre_3_0_uid_columns"
)


def _uid() -> str:
    # SQLite stores sa.Uuid as CHAR(32) hex, which reflection reports as CHAR.
    return uuid.uuid4().hex


def _row(connection, table_name: str) -> dict:
    table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
    return dict(connection.execute(sa.select(table)).mappings().one())


def _columns(connection, table_name: str) -> dict[str, dict]:
    return {column["name"]: column for column in sa.inspect(connection).get_columns(table_name)}


def _indexes(connection) -> set[str]:
    return {index["name"] for index in sa.inspect(connection).get_indexes(REVISION.BINDING_TABLE)}


def _foreign_keys(connection) -> dict[str, list]:
    inspector = sa.inspect(connection)
    return {
        table_name: sorted(
            (fk["constrained_columns"], fk["referred_table"], fk["options"].get("ondelete"))
            for fk in inspector.get_foreign_keys(table_name)
        )
        for table_name in REVISION.RENAMED_COLUMNS
    }


def _seed(engine) -> None:
    """One row per table; some successors differ from the pre-3.0 value every release read."""

    account = _insert(
        engine,
        "ms_markets__account",
        holdings_data_node_uid=_uid(),
        holdings_storage_table_uid=_uid(),
    )
    _insert(
        engine,
        "ms_markets__accountholdingsset",
        account_uid=account["uid"],
        source_data_node_uid=None,
        source_storage_table_uid=_uid(),
    )
    calendar = _insert(engine, "ms_markets__calendar")
    _insert(
        engine,
        "ms_markets__portfolio",
        calendar_uid=calendar["uid"],
        signal_uid=None,
        portfolio_weights_data_node_uid=_uid(),
        portfolio_weights_table_update_uid=None,
        signal_weights_data_node_uid=_uid(),
        signal_weights_table_update_uid=_uid(),
        portfolio_data_node_uid=(shared := _uid()),
        portfolio_table_update_uid=shared,
    )
    market_data_set = _insert(engine, "ms_markets__pricingmarketdataset")
    _insert(
        engine,
        REVISION.BINDING_TABLE,
        market_data_set_uid=market_data_set["uid"],
        data_node_uid=_uid(),
        storage_table_uid=None,
    )


def test_0035_keeps_the_values_releases_read_and_drops_the_pre_3_0_columns(
    tmp_path, sqlite_revisions
) -> None:
    engine = sqlite_revisions.engine(tmp_path / "pre-3-0-columns.sqlite", "0034")
    _seed(engine)
    with engine.connect() as connection:
        config = _config(connection)
        before = {table_name: _row(connection, table_name) for table_name in REVISION.RENAMED_COLUMNS}
        foreign_keys = _foreign_keys(connection)

        command.upgrade(config, "0035")
        for table_name, columns in REVISION.RENAMED_COLUMNS.items():
            expected = dict(before[table_name])
            for previous, current in columns:
                expected[current] = expected.pop(previous)
            assert _row(connection, table_name) == expected
        assert _columns(connection, REVISION.BINDING_TABLE)["storage_table_uid"]["nullable"] is False
        assert REVISION.BINDING_INDEX not in _indexes(connection)
        assert _foreign_keys(connection) == foreign_keys

        command.downgrade(config, "0034")
        for table_name, columns in REVISION.RENAMED_COLUMNS.items():
            row = _row(connection, table_name)
            for previous, current in columns:
                assert row[previous] == row[current] == before[table_name][previous]
        binding_columns = _columns(connection, REVISION.BINDING_TABLE)
        assert binding_columns["data_node_uid"]["nullable"] is False
        assert binding_columns["storage_table_uid"]["nullable"] is True
        assert REVISION.BINDING_INDEX in _indexes(connection)
        assert _foreign_keys(connection) == foreign_keys
    engine.dispose()
