from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from msm_portfolios.services.portfolio_timestamp_repair import (
    PortfolioTimestampRepairPlan,
    apply_legacy_midnight_portfolio_timestamp_repair,
    build_legacy_midnight_portfolio_timestamp_repair_plan,
    plan_legacy_midnight_portfolio_timestamp_repair,
)


def portfolio(identifier: str = "portfolio", calendar_uid: str = "calendar") -> dict:
    return {"unique_identifier": identifier, "calendar_uid": calendar_uid}


def value(identifier: str, time_index: str, close_time: str | None = None) -> dict:
    return {
        "portfolio_identifier": identifier,
        "time_index": time_index,
        "close_time": close_time,
        "close": 1.0,
    }


def session(local_date: str, closes_at: str, calendar_uid: str = "calendar") -> dict:
    return {
        "calendar_uid": calendar_uid,
        "local_date": local_date,
        "session_label": "regular",
        "closes_at": closes_at,
    }


def test_repair_plan_maps_normal_dst_and_early_closes() -> None:
    rows = [
        value("portfolio", "2026-03-06T00:00:00Z", "2026-03-06T21:00:00Z"),
        value("portfolio", "2026-03-09T00:00:00Z", "2026-03-09T20:00:00Z"),
        value("portfolio", "2026-03-10T00:00:00Z", "2026-03-10T17:00:00Z"),
    ]
    plan = build_legacy_midnight_portfolio_timestamp_repair_plan(
        portfolio_rows=[portfolio()],
        value_rows=rows,
        session_rows=[
            session("2026-03-06", "2026-03-06T21:00:00Z"),
            session("2026-03-09", "2026-03-09T20:00:00Z"),
            session("2026-03-10", "2026-03-10T17:00:00Z"),
        ],
        inspection_end="2026-03-10T17:00:00Z",
        latest_value_rows=[rows[-1]],
    )

    assert plan.can_apply is True
    assert plan.issues == ()
    assert len(plan.rollbacks) == 1
    rollback = plan.rollbacks[0]
    assert rollback.rollback_from == pd.Timestamp("2026-03-06T00:00:00Z")
    assert rollback.legacy_midnight_rows == 3
    assert rollback.tail_rows == 3
    assert rollback.expected_session_closes == (
        pd.Timestamp("2026-03-06T21:00:00Z"),
        pd.Timestamp("2026-03-09T20:00:00Z"),
        pd.Timestamp("2026-03-10T17:00:00Z"),
    )


def test_planner_reads_the_latest_tail_boundary_and_persisted_sessions() -> None:
    calls: list[tuple[str, dict]] = []
    legacy = value(
        "portfolio", "2026-03-06T00:00:00Z", "2026-03-06T21:00:00Z"
    )

    def read_portfolios(**kwargs):
        calls.append(("portfolios", kwargs))
        return [portfolio()]

    def read_values(identifiers, **kwargs):
        calls.append(("values", {"identifiers": identifiers, **kwargs}))
        return [legacy]

    def read_sessions(context, **kwargs):
        calls.append(("sessions", {"context": context, **kwargs}))
        return [session("2026-03-06", "2026-03-06T21:00:00Z")]

    context = object()
    plan = plan_legacy_midnight_portfolio_timestamp_repair(
        "portfolio",
        start="2026-03-06T00:00:00Z",
        end="2026-03-06T23:59:59Z",
        repository_context=context,
        portfolio_rows_reader=read_portfolios,
        portfolio_values_reader=read_values,
        calendar_sessions_reader=read_sessions,
    )

    assert plan.can_apply is True
    assert [name for name, _ in calls] == [
        "portfolios",
        "values",
        "values",
        "sessions",
    ]
    assert calls[1][1]["start"] == pd.Timestamp("2026-03-06T00:00:00Z").to_pydatetime()
    assert calls[1][1]["end"] == pd.Timestamp("2026-03-06T23:59:59Z").to_pydatetime()
    assert calls[1][1]["limit"] == 1000
    assert calls[2][1]["latest_only"] is True
    assert calls[3][1]["start_date"].isoformat() == "2026-03-05"
    assert calls[3][1]["end_date"].isoformat() == "2026-03-07"


@pytest.mark.parametrize(
    ("session_rows", "extra_values", "close_time", "expected_code"),
    [
        ([], [], "2026-03-06T21:00:00Z", "missing_calendar_session"),
        (
            [
                session("2026-03-06", "2026-03-06T20:00:00Z"),
                session("2026-03-06", "2026-03-06T21:00:00Z"),
            ],
            [],
            "2026-03-06T21:00:00Z",
            "ambiguous_calendar_session",
        ),
        (
            [session("2026-03-06", "2026-03-06T21:00:00Z")],
            [value("portfolio", "2026-03-06T21:00:00Z", "2026-03-06T21:00:00Z")],
            "2026-03-06T21:00:00Z",
            "destination_conflict",
        ),
        (
            [session("2026-03-06", "2026-03-06T21:00:00Z")],
            [],
            "2026-03-06T20:00:00Z",
            "close_time_conflict",
        ),
        (
            [session("2026-03-06", "2026-03-06T21:00:00Z")],
            [],
            None,
            "missing_close_time",
        ),
    ],
)
def test_repair_plan_reports_blocking_conditions(
    session_rows,
    extra_values,
    close_time,
    expected_code,
) -> None:
    plan = build_legacy_midnight_portfolio_timestamp_repair_plan(
        portfolio_rows=[portfolio()],
        value_rows=[value("portfolio", "2026-03-06T00:00:00Z", close_time), *extra_values],
        session_rows=session_rows,
    )

    assert plan.can_apply is False
    assert {issue.code for issue in plan.issues} == {expected_code}


