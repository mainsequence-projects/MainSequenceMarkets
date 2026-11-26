"""The portfolio-group membership bulk delete, on SQLite (issue 152).

`msm.services.portfolios.bulk_delete_portfolio_group_memberships` deletes the whole
selection in one statement, which the database resolves, and answers the bulk-delete
envelope, through MetaTables' own server code for the local runtime.
"""

from __future__ import annotations

import uuid

from msm.repositories.base import UnansweredReadError
from msm.services.bulk_deletion import (
    gone_after_unanswered_delete_reason,
    unconfirmed_delete_reason,
    unknown_delete_reason,
)
from msm.services.portfolios import bulk_delete_portfolio_group_memberships
from tests.support.sqlite_markets import _count, _insert, _insert_many
from tests.support.unanswered_calls import unanswered_reads, unanswered_write

MEMBERSHIPS = "ms_markets__portfoliogroupmembership"


def _uid(value) -> str:
    return str(uuid.UUID(str(value)))


def _group(engine) -> str:
    return _uid(_insert(engine, "ms_markets__portfoliogroup")["uid"])


def _portfolios(engine, count: int) -> list[str]:
    calendar = _insert(engine, "ms_markets__calendar")
    rows = _insert_many(
        engine,
        "ms_markets__portfolio",
        [
            {"calendar_uid": calendar["uid"], "unique_identifier": f"portfolio-{index}"}
            for index in range(count)
        ],
    )
    return [_uid(row["uid"]) for row in rows]


def _label(uid: str) -> str:
    return f"Portfolio group membership {uid}"


def _unreturned(uid: str) -> str:
    return (
        f"{_label(uid)}: it no longer exists. This call cannot tell whether it deleted it or "
        "it never existed."
    )


def _memberships(engine, group: str, portfolios: list[str]) -> list[str]:
    rows = _insert_many(
        engine,
        MEMBERSHIPS,
        [
            {"portfolio_group_uid": uuid.UUID(group).hex, "portfolio_uid": uuid.UUID(portfolio).hex}
            for portfolio in portfolios
        ],
    )
    return [_uid(row["uid"]) for row in rows]


