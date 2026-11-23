"""Revision 0034 indexes the account history tables by their keys' and owners' columns."""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic import command

from msm.time_index.accounts.storage import AccountHoldingsStorage
from msm.time_index.accounts.virtual_funds.storage import (
    AccountAllocationLinesStorage,
    VirtualFundHoldingsStorage,
)
from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage
from tests.support.migrations import _config

MIGRATION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0034_account_history_indexes"
)
HISTORY_TABLES = [
    model.__table__
    for model in (
        AccountHoldingsStorage,
        AccountAllocationLinesStorage,
        VirtualFundHoldingsStorage,
        OrdersStorage,
        TradesStorage,
        OrderEventsStorage,
    )
]


def _indexes(connection: sa.Connection, table_name: str) -> dict[str, tuple[list[str], bool]]:
    return {
        index["name"]: (index["column_names"], bool(index["unique"]))
        for index in sa.inspect(connection).get_indexes(table_name)
    }


REKEYED_TABLES = {"ms_markets__ordersts", "ms_markets__ordereventsts", "ms_markets__tradests"}
"""Revision 0037 re-keys the execution tables on their order (ADR 0064)."""


def test_the_revision_creates_the_models_non_unique_indexes() -> None:
    declared = {
        (table.name, index.name, tuple(column.name for column in index.columns))
        for table in HISTORY_TABLES
        if table.name not in REKEYED_TABLES
        for index in table.indexes
        if not index.unique
    }

    assert {index for index in MIGRATION.INDEXES if index[0] not in REKEYED_TABLES} == declared


def test_0034_matches_the_storage_models(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "account-history-indexes.sqlite", "head")
    with engine.connect() as connection:
        for table in HISTORY_TABLES:
            assert _indexes(connection, table.name) == {
                index.name: ([column.name for column in index.columns], bool(index.unique))
                for index in table.indexes
            }


def test_0034_downgrade_restores_the_0033_indexes(tmp_path, sqlite_revisions) -> None:
    before = sqlite_revisions.engine(tmp_path / "account-history-0033.sqlite", "0033")
    with before.connect() as connection:
        at_0033 = {table.name: _indexes(connection, table.name) for table in HISTORY_TABLES}
    engine = sqlite_revisions.engine(tmp_path / "account-history-down.sqlite", "0034")
    with engine.connect() as connection:
        command.downgrade(_config(connection), "0033")

        assert {table.name: _indexes(connection, table.name) for table in HISTORY_TABLES} == at_0033
    assert all(
        [unique for _columns, unique in indexes.values()] == [True] for indexes in at_0033.values()
    )
