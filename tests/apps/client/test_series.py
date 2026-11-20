"""The three published series under both row backends, on a SQLite DataSource (ADR 0060).

Each test migrates a fresh SQLite file and runs the series row classes through
MetaTables' own server code for the local runtime (`make_sqlite_markets`). Under the
``remote`` backend the same calls go through an in-process Markets API
(``POST /api/v1/rows/{resource}/{operation}/``), which runs them on that runtime, so a
test proves the whole path. Nothing leaves the process.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mainsequence.server.caller_assertions import ASSERTION_HEADER

from msm.api.remote import MarketsAccessError, use_remote_backend, use_runtime_backend
from msm_portfolios.api import (
    PortfolioValuesSeries,
    PortfolioWeightsSeries,
    SeriesRows,
    SignalWeightsSeries,
)
from tests.support.sqlite_markets import (
    _asset,
    _insert,
    _rows,
    make_sqlite_markets,
)

UTC = dt.UTC
T0 = dt.datetime(2026, 1, 5, 21, 0, tzinfo=UTC)
T1 = T0 + dt.timedelta(days=1)
T2 = T0 + dt.timedelta(days=2)
CALLER_UID = "5f0c7a52-3b1e-4d7a-9c2e-1a4b6d8e0f13"
OTHER_UID = "3c2b1a09-8f7e-4d6c-9b5a-0e1f2a3b4c5d"
BRANCH = "b7a1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d"
OTHER_BRANCH = "c8b2d3e4-f5a6-4b7c-9d8e-0f1a2b3c4d5e"


@pytest.fixture
def markets(tmp_path, monkeypatch, sqlite_revisions):
    markets = make_sqlite_markets(tmp_path, monkeypatch, template=sqlite_revisions.file("head"))
    for asset in ("AAA", "BBB", "CCC"):
        _asset(markets.engine, asset)
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **_kwargs: SimpleNamespace(context=markets.context),
    )
    return markets


def _remote_client(*, uid: str = CALLER_UID, admin: bool = False, caller_assertions=None):
    from apps.v1.main import app
    from msm.client import MarketsClient

    headers = {}
    if caller_assertions is not None:
        headers[ASSERTION_HEADER] = caller_assertions.sign(uid, is_organization_admin=admin)
    return MarketsClient("http://testserver", session=TestClient(app, headers=headers))


@pytest.fixture(params=["runtime", "remote"])
def backend(request, markets, monkeypatch):
    """Run the test under each row backend; under ``remote`` the caller is a branch's workload."""

    if request.param == "runtime":
        yield request.param
        return
    principals = {CALLER_UID: f"branch:{BRANCH}", OTHER_UID: f"branch:{OTHER_BRANCH}"}
    monkeypatch.setattr("apps.v1.identity.caller_principal", lambda uid: principals[uid])
    use_remote_backend(_remote_client().backend)
    try:
        yield request.param
    finally:
        use_runtime_backend()


def _signal(engine, signal_uid: str = "signal-1", *, managed_by: str | None = None) -> str:
    _insert(
        engine,
        "ms_markets__signalmetadata",
        uid=uuid.uuid4().hex,
        signal_uid=signal_uid,
        managed_by=managed_by,
    )
    return signal_uid


def _portfolio(engine, *, managed_by: str | None = None, retired_at=None) -> str:
    calendar = _insert(engine, "ms_markets__calendar")
    identifier = f"portfolio-{uuid.uuid4().hex[:8]}"
    _insert(
        engine,
        "ms_markets__portfolio",
        uid=uuid.uuid4().hex,
        unique_identifier=identifier,
        calendar_uid=calendar["uid"],
        managed_by=managed_by,
        retired_at=retired_at,
    )
    return identifier


def _managed(backend: str) -> str | None:
    return f"branch:{BRANCH}" if backend == "remote" else None


def _weights(time: dt.datetime, **weights: float) -> list[dict]:
    return [
        {"time_index": time, "asset_identifier": asset, "signal_weight": weight}
        for asset, weight in weights.items()
    ]


# Signal weights ----------------------------------------------------------------------------


