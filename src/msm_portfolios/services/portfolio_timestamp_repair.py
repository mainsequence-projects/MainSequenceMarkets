"""Plan and apply rollback-based repair for legacy midnight portfolio values."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from msm.api.base import operation_result_rows
from msm.api.portfolios import Portfolio
from msm.repositories.base import MarketsOperationContext
from msm.repositories.calendars import search_calendar_sessions
from msm_portfolios.data_nodes.portfolios.storage import PortfoliosStorage

from .portfolio_reads import portfolio_values

PortfolioRowsReader = Callable[..., Sequence[Mapping[str, Any]]]
PortfolioValuesReader = Callable[..., Sequence[Mapping[str, Any]]]
CalendarSessionsReader = Callable[..., Mapping[str, Any] | Sequence[Mapping[str, Any]]]

_PORTFOLIO_VALUE_PAGE_SIZE = 1000
_SESSION_QUERY_WINDOW_DAYS = 366 * 2


@dataclass(frozen=True)
class PortfolioTimestampRepairIssue:
    """One condition that must be resolved before rollback can be applied."""

    code: str
    portfolio_identifier: str
    time_index: pd.Timestamp | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "portfolio_identifier": self.portfolio_identifier,
            "time_index": None if self.time_index is None else self.time_index.isoformat(),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PortfolioTimestampRollback:
    """A scoped rollback boundary whose tail must be deterministically replayed."""

    portfolio_identifier: str
    calendar_uid: str
    rollback_from: pd.Timestamp
    legacy_midnight_rows: int
    tail_rows: int
    expected_session_closes: tuple[pd.Timestamp, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "portfolio_identifier": self.portfolio_identifier,
            "calendar_uid": self.calendar_uid,
            "rollback_from": self.rollback_from.isoformat(),
            "legacy_midnight_rows": self.legacy_midnight_rows,
            "tail_rows": self.tail_rows,
            "expected_session_closes": [value.isoformat() for value in self.expected_session_closes],
        }


@dataclass(frozen=True)
class PortfolioTimestampRepairPlan:
    """Read-only result of validating legacy midnight rows against sessions."""

    inspected_rows: int
    rollbacks: tuple[PortfolioTimestampRollback, ...]
    issues: tuple[PortfolioTimestampRepairIssue, ...]
    inspection_end: pd.Timestamp | None = None
    tail_fully_inspected: bool = False

    @property
    def can_apply(self) -> bool:
        return bool(self.rollbacks) and self.tail_fully_inspected and not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": True,
            "inspected_rows": self.inspected_rows,
            "inspection_end": (
                None if self.inspection_end is None else self.inspection_end.isoformat()
            ),
            "tail_fully_inspected": self.tail_fully_inspected,
            "can_apply": self.can_apply,
            "rollback_count": len(self.rollbacks),
            "issue_count": len(self.issues),
            "rollbacks": [value.to_dict() for value in self.rollbacks],
            "issues": [value.to_dict() for value in self.issues],
        }


def plan_legacy_midnight_portfolio_timestamp_repair(
    portfolio_identifiers: str | Sequence[str],
    *,
    start: dt.datetime | dt.date | str,
    end: dt.datetime | dt.date | str,
    session_label: str = "regular",
    repository_context: MarketsOperationContext | None = None,
    portfolio_rows_reader: PortfolioRowsReader | None = None,
    portfolio_values_reader: PortfolioValuesReader | None = None,
    calendar_sessions_reader: CalendarSessionsReader | None = None,
) -> PortfolioTimestampRepairPlan:
    """Load a bounded repair window and return a mutation-free repair plan."""

    identifiers = _normalize_identifiers(portfolio_identifiers)
    start_timestamp = _utc_timestamp(start, field_name="start")
    end_timestamp = _utc_timestamp(end, field_name="end")
    if start_timestamp > end_timestamp:
        raise ValueError("start must be before or equal to end.")
    if not session_label.strip():
        raise ValueError("session_label must be a non-empty string.")

    context = repository_context or Portfolio._active_context()
    row_reader = portfolio_rows_reader or _read_portfolio_rows
    value_reader = portfolio_values_reader or portfolio_values
    session_reader = calendar_sessions_reader or search_calendar_sessions
    portfolio_rows = [dict(row) for row in row_reader(identifiers=identifiers)]
    value_rows: list[dict[str, Any]] = []
    for identifier in identifiers:
        page_start = start_timestamp
        while page_start <= end_timestamp:
            page = [
                dict(row)
                for row in value_reader(
                    identifier,
                    start=page_start.to_pydatetime(),
                    end=end_timestamp.to_pydatetime(),
                    limit=_PORTFOLIO_VALUE_PAGE_SIZE,
                    repository_context=context,
                )
            ]
            value_rows.extend(page)
            if len(page) < _PORTFOLIO_VALUE_PAGE_SIZE:
                break
            page_start = _utc_timestamp(
                page[-1].get("time_index"), field_name="time_index"
            ) + pd.Timedelta(1, unit="ns")
    latest_value_rows = value_reader(
        identifiers,
        latest_only=True,
        repository_context=context,
    )

    calendar_uids = sorted(
        {
            str(row["calendar_uid"])
            for row in portfolio_rows
            if row.get("calendar_uid") not in (None, "")
        }
    )
    session_rows: list[dict[str, Any]] = []
    local_start = start_timestamp.date() - dt.timedelta(days=1)
    local_end = end_timestamp.date() + dt.timedelta(days=1)
    for calendar_uid in calendar_uids:
        for window_start, window_end in _date_windows(local_start, local_end):
            result = session_reader(
                context,
                calendar_uid=calendar_uid,
                start_date=window_start,
                end_date=window_end,
                session_label=session_label,
            )
            session_rows.extend(_result_rows(result))

    return build_legacy_midnight_portfolio_timestamp_repair_plan(
        portfolio_rows=portfolio_rows,
        value_rows=value_rows,
        session_rows=session_rows,
        session_label=session_label,
        inspection_end=end_timestamp,
        latest_value_rows=latest_value_rows,
    )


def build_legacy_midnight_portfolio_timestamp_repair_plan(
    *,
    portfolio_rows: Sequence[Mapping[str, Any]],
    value_rows: Sequence[Mapping[str, Any]],
    session_rows: Sequence[Mapping[str, Any]],
    session_label: str = "regular",
    inspection_end: dt.datetime | dt.date | str | pd.Timestamp | None = None,
    latest_value_rows: Sequence[Mapping[str, Any]] = (),
) -> PortfolioTimestampRepairPlan:
    """Validate midnight rows and calculate portfolio-scoped rollback boundaries."""

    portfolios = {
        str(row["unique_identifier"]): str(row["calendar_uid"])
        for row in portfolio_rows
        if row.get("unique_identifier") not in (None, "")
        and row.get("calendar_uid") not in (None, "")
    }
    sessions_by_bucket: dict[tuple[str, pd.Timestamp], set[pd.Timestamp]] = defaultdict(set)
    for row in session_rows:
        if str(row.get("session_label", session_label)) != session_label:
            continue
        calendar_uid = row.get("calendar_uid")
        closes_at = row.get("closes_at")
        if calendar_uid in (None, "") or closes_at in (None, ""):
            continue
        close_timestamp = _utc_timestamp(closes_at, field_name="closes_at")
        sessions_by_bucket[(str(calendar_uid), close_timestamp.floor("D"))].add(close_timestamp)

    normalized_values = [_normalize_value_row(row) for row in value_rows]
    existing_coordinates = {
        (row["portfolio_identifier"], row["time_index"]) for row in normalized_values
    }
    ready_by_portfolio: dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]] = defaultdict(list)
    issues: list[PortfolioTimestampRepairIssue] = []

    for row in normalized_values:
        portfolio_identifier = row["portfolio_identifier"]
        old_timestamp = row["time_index"]
        if old_timestamp != old_timestamp.floor("D"):
            continue

        calendar_uid = portfolios.get(portfolio_identifier)
        if calendar_uid is None:
            issues.append(
                PortfolioTimestampRepairIssue(
                    code="missing_portfolio_calendar",
                    portfolio_identifier=portfolio_identifier,
                    time_index=old_timestamp,
                    detail="Portfolio identity or calendar_uid is unavailable.",
                )
            )
            continue

        candidate_closes = sorted(sessions_by_bucket[(calendar_uid, old_timestamp)])
        if not candidate_closes:
            issues.append(
                PortfolioTimestampRepairIssue(
                    code="missing_calendar_session",
                    portfolio_identifier=portfolio_identifier,
                    time_index=old_timestamp,
                    detail=(
                        "No persisted session close maps to this UTC daily bucket "
                        f"for calendar {calendar_uid}."
                    ),
                )
            )
            continue
        if len(candidate_closes) > 1:
            issues.append(
                PortfolioTimestampRepairIssue(
                    code="ambiguous_calendar_session",
                    portfolio_identifier=portfolio_identifier,
                    time_index=old_timestamp,
                    detail=(
                        "Multiple persisted session closes map to this UTC daily bucket: "
                        + ", ".join(value.isoformat() for value in candidate_closes)
                    ),
                )
            )
            continue

        expected_close = candidate_closes[0]
        if expected_close == old_timestamp:
            continue
        close_time = row["close_time"]
        if close_time is None:
            issues.append(
                PortfolioTimestampRepairIssue(
                    code="missing_close_time",
                    portfolio_identifier=portfolio_identifier,
                    time_index=old_timestamp,
                    detail=(
                        "Legacy midnight rows require close_time evidence before their "
                        "persisted session mapping can be approved."
                    ),
                )
            )
            continue
        if close_time != expected_close:
            issues.append(
                PortfolioTimestampRepairIssue(
                    code="close_time_conflict",
                    portfolio_identifier=portfolio_identifier,
                    time_index=old_timestamp,
                    detail=(
                        f"Stored close_time {close_time.isoformat()} does not match "
                        f"persisted session close {expected_close.isoformat()}."
                    ),
                )
            )
            continue
        if (portfolio_identifier, expected_close) in existing_coordinates:
            issues.append(
                PortfolioTimestampRepairIssue(
                    code="destination_conflict",
                    portfolio_identifier=portfolio_identifier,
                    time_index=old_timestamp,
                    detail=(
                        "A canonical portfolio value already exists at persisted session close "
                        f"{expected_close.isoformat()}."
                    ),
                )
            )
            continue
        ready_by_portfolio[portfolio_identifier].append((old_timestamp, expected_close))

    rollbacks: list[PortfolioTimestampRollback] = []
    for portfolio_identifier, candidates in sorted(ready_by_portfolio.items()):
        rollback_from = min(value[0] for value in candidates)
        tail_rows = sum(
            row["portfolio_identifier"] == portfolio_identifier
            and row["time_index"] >= rollback_from
            for row in normalized_values
        )
        rollbacks.append(
            PortfolioTimestampRollback(
                portfolio_identifier=portfolio_identifier,
                calendar_uid=portfolios[portfolio_identifier],
                rollback_from=rollback_from,
                legacy_midnight_rows=len(candidates),
                tail_rows=tail_rows,
                expected_session_closes=tuple(sorted(value[1] for value in candidates)),
            )
        )

    normalized_inspection_end = (
        None
        if inspection_end is None
        else _utc_timestamp(inspection_end, field_name="inspection_end")
    )
    latest_by_portfolio = {
        row["portfolio_identifier"]: row["time_index"]
        for row in (_normalize_value_row(value) for value in latest_value_rows)
    }
    rollback_identifiers = {rollback.portfolio_identifier for rollback in rollbacks}
    tail_fully_inspected = bool(rollbacks) and normalized_inspection_end is not None
    for portfolio_identifier in sorted(rollback_identifiers):
        latest_timestamp = latest_by_portfolio.get(portfolio_identifier)
        if normalized_inspection_end is None or latest_timestamp is None:
            tail_fully_inspected = False
            issues.append(
                PortfolioTimestampRepairIssue(
                    code="unverified_tail_boundary",
                    portfolio_identifier=portfolio_identifier,
                    time_index=latest_timestamp,
                    detail=(
                        "The dry run must include an inspection end and the latest persisted "
                        "portfolio value before an inclusive tail rollback can be applied."
                    ),
                )
            )
            continue
        if latest_timestamp > normalized_inspection_end:
            tail_fully_inspected = False
            issues.append(
                PortfolioTimestampRepairIssue(
                    code="uninspected_tail",
                    portfolio_identifier=portfolio_identifier,
                    time_index=latest_timestamp,
                    detail=(
                        "The latest persisted portfolio value is beyond the inspected window. "
                        "Extend --end through this timestamp before applying the tail rollback."
                    ),
                )
            )

    return PortfolioTimestampRepairPlan(
        inspected_rows=len(normalized_values),
        rollbacks=tuple(rollbacks),
        issues=tuple(issues),
        inspection_end=normalized_inspection_end,
        tail_fully_inspected=tail_fully_inspected,
    )


def apply_legacy_midnight_portfolio_timestamp_repair(
    plan: PortfolioTimestampRepairPlan,
    *,
    storage_model: type = PortfoliosStorage,
    timeout: int | float | tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Apply one validated scoped tail rollback and require updater replay."""

    if plan.issues:
        codes = ", ".join(sorted({issue.code for issue in plan.issues}))
        raise ValueError(f"Repair plan contains blocking issues: {codes}.")
    if not plan.rollbacks:
        return {
            "applied": False,
            "deleted_count": 0,
            "replay_required": False,
            "detail": "No legacy midnight portfolio rows require repair.",
        }
    if not plan.tail_fully_inspected:
        raise ValueError(
            "Repair plan does not prove that the full persisted tail was inspected."
        )
    if len(plan.rollbacks) != 1:
        raise ValueError(
            "Apply legacy portfolio timestamp repair to one portfolio at a time "
            "so each scoped rollback is independently auditable."
        )

    rollback = plan.rollbacks[0]
    time_index_meta_table = storage_model.get_time_index_meta_table()
    if time_index_meta_table is None:
        raise RuntimeError(
            f"{storage_model.__name__} is not attached to a backend TimeIndexMetaTable."
        )
    result = time_index_meta_table.delete_after_date(
        rollback.rollback_from.to_pydatetime(),
        dimension_filters={"portfolio_identifier": [rollback.portfolio_identifier]},
        timeout=timeout,
    )
    deleted_count = int(result["deleted_count"])
    delete_count_matches_plan = deleted_count == rollback.tail_rows
    if delete_count_matches_plan:
        detail = (
            "Scoped portfolio value tail deleted. Rerun the portfolio workflow "
            "with the migrated configuration to rebuild canonical timestamps."
        )
    else:
        detail = (
            "Scoped portfolio value tail deleted, but its row count changed after "
            "planning. A concurrent writer may have modified the tail. Keep writers "
            "paused and rerun the migrated portfolio workflow before any further repair."
        )
    return {
        "applied": True,
        "deleted_count": deleted_count,
        "planned_tail_rows": rollback.tail_rows,
        "delete_count_matches_plan": delete_count_matches_plan,
        "portfolio_identifier": rollback.portfolio_identifier,
        "rollback_from": rollback.rollback_from.isoformat(),
        "replay_required": True,
        "detail": detail,
    }


