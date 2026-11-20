"""Revision 0023 adds the portfolio retirement time (ADR 0049)."""

from __future__ import annotations

import importlib

import sqlalchemy as sa
from alembic import command

from tests.support.migrations import _config, _seed_every_table

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0023_portfolio_retired_at"
)


def _portfolio_columns(connection) -> dict[str, dict]:
    return {
        column["name"]: column for column in sa.inspect(connection).get_columns(REVISION.TABLE)
    }


def test_0023_adds_a_nullable_retired_at_and_downgrades_cleanly(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "retired-at.sqlite", "0022")
    with engine.connect() as connection:
        config = _config(connection)
        _seed_every_table(connection, expected_tables=63)
        connection.commit()
        portfolio = sa.Table(REVISION.TABLE, sa.MetaData(), autoload_with=connection)
        before = dict(connection.execute(sa.select(portfolio)).mappings().one())

        command.upgrade(config, "0023")
        columns = _portfolio_columns(connection)
        assert columns[REVISION.COLUMN]["nullable"] is True
        portfolio = sa.Table(REVISION.TABLE, sa.MetaData(), autoload_with=connection)
        after = dict(connection.execute(sa.select(portfolio)).mappings().one())
        assert after.pop(REVISION.COLUMN) is None
        assert after == before

        command.downgrade(config, "0022")
        assert REVISION.COLUMN not in _portfolio_columns(connection)

        command.upgrade(config, "head")