def test_signal_publish_writes_once_and_closes_dropped_assets(markets, backend) -> None:
    signal = _signal(markets.engine, managed_by=_managed(backend))

    first = SignalWeightsSeries.publish(signal, [*_weights(T0, AAA=0.6, BBB=0.4)])
    again = SignalWeightsSeries.publish(signal, [*_weights(T0, AAA=0.6, BBB=0.4)])
    later = SignalWeightsSeries.publish(signal, _weights(T1, AAA=1.0))

    assert (first.written, first.skipped, first.row_count) == (2, 0, 2)
    assert (again.written, again.skipped, again.row_count) == (0, 2, 2)
    assert (later.written, later.first_time, later.last_time) == (2, T0, T1)
    rows = SignalWeightsSeries.window([signal]).rows
    assert [(row["time_index"], row["asset_identifier"], row["signal_weight"]) for row in rows] == [
        (T0, "AAA", 0.6),
        (T0, "BBB", 0.4),
        (T1, "AAA", 1.0),
        (T1, "BBB", 0.0),
    ]
    assert SignalWeightsSeries.assets(signal) == ["AAA", "BBB"]


def test_signal_publish_refuses_restating_and_writes_nothing(markets, backend) -> None:
    signal = _signal(markets.engine, managed_by=_managed(backend))
    SignalWeightsSeries.publish(signal, _weights(T1, AAA=1.0))

    with pytest.raises(ValueError, match="already has different signal-weights rows"):
        SignalWeightsSeries.publish(signal, _weights(T1, AAA=0.5) + _weights(T2, AAA=0.2))
    with pytest.raises(ValueError, match="at or before this signal's last stored observation"):
        SignalWeightsSeries.publish(signal, _weights(T0, AAA=1.0))

    assert SignalWeightsSeries.bounds([signal])[0].row_count == 1


@pytest.mark.parametrize(
    ("row", "error", "match"),
    [
        (
            {
                "time_index": dt.datetime(2026, 1, 9),
                "asset_identifier": "AAA",
                "signal_weight": 1.0,
            },
            ValueError,
            "has no timezone",
        ),
        (
            {"time_index": T1, "asset_identifier": "AAA", "signal_weight": float("inf")},
            ValueError,
            "not finite|not JSON compliant",
        ),
        (
            {"time_index": T1, "asset_identifier": "ZZZ", "signal_weight": 1.0},
            LookupError,
            "Unknown asset",
        ),
        ({"time_index": T1, "asset_identifier": "AAA", "weight": 1.0}, ValueError, "does not have"),
    ],
)
def test_signal_publish_validates_rows(markets, backend, row, error, match) -> None:
    signal = _signal(markets.engine, managed_by=_managed(backend))

    with pytest.raises(error, match=match):
        SignalWeightsSeries.publish(signal, [row])


def test_signal_publish_needs_the_signal_metadata(markets, backend) -> None:
    with pytest.raises(LookupError, match="No SignalMetadata row"):
        SignalWeightsSeries.publish("unknown-signal", _weights(T0, AAA=1.0))


def test_last_answers_per_key_and_per_asset(markets, backend) -> None:
    signal = _signal(markets.engine, managed_by=_managed(backend))
    SignalWeightsSeries.publish(signal, _weights(T0, AAA=0.5, BBB=0.5))
    SignalWeightsSeries.publish(signal, _weights(T1, CCC=1.0))

    by_key = SignalWeightsSeries.last([signal])
    by_asset = SignalWeightsSeries.last([signal], at=T1, by="asset", inclusive=False)

    assert {(row["asset_identifier"], row["signal_weight"]) for row in by_key.rows} == {
        ("AAA", 0.0),
        ("BBB", 0.0),
        ("CCC", 1.0),
    }
    assert {(row["time_index"], row["asset_identifier"]) for row in by_asset.rows} == {
        (T0, "AAA"),
        (T0, "BBB"),
    }
    assert by_key.frame().index.names == ["time_index", "signal_uid", "asset_identifier"]


# Portfolio series ---------------------------------------------------------------------------


