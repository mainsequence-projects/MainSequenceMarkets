"""Revision 0033 drops the portfolio dataset catalog (ADR 0060, decision 8)."""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic import command

from tests.support.migrations import _config
from tests.support.sqlite_markets import _insert

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0033_drop_portfolio_dataset_catalog"
)


def _rows(connection, table: str) -> list[dict]:
    reflected = sa.Table(table, sa.MetaData(), autoload_with=connection)
    return [dict(row) for row in connection.execute(sa.select(reflected)).mappings()]


def test_0033_drops_the_catalog_and_the_signal_table_uid_and_keeps_every_other_row(
    tmp_path, sqlite_revisions
) -> None:
    engine = sqlite_revisions.engine(tmp_path / "catalog.sqlite", "0032")
    with engine.connect() as connection:
        config = _config(connection)
        calendar = _insert(engine, "ms_markets__calendar")
        _insert(engine, "ms_markets__signalmetadata", signal_uid="signal", meta_table_uid="table")
        portfolio = _insert(
            engine,
            "ms_markets__portfolio",
            unique_identifier="portfolio",
            calendar_uid=calendar["uid"],
            signal_uid="signal",
        )
        _insert(
            engine,
            REVISION.CATALOG_TABLE,
            portfolio_uid=portfolio["uid"],
            values_meta_table_uid="table",
            population_state="unavailable",
            row_count=None,
            earliest_time_index=None,
            latest_time_index=None,
            error_code=None,
            error_message=None,
        )
        portfolios = _rows(connection, "ms_markets__portfolio")
        signals = [
            {key: value for key, value in row.items() if key != REVISION.SIGNAL_COLUMN}
            for row in _rows(connection, REVISION.SIGNAL_TABLE)
        ]

        command.upgrade(config, "0033")
        assert REVISION.CATALOG_TABLE not in sa.inspect(connection).get_table_names()
        assert REVISION.SIGNAL_COLUMN not in {
            column["name"] for column in sa.inspect(connection).get_columns(REVISION.SIGNAL_TABLE)
        }
        assert _rows(connection, "ms_markets__portfolio") == portfolios
        assert _rows(connection, REVISION.SIGNAL_TABLE) == signals

        command.downgrade(config, "0032")
        assert _rows(connection, REVISION.CATALOG_TABLE) == []
        assert [
            row[REVISION.SIGNAL_COLUMN] for row in _rows(connection, REVISION.SIGNAL_TABLE)
        ] == [None]
    engine.dispose()
