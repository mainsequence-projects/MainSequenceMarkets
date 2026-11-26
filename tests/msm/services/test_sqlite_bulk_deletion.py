"""Bulk deletes that delete what may go and report the rest, on SQLite (issue 128).

`msm.services.bulk_deletion.bulk_delete_rows` serves the asset-category and
portfolio-group bulk deletes, through MetaTables' own server code for the local runtime.
"""

from __future__ import annotations

import uuid

import pytest

from msm.models import PortfolioGroupTable
from msm.services.bulk_deletion import bulk_delete_rows
from tests.support.sqlite_markets import _count, _insert
from tests.support.unanswered_calls import unanswered_write

APPLICATION_TABLE = "provider_ns__groupnotes"


def _group(engine) -> str:
    return str(uuid.UUID(_insert(engine, "ms_markets__portfoliogroup")["uid"]))


def _delete(markets, uids, **kwargs):
    return bulk_delete_rows(
        markets.context,
        model=PortfolioGroupTable,
        uids=uids,
        label="Portfolio group",
        plural="portfolio groups",
        **kwargs,
    )


def _deletes(markets) -> list[str]:
    return [sql for sql in markets.statements if sql.lstrip().upper().startswith("DELETE")]


def test_what_exists_goes_in_one_statement_and_the_rest_is_reported(sqlite_markets) -> None:
    first, second = _group(sqlite_markets.engine), _group(sqlite_markets.engine)
    missing = str(uuid.uuid4())
    sqlite_markets.statements.clear()

    result = _delete(sqlite_markets, [first, missing, second, first])

    assert len(_deletes(sqlite_markets)) == 1
    assert [item["uid"] for item in result["deleted"]] == [first, second]
    assert result["failed"] == [{"uid": missing, "detail": f"Portfolio group {missing} was not found."}]
    assert result["detail"] == "Deleted 2 portfolio groups. 1 could not be deleted."
    assert _count(sqlite_markets.engine, "ms_markets__portfoliogroup") == 0


def test_a_key_the_database_applies_keeps_only_its_row(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    kept, deleted = _group(engine), _group(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {APPLICATION_TABLE} (group_uid CHAR(32) NOT NULL REFERENCES "
            "ms_markets__portfoliogroup (uid) ON DELETE RESTRICT)"
        )
        connection.exec_driver_sql(
            f"INSERT INTO {APPLICATION_TABLE} VALUES (?)", (uuid.UUID(kept).hex,)
        )

    result = _delete(sqlite_markets, [kept, deleted])

    # The selection's statement is refused and deletes nothing; each group then goes on
    # its own, and only the one the key holds stays.
    assert [item["uid"] for item in result["deleted"]] == [deleted]
    (failure,) = result["failed"]
    assert failure["uid"] == kept and "FOREIGN KEY constraint failed" in failure["detail"]
    assert _count(engine, "ms_markets__portfoliogroup") == 1


def test_a_blocker_on_the_whole_table_keeps_every_row(sqlite_markets) -> None:
    first = _group(sqlite_markets.engine)
    sqlite_markets.statements.clear()

    result = _delete(sqlite_markets, [first], table_blockers=["You cannot write this table."])

    assert result["deleted"] == [] and _deletes(sqlite_markets) == []
    assert "You cannot write this table." in result["failed"][0]["detail"]
    assert _count(sqlite_markets.engine, "ms_markets__portfoliogroup") == 1


@pytest.mark.parametrize("committed", [True, False])
def test_a_delete_without_an_answer_never_reports_a_row_it_cannot_confirm(
    sqlite_markets, monkeypatch, committed
) -> None:
    """Issue 151: nothing read the rows before the delete, so a row that is gone after an
    unanswered delete was deleted by it or never existed, and is not reported deleted."""

    engine = sqlite_markets.engine
    first, second = _group(engine), _group(engine)
    missing = str(uuid.uuid4())
    unanswered_write(monkeypatch, committed=committed)

    result = _delete(sqlite_markets, [first, missing, second])

    assert result["deleted"] == []
    assert result["detail"] == "No portfolio groups were deleted. 3 could not be deleted."
    if committed:
        assert result["failed"] == [
            {
                "uid": uid,
                "detail": (
                    f"Portfolio group {uid} is gone: MetaTables did not answer its delete, so "
                    "this call deleted it, or it did not exist."
                ),
            }
            for uid in (first, missing, second)
        ]
        assert _count(engine, "ms_markets__portfoliogroup") == 0
    else:
        unknown = (
            "Portfolio group {}: the outcome of its delete is unknown. MetaTables did not "
            "answer it, and the portfolio group still existed when read again; the delete "
            "may still finish. The call may be retried."
        )
        assert result["failed"] == [
            {"uid": first, "detail": unknown.format(first)},
            {"uid": missing, "detail": f"Portfolio group {missing} was not found."},
            {"uid": second, "detail": unknown.format(second)},
        ]
        assert _count(engine, "ms_markets__portfoliogroup") == 2
