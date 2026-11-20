"""Portfolio datasets in the account delete's data on SQLite (ADR 0050, issue 91).

For the account delete tests that look at the portfolios' datasets; the rest of the
harness and data is in `tests/support/account_delete.py`.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.support.account_delete import _portfolio_identifier
from tests.support.sqlite_markets import WHEN, _insert, _portfolio

DATASETS = {table.key: table.table_name for table in PORTFOLIO_DATASET_TABLES}


def _portfolio_with_data(engine) -> tuple[uuid.UUID, str]:
    """A portfolio with one row in each of its datasets."""

    portfolio = _portfolio(engine)
    identifier = _portfolio_identifier(engine, portfolio)
    for table_name in DATASETS.values():
        assets = {
            foreign_key["constrained_columns"][0]: "AAA"
            for foreign_key in sa.inspect(engine).get_foreign_keys(table_name)
            if foreign_key["referred_table"] == "ms_markets__asset"
        }
        _insert(engine, table_name, time_index=WHEN, portfolio_identifier=identifier, **assets)
    return portfolio, identifier


def _dataset_rows(engine, identifier: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            key: connection.execute(
                sa.text(f"SELECT count(*) FROM {table_name} WHERE portfolio_identifier = :identifier"),
                {"identifier": identifier},
            ).scalar_one()
            for key, table_name in DATASETS.items()
        }