def _read_portfolio_rows(*, identifiers: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for identifier in identifiers:
        matches = Portfolio.filter(unique_identifier=identifier, limit=2)
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one Portfolio row for {identifier!r}; found {len(matches)}."
            )
        rows.append(matches[0].model_dump())
    return rows


def _normalize_identifiers(values: str | Sequence[str]) -> tuple[str, ...]:
    raw_values = [values] if isinstance(values, str) else list(values)
    identifiers = tuple(dict.fromkeys(str(value).strip() for value in raw_values))
    if not identifiers or any(not value for value in identifiers):
        raise ValueError("portfolio_identifiers must contain non-empty strings.")
    return identifiers


def _normalize_value_row(row: Mapping[str, Any]) -> dict[str, Any]:
    portfolio_identifier = str(row.get("portfolio_identifier", "")).strip()
    if not portfolio_identifier:
        raise ValueError("Portfolio value row is missing portfolio_identifier.")
    time_index = _utc_timestamp(row.get("time_index"), field_name="time_index")
    close_time_value = row.get("close_time")
    close_time = (
        None
        if close_time_value in (None, "")
        else _utc_timestamp(close_time_value, field_name="close_time")
    )
    return {
        **dict(row),
        "portfolio_identifier": portfolio_identifier,
        "time_index": time_index,
        "close_time": close_time,
    }


def _utc_timestamp(value: Any, *, field_name: str) -> pd.Timestamp:
    if value is None:
        raise ValueError(f"{field_name} is required.")
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp


def _result_rows(
    result: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(result, Mapping):
        return operation_result_rows(result)
    return [dict(row) for row in result]


def _date_windows(start: dt.date, end: dt.date):
    window_start = start
    while window_start <= end:
        window_end = min(
            window_start + dt.timedelta(days=_SESSION_QUERY_WINDOW_DAYS - 1),
            end,
        )
        yield window_start, window_end
        window_start = window_end + dt.timedelta(days=1)


__all__ = [
    "PortfolioTimestampRepairIssue",
    "PortfolioTimestampRepairPlan",
    "PortfolioTimestampRollback",
    "apply_legacy_midnight_portfolio_timestamp_repair",
    "build_legacy_midnight_portfolio_timestamp_repair_plan",
    "plan_legacy_midnight_portfolio_timestamp_repair",
]