def test_portfolio_values_publish_page_and_restate(markets, backend) -> None:
    portfolio = _portfolio(markets.engine, managed_by=_managed(backend))
    rows = [
        {"time_index": T0 + dt.timedelta(hours=hour), "close": 1.0 + hour / 100, "return": 0.01}
        for hour in range(5)
    ]

    published = PortfolioValuesSeries.publish(portfolio, rows)
    first_page = PortfolioValuesSeries.window([portfolio], limit=2)
    last_page = PortfolioValuesSeries.window([portfolio], limit=2, offset=4)
    deleted = PortfolioValuesSeries.delete_after(portfolio, T0 + dt.timedelta(hours=2))
    (bounds,) = PortfolioValuesSeries.bounds([portfolio])
    (last,) = PortfolioValuesSeries.last([portfolio]).rows

    assert published.written == 5
    assert [row["close"] for row in first_page.rows] == [1.0, 1.01]
    assert first_page.next_offset == 2
    assert last_page.next_offset is None and len(last_page.rows) == 1
    assert deleted.deleted == 2
    assert (bounds.first_time, bounds.last_time, bounds.row_count) == (
        T0,
        T0 + dt.timedelta(hours=2),
        3,
    )
    assert last["close"] == 1.02
    assert PortfolioValuesSeries.publish(portfolio, rows).written == 2


def test_portfolio_weights_refuse_different_rows_and_rows_after_retirement(
    markets, backend
) -> None:
    portfolio = _portfolio(markets.engine, managed_by=_managed(backend), retired_at=T2)
    row = {"time_index": T0, "asset_identifier": "AAA", "weight": 0.5, "weight_before": 0.0}
    PortfolioWeightsSeries.publish(portfolio, [row])

    with pytest.raises(ValueError, match="already has different"):
        PortfolioWeightsSeries.publish(portfolio, [{**row, "weight": 0.6}])
    with pytest.raises(ValueError, match="is retired"):
        PortfolioWeightsSeries.publish(portfolio, [{**row, "time_index": T2}])

    assert PortfolioWeightsSeries.assets(portfolio) == ["AAA"]
    assert PortfolioValuesSeries.assets(portfolio) == ["AAA"]
    frame = PortfolioWeightsSeries.window([portfolio], columns=["weight"]).frame()
    assert list(frame.columns) == ["weight"]
    assert frame["weight"].tolist() == [0.5]


def test_rows_returned_by_both_backends_are_typed(markets, backend) -> None:
    portfolio = _portfolio(markets.engine, managed_by=_managed(backend))
    PortfolioValuesSeries.publish(
        portfolio,
        [{"time_index": T0, "close": 1.0, "close_time": T0, "valuation_stale": False}],
    )

    (row,) = PortfolioValuesSeries.window([portfolio]).rows

    assert isinstance(PortfolioValuesSeries.window([portfolio]), SeriesRows)
    assert row["time_index"] == T0 and row["close_time"] == T0
    assert row["valuation_stale"] is False and row["return"] is None


# Managers (decision 4) ----------------------------------------------------------------------


@pytest.fixture
def api(markets, monkeypatch, caller_assertions):
    principals = {CALLER_UID: f"branch:{BRANCH}", OTHER_UID: f"branch:{OTHER_BRANCH}"}
    monkeypatch.setattr("apps.v1.identity.caller_principal", lambda uid: principals[uid])

    def use(uid: str = CALLER_UID, *, admin: bool = False) -> None:
        use_remote_backend(
            _remote_client(uid=uid, admin=admin, caller_assertions=caller_assertions).backend
        )

    try:
        yield use
    finally:
        use_runtime_backend()


def test_a_created_portfolio_is_managed_by_the_callers_branch(markets, api) -> None:
    from msm.api.portfolios import Portfolio

    calendar = _insert(markets.engine, "ms_markets__calendar")
    api(CALLER_UID)
    portfolio = Portfolio.create(
        unique_identifier="managed", calendar_uid=uuid.UUID(calendar["uid"])
    )
    Portfolio.upsert(unique_identifier="managed", calendar_uid=uuid.UUID(calendar["uid"]))

    assert portfolio.managed_by == f"branch:{BRANCH}"
    (row,) = _rows(markets.engine, "SELECT managed_by FROM ms_markets__portfolio")
    assert row["managed_by"] == f"branch:{BRANCH}"

    api(OTHER_UID)
    with pytest.raises(MarketsAccessError, match="managed by"):
        PortfolioValuesSeries.publish("managed", [{"time_index": T0, "close": 1.0}])
    with pytest.raises(MarketsAccessError, match="managed by"):
        PortfolioValuesSeries.delete_after("managed", T0)
    with pytest.raises(ValueError, match="managed_by is recorded by Markets"):
        Portfolio.upsert(
            unique_identifier="managed",
            calendar_uid=uuid.UUID(calendar["uid"]),
            managed_by=f"branch:{OTHER_BRANCH}",
        )


