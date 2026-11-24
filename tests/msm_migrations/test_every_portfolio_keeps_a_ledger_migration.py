"""Revision 0038: every portfolio keeps a ledger (ADR 0065).

The weights lose the rebalance book's ``held_shares`` and ``book_cash``; the asset types
gain ``event_types``, set on the built-in rows.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json

import sqlalchemy as sa
from alembic import command

from tests.support.migrations import _config
from tests.support.sqlite_markets import _asset, _insert, _portfolio

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0038_every_portfolio_keeps_a_ledger"
)
WHEN = dt.datetime(2026, 11, 24, tzinfo=dt.UTC)


def _columns(connection, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table)}


def _seed(engine) -> None:
    for asset_type in ("equity", "bond", "future", "crypto", "my-provider-type"):
        _insert(engine, REVISION.ASSET_TYPE_TABLE, asset_type=asset_type)
    portfolio = _portfolio(engine)
    unique_identifier = (
        sa.Table("ms_markets__portfolio", sa.MetaData(), autoload_with=engine)
    )
    with engine.connect() as connection:
        portfolio_identifier = connection.execute(
            sa.select(unique_identifier.c.unique_identifier).where(
                unique_identifier.c.uid == portfolio.hex
            )
        ).scalar_one()
    _asset(engine, "AAA")
    _insert(
        engine,
        REVISION.WEIGHTS_TABLE,
        time_index=WHEN,
        portfolio_identifier=portfolio_identifier,
        asset_identifier="AAA",
        weight=0.6,
        held_shares=6.0,
        book_cash=400.0,
    )


def test_0038_drops_the_book_columns_and_sets_the_built_in_events(
    tmp_path, sqlite_revisions
) -> None:
    engine = sqlite_revisions.engine(tmp_path / "ledger.sqlite", "0037")
    _seed(engine)
    with engine.connect() as connection:
        command.upgrade(_config(connection), "0038")
        connection.commit()

        weights = connection.exec_driver_sql(
            f"SELECT asset_identifier, weight FROM {REVISION.WEIGHTS_TABLE}"
        ).all()
        events = dict(
            connection.exec_driver_sql(
                f"SELECT asset_type, event_types FROM {REVISION.ASSET_TYPE_TABLE}"
            ).all()
        )
        weights_columns = _columns(connection, REVISION.WEIGHTS_TABLE)

    assert not {"held_shares", "book_cash"} & weights_columns
    assert [tuple(row) for row in weights] == [("AAA", 0.6)]
    assert {asset_type: json.loads(value) for asset_type, value in events.items()} == {
        "equity": ["dividend", "split"],
        "bond": ["coupon", "redemption"],
        "future": ["expiry"],
        "crypto": [],
        "my-provider-type": [],
    }


def test_0038_downgrade_restores_the_schema_of_0037(tmp_path, sqlite_revisions) -> None:
    def schema(connection) -> dict[str, set[str]]:
        return {
            table: _columns(connection, table)
            for table in (REVISION.WEIGHTS_TABLE, REVISION.ASSET_TYPE_TABLE)
        }

    with sqlite_revisions.engine(tmp_path / "at-0037.sqlite", "0037").connect() as connection:
        at_0037 = schema(connection)
    engine = sqlite_revisions.engine(tmp_path / "down.sqlite", "0038")
    with engine.connect() as connection:
        command.downgrade(_config(connection), "0037")
        connection.commit()

        assert schema(connection) == at_0037
