"""Revision 0031 adds the series-leading index of the six other portfolio datasets (issue 96)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command

from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.support.migrations import _config

SERIES_COLUMNS = ["portfolio_identifier", "time_index"]
INDEXED = [table.model.__table__ for table in PORTFOLIO_DATASET_TABLES if table.key != "weights"]


def _indexes(connection: sa.Connection, table_name: str) -> dict[str, tuple[list[str], bool]]:
    return {
        index["name"]: (index["column_names"], bool(index["unique"]))
        for index in sa.inspect(connection).get_indexes(table_name)
    }


def test_every_portfolio_dataset_model_has_the_series_index() -> None:
    for table in PORTFOLIO_DATASET_TABLES:
        series = [
            index
            for index in table.model.__table__.indexes
            if [column.name for column in index.columns] == SERIES_COLUMNS
        ]
        assert len(series) == 1, table.key
        assert not series[0].unique


def test_0031_matches_the_storage_models(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'dataset-series-index.sqlite'}")
    with engine.connect() as connection:
        command.upgrade(_config(connection), "head")

        for table in INDEXED:
            migrated = _indexes(connection, table.name)
            assert migrated == {
                index.name: ([column.name for column in index.columns], bool(index.unique))
                for index in table.indexes
            }
            assert (SERIES_COLUMNS, False) in migrated.values()


def test_0031_downgrade_leaves_only_the_unique_index(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'dataset-series-index-down.sqlite'}")
    with engine.connect() as connection:
        config = _config(connection)
        command.upgrade(config, "0031")
        command.downgrade(config, "0030")

        for table in INDEXED:
            assert [unique for _, unique in _indexes(connection, table.name).values()] == [True]