def test_a_row_without_a_manager_accepts_no_publish_until_an_admin_assigns_one(
    markets, api
) -> None:
    from msm_portfolios.api import SignalMetadata

    signal = _signal(markets.engine)
    (row,) = _rows(markets.engine, "SELECT uid FROM ms_markets__signalmetadata")
    uid = uuid.UUID(row["uid"])

    api(CALLER_UID)
    with pytest.raises(MarketsAccessError, match="has no manager"):
        SignalWeightsSeries.publish(signal, _weights(T0, AAA=1.0))
    with pytest.raises(MarketsAccessError, match="Organization admin"):
        SignalMetadata.assign_manager(uid, f"branch:{BRANCH}")

    api(OTHER_UID, admin=True)
    assigned = SignalMetadata.assign_manager(uid, f"branch:{BRANCH}")

    api(CALLER_UID)
    assert assigned.managed_by == f"branch:{BRANCH}"
    assert SignalWeightsSeries.publish(signal, _weights(T0, AAA=1.0)).written == 1


def test_a_person_caller_manages_as_itself(monkeypatch) -> None:
    from apps.v1 import identity

    class Person:
        identity_type = "human"
        code_repository_branch_uid = None

    class Workload:
        identity_type = "workload"
        code_repository_branch_uid = BRANCH

    users = {CALLER_UID: Person(), OTHER_UID: Workload()}
    monkeypatch.setattr(identity, "_caller_principals", {})
    monkeypatch.setattr(
        identity._DirectoryUser, "get_by_uid", classmethod(lambda cls, uid: users[uid])
    )
    monkeypatch.setattr("mainsequence.server.fastapi.reads_as_caller", _no_op_context)

    assert identity.caller_principal(CALLER_UID) == f"user:{CALLER_UID}"
    assert identity.caller_principal(OTHER_UID) == f"branch:{BRANCH}"
    requester = identity.ActingIdentity(uid=OTHER_UID, kind="requester", is_organization_admin=True)
    assert identity.acting_manager_of(requester).principal == f"user:{OTHER_UID}"
    assert identity.acting_manager_of(requester).is_organization_admin is True


def test_a_local_caller_manages_as_itself(markets, monkeypatch) -> None:
    # In local mode the caller is whoever holds the Bearer token, as the platform's
    # users/me answers; no caller assertion arrives, so nothing reads the directory (#101).
    import requests

    from apps.v1 import identity
    from apps.v1.main import create_app
    from msm.api.portfolios import Portfolio
    from msm.client import MarketsClient

    platform = "http://platform.test"

    def users_me(url, *, headers, **_kwargs):
        assert (url, headers) == (
            f"{platform}/api/v1/users/me/",
            {"Authorization": "Bearer developer-token"},
        )
        return SimpleNamespace(status_code=200, json=lambda: {"uid": CALLER_UID})

    monkeypatch.setenv("MAINSEQUENCE_CALLER_AUTH_MODE", "local")
    monkeypatch.setenv("MAINSEQUENCE_ENDPOINT", platform)
    monkeypatch.setattr(requests, "get", users_me)
    monkeypatch.setattr(identity, "_caller_principals", {})
    local_api = MarketsClient(
        "http://testserver",
        headers=lambda _force: {"Authorization": "Bearer developer-token"},
        session=TestClient(create_app()),
    )
    calendar = _insert(markets.engine, "ms_markets__calendar")

    use_remote_backend(local_api.backend)
    try:
        portfolio = Portfolio.upsert(
            unique_identifier="local", calendar_uid=uuid.UUID(calendar["uid"])
        )
        published = PortfolioValuesSeries.publish("local", [{"time_index": T0, "close": 1.0}])
    finally:
        use_runtime_backend()

    assert portfolio.managed_by == f"user:{CALLER_UID}"
    assert published.written == 1


class _no_op_context:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False
