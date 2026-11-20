"""The portfolio delete's harness and data on SQLite (issue 93, ADR 0049).

`tests/msm_portfolios/services/test_sqlite_portfolio_delete.py`, its route test in
`tests/apps/v1/test_sqlite_portfolio_delete.py`, and the account delete with portfolios
share them.
"""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa

from msm.models import PortfolioTable
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.support.sqlite_markets import WHEN, _asset, _insert, _portfolio, _rows

DATASETS = {table.key: table.table_name for table in PORTFOLIO_DATASET_TABLES}


def _identifier(engine, portfolio: uuid.UUID) -> str:
    (row,) = _rows(
        engine,
        "SELECT unique_identifier FROM ms_markets__portfolio WHERE uid = :uid",
        uid=portfolio.hex,
    )
    return row["unique_identifier"]


def _dataset_row(engine, key: str, identifier: str, *, when: dt.datetime = WHEN) -> None:
    table_name = DATASETS[key]
    assets = {
        foreign_key["constrained_columns"][0]: "AAA"
        for foreign_key in sa.inspect(engine).get_foreign_keys(table_name)
        if foreign_key["referred_table"] == "ms_markets__asset"
    }
    _insert(engine, table_name, time_index=when, portfolio_identifier=identifier, **assets)


def _portfolio_with(engine, *keys: str) -> tuple[uuid.UUID, str]:
    portfolio = _portfolio(engine)
    identifier = _identifier(engine, portfolio)
    for key in keys:
        _dataset_row(engine, key, identifier)
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


def _exists(engine, portfolio: uuid.UUID) -> bool:
    return bool(
        _rows(engine, "SELECT uid FROM ms_markets__portfolio WHERE uid = :uid", uid=portfolio.hex)
    )


def _deletes(markets) -> list[str]:
    return [sql for sql in markets.statements if sql.lstrip().upper().startswith("DELETE")]


def _reads(markets) -> list[str]:
    return [sql for sql in markets.statements if sql.lstrip().upper().startswith("SELECT")]


def portfolio_markets(sqlite_markets, monkeypatch):
    """The harness, with no MetaTables impact and no delete-after-date call allowed."""

    from metatables import TimeIndexMetaTable

    def refuse_delete_after_date(self, *args, **kwargs):
        raise AssertionError("The portfolio delete must not call delete_after_date.")

    monkeypatch.setattr(TimeIndexMetaTable, "delete_after_date", refuse_delete_after_date)
    monkeypatch.setattr(PortfolioTable, "get_meta_table", classmethod(lambda cls: None))
    _asset(sqlite_markets.engine, "AAA")
    return sqlite_markets


def series_index(table) -> str:
    """The dataset's index that leads with ``portfolio_identifier`` (revisions 0026, 0031)."""

    (name,) = [index.name for index in table.model.__table__.indexes if not index.unique]
    return name
