"""Plan and apply a virtual-fund allocation on SQLite, end to end (ADR 0053, ADR 0054).

The reference case: two funds of two assets each share one asset, and the account
holds one asset that is in no fund. The account target states exposure, as a share
of NAV; the caller sizes it into units and sends them with the call.
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
from tests.support.sqlite_markets import (
    WHEN,
    _account,
    _asset,
    _count,
    _portfolio,
    _rows,
    _write_holdings,
    _write_target,
)

FUND_TABLES = (
    "ms_markets__virtualfund",
    "ms_markets__virtualfundholdingsset",
    "ms_markets__virtualfundholdingsts",
    "ms_markets__accountallocationlinests",
)
FUND_INSERT = (
    "INSERT INTO ms_markets__virtualfund (uid, unique_identifier, account_uid, "
    "account_target_allocation_uid, target_portfolio_uid)"
)
LINES_SQL = (
    "SELECT owner_type, owner_uid, virtual_fund_uid, asset_identifier, target_quantity, "
    "target_direction, assigned_quantity, assigned_direction, allocation_strategy, "
    "extra_details, account_uid FROM ms_markets__accountallocationlinests"
)


def _stored_lines(engine):
    """The stored lines as {(owner_type, owner_uid, asset): (target, assigned)}, signed."""

    return {
        (row["owner_type"], row["owner_uid"], row["asset_identifier"]): (
            row["target_quantity"] * row["target_direction"],
            row["assigned_quantity"] * row["assigned_direction"],
        )
        for row in _rows(engine, LINES_SQL)
    }
HELD = {"AAPL": 1_100.0, "MSFT": 600.0, "JNJ": 750.0, "TSLA": 1_100.0}


def _exposure_row(portfolio, **exposure):
    return {
        "target_type": "portfolio",
        "target_uid": portfolio,
        "portfolio_uid": portfolio,
        **exposure,
        "metadata_json": {},
    }


def _sized(portfolio, positions):
    return {
        "target_type": "portfolio",
        "target_uid": str(portfolio),
        "positions": [
            {"asset_uid": str(asset), "quantity": quantity, "direction": 1}
            for asset, quantity in positions
        ],
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
    # The exposure: a share of NAV in each portfolio.
    target = _write_target(
        sqlite_markets,
        account,
        [
            _exposure_row(fund_a, weight_notional_exposure=0.4),
            _exposure_row(fund_b, weight_notional_exposure=0.3),
        ],
    )
    position_set = uuid.UUID(str(target["rows"][0]["position_set_uid"]))
    return {
        "account": account,
        "assets": assets,
        "fund_a": fund_a,
        "fund_b": fund_b,
        "position_set": position_set,
        # The provider's sizing of that exposure, in units.
        "sized": [
            _sized(fund_a, [(assets["AAPL"], 1_000.0), (assets["MSFT"], 500.0)]),
            _sized(fund_b, [(assets["MSFT"], 300.0), (assets["JNJ"], 750.0)]),
        ],
    }


def _plan(sqlite_markets, case, **kwargs):
    return plan_account_virtual_fund_allocations_in_context(
        sqlite_markets.context,
        position_set_uid=case["position_set"],
        valuation_time=WHEN,
        account_uid=case["account"],
        **{"sized_targets": case["sized"], **kwargs},
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
    funds = _rows(
        engine,
        "SELECT uid, unique_identifier, account_uid, account_target_allocation_uid, "
        "target_portfolio_uid FROM ms_markets__virtualfund",
    )
    assert {row["target_portfolio_uid"] for row in funds} == {case["fund_a"].hex, case["fund_b"].hex}
    assert {row["account_uid"] for row in funds} == {case["account"].hex}
    # Each fund names the target allocation of the plan's PositionSet (issue 157).
    (allocation,) = _rows(engine, "SELECT uid FROM ms_markets__accounttargetallocation")
    assert plan.account_target_allocation_uid == str(uuid.UUID(allocation["uid"]))
    assert {row["account_target_allocation_uid"] for row in funds} == {allocation["uid"]}
    assert _count(engine, "ms_markets__virtualfundholdingsset") == 2
    by_portfolio = {row["target_portfolio_uid"]: row["uid"] for row in funds}
    fund_a, fund_b = by_portfolio[case["fund_a"].hex], by_portfolio[case["fund_b"].hex]

    # The fund holdings are what each fund was assigned.
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
            (fund_a, "AAPL"): 1_000.0,
            (fund_a, "MSFT"): 375.0,
            (fund_b, "MSFT"): 225.0,
            (fund_b, "JNJ"): 750.0,
        }
    )
    assert {row["direction"] for row in stored} == {1}
    sets = {
        row["virtual_fund_uid"]: row["uid"]
        for row in _rows(engine, "SELECT uid, virtual_fund_uid FROM ms_markets__virtualfundholdingsset")
    }
    assert {row["virtual_fund_holdings_set_uid"] for row in stored} == set(sets.values())
    assert {fund.holdings_set_uid.replace("-", "") for fund in result.funds} == set(sets.values())

    # The lines are the sync's record: target and assigned for every owner, fund or
    # direct. The delta is target minus assigned.
    account = case["account"].hex
    assert _stored_lines(engine) == pytest.approx(
        {
            ("fund", fund_a, "AAPL"): (1_000.0, 1_000.0),
            ("fund", fund_a, "MSFT"): (500.0, 375.0),
            ("fund", fund_b, "MSFT"): (300.0, 225.0),
            ("fund", fund_b, "JNJ"): (750.0, 750.0),
            ("direct", account, "AAPL"): (0.0, 100.0),
            ("direct", account, "TSLA"): (0.0, 1_100.0),
        }
    )
    assert len(result.rows) == 6
    for row in _rows(engine, LINES_SQL):
        assert row["account_uid"] == account
        assert row["allocation_strategy"] == "proportional_attribution"
        assert row["virtual_fund_uid"] == (row["owner_uid"] if row["owner_type"] == "fund" else None)
        details = json.loads(row["extra_details"])
        assert details["plan_digest"] == plan.plan_digest
        assert details["policy_version"] == "1.0.0"
        assert details["position_set_uid"] == str(case["position_set"])


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
    assert _count(sqlite_markets.engine, "ms_markets__accountallocationlinests") == 6


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
            sized_targets=case["sized"],
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
        sized_targets=case["sized"],
        plan_digest=plan.plan_digest,
    )

    assert result.applied is True
    assert result.plan.plan_digest == plan.plan_digest


def test_allocate_with_other_sized_targets_than_the_plan_is_a_changed_plan(sqlite_markets) -> None:
    case = _reference_case(sqlite_markets)
    plan = _plan(sqlite_markets, case)
    resized = [
        _sized(case["fund_a"], [(case["assets"]["AAPL"], 900.0)]),
        case["sized"][1],
    ]

    with pytest.raises(AllocationError) as changed:
        allocate_account_virtual_funds_in_context(
            sqlite_markets.context,
            account_uid=case["account"],
            position_set_uid=case["position_set"],
            valuation_time=WHEN,
            sized_targets=resized,
            plan_digest=plan.plan_digest,
        )

    assert changed.value.code == "plan_changed"
    for table in FUND_TABLES:
        assert _count(sqlite_markets.engine, table) == 0, table


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
            sized_targets=case["sized"],
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
            sized_targets=case["sized"],
        )

    assert missing.value.code == "not_found"


def test_a_fund_the_account_holds_nothing_of_has_its_whole_target_as_delta(
    sqlite_markets,
) -> None:
    engine = sqlite_markets.engine
    case = _reference_case(sqlite_markets, held={"TSLA": 1_100.0})

    plan = _plan(sqlite_markets, case)
    result = apply_account_virtual_fund_allocation_plan_in_context(sqlite_markets.context, plan)

    assert {line.assigned for line in plan.fund_lines} == {0.0}
    assert (result.applied, result.already_applied) == (True, False)
    # Each fund gets its holdings set and holds nothing.
    assert _count(engine, "ms_markets__virtualfund") == 2
    assert _count(engine, "ms_markets__virtualfundholdingsset") == 2
    assert _count(engine, "ms_markets__virtualfundholdingsts") == 0
    # Its target is recorded with nothing assigned, so the whole target is the delta.
    lines = _stored_lines(engine)
    assert sorted(
        (owner_type, asset, target, assigned)
        for (owner_type, _, asset), (target, assigned) in lines.items()
    ) == [
        ("direct", "TSLA", 0.0, 1_100.0),
        ("fund", "AAPL", 1_000.0, 0.0),
        ("fund", "JNJ", 750.0, 0.0),
        ("fund", "MSFT", 300.0, 0.0),
        ("fund", "MSFT", 500.0, 0.0),
    ]

    again = apply_account_virtual_fund_allocation_plan_in_context(
        sqlite_markets.context, _plan(sqlite_markets, case)
    )
    assert (again.applied, again.already_applied) == (False, True)


def test_a_fund_sized_to_nothing_gets_its_holdings_set_and_no_line(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    case = _reference_case(sqlite_markets)
    sized = [_sized(case["fund_a"], []), _sized(case["fund_b"], [])]

    plan = _plan(sqlite_markets, case, sized_targets=sized)
    result = apply_account_virtual_fund_allocation_plan_in_context(sqlite_markets.context, plan)

    assert plan.fund_lines == ()
    assert {fund.target_portfolio_uid for fund in plan.funds} == {
        str(case["fund_a"]),
        str(case["fund_b"]),
    }
    assert result.applied is True
    assert _count(engine, "ms_markets__virtualfundholdingsset") == 2
    assert _count(engine, "ms_markets__virtualfundholdingsts") == 0
    # Everything the account holds stays in its direct part.
    assert {
        (owner_type, asset): values for (owner_type, _, asset), values in _stored_lines(engine).items()
    } == {("direct", asset): (0.0, quantity) for asset, quantity in HELD.items()}

    again = apply_account_virtual_fund_allocation_plan_in_context(
        sqlite_markets.context, _plan(sqlite_markets, case, sized_targets=sized)
    )
    assert (again.applied, again.already_applied) == (False, True)
    with pytest.raises(AllocationError) as refused:
        apply_account_virtual_fund_allocation_plan_in_context(
            sqlite_markets.context, _plan(sqlite_markets, case)
        )
    assert refused.value.code == "allocation_exists"


def test_a_direct_asset_target_is_sized_and_its_delta_is_recorded(sqlite_markets) -> None:
    """A target with no fund: the direct lines are the whole allocation (ADR 0054)."""

    engine = sqlite_markets.engine
    account = _account(engine)
    tsla, aapl = _asset(engine, "TSLA"), _asset(engine, "AAPL")
    _write_holdings(sqlite_markets, account, [{"asset_identifier": "TSLA", "quantity": 1_640.0}])
    target = _write_target(
        sqlite_markets,
        account,
        [
            # 5% of the account in TSLA: the caller sizes it. 10 AAPL: already units.
            {
                "target_type": "asset",
                "target_uid": tsla,
                "asset_uid": tsla,
                "weight_notional_exposure": 0.05,
                "metadata_json": {},
            },
            {
                "target_type": "asset",
                "target_uid": aapl,
                "asset_uid": aapl,
                "single_asset_quantity": 10.0,
                "metadata_json": {},
            },
        ],
    )
    request = {
        "account_uid": account,
        "position_set_uid": uuid.UUID(str(target["rows"][0]["position_set_uid"])),
        "valuation_time": WHEN,
        "sized_targets": [
            {
                "target_type": "asset",
                "target_uid": str(tsla),
                "positions": [{"asset_uid": str(tsla), "quantity": 200.0, "direction": 1}],
            }
        ],
    }

    result = allocate_account_virtual_funds_in_context(sqlite_markets.context, **request)

    assert (result.applied, result.funds) == (True, ())
    assert _count(engine, "ms_markets__virtualfund") == 0
    assert _stored_lines(engine) == {
        ("direct", account.hex, "TSLA"): (200.0, 1_640.0),
        ("direct", account.hex, "AAPL"): (10.0, 0.0),
    }
    again = allocate_account_virtual_funds_in_context(sqlite_markets.context, **request)
    assert (again.applied, again.already_applied) == (False, True)
    assert _count(engine, "ms_markets__accountallocationlinests") == 2


def test_every_exposure_must_be_sized_and_only_the_targets_exposures(sqlite_markets) -> None:
    case = _reference_case(sqlite_markets)
    stranger = _portfolio(sqlite_markets.engine)

    with pytest.raises(AllocationError) as invalid:
        _plan(
            sqlite_markets,
            case,
            sized_targets=[case["sized"][0], _sized(stranger, [(case["assets"]["JNJ"], 1.0)])],
        )

    assert (invalid.value.code, invalid.value.status_code) == ("invalid_sized_targets", 400)
    messages = [error["message"] for error in invalid.value.errors]
    assert any(str(stranger) in message for message in messages)
    assert any(
        str(case["fund_b"]) in message and "not sized" in message for message in messages
    )


def test_an_allocation_uses_the_fund_the_target_write_created(sqlite_markets) -> None:
    from msm.services import add_account_target_positions_snapshot_response

    engine = sqlite_markets.engine
    account = _account(engine)
    asset = _asset(engine, "AAPL")
    portfolio = _portfolio(engine)
    _write_holdings(sqlite_markets, account, [{"asset_identifier": "AAPL", "quantity": 60.0}])
    snapshot = add_account_target_positions_snapshot_response(
        sqlite_markets.context,
        account_uid=str(account),
        target_positions_date=WHEN,
        positions=[
            {
                "target_type": "portfolio",
                "portfolio_uid": str(portfolio),
                "weight_notional_exposure": 1.0,
            }
        ],
    )
    (requested,) = _rows(engine, "SELECT uid FROM ms_markets__virtualfund")

    result = allocate_account_virtual_funds_in_context(
        sqlite_markets.context,
        account_uid=account,
        position_set_uid=snapshot["position_set_uid"],
        valuation_time=WHEN,
        sized_targets=[_sized(portfolio, [(asset, 100.0)])],
    )

    assert result.applied is True
    assert [fund.virtual_fund_uid.replace("-", "") for fund in result.funds] == [requested["uid"]]
    assert _count(engine, "ms_markets__virtualfund") == 1
    (row,) = _rows(engine, "SELECT allocated_quantity FROM ms_markets__virtualfundholdingsts")
    assert row["allocated_quantity"] == 60.0
    assert _stored_lines(engine) == {("fund", requested["uid"], "AAPL"): (100.0, 60.0)}


def test_the_postgresql_writes_compile_with_the_funds_and_the_lines(
    offline_postgresql_runtime,
) -> None:
    """The PostgreSQL statements are checked as compiled SQL; they are not run here."""

    from msm.repositories.accounts import build_replace_account_target_positions_snapshot_operation
    from msm.repositories.virtual_funds import build_write_account_virtual_fund_allocation_operation

    class FakeContext:
        data_source_uid = None
        limits = None

    account, portfolio, allocation = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    target_sql = build_replace_account_target_positions_snapshot_operation(
        FakeContext(),
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=allocation,
        position_set_uid=uuid.uuid4(),
        account_uid=account,
        account_name="Some account",
        target_positions_date=WHEN,
        positions=[
            {
                "target_type": "portfolio",
                "target_uid": str(portfolio),
                "asset_uid": None,
                "portfolio_uid": str(portfolio),
                "weight_notional_exposure": "0.4",
                "single_asset_quantity": None,
                "metadata_json": {},
            }
        ],
        virtual_funds=[
            {
                "unique_identifier": "account-virtual-fund-x",
                "virtual_fund_uid": str(uuid.uuid4()),
                "target_portfolio_uid": str(portfolio),
            }
        ],
    ).statement.sql
    assert "created_virtual_funds AS" in target_sql
    assert FUND_INSERT in target_sql
    assert "ON CONFLICT (unique_identifier) DO NOTHING" in target_sql
    assert "JOIN position_set ON true JOIN account_target_allocation ON true" in target_sql

    fund = {
        "unique_identifier": "account-virtual-fund-x",
        "account_target_allocation_uid": str(allocation),
        "target_portfolio_uid": str(portfolio),
        "virtual_fund_uid": str(uuid.uuid4()),
        "holdings_set_uid": str(uuid.uuid4()),
        "holdings": [
            {
                "asset_identifier": "AAPL",
                "allocated_quantity": 1_000.0,
                "allocation_strategy": "proportional_attribution",
                "direction": 1,
                "extra_details": {},
            }
        ],
    }

    def line(owner_type, fund_unique_identifier, asset, target, assigned):
        return {
            "owner_type": owner_type,
            "fund_unique_identifier": fund_unique_identifier,
            "asset_identifier": asset,
            "target_quantity": target,
            "target_direction": 1,
            "assigned_quantity": assigned,
            "assigned_direction": 1,
            "allocation_strategy": "proportional_attribution",
            "extra_details": {},
        }

    def allocation_sql(funds, lines):
        return build_write_account_virtual_fund_allocation_operation(
            FakeContext(),
            account_uid=account,
            source_account_holdings_set_uid=uuid.uuid4(),
            allocation_time=WHEN,
            funds=funds,
            lines=lines,
        ).statement.sql

    lines_table = "ms_markets__accountallocationlinests"
    with_funds = allocation_sql(
        [fund],
        [
            line("fund", fund["unique_identifier"], "AAPL", 1_200.0, 1_000.0),
            line("direct", None, "TSLA", 0.0, 1_640.0),
        ],
    )
    # The lines are the statement; the funds, sets and holdings are CTEs it runs.
    assert f"INSERT INTO {lines_table}" in with_funds
    assert "upserted_funds AS" in with_funds
    assert FUND_INSERT in with_funds
    assert "holdings_sets AS" in with_funds
    assert "inserted_holdings AS" in with_funds
    assert "LEFT OUTER JOIN upserted_funds" in with_funds
    assert "RETURNING" in with_funds

    # A target with no fund: the direct lines are the whole write.
    direct_only = allocation_sql([], [line("direct", None, "TSLA", 200.0, 1_640.0)])
    assert f"INSERT INTO {lines_table}" in direct_only
    assert "upserted_funds" not in direct_only
    assert "WHERE NOT (" in direct_only and "EXISTS (SELECT existing_line.owner_uid" in direct_only


def test_the_stored_lines_of_a_sync_are_read_back_with_their_deltas(sqlite_markets) -> None:
    from msm.services.accounts.account_virtual_allocations import (
        get_account_allocation_record_in_context,
    )

    case = _reference_case(sqlite_markets)
    empty = get_account_allocation_record_in_context(
        sqlite_markets.context, account_uid=case["account"]
    )
    assert (empty["holdings_set_uid"], empty["lines"]) == (None, [])

    plan = _plan(sqlite_markets, case)
    apply_account_virtual_fund_allocation_plan_in_context(sqlite_markets.context, plan)

    latest = get_account_allocation_record_in_context(
        sqlite_markets.context, account_uid=case["account"]
    )
    at_time = get_account_allocation_record_in_context(
        sqlite_markets.context, account_uid=case["account"], valuation_time=WHEN
    )
    another_time = get_account_allocation_record_in_context(
        sqlite_markets.context,
        account_uid=case["account"],
        valuation_time=WHEN + dt.timedelta(hours=1),
    )

    assert latest == at_time
    assert another_time["lines"] == []
    assert latest["account_uid"] == str(case["account"])
    assert latest["holdings_set_uid"] == plan.source_account_holdings_set_uid
    assert latest["valuation_time"] == WHEN
    assert latest["position_set_uid"] == str(case["position_set"])
    assert latest["policy"] == {"id": "proportional_attribution", "version": "1.0.0"}
    assert latest["plan_digest"] == plan.plan_digest
    fund_a, fund_b = str(case["fund_a"]), str(case["fund_b"])
    assert {
        (line["owner"], line["target_portfolio_uid"], line["asset_identifier"]): (
            line["target"],
            line["assigned"],
            line["delta"],
        )
        for line in latest["lines"]
    } == pytest.approx(
        {
            ("fund", fund_a, "AAPL"): (1_000.0, 1_000.0, 0.0),
            ("fund", fund_a, "MSFT"): (500.0, 375.0, 125.0),
            ("fund", fund_b, "MSFT"): (300.0, 225.0, 75.0),
            ("fund", fund_b, "JNJ"): (750.0, 750.0, 0.0),
            ("direct", None, "AAPL"): (0.0, 100.0, -100.0),
            ("direct", None, "TSLA"): (0.0, 1_100.0, -1_100.0),
        }
    )
    for line in latest["lines"]:
        assert (line["virtual_fund_uid"] is None) == (line["owner"] == "direct")
