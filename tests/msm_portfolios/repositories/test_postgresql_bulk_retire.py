"""Retiring several portfolios in one call, on PostgreSQL (issue 124, ADR 0049).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost to run this test; it is skipped otherwise. The update checks each
portfolio's current targets in a subquery correlated to the updated row, and the read
after it counts them per portfolio: SQL that SQLite compiles differently.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa

from msm.models import AccountTable
from msm.repositories.accounts import replace_account_target_positions_snapshot
from msm.services import bulk_retire_portfolio_records
from tests.support.postgresql_portfolios import _insert, _portfolio

WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)


@pytest.fixture
def markets(postgresql_markets, monkeypatch):
    monkeypatch.setattr(AccountTable, "get_meta_table", classmethod(lambda cls: None))
    return postgresql_markets


def _retired_at(engine, portfolio: uuid.UUID):
    with engine.connect() as connection:
        return connection.execute(
            sa.text("SELECT retired_at FROM ms_markets__portfolio WHERE uid = :uid"),
            {"uid": portfolio},
        ).scalar_one()


def test_the_selection_is_retired_in_one_update_and_one_read(markets) -> None:
    engine, context, operations = markets
    (live, _), (targeted, _) = _portfolio(engine), _portfolio(engine)
    account = _insert(engine, "ms_markets__account", is_paper=True, account_is_active=True)
    replace_account_target_positions_snapshot(
        context,
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        account_uid=account["uid"],
        account_name="PostgreSQL account",
        target_positions_date=WHEN,
        positions=[
            {
                "target_type": "portfolio",
                "target_uid": targeted,
                "portfolio_uid": targeted,
                "weight_notional_exposure": 0.4,
                "metadata_json": {},
            }
        ],
        overwrite=False,
    )
    operations.clear()

    result = bulk_retire_portfolio_records(context, uids=[live, targeted])

    assert operations == ["update", "read"]
    assert [str(uuid.UUID(str(row["uid"]))) for row in result["retired"]] == [str(live)]
    assert [item["uid"] for item in result["failed"]] == [str(targeted)]
    assert "1 account's current target names it" in result["failed"][0]["detail"]
    assert _retired_at(engine, live) is not None
    assert _retired_at(engine, targeted) is None
