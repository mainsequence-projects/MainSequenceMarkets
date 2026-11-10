"""Portfolio retirement and the accounts whose current target names a portfolio (ADR 0049)."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.services.portfolio_lifecycle import (
    PortfolioRetiredError,
    PortfolioRetirementConflictError,
)

RETIRED_AT = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.UTC)
TARGET_TIME = dt.datetime(2026, 11, 9, 15, 0, tzinfo=dt.UTC)


class FakeContext:
    data_source_uid = None
    limits = None


def _portfolio_row(uid: str, retired_at: dt.datetime | None = None) -> dict[str, object]:
    return {
        "uid": uid,
        "unique_identifier": "example-sleeve",
        "calendar_uid": str(uuid.uuid4()),
        "published_index_uid": None,
        "portfolio_weights_table_update_uid": None,
        "signal_weights_table_update_uid": None,
        "signal_uid": None,
        "portfolio_table_update_uid": None,
        "backtest_table_price_column_name": "close",
        "retired_at": retired_at,
    }


# Routes ---------------------------------------------------------------------------------


def test_account_targets_route_pages_the_service_result(monkeypatch) -> None:
    portfolio_uid = str(uuid.uuid4())
    account_uid = str(uuid.uuid4())
    captured: dict[str, object] = {}

    def fake_list(*, uid, limit, offset):
        captured.update(uid=uid, limit=limit, offset=offset)
        return {
            "count": 3,
            "results": [
                {
                    "account_uid": account_uid,
                    "account_target_allocation_uid": str(uuid.uuid4()),
                    "position_set_uid": str(uuid.uuid4()),
                    "target_positions_date": TARGET_TIME,
                    "weight_notional_exposure": None,
                    "constant_notional_exposure": "250000",
                }
            ],
        }

    monkeypatch.setattr("apps.v1.routers.portfolios.list_portfolio_account_targets", fake_list)

    response = TestClient(app).get(
        f"/api/v1/portfolio/{portfolio_uid}/account-targets/",
        params={"limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    assert captured == {"uid": portfolio_uid, "limit": 1, "offset": 1}
    payload = response.json()
    assert [item["account_uid"] for item in payload["items"]] == [account_uid]
    assert payload["items"][0]["constant_notional_exposure"] == "250000"
    assert payload["pageInfo"]["totalItems"] == 3
    assert payload["pageInfo"]["hasNextPage"] is True


def test_account_targets_route_answers_404_for_an_unknown_portfolio(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.list_portfolio_account_targets",
        lambda **_: None,
    )

    response = TestClient(app).get(f"/api/v1/portfolio/{uuid.uuid4()}/account-targets/")

    assert response.status_code == 404


def test_retire_route_returns_the_portfolio_with_retired_at(monkeypatch) -> None:
    portfolio_uid = str(uuid.uuid4())
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.retire_portfolio",
        lambda *, uid: _portfolio_row(uid, RETIRED_AT),
    )

    response = TestClient(app).post(f"/api/v1/portfolio/{portfolio_uid}/retire/")

    assert response.status_code == 200
    assert response.json()["uid"] == portfolio_uid
    assert dt.datetime.fromisoformat(response.json()["retired_at"]) == RETIRED_AT


def test_retire_route_answers_409_while_a_current_target_names_the_portfolio(monkeypatch) -> None:
    portfolio_uid = str(uuid.uuid4())

    def refused(*, uid):
        raise PortfolioRetirementConflictError(portfolio_uid=uid, account_count=2)

    monkeypatch.setattr("apps.v1.routers.portfolios.retire_portfolio", refused)

    response = TestClient(app).post(f"/api/v1/portfolio/{portfolio_uid}/retire/")

    assert response.status_code == 409
    assert "2 accounts' current target names it" in response.json()["detail"]


def test_reinstate_route_returns_the_live_portfolio(monkeypatch) -> None:
    portfolio_uid = str(uuid.uuid4())
    monkeypatch.setattr(
        "apps.v1.routers.portfolios.reinstate_portfolio",
        lambda *, uid: _portfolio_row(uid),
    )

    response = TestClient(app).post(f"/api/v1/portfolio/{portfolio_uid}/reinstate/")

    assert response.status_code == 200
    assert response.json()["retired_at"] is None


def test_retire_and_reinstate_routes_answer_404_for_an_unknown_portfolio(monkeypatch) -> None:
    monkeypatch.setattr("apps.v1.routers.portfolios.retire_portfolio", lambda *, uid: None)
    monkeypatch.setattr("apps.v1.routers.portfolios.reinstate_portfolio", lambda *, uid: None)
    client = TestClient(app)

    assert client.post(f"/api/v1/portfolio/{uuid.uuid4()}/retire/").status_code == 404
    assert client.post(f"/api/v1/portfolio/{uuid.uuid4()}/reinstate/").status_code == 404


def test_target_write_naming_a_retired_portfolio_answers_409(monkeypatch) -> None:
    portfolio_uid = str(uuid.uuid4())

    def refused(*, account_uid, payload):
        raise PortfolioRetiredError({portfolio_uid: RETIRED_AT}, action="The target snapshot")

    monkeypatch.setattr("apps.v1.routers.accounts.add_account_target_positions", refused)

    response = TestClient(app).post(
        f"/api/v1/account/{uuid.uuid4()}/add-target-positions/",
        json={
            "target_positions_date": TARGET_TIME.isoformat(),
            "overwrite": False,
            "positions": [
                {
                    "target_type": "portfolio",
                    "target_uid": portfolio_uid,
                    "portfolio_uid": portfolio_uid,
                    "weight_notional_exposure": 1.0,
                }
            ],
        },
    )

    assert response.status_code == 409
    assert "names a retired portfolio" in response.json()["detail"]


def test_lists_hide_retired_portfolios_unless_asked(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_list(**kwargs):
        captured.append(kwargs)
        return {"count": 0, "results": []}

    monkeypatch.setattr("apps.v1.routers.portfolios.list_portfolios", fake_list)
    monkeypatch.setattr(
        "apps.v1.routers.accounts.search_account_target_allocation_targets", fake_list
    )
    client = TestClient(app)

    client.get("/api/v1/portfolio/")
    client.get("/api/v1/portfolio/", params={"include_retired": "true"})
    client.get("/api/v1/account/target-allocation/targets/")
    client.get("/api/v1/account/target-allocation/targets/", params={"include_retired": "true"})

    assert [call["include_retired"] for call in captured] == [False, True, False, True]


# Services -------------------------------------------------------------------------------


@pytest.fixture
def lifecycle(monkeypatch):
    """A fake portfolio row plus the repository calls retire_portfolio_record makes."""

    state = SimpleNamespace(
        row=_portfolio_row(str(uuid.uuid4())),
        current_targets=[0],
        retire_result=None,
        cleared=[],
    )

    def get_model_by_uid(context, *, model, uid):
        return {"rows": [] if state.row is None else [dict(state.row)]}

    def retire(context, *, uid, retired_at):
        if state.retire_result == "refused":
            return {"rows": []}
        state.row = {**state.row, "retired_at": retired_at}
        return {"rows": [dict(state.row)]}

    def clear(context, *, uid, retired_at=None):
        state.cleared.append(retired_at)
        if state.row is None:
            return {"rows": []}
        state.row = {**state.row, "retired_at": None}
        return {"rows": [dict(state.row)]}

    def count(context, *, portfolio_uid):
        return {"rows": [{"count": state.current_targets.pop(0)}]}

    monkeypatch.setattr("msm.repositories.crud.get_model_by_uid", get_model_by_uid)
    monkeypatch.setattr("msm.repositories.portfolios.retire_portfolio", retire)
    monkeypatch.setattr("msm.repositories.portfolios.clear_portfolio_retirement", clear)
    monkeypatch.setattr("msm.repositories.accounts.count_portfolio_account_targets", count)
    return state


def test_retiring_sets_retired_at_once_no_current_target_names_the_portfolio(lifecycle) -> None:
    from msm.services.portfolio_lifecycle import retire_portfolio_record

    before = dt.datetime.now(dt.UTC)
    row = retire_portfolio_record(FakeContext(), uid=lifecycle.row["uid"])

    assert row is not None and before <= row["retired_at"] <= dt.datetime.now(dt.UTC)
    assert lifecycle.cleared == []


def test_retiring_a_retired_portfolio_returns_it_unchanged(lifecycle) -> None:
    from msm.services.portfolio_lifecycle import retire_portfolio_record

    lifecycle.row = {**lifecycle.row, "retired_at": RETIRED_AT}

    assert retire_portfolio_record(FakeContext(), uid=lifecycle.row["uid"])["retired_at"] == RETIRED_AT


def test_retiring_is_refused_with_the_number_of_current_targets(lifecycle) -> None:
    from msm.services.portfolio_lifecycle import retire_portfolio_record

    lifecycle.retire_result = "refused"
    lifecycle.current_targets = [3]

    with pytest.raises(PortfolioRetirementConflictError) as raised:
        retire_portfolio_record(FakeContext(), uid=lifecycle.row["uid"])

    assert raised.value.account_count == 3
    assert lifecycle.row["retired_at"] is None


def test_a_target_written_during_the_retirement_undoes_it(lifecycle) -> None:
    from msm.services.portfolio_lifecycle import retire_portfolio_record

    lifecycle.current_targets = [1]

    with pytest.raises(PortfolioRetirementConflictError):
        retire_portfolio_record(FakeContext(), uid=lifecycle.row["uid"])

    assert lifecycle.row["retired_at"] is None
    assert len(lifecycle.cleared) == 1 and lifecycle.cleared[0] is not None


def test_retiring_or_reinstating_an_unknown_portfolio_returns_none(lifecycle) -> None:
    from msm.services.portfolio_lifecycle import reinstate_portfolio_record, retire_portfolio_record

    lifecycle.row = None

    assert retire_portfolio_record(FakeContext(), uid=uuid.uuid4()) is None
    assert reinstate_portfolio_record(FakeContext(), uid=uuid.uuid4()) is None


def test_reinstating_clears_retired_at_unconditionally(lifecycle) -> None:
    from msm.services.portfolio_lifecycle import reinstate_portfolio_record

    lifecycle.row = {**lifecycle.row, "retired_at": RETIRED_AT}

    assert reinstate_portfolio_record(FakeContext(), uid=lifecycle.row["uid"])["retired_at"] is None
    assert lifecycle.cleared == [None]


def test_retired_portfolios_filters_by_retirement_time(monkeypatch) -> None:
    from msm.services.portfolio_lifecycle import retired_portfolios

    live, early, late = (str(uuid.uuid4()) for _ in range(3))
    captured: dict[str, object] = {}

    def search_model(context, *, model, in_filters, limit):
        captured.update(in_filters=in_filters, limit=limit)
        return {
            "rows": [
                {"uid": live, "retired_at": None},
                {"uid": early, "retired_at": RETIRED_AT - dt.timedelta(days=1)},
                {"uid": late, "retired_at": (RETIRED_AT + dt.timedelta(days=1)).isoformat()},
            ]
        }

    monkeypatch.setattr("msm.repositories.crud.search_model", search_model)

    assert set(retired_portfolios(FakeContext(), [live, early, late, None])) == {early, late}
    assert set(retired_portfolios(FakeContext(), [live, early, late], as_of=RETIRED_AT)) == {early}
    assert sorted(captured["in_filters"]["uid"]) == sorted([live, early, late])
    assert retired_portfolios(FakeContext(), []) == {}


def test_a_refused_target_write_reports_the_retired_portfolio(monkeypatch) -> None:
    from msm.services import target_positions as services

    account_uid = str(uuid.uuid4())
    portfolio_uid = str(uuid.uuid4())
    monkeypatch.setattr(
        services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": account_uid, "account_name": "Some account"}},
    )
    monkeypatch.setattr(
        "msm.repositories.accounts.replace_account_target_positions_snapshot",
        lambda context, **kwargs: {"rows": []},
    )
    monkeypatch.setattr(
        "msm.services.portfolio_lifecycle.retired_portfolios",
        lambda context, portfolio_uids, as_of=None: {
            uid: RETIRED_AT for uid in portfolio_uids if uid == portfolio_uid
        },
    )

    with pytest.raises(PortfolioRetiredError, match="names a retired portfolio"):
        services.add_account_target_positions_snapshot_response(
            FakeContext(),
            account_uid=account_uid,
            target_positions_date=RETIRED_AT - dt.timedelta(days=30),
            positions=[
                {
                    "target_type": "portfolio",
                    "target_uid": portfolio_uid,
                    "portfolio_uid": portfolio_uid,
                    "weight_notional_exposure": 1.0,
                }
            ],
        )


def test_list_portfolio_account_targets_maps_rows(monkeypatch) -> None:
    from msm.services.target_positions import list_portfolio_account_targets_response

    portfolio_uid = str(uuid.uuid4())
    row = {
        "account_uid": uuid.uuid4(),
        "account_target_allocation_uid": uuid.uuid4(),
        "position_set_uid": uuid.uuid4(),
        "target_positions_date": TARGET_TIME,
        "weight_notional_exposure": 0.25,
        "constant_notional_exposure": None,
    }
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "msm.repositories.crud.get_model_by_uid",
        lambda context, *, model, uid: {"rows": [{"uid": uid}]},
    )
    monkeypatch.setattr(
        "msm.repositories.accounts.count_portfolio_account_targets",
        lambda context, *, portfolio_uid: {"rows": [{"count": 7}]},
    )

    def search(context, **kwargs):
        captured.update(kwargs)
        return {"rows": [row]}

    monkeypatch.setattr("msm.repositories.accounts.search_portfolio_account_targets", search)

    response = list_portfolio_account_targets_response(
        FakeContext(), portfolio_uid=portfolio_uid, limit=5, offset=10
    )

    assert captured == {"portfolio_uid": portfolio_uid, "limit": 5, "offset": 10}
    assert response["count"] == 7
    assert response["results"] == [
        {
            "account_uid": str(row["account_uid"]),
            "account_target_allocation_uid": str(row["account_target_allocation_uid"]),
            "position_set_uid": str(row["position_set_uid"]),
            "target_positions_date": TARGET_TIME,
            "weight_notional_exposure": "0.25",
            "constant_notional_exposure": None,
        }
    ]


def test_list_portfolio_account_targets_is_none_for_an_unknown_portfolio(monkeypatch) -> None:
    from msm.services.target_positions import list_portfolio_account_targets_response

    monkeypatch.setattr(
        "msm.repositories.crud.get_model_by_uid",
        lambda context, *, model, uid: {"rows": []},
    )

    assert list_portfolio_account_targets_response(FakeContext(), portfolio_uid=uuid.uuid4()) is None


# Statements -----------------------------------------------------------------------------


def test_current_target_read_starts_from_the_portfolio_and_keeps_the_latest_snapshot(
    offline_postgresql_runtime,
) -> None:
    from msm.repositories.accounts import build_search_portfolio_account_targets_operation

    portfolio_uid = uuid.uuid4()
    operation = build_search_portfolio_account_targets_operation(
        FakeContext(), portfolio_uid=portfolio_uid, limit=10, offset=20
    )
    sql = operation.statement.sql

    assert operation.statement.parameters["portfolio_uid"] == portfolio_uid
    assert "FROM ms_markets__targetpositionsts JOIN ms_markets__positionset" in sql
    assert "ms_markets__targetpositionsts.portfolio_uid = %(portfolio_uid)s::UUID" in sql
    assert "ms_markets__targetpositionsts.time_index = ms_markets__positionset.position_set_time" in sql
    assert "ms_markets__accounttargetallocation.is_active IS true" in sql
    # A later snapshot of the same account, among its active allocations, hides this one.
    assert "NOT (EXISTS (SELECT later_position_set.uid" in sql
    assert "later_allocation.account_uid = ms_markets__accounttargetallocation.account_uid" in sql
    assert (
        "later_position_set.position_set_time = ms_markets__positionset.position_set_time "
        "AND later_position_set.uid > ms_markets__positionset.uid"
    ) in sql
    assert "ORDER BY current_portfolio_targets.account_uid" in sql


def test_retire_statement_checks_current_targets_in_the_same_update(
    offline_postgresql_runtime,
) -> None:
    from msm.repositories.portfolios import build_retire_portfolio_operation

    portfolio_uid = uuid.uuid4()
    operation = build_retire_portfolio_operation(
        FakeContext(), uid=portfolio_uid, retired_at=RETIRED_AT
    )
    sql = operation.statement.sql

    assert sql.startswith("UPDATE ms_markets__portfolio SET retired_at=")
    assert "ms_markets__portfolio.retired_at IS NULL" in sql
    assert "NOT (EXISTS (SELECT ms_markets__accounttargetallocation.account_uid" in sql
    assert "ms_markets__targetpositionsts.portfolio_uid = %(uid)s::UUID" in sql
    assert dt.datetime.fromisoformat(
        str(operation.statement.parameters["retired_at"]).replace("Z", "+00:00")
    ) == RETIRED_AT


def test_clearing_a_retirement_can_require_the_value_it_set(offline_postgresql_runtime) -> None:
    from msm.repositories.portfolios import build_clear_portfolio_retirement_operation

    portfolio_uid = uuid.uuid4()
    guarded = build_clear_portfolio_retirement_operation(
        FakeContext(), uid=portfolio_uid, retired_at=RETIRED_AT
    ).statement.sql
    unconditional = build_clear_portfolio_retirement_operation(
        FakeContext(), uid=portfolio_uid
    ).statement.sql

    assert "SET retired_at=" in guarded
    assert "ms_markets__portfolio.retired_at = %(expected_retired_at)s" in guarded
    assert "expected_retired_at" not in unconditional


def test_target_write_locks_named_portfolios_and_writes_nothing_if_one_is_retired(
    offline_postgresql_runtime,
) -> None:
    from msm.repositories.accounts import build_replace_account_target_positions_snapshot_operation

    def operation(positions):
        return build_replace_account_target_positions_snapshot_operation(
            FakeContext(),
            account_allocation_model_uid=uuid.uuid4(),
            account_target_allocation_uid=uuid.uuid4(),
            position_set_uid=uuid.uuid4(),
            account_uid=uuid.uuid4(),
            account_name="Some account",
            target_positions_date=TARGET_TIME,
            positions=positions,
        )

    portfolio_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    named = operation(
        [
            {
                "target_type": "portfolio",
                "target_uid": str(portfolio_uid),
                "portfolio_uid": str(portfolio_uid),
                "weight_notional_exposure": 1.0,
            }
        ]
    ).statement.sql
    assets_only = operation(
        [
            {
                "target_type": "asset",
                "target_uid": str(asset_uid),
                "asset_uid": str(asset_uid),
                "weight_notional_exposure": 1.0,
            }
        ]
    ).statement.sql

    assert "live_portfolios AS \n(SELECT ms_markets__portfolio.uid" in named
    assert "ms_markets__portfolio.retired_at IS NULL FOR SHARE" in named
    assert "FROM account_allocation_model \nWHERE (SELECT count(*)" in named
    assert "live_portfolios" not in assets_only
    assert "FROM account_allocation_model ON CONFLICT" in assets_only


def test_candidate_search_and_list_leave_retired_portfolios_out(offline_postgresql_runtime) -> None:
    from msm.repositories.accounts import (
        build_search_account_target_allocation_candidates_operation,
    )

    hidden = build_search_account_target_allocation_candidates_operation(
        FakeContext(), target_type="portfolio"
    ).statement.sql
    shown = build_search_account_target_allocation_candidates_operation(
        FakeContext(), target_type="portfolio", include_retired=True
    ).statement.sql

    assert "ms_markets__portfolio.retired_at IS NULL" in hidden
    assert "retired_at" not in shown


# Virtual-fund allocation ----------------------------------------------------------------


def test_applying_an_allocation_for_a_retired_portfolio_is_refused(monkeypatch) -> None:
    from msm.services.accounts import holdings_set_allocation

    portfolio_uid = str(uuid.uuid4())
    plan = SimpleNamespace(account_uid=str(uuid.uuid4()), valuation_time=RETIRED_AT)
    asked: dict[str, object] = {}

    def retired(context, portfolio_uids, *, as_of=None):
        asked.update(portfolio_uids=list(portfolio_uids), as_of=as_of)
        return {portfolio_uid: RETIRED_AT}

    monkeypatch.setattr("msm.services.portfolio_lifecycle.retired_portfolios", retired)

    with pytest.raises(PortfolioRetiredError, match="virtual-fund allocation"):
        holdings_set_allocation._refuse_retired_portfolios(
            FakeContext(), plan, [{"target_portfolio_uid": portfolio_uid}]
        )
    assert asked == {"portfolio_uids": [portfolio_uid], "as_of": RETIRED_AT}


def test_allocation_route_answers_409_for_a_retired_portfolio(monkeypatch) -> None:
    portfolio_uid = str(uuid.uuid4())

    def refused(*, account_uid, payload):
        raise PortfolioRetiredError({portfolio_uid: RETIRED_AT}, action="The allocation")

    monkeypatch.setattr("apps.v1.routers.accounts.allocate_account_virtual_funds", refused)

    response = TestClient(app).post(
        f"/api/v1/account/{uuid.uuid4()}/virtual-fund-allocations/",
        json={
            "holdings_set_uid": str(uuid.uuid4()),
            "valuation_asset_uid": str(uuid.uuid4()),
            "apply": True,
        },
    )

    assert response.status_code == 409


def test_sdk_allocation_apply_is_refused_for_a_retired_portfolio(monkeypatch) -> None:
    from msm.services.accounts import account_virtual_allocations

    portfolio_uid = str(uuid.uuid4())
    plan = SimpleNamespace(account_uid=str(uuid.uuid4()), valuation_time=RETIRED_AT)
    monkeypatch.setattr(
        "msm.services.portfolio_lifecycle.retired_portfolios_from_rows",
        lambda portfolio_uids, *, as_of=None: {portfolio_uid: RETIRED_AT},
    )

    with pytest.raises(PortfolioRetiredError):
        account_virtual_allocations._refuse_retired_portfolios(
            plan, [{"target_portfolio_uid": portfolio_uid}]
        )


def test_retired_portfolios_from_rows_reads_each_portfolio(monkeypatch) -> None:
    from msm.api.portfolios import Portfolio
    from msm.services.portfolio_lifecycle import retired_portfolios_from_rows

    live, retired = str(uuid.uuid4()), str(uuid.uuid4())
    rows = {
        live: SimpleNamespace(retired_at=None),
        retired: SimpleNamespace(retired_at=RETIRED_AT),
    }
    monkeypatch.setattr(Portfolio, "get_by_uid", classmethod(lambda cls, uid: rows.get(uid)))

    assert retired_portfolios_from_rows([live, retired, retired]) == {retired: RETIRED_AT}
    assert retired_portfolios_from_rows([retired], as_of=RETIRED_AT - dt.timedelta(1)) == {}


def test_sdk_target_frame_naming_a_retired_portfolio_is_refused(monkeypatch) -> None:
    from msm.services.target_positions import build_target_positions_frame
    from msm.time_index.accounts import TargetPositions

    portfolio_uid = str(uuid.uuid4())
    asked: list[list[str]] = []

    def retired(portfolio_uids, *, as_of=None):
        asked.append([str(uid) for uid in portfolio_uids])
        return {portfolio_uid: RETIRED_AT}

    monkeypatch.setattr("msm.services.portfolio_lifecycle.retired_portfolios_from_rows", retired)
    updater = object.__new__(TargetPositions)
    updater.set_frame(
        build_target_positions_frame(
            target_positions_date=RETIRED_AT - dt.timedelta(days=30),
            position_set_uid=uuid.uuid4(),
            positions=[
                {
                    "target_type": "portfolio",
                    "target_uid": portfolio_uid,
                    "portfolio_uid": portfolio_uid,
                    "weight_notional_exposure": 1.0,
                }
            ],
        )
    )

    with pytest.raises(PortfolioRetiredError, match="target-position frame"):
        updater.update()
    assert asked == [[portfolio_uid]]


def test_portfolio_list_leaves_retired_portfolios_out_unless_asked(
    monkeypatch, offline_postgresql_runtime
) -> None:
    from msm.repositories.base import compile_markets_statement
    from msm_portfolios.services import public_api

    statements: list[str] = []

    def capture(context, statement):
        statements.append(
            compile_markets_statement(statement, context=context, operation="select").statement.sql
        )
        return {"rows": [{"count": 0}]}

    monkeypatch.setattr(public_api, "_execute_portfolio_select", capture)

    public_api.list_portfolio_rows_response(FakeContext())
    public_api.list_portfolio_rows_response(FakeContext(), include_retired=True)

    hidden, hidden_count, shown, shown_count = statements
    assert "ms_markets__portfolio.retired_at IS NULL" in hidden
    assert "ms_markets__portfolio.retired_at IS NULL" in hidden_count
    assert "retired_at IS NULL" not in shown
    assert "retired_at IS NULL" not in shown_count
