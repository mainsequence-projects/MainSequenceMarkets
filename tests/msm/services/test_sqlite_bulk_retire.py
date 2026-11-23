"""Retiring several portfolios in one call, on SQLite (issue 124, ADR 0049).

`msm.services.bulk_retire_portfolio_records` runs through MetaTables' own server code for
the local runtime: one update checks each portfolio's current targets in the same
statement, and one read counts them afterwards.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from msm.services import bulk_retire_portfolio_records
from tests.support.sqlite_markets import _account, _portfolio, _portfolio_position, _write_target


def _retired_at(engine, portfolio: uuid.UUID):
    with engine.connect() as connection:
        return connection.execute(
            sa.text("SELECT retired_at FROM ms_markets__portfolio WHERE uid = :uid"),
            {"uid": portfolio.hex},
        ).scalar_one()


def test_what_may_be_retired_is_retired_and_the_rest_is_reported(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    live, targeted, retired = _portfolio(engine), _portfolio(engine), _portfolio(engine, retired=True)
    _write_target(sqlite_markets, _account(engine), [_portfolio_position(targeted)])
    missing = uuid.uuid4()
    before = _retired_at(engine, retired)
    sqlite_markets.statements.clear()

    result = bulk_retire_portfolio_records(
        sqlite_markets.context, uids=[live, targeted, retired, missing, live]
    )

    # One update and one read, whatever the number of portfolios.
    assert len(sqlite_markets.statements) == 2
    assert [row["uid"] for row in map(_canonical, result["retired"])] == [str(live), str(retired)]
    assert [item["uid"] for item in result["failed"]] == [str(targeted), str(missing)]
    assert "1 account's current target names it" in result["failed"][0]["detail"]
    assert result["failed"][1]["detail"] == f"Portfolio {missing} was not found."
    assert _retired_at(engine, live) is not None
    assert _retired_at(engine, targeted) is None
    assert _retired_at(engine, retired) == before


def test_a_target_written_during_the_update_undoes_that_retirement(sqlite_markets, monkeypatch) -> None:
    from msm.repositories import accounts as account_repository

    engine = sqlite_markets.engine
    overtaken, kept = _portfolio(engine), _portfolio(engine)
    read = account_repository.read_portfolios_current_targets

    def read_after_a_concurrent_target(context, **kwargs):
        # A target write that committed while the update ran: the update did not see it,
        # the read after it does. (A target write after the update refuses the retired
        # portfolio, ADR 0049 decision 3, so it is reported here.)
        result = read(context, **kwargs)
        for row in result["rows"]:
            if str(uuid.UUID(str(row["uid"]))) == str(overtaken):
                row["current_target_count"] = 1
        return result

    monkeypatch.setattr(
        account_repository, "read_portfolios_current_targets", read_after_a_concurrent_target
    )

    result = bulk_retire_portfolio_records(sqlite_markets.context, uids=[overtaken, kept])

    assert [_canonical(row)["uid"] for row in result["retired"]] == [str(kept)]
    assert [item["uid"] for item in result["failed"]] == [str(overtaken)]
    assert _retired_at(engine, overtaken) is None
    assert _retired_at(engine, kept) is not None


def _canonical(row: dict) -> dict:
    return {**row, "uid": str(uuid.UUID(str(row["uid"])))}
