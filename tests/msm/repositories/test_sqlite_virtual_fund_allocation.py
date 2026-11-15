"""Plan and apply a virtual-fund allocation on SQLite, end to end (ADR 0053).

The reference case: two funds of two assets each share one asset, and the account
holds one asset that is in no fund. Everything is in units.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
import sqlalchemy as sa

from msm.services.accounts.account_virtual_allocations import (
    allocate_account_virtual_funds_in_context,
    apply_account_virtual_fund_allocation_plan_in_context,
    plan_account_virtual_fund_allocations_in_context,
)
from msm.services.accounts.allocation_policies import AllocationError
from msm.services.portfolio_lifecycle import PortfolioRetiredError
from tests.msm.repositories.test_sqlite_snapshot_writes import (
    WHEN,
    _account,
    _asset,
    _count,
    _portfolio,
    _rows,
    _write_holdings,
    _write_target,
    make_sqlite_markets,
)

FUND_TABLES = (
    "ms_markets__virtualfund",
    "ms_markets__virtualfundholdingsset",
    "ms_markets__virtualfundholdingsts",
)
HELD = {"AAPL": 1_100.0, "MSFT": 600.0, "JNJ": 750.0, "TSLA": 1_100.0}


@pytest.fixture
def sqlite_markets(tmp_path, monkeypatch):
    return make_sqlite_markets(tmp_path, monkeypatch)


def _basket_row(portfolio, asset, quantity, direction=1):
    return {
        "target_type": "portfolio",
        "target_uid": portfolio,
        "portfolio_uid": portfolio,
        "asset_uid": asset,
        "quantity": quantity,
        "direction": direction,
        "metadata_json": {},
    }


def _reference_case(sqlite_markets, *, held=HELD):
    engine = sqlite_markets.engine
    account = _account(engine)
    assets = {name: _asset(engine, name) for name in HELD}
    fund_a = _portfolio(engine)
    fund_b = _portfolio(engine)
    _write_holdings(
        sqlite_markets,
        account,
        [{"asset_identifier": name, "quantity": quantity} for name, quantity in held.items()],
    )
    target = _write_target(
        sqlite_markets,
        account,
        [
            _basket_row(fund_a, assets["AAPL"], 1_000.0),
            _basket_row(fund_a, assets["MSFT"], 500.0),
            _basket_row(fund_b, assets["MSFT"], 300.0),
            _basket_row(fund_b, assets["JNJ"], 750.0),
        ],
    )
    position_set = uuid.UUID(str(target["rows"][0]["position_set_uid"]))
    return {
        "account": account,
        "assets": assets,
        "fund_a": fund_a,
        "fund_b": fund_b,
        "position_set": position_set,
    }


def _plan(sqlite_markets, case, **kwargs):
    return plan_account_virtual_fund_allocations_in_context(
        sqlite_markets.context,
        position_set_uid=case["position_set"],
        valuation_time=WHEN,
        account_uid=case["account"],
        **kwargs,
    )


def _lines(plan):
    return {
        (line.owner, line.target_portfolio_uid, line.asset_identifier): (
            line.target,
            line.assigned,
            line.delta,
        )
        for line in plan.lines
    }


def test_the_plan_answers_target_assigned_and_delta_for_every_owner(sqlite_markets) -> None:
    case = _reference_case(sqlite_markets)
    fund_a, fund_b = str(case["fund_a"]), str(case["fund_b"])

    plan = _plan(sqlite_markets, case)

    assert _lines(plan) == pytest.approx(
        {
            ("fund", fund_a, "AAPL"): (1_000.0, 1_000.0, 0.0),
            ("fund", fund_a, "MSFT"): (500.0, 375.0, 125.0),
            ("fund", fund_b, "MSFT"): (300.0, 225.0, 75.0),
            ("fund", fund_b, "JNJ"): (750.0, 750.0, 0.0),
            ("direct", None, "AAPL"): (0.0, 100.0, -100.0),
            ("direct", None, "TSLA"): (0.0, 1_100.0, -1_100.0),
        }
    )
    assert {row.asset_identifier: (row.held, row.target, row.delta) for row in plan.account_deltas} == (
        pytest.approx(
            {
                "AAPL": (1_100.0, 1_000.0, -100.0),
                "MSFT": (600.0, 800.0, 200.0),
                "JNJ": (750.0, 750.0, 0.0),
                "TSLA": (1_100.0, 0.0, -1_100.0),
            }
        )
    )
    assigned: dict[str, float] = {}
    for line in plan.lines:
        assigned[line.asset_identifier] = assigned.get(line.asset_identifier, 0.0) + line.assigned
    assert assigned == pytest.approx(HELD)
    assert plan.policy.id == "proportional_attribution"
    assert plan.policy.version == "1.0.0"
    assert plan.plan_digest.startswith("sha256:")
    assert plan.apply_blockers == ()
    for table in FUND_TABLES:
        assert _count(sqlite_markets.engine, table) == 0, table


def test_apply_writes_the_funds_their_sets_and_their_rows(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    case = _reference_case(sqlite_markets)
    plan = _plan(sqlite_markets, case)

    result = apply_account_virtual_fund_allocation_plan_in_context(sqlite_markets.context, plan)

    assert (result.applied, result.already_applied) == (True, False)
    assert len(result.rows) == 4
    funds = _rows(engine, "SELECT uid, unique_identifier, account_uid, target_portfolio_uid FROM ms_markets__virtualfund")
    assert {row["target_portfolio_uid"] for row in funds} == {case["fund_a"].hex, case["fund_b"].hex}
    assert {row["account_uid"] for row in funds} == {case["account"].hex}
    assert _count(engine, "ms_markets__virtualfundholdingsset") == 2
    by_portfolio = {row["target_portfolio_uid"]: row["uid"] for row in funds}
    stored = _rows(
        engine,
        "SELECT virtual_fund_uid, asset_identifier, allocated_quantity, direction, "
        "allocation_strategy, extra_details, virtual_fund_holdings_set_uid "
        "FROM ms_markets__virtualfundholdingsts",
    )
    assert {
        (row["virtual_fund_uid"], row["asset_identifier"]): row["allocated_quantity"]
        for row in stored
    } == pytest.approx(
        {
            (by_portfolio[case["fund_a"].hex], "AAPL"): 1_000.0,
            (by_portfolio[case["fund_a"].hex], "MSFT"): 375.0,
            (by_portfolio[case["fund_b"].hex], "MSFT"): 225.0,
            (by_portfolio[case["fund_b"].hex], "JNJ"): 750.0,
        }
    )
    assert {row["direction"] for row in stored} == {1}
    assert {row["allocation_strategy"] for row in stored} == {"proportional_attribution"}
    for row in stored:
        details = json.loads(row["extra_details"])
        assert details["plan_digest"] == plan.plan_digest
        assert details["policy_version"] == "1.0.0"
        assert details["position_set_uid"] == str(case["position_set"])
        assert not [key for key in details if "gap" in key or "delta" in key or key == "scale"]
    sets = {
        row["virtual_fund_uid"]: row["uid"]
        for row in _rows(engine, "SELECT uid, virtual_fund_uid FROM ms_markets__virtualfundholdingsset")
    }
    assert {row["virtual_fund_holdings_set_uid"] for row in stored} == set(sets.values())
    assert {fund.holdings_set_uid.replace("-", "") for fund in result.funds} == set(sets.values())


def test_applying_the_same_plan_again_writes_nothing(sqlite_markets) -> None:
    case = _reference_case(sqlite_markets)
    plan = _plan(sqlite_markets, case)
    first = apply_account_virtual_fund_allocation_plan_in_context(sqlite_markets.context, plan)

    again = apply_account_virtual_fund_allocation_plan_in_context(
        sqlite_markets.context, _plan(sqlite_markets, case)
    )

    assert (again.applied, again.already_applied) == (False, True)
    assert {fund.virtual_fund_uid for fund in again.funds} == {
        fund.virtual_fund_uid for fund in first.funds
    }
    assert _count(sqlite_markets.engine, "ms_markets__virtualfundholdingsts") == 4
    assert _count(sqlite_markets.engine, "ms_markets__virtualfundholdingsset") == 2


def test_a_different_allocation_of_the_same_snapshot_is_refused(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    case = _reference_case(sqlite_markets)
    apply_account_virtual_fund_allocation_plan_in_context(
        sqlite_markets.context, _plan(sqlite_markets, case)
    )
    before = _rows(engine, "SELECT * FROM ms_markets__virtualfundholdingsts ORDER BY asset_identifier")

    other = _plan(
        sqlite_markets,
        case,
        policy={
            "id": "proportional_attribution",
            "version": "1.0.0",
            "arguments": {"quantity_tolerance": 0.5},
        },
    )
    with pytest.raises(AllocationError) as refused:
        apply_account_virtual_fund_allocation_plan_in_context(sqlite_markets.context, other)

    assert (refused.value.code, refused.value.status_code) == ("allocation_exists", 409)
    assert _rows(engine, "SELECT * FROM ms_markets__virtualfundholdingsts ORDER BY asset_identifier") == before


def test_allocate_plans_again_and_checks_the_digest(sqlite_markets) -> None:
    case = _reference_case(sqlite_markets)
    plan = _plan(sqlite_markets, case)

    with pytest.raises(AllocationError) as changed:
        allocate_account_virtual_funds_in_context(
            sqlite_markets.context,
            account_uid=case["account"],
            position_set_uid=case["position_set"],
            valuation_time=WHEN,
            plan_digest="sha256:" + "0" * 64,
        )
    assert (changed.value.code, changed.value.status_code) == ("plan_changed", 409)
    for table in FUND_TABLES:
        assert _count(sqlite_markets.engine, table) == 0, table

    result = allocate_account_virtual_funds_in_context(
        sqlite_markets.context,
        account_uid=case["account"],
        position_set_uid=case["position_set"],
        valuation_time=WHEN,
        plan_digest=plan.plan_digest,
    )

    assert result.applied is True
    assert result.plan.plan_digest == plan.plan_digest


def test_a_retired_portfolio_blocks_the_apply_and_not_the_plan(sqlite_markets) -> None:
    case = _reference_case(sqlite_markets)
    with sqlite_markets.engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE ms_markets__portfolio SET retired_at = :retired_at WHERE uid = :uid"),
            {"retired_at": "2026-11-10 12:00:00.000000", "uid": case["fund_b"].hex},
        )

    plan = _plan(sqlite_markets, case)

    assert plan.apply_blockers == (
        {"code": "portfolio_retired", "portfolio_uid": str(case["fund_b"])},
    )
    with pytest.raises(PortfolioRetiredError):
        apply_account_virtual_fund_allocation_plan_in_context(sqlite_markets.context, plan)
    for table in FUND_TABLES:
        assert _count(sqlite_markets.engine, table) == 0, table


def test_a_position_set_of_another_account_is_not_found(sqlite_markets) -> None:
    case = _reference_case(sqlite_markets)
    other_account = _account(sqlite_markets.engine)

    with pytest.raises(AllocationError) as missing:
        plan_account_virtual_fund_allocations_in_context(
            sqlite_markets.context,
            position_set_uid=case["position_set"],
            valuation_time=WHEN,
            account_uid=other_account,
        )

    assert (missing.value.code, missing.value.status_code) == ("not_found", 404)


def test_a_snapshot_at_another_time_is_not_found(sqlite_markets) -> None:
    case = _reference_case(sqlite_markets)

    with pytest.raises(AllocationError) as missing:
        plan_account_virtual_fund_allocations_in_context(
            sqlite_markets.context,
            position_set_uid=case["position_set"],
            valuation_time=WHEN + dt.timedelta(hours=1),
        )

    assert missing.value.code == "not_found"


def test_holding_none_of_a_funds_assets_leaves_nothing_to_apply(sqlite_markets) -> None:
    case = _reference_case(sqlite_markets, held={"TSLA": 1_100.0})

    plan = _plan(sqlite_markets, case)

    assert {line.assigned for line in plan.fund_lines} == {0.0}
    assert [(line.asset_identifier, line.assigned) for line in plan.direct_lines] == [
        ("TSLA", 1_100.0)
    ]
    with pytest.raises(AllocationError) as nothing:
        apply_account_virtual_fund_allocation_plan_in_context(sqlite_markets.context, plan)
    assert nothing.value.code == "nothing_to_apply"