def test_repair_plan_is_noop_after_canonical_replay() -> None:
    plan = build_legacy_midnight_portfolio_timestamp_repair_plan(
        portfolio_rows=[portfolio()],
        value_rows=[
            value("portfolio", "2026-03-06T21:00:00Z", "2026-03-06T21:00:00Z")
        ],
        session_rows=[session("2026-03-06", "2026-03-06T21:00:00Z")],
        inspection_end="2026-03-06T21:00:00Z",
        latest_value_rows=[
            value("portfolio", "2026-03-06T21:00:00Z", "2026-03-06T21:00:00Z")
        ],
    )

    assert plan.can_apply is False
    assert plan.rollbacks == ()
    assert plan.issues == ()


@pytest.mark.parametrize(("deleted_count", "matches_plan"), [(1, True), (7, False)])
def test_apply_uses_scoped_tail_delete_and_requires_replay(
    deleted_count,
    matches_plan,
) -> None:
    captured: dict = {}

    class TimeIndexMetaTable:
        def delete_after_date(self, after_date, *, dimension_filters, timeout):
            captured.update(
                after_date=after_date,
                dimension_filters=dimension_filters,
                timeout=timeout,
            )
            return {"deleted_count": deleted_count}

    storage = SimpleNamespace(get_time_index_meta_table=lambda: TimeIndexMetaTable())
    plan = build_legacy_midnight_portfolio_timestamp_repair_plan(
        portfolio_rows=[portfolio()],
        value_rows=[
            value("portfolio", "2026-03-06T00:00:00Z", "2026-03-06T21:00:00Z")
        ],
        session_rows=[session("2026-03-06", "2026-03-06T21:00:00Z")],
        inspection_end="2026-03-06T21:00:00Z",
        latest_value_rows=[
            value("portfolio", "2026-03-06T00:00:00Z", "2026-03-06T21:00:00Z")
        ],
    )

    result = apply_legacy_midnight_portfolio_timestamp_repair(
        plan,
        storage_model=storage,
        timeout=30,
    )

    assert captured == {
        "after_date": pd.Timestamp("2026-03-06T00:00:00Z").to_pydatetime(),
        "dimension_filters": {"portfolio_identifier": ["portfolio"]},
        "timeout": 30,
    }
    assert result["deleted_count"] == deleted_count
    assert result["planned_tail_rows"] == 1
    assert result["delete_count_matches_plan"] is matches_plan
    assert result["replay_required"] is True


def test_apply_refuses_blocked_or_multi_portfolio_plans() -> None:
    blocked = build_legacy_midnight_portfolio_timestamp_repair_plan(
        portfolio_rows=[portfolio()],
        value_rows=[value("portfolio", "2026-03-06T00:00:00Z")],
        session_rows=[],
    )
    with pytest.raises(ValueError, match="blocking issues"):
        apply_legacy_midnight_portfolio_timestamp_repair(blocked)

    first = build_legacy_midnight_portfolio_timestamp_repair_plan(
        portfolio_rows=[portfolio("a", "calendar-a"), portfolio("b", "calendar-b")],
        value_rows=[
            value("a", "2026-03-06T00:00:00Z", "2026-03-06T20:00:00Z"),
            value("b", "2026-03-06T00:00:00Z", "2026-03-06T21:00:00Z"),
        ],
        session_rows=[
            session("2026-03-06", "2026-03-06T20:00:00Z", "calendar-a"),
            session("2026-03-06", "2026-03-06T21:00:00Z", "calendar-b"),
        ],
        inspection_end="2026-03-06T21:00:00Z",
        latest_value_rows=[
            value("a", "2026-03-06T00:00:00Z", "2026-03-06T20:00:00Z"),
            value("b", "2026-03-06T00:00:00Z", "2026-03-06T21:00:00Z"),
        ],
    )
    assert len(first.rollbacks) == 2
    with pytest.raises(ValueError, match="one portfolio at a time"):
        apply_legacy_midnight_portfolio_timestamp_repair(first)


def test_empty_plan_apply_is_an_idempotent_noop() -> None:
    result = apply_legacy_midnight_portfolio_timestamp_repair(
        PortfolioTimestampRepairPlan(inspected_rows=0, rollbacks=(), issues=())
    )

    assert result == {
        "applied": False,
        "deleted_count": 0,
        "replay_required": False,
        "detail": "No legacy midnight portfolio rows require repair.",
    }


def test_repair_plan_blocks_an_uninspected_tail() -> None:
    legacy = value(
        "portfolio", "2026-03-06T00:00:00Z", "2026-03-06T21:00:00Z"
    )
    plan = build_legacy_midnight_portfolio_timestamp_repair_plan(
        portfolio_rows=[portfolio()],
        value_rows=[legacy],
        session_rows=[session("2026-03-06", "2026-03-06T21:00:00Z")],
        inspection_end="2026-03-06T23:59:59Z",
        latest_value_rows=[
            value("portfolio", "2026-03-07T21:00:00Z", "2026-03-07T21:00:00Z")
        ],
    )

    assert plan.can_apply is False
    assert plan.tail_fully_inspected is False
    assert {issue.code for issue in plan.issues} == {"uninspected_tail"}
    with pytest.raises(ValueError, match="blocking issues"):
        apply_legacy_midnight_portfolio_timestamp_repair(plan)