def test_a_group_past_5000_memberships_goes_whole_in_one_statement(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    selected, other = _group(engine), _group(engine)
    portfolios = _portfolios(engine, 5_001)
    memberships = _memberships(engine, selected, portfolios)
    _memberships(engine, other, portfolios[:1])
    sqlite_markets.statements.clear()

    result = bulk_delete_portfolio_group_memberships(
        sqlite_markets.context, portfolio_group_uids=[selected]
    )

    # The database resolves the selection: one statement, no read before it, no cap.
    (statement,) = sqlite_markets.statements
    assert statement.lstrip().upper().startswith("DELETE")
    assert result["detail"] == "Deleted 5001 portfolio group memberships."
    assert result["deleted_count"] == 5_001
    assert sorted(item["uid"] for item in result["deleted"]) == sorted(memberships)
    assert result["failed"] == []
    assert _count(engine, MEMBERSHIPS) == 1


def test_uids_and_both_filters_select_together_and_a_missing_uid_fails(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    first_group, second_group = _group(engine), _group(engine)
    first, second, third = _portfolios(engine, 3)
    in_both_filters, other_portfolio = _memberships(engine, first_group, [first, second])
    other_group, by_uid = _memberships(engine, second_group, [first, third])
    missing = str(uuid.uuid4())
    sqlite_markets.statements.clear()

    result = bulk_delete_portfolio_group_memberships(
        sqlite_markets.context,
        uids=[by_uid, missing, by_uid],
        portfolio_group_uids=[first_group],
        portfolio_uids=[first],
    )

    assert len(sqlite_markets.statements) == 1
    assert {item["uid"] for item in result["deleted"]} == {in_both_filters, by_uid}
    assert result["failed"] == [
        {"uid": missing, "detail": f"Portfolio group membership {missing} was not found."}
    ]
    assert result["detail"] == "Deleted 2 portfolio group memberships. 1 could not be deleted."
    assert _count(engine, MEMBERSHIPS) == 2


def test_past_10000_deletes_all_and_counts_them_though_only_10000_return(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    group = _group(engine)
    memberships = _memberships(engine, group, _portfolios(engine, 10_050))
    missing = str(uuid.uuid4())

    result = bulk_delete_portfolio_group_memberships(
        sqlite_markets.context, uids=[missing], portfolio_group_uids=[group]
    )

    # MetaTables returns at most 10,000 rows of a statement and counts every row deleted.
    assert result["deleted_count"] == 10_050
    assert len(result["deleted"]) == 10_000
    assert {item["uid"] for item in result["deleted"]} <= set(memberships)
    # A selected uid it did not return is gone, and the call cannot tell whether it was
    # ever there.
    assert result["failed"] == [{"uid": missing, "detail": _unreturned(missing)}]
    assert result["detail"] == (
        "Deleted 10050 portfolio group memberships; MetaTables returned 10000 of them, which "
        "`deleted` lists. The call cannot tell the outcome of 1 selected."
    )
    assert _count(engine, MEMBERSHIPS) == 0


def test_an_unanswered_delete_that_committed_confirms_no_membership(
    sqlite_markets, monkeypatch
) -> None:
    engine = sqlite_markets.engine
    group = _group(engine)
    (by_uid, _by_group) = _memberships(engine, group, _portfolios(engine, 2))
    missing = str(uuid.uuid4())
    unanswered_write(monkeypatch, committed=True)

    result = bulk_delete_portfolio_group_memberships(
        sqlite_markets.context, uids=[by_uid, missing], portfolio_group_uids=[group]
    )

    # Nothing matches any more, which also holds for a selection that matched nothing, so
    # the call confirms no delete.
    assert result["deleted"] == [] and result["deleted_count"] == 0
    # The reasons are the other bulk deletes' (issue 151).
    assert result["failed"] == [
        {"uid": by_uid, "detail": gone_after_unanswered_delete_reason(_label(by_uid))},
        {"uid": missing, "detail": gone_after_unanswered_delete_reason(_label(missing))},
    ]
    assert result["detail"] == (
        "MetaTables did not answer the delete, and nothing matching the selection remains; "
        "the call cannot tell how many portfolio group memberships it deleted."
    )
    assert _count(engine, MEMBERSHIPS) == 0


def test_an_unanswered_delete_reports_each_membership_still_matching(
    sqlite_markets, monkeypatch
) -> None:
    engine = sqlite_markets.engine
    selected, other = _group(engine), _group(engine)
    first, second = _portfolios(engine, 2)
    by_group = _memberships(engine, selected, [first, second])
    (by_uid,) = _memberships(engine, other, [first])
    missing = str(uuid.uuid4())
    unanswered_write(monkeypatch, committed=False)

    result = bulk_delete_portfolio_group_memberships(
        sqlite_markets.context, uids=[by_uid, missing], portfolio_group_uids=[selected]
    )

    assert result["deleted"] == [] and result["deleted_count"] == 0
    failed = {item["uid"]: item["detail"] for item in result["failed"]}
    assert [item["uid"] for item in result["failed"]][:2] == [by_uid, missing]
    assert set(failed) == {by_uid, missing, *by_group}
    assert failed[missing] == f"Portfolio group membership {missing} was not found."
    for uid in (by_uid, *by_group):
        assert failed[uid] == unknown_delete_reason(_label(uid), noun="Portfolio group membership")
    assert "`failed` lists them" in result["detail"]
    assert _count(engine, MEMBERSHIPS) == 3


def test_an_unanswered_delete_whose_read_fails_too_leaves_each_uid_unknown(
    sqlite_markets, monkeypatch
) -> None:
    engine = sqlite_markets.engine
    group = _group(engine)
    (by_uid,) = _memberships(engine, group, _portfolios(engine, 1))
    unanswered_write(monkeypatch, committed=False)
    unanswered_reads(monkeypatch)

    result = bulk_delete_portfolio_group_memberships(
        sqlite_markets.context, uids=[by_uid], portfolio_group_uids=[group]
    )

    assert result["deleted"] == [] and result["deleted_count"] == 0
    (failure,) = result["failed"]
    assert failure["uid"] == by_uid
    assert failure["detail"] == unconfirmed_delete_reason(
        _label(by_uid), noun="Portfolio group membership", error=UnansweredReadError("")
    )
    assert "cannot tell which portfolio group memberships it deleted" in result["detail"]


def test_an_empty_selection_sends_nothing(sqlite_markets) -> None:
    sqlite_markets.statements.clear()

    result = bulk_delete_portfolio_group_memberships(sqlite_markets.context)

    assert sqlite_markets.statements == []
    assert result == {
        "detail": "No portfolio group memberships were deleted.",
        "deleted_count": 0,
        "deleted": [],
        "failed": [],
    }
