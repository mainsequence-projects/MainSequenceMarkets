"""Revision 0026 adds the series-leading index of the weights tables (issue 77)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command

from msm_portfolios.time_index.portfolios.storage import PortfolioWeightsStorage
from msm_portfolios.time_index.signals.storage import SignalWeightsStorage
from tests.support.migrations import _config

SERIES_INDEXES = {
    SignalWeightsStorage.__table__: ["signal_uid", "time_index"],
    PortfolioWeightsStorage.__table__: ["portfolio_identifier", "time_index"],
}


def _indexes(connection: sa.Connection, table_name: str) -> dict[str, tuple[list[str], bool]]:
    return {
        index["name"]: (index["column_names"], bool(index["unique"]))
        for index in sa.inspect(connection).get_indexes(table_name)
    }


def test_0026_matches_the_storage_models(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'series-index.sqlite'}")
    with engine.connect() as connection:
        command.upgrade(_config(connection), "head")

        for table, series_columns in SERIES_INDEXES.items():
            migrated = _indexes(connection, table.name)
            assert migrated == {
                index.name: ([column.name for column in index.columns], bool(index.unique))
                for index in table.indexes
            }
            assert (series_columns, False) in migrated.values()


def test_0026_downgrade_leaves_only_the_unique_index(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'series-index-down.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        command.upgrade(config, "0026")
        command.downgrade(config, "0025")

        for table in SERIES_INDEXES:
            assert [unique for _, unique in _indexes(connection, table.name).values()] == [True]
