"""The allocation planner on sized targets, and its policy registry (ADR 0053, ADR 0054)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from jsonschema import Draft202012Validator

from msm.services.accounts.account_virtual_allocations import (
    build_account_virtual_fund_allocation_inputs,
    plan_from_inputs,
    allocation_lines_from_plan,
    plan_response,
    sized_target_rows,
    virtual_fund_holdings_from_plan,
    virtual_fund_unique_identifier_for_target,
)
from msm.services.accounts.allocation_policies import (
    ALLOCATION_POLICIES,
    SCHEMA_DIALECT,
    AllocationError,
    allocation_policy,
    describe_allocation_policy,
    proportional_attribution,
    resolve_allocation_policy,
)

ASSETS = {
    name: uuid.UUID(f"00000000-0000-0000-0000-0000000000{index:02d}")
    for index, name in enumerate(("AAPL", "MSFT", "JNJ", "TSLA", "X", "Y"), start=1)
}
FUND_A = uuid.UUID("00000000-0000-0000-0000-000000000201")
FUND_B = uuid.UUID("00000000-0000-0000-0000-000000000202")
ACCOUNT_UID = uuid.UUID("00000000-0000-0000-0000-000000000301")
TARGET_ALLOCATION_UID = uuid.UUID("00000000-0000-0000-0000-000000000302")
POSITION_SET_UID = uuid.UUID("00000000-0000-0000-0000-000000000303")
HOLDINGS_SET_UID = uuid.UUID("00000000-0000-0000-0000-000000000304")
VALUATION_TIME = dt.datetime(2026, 6, 7, tzinfo=dt.UTC)
TARGET_TIME = VALUATION_TIME - dt.timedelta(days=1)
FUNDS = {"A": FUND_A, "B": FUND_B}


# The policy function ------------------------------------------------------------------


def test_the_reference_case_two_funds_share_one_asset_and_one_asset_is_in_no_fund() -> None:
    allocation = proportional_attribution(
        {"AAPL": 1_100, "MSFT": 600, "JNJ": 750, "TSLA": 1_100},
        {("A", "AAPL"): 1_000, ("A", "MSFT"): 500, ("B", "MSFT"): 300, ("B", "JNJ"): 750},
    )

    assert allocation.fills == pytest.approx(
        {("A", "AAPL"): 1_000, ("A", "MSFT"): 375, ("B", "MSFT"): 225, ("B", "JNJ"): 750}
    )
    assert allocation.direct == pytest.approx({"AAPL": 100, "MSFT": 0, "JNJ": 0, "TSLA": 1_100})


# ADR 0053's edge cases: holdings, fund claims, fills, direct sleeve.
EDGE_CASES = [
    ({"X": 120}, {("A", "X"): 80, ("B", "X"): 40}, {("A", "X"): 80, ("B", "X"): 40}, {"X": 0}),
    ({"X": 150}, {("A", "X"): 80, ("B", "X"): 40}, {("A", "X"): 80, ("B", "X"): 40}, {"X": 30}),
    (
        {"X": 100},
        {("A", "X"): 80, ("B", "X"): 40},
        {("A", "X"): 200 / 3, ("B", "X"): 100 / 3},
        {"X": 0},
    ),
    ({"X": 100}, {("A", "Y"): 50}, {("A", "Y"): 0}, {"X": 100, "Y": 0}),
    ({"X": 10}, {("A", "X"): -5}, {("A", "X"): -5}, {"X": 15}),
    (
        {"X": 100},
        {("A", "X"): 80, ("B", "X"): -40},
        {("A", "X"): 200 / 3, ("B", "X"): -100 / 3},
        {"X": 200 / 3},
    ),
    ({"X": -100}, {("A", "X"): 50}, {("A", "X"): 50}, {"X": -150}),
    ({"X": 100}, {("A", "X"): 60}, {("A", "X"): 60}, {"X": 40}),
    (
        {"X": 100, "Y": 25},
        {("A", "X"): 80, ("A", "Y"): 50, ("B", "X"): 40},
        {("A", "X"): 200 / 3, ("A", "Y"): 25, ("B", "X"): 100 / 3},
        {"X": 0, "Y": 0},
    ),
    ({"X": -100}, {("A", "X"): -80}, {("A", "X"): -80}, {"X": -20}),
]


@pytest.mark.parametrize(("holdings", "targets", "fills", "direct"), EDGE_CASES)
def test_proportional_attribution_edge_cases(holdings, targets, fills, direct) -> None:
    allocation = proportional_attribution(holdings, targets)

    assert allocation.fills == pytest.approx(fills)
    assert allocation.direct == pytest.approx(direct, abs=1e-9)
    for asset in direct:
        taken = sum(fill for (_, claimed), fill in allocation.fills.items() if claimed == asset)
        assert taken + allocation.direct[asset] == pytest.approx(holdings.get(asset, 0))


def test_a_fill_at_or_below_the_tolerance_is_dropped_and_stays_direct() -> None:
    allocation = proportional_attribution(
        {"X": 0.001}, {("A", "X"): 0.001}, quantity_tolerance=0.01
    )

    assert allocation.fills == {("A", "X"): 0.0}
    assert allocation.direct == {"X": 0.001}


def test_with_no_fund_everything_is_direct() -> None:
    allocation = proportional_attribution({"X": 100, "Y": 5}, {})

    assert allocation.fills == {}
    assert allocation.direct == {"X": 100.0, "Y": 5.0}


# The registry -------------------------------------------------------------------------


def test_the_registry_has_one_policy() -> None:
    assert [policy.id for policy in ALLOCATION_POLICIES] == ["proportional_attribution"]
    assert allocation_policy("strict_feasible") is None


def test_every_argument_is_a_described_self_contained_json_schema_2020_12() -> None:
    for policy in ALLOCATION_POLICIES:
        description = describe_allocation_policy(policy)

        assert description["id"] == policy.id
        assert description["version"] == policy.version
        assert description["title"] and description["description"]
        assert set(description["arguments"]) == set(policy.Arguments.model_fields)
        for argument in description["arguments"].values():
            schema = argument["schema"]
            assert schema["$schema"] == SCHEMA_DIALECT
            assert argument["title"] and argument["description"]
            assert "$ref" not in str(schema) and "$defs" not in str(schema)
            Draft202012Validator.check_schema(schema)
        Draft202012Validator.check_schema(description["arguments_schema"])


def test_the_tolerance_is_an_argument_with_a_default_and_bounds() -> None:
    description = describe_allocation_policy(allocation_policy("proportional_attribution"))
    argument = description["arguments"]["quantity_tolerance"]

    assert argument["required"] is False
    assert argument["schema"]["default"] == 1e-9
    assert (argument["schema"]["minimum"], argument["schema"]["maximum"]) == (0.0, 1.0)
    validator = Draft202012Validator(description["arguments_schema"])
    assert validator.is_valid({})
    assert validator.is_valid({"quantity_tolerance": 0.5})
    assert not validator.is_valid({"quantity_tolerance": 2})
    assert not validator.is_valid({"other": 1})


def test_the_description_and_the_validation_agree() -> None:
    policy = resolve_allocation_policy({"id": "proportional_attribution", "version": "1.0.0"})

    assert policy.arguments == {"quantity_tolerance": 1e-9}
    assert policy.as_choice() == {
        "id": "proportional_attribution",
        "version": "1.0.0",
        "arguments": {"quantity_tolerance": 1e-9},
    }


@pytest.mark.parametrize(
    ("choice", "code", "status_code"),
    [
        ({"id": "strict_feasible", "version": "1.0.0"}, "not_found", 404),
        ({"id": "proportional_attribution", "version": "0.9.0"}, "policy_version_mismatch", 409),
        (
            {
                "id": "proportional_attribution",
                "version": "1.0.0",
                "arguments": {"quantity_tolerance": 5},
            },
            "invalid_policy_arguments",
            400,
        ),
        (
            {"id": "proportional_attribution", "version": "1.0.0", "arguments": {"mode": "x"}},
            "invalid_policy_arguments",
            400,
        ),
        ({"id": "proportional_attribution"}, "invalid_policy_arguments", 400),
    ],
)
def test_a_policy_choice_that_does_not_match_the_registry_is_refused(
    choice, code, status_code
) -> None:
    with pytest.raises(AllocationError) as refused:
        resolve_allocation_policy(choice)

    assert (refused.value.code, refused.value.status_code) == (code, status_code)
    if code == "invalid_policy_arguments":
        assert refused.value.errors
        assert all(set(error) == {"input", "message"} for error in refused.value.errors)


# Inputs from rows ---------------------------------------------------------------------


def test_inputs_read_unit_targets_as_signed_quantities() -> None:
    inputs = _inputs(
        targets=[
            _asset_row("TSLA", 4),
            _fund_row("A", "AAPL", 3),
            _fund_row("A", "MSFT", 12, direction=-1),
            _fund_row("B", "MSFT", 2),
        ],
    )

    assert inputs.holdings == {str(ASSETS["AAPL"]): 10.0, str(ASSETS["MSFT"]): -20.0}
    assert inputs.direct_targets == {str(ASSETS["TSLA"]): 4.0}
    assert inputs.fund_targets == {
        (str(FUND_A), str(ASSETS["AAPL"])): 3.0,
        (str(FUND_A), str(ASSETS["MSFT"])): -12.0,
        (str(FUND_B), str(ASSETS["MSFT"])): 2.0,
    }
    assert inputs.fund_unique_identifiers[str(FUND_A)] == virtual_fund_unique_identifier_for_target(
        account_uid=ACCOUNT_UID,
        target_portfolio_uid=FUND_A,
        account_target_allocation_uid=TARGET_ALLOCATION_UID,
    )
    assert len(set(inputs.fund_unique_identifiers.values())) == 2


def test_inputs_accept_uids_without_dashes() -> None:
    inputs = _inputs(
        targets=[{**_fund_row("A", "AAPL", 3), "asset_uid": ASSETS["AAPL"].hex}],
    )

    assert inputs.fund_targets == {(str(FUND_A), str(ASSETS["AAPL"])): 3.0}


@pytest.mark.parametrize("quantity", [0, -3, None])
def test_inputs_refuse_a_target_row_without_a_positive_quantity(quantity) -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        _inputs(targets=[_fund_row("A", "AAPL", quantity)])


def test_inputs_refuse_one_asset_twice_in_a_basket() -> None:
    with pytest.raises(ValueError, match="twice in its basket"):
        _inputs(targets=[_fund_row("A", "AAPL", 3), _fund_row("A", "AAPL", 4)])


def test_inputs_refuse_a_fund_target_without_a_target_allocation() -> None:
    with pytest.raises(ValueError, match="account_target_allocation_uid"):
        _inputs(account_target_allocation_uid=None, targets=[_fund_row("A", "AAPL", 3)])


def test_inputs_use_a_target_written_before_the_holdings_capture() -> None:
    inputs = _inputs(targets=[_fund_row("A", "AAPL", 3, time_index=TARGET_TIME)])

    assert list(inputs.fund_targets.values()) == [3.0]


def test_inputs_refuse_a_target_written_after_the_holdings_capture() -> None:
    with pytest.raises(AllocationError) as refused:
        _inputs(
            targets=[
                _fund_row("A", "AAPL", 3, time_index=VALUATION_TIME + dt.timedelta(minutes=1))
            ],
        )

    assert refused.value.code == "target_after_snapshot"


def test_inputs_refuse_rows_of_another_position_set() -> None:
    with pytest.raises(ValueError, match="belongs to position_set_uid"):
        _inputs(targets=[{**_fund_row("A", "AAPL", 3), "position_set_uid": str(uuid.uuid4())}])


def test_inputs_refuse_rows_from_several_snapshots() -> None:
    with pytest.raises(ValueError, match="span 2 snapshot times"):
        _inputs(
            targets=[
                {**_fund_row("A", "AAPL", 3, time_index=TARGET_TIME), "position_set_uid": None},
                {**_fund_row("A", "MSFT", 12, time_index=VALUATION_TIME), "position_set_uid": None},
            ],
        )


# The plan -----------------------------------------------------------------------------


def _reference_plan(**kwargs):
    inputs = _inputs(
        holdings=[("AAPL", 1_100, 1), ("MSFT", 600, 1), ("JNJ", 750, 1), ("TSLA", 1_100, 1)],
        targets=[
            _fund_row("A", "AAPL", 1_000),
            _fund_row("A", "MSFT", 500),
            _fund_row("B", "MSFT", 300),
            _fund_row("B", "JNJ", 750),
        ],
    )
    return plan_from_inputs(
        inputs, position_set_uid=POSITION_SET_UID, valuation_time=VALUATION_TIME, **kwargs
    )


def test_the_plan_has_one_line_per_owner_and_asset_with_target_assigned_and_delta() -> None:
    plan = _reference_plan()

    assert {
        (line.owner, line.target_portfolio_uid, line.asset_identifier): (
            line.target,
            line.assigned,
            line.delta,
        )
        for line in plan.lines
    } == pytest.approx(
        {
            ("fund", str(FUND_A), "AAPL"): (1_000, 1_000, 0),
            ("fund", str(FUND_A), "MSFT"): (500, 375, 125),
            ("fund", str(FUND_B), "MSFT"): (300, 225, 75),
            ("fund", str(FUND_B), "JNJ"): (750, 750, 0),
            ("direct", None, "AAPL"): (0, 100, -100),
            ("direct", None, "TSLA"): (0, 1_100, -1_100),
        }
    )
    for line in plan.lines:
        assert line.delta == pytest.approx(line.target - line.assigned)


def test_every_unit_held_appears_once_and_the_account_delta_is_target_minus_held() -> None:
    plan = _reference_plan()

    assigned: dict[str, float] = {}
    line_deltas: dict[str, float] = {}
    for line in plan.lines:
        assigned[line.asset_identifier] = assigned.get(line.asset_identifier, 0) + line.assigned
        line_deltas[line.asset_identifier] = line_deltas.get(line.asset_identifier, 0) + line.delta
    assert assigned == pytest.approx({"AAPL": 1_100, "MSFT": 600, "JNJ": 750, "TSLA": 1_100})
    deltas = {row.asset_identifier: (row.held, row.target, row.delta) for row in plan.account_deltas}
    assert deltas == pytest.approx(
        {
            "AAPL": (1_100, 1_000, -100),
            "MSFT": (600, 800, 200),
            "JNJ": (750, 750, 0),
            "TSLA": (1_100, 0, -1_100),
        }
    )
    assert line_deltas == pytest.approx({name: delta for name, (_, _, delta) in deltas.items()})


def test_the_plan_carries_no_status_no_valuation_and_no_deficits_list() -> None:
    plan = _reference_plan()
    response = plan_response(plan)

    for name in ("status", "deficits", "residuals", "account_nav", "valuation_asset_uid"):
        assert not hasattr(plan, name), name
        assert name not in response, name
    assert set(response) == {
        "account_uid",
        "holdings_set_uid",
        "position_set_uid",
        "valuation_time",
        "policy",
        "funds",
        "lines",
        "account_deltas",
        "apply_blockers",
        "plan_digest",
    }
    assert set(response["lines"][0]) >= {"owner", "target", "assigned", "delta"}


def test_a_direct_target_is_measured_and_does_not_compete() -> None:
    inputs = _inputs(
        holdings=[("X", 100, 1)],
        targets=[_fund_row("A", "X", 60), _asset_row("X", 50)],
    )

    plan = plan_from_inputs(inputs, position_set_uid=POSITION_SET_UID, valuation_time=VALUATION_TIME)

    (fund_line,) = plan.fund_lines
    (direct_line,) = plan.direct_lines
    assert (fund_line.target, fund_line.assigned, fund_line.delta) == (60, 60, 0)
    assert (direct_line.target, direct_line.assigned, direct_line.delta) == (50, 40, 10)
    (asset,) = plan.account_deltas
    assert (asset.held, asset.target, asset.delta) == (100, 110, 10)


def test_a_direct_target_on_an_asset_the_account_does_not_hold_is_a_line() -> None:
    inputs = _inputs(holdings=[("X", 100, 1)], targets=[_fund_row("A", "X", 100), _asset_row("Y", 7)])

    plan = plan_from_inputs(inputs, position_set_uid=POSITION_SET_UID, valuation_time=VALUATION_TIME)

    assert [(line.asset_identifier, line.target, line.assigned, line.delta) for line in plan.direct_lines] == [
        ("Y", 7, 0, 7)
    ]


def test_a_target_with_no_fund_puts_every_holding_on_the_direct_sleeve() -> None:
    inputs = _inputs(holdings=[("X", 100, 1), ("Y", 5, -1)], targets=[_asset_row("X", 100)])

    plan = plan_from_inputs(inputs, position_set_uid=POSITION_SET_UID, valuation_time=VALUATION_TIME)

    assert plan.funds == ()
    assert plan.fund_lines == ()
    assert {
        line.asset_identifier: (line.target, line.assigned, line.delta) for line in plan.direct_lines
    } == {"X": (100, 100, 0), "Y": (0, -5, 5)}
    assert virtual_fund_holdings_from_plan(plan) == []


def test_the_digest_follows_the_request_and_the_lines() -> None:
    plan = _reference_plan()

    assert plan.plan_digest.startswith("sha256:") and len(plan.plan_digest) == 71
    assert _reference_plan().plan_digest == plan.plan_digest
    other_policy = _reference_plan(
        policy={
            "id": "proportional_attribution",
            "version": "1.0.0",
            "arguments": {"quantity_tolerance": 0.5},
        }
    )
    assert other_policy.plan_digest != plan.plan_digest
    other_time = plan_from_inputs(
        _inputs(targets=[_fund_row("A", "AAPL", 3)]),
        position_set_uid=POSITION_SET_UID,
        valuation_time=VALUATION_TIME,
    )
    assert other_time.plan_digest != plan.plan_digest


def test_the_fund_holdings_rows_are_what_each_fund_was_assigned() -> None:
    plan = _reference_plan()

    funds = virtual_fund_holdings_from_plan(plan)

    assert {fund["target_portfolio_uid"] for fund in funds} == {str(FUND_A), str(FUND_B)}
    rows = {
        (fund["target_portfolio_uid"], holding["asset_identifier"]): holding
        for fund in funds
        for holding in fund["holdings"]
    }
    assert {key: row["allocated_quantity"] for key, row in rows.items()} == pytest.approx(
        {
            (str(FUND_A), "AAPL"): 1_000,
            (str(FUND_A), "MSFT"): 375,
            (str(FUND_B), "MSFT"): 225,
            (str(FUND_B), "JNJ"): 750,
        }
    )
    for row in rows.values():
        assert row["direction"] == 1
        assert "target_quantity" not in row
        assert row["allocation_strategy"] == "proportional_attribution"
        assert set(row["extra_details"]) == {
            "source",
            "policy_version",
            "position_set_uid",
            "plan_digest",
        }
        assert row["extra_details"]["plan_digest"] == plan.plan_digest


def test_a_short_fill_is_written_as_a_positive_quantity_with_a_short_direction() -> None:
    inputs = _inputs(holdings=[("X", 10, 1)], targets=[_fund_row("A", "X", 5, direction=-1)])
    plan = plan_from_inputs(inputs, position_set_uid=POSITION_SET_UID, valuation_time=VALUATION_TIME)

    ((holding,),) = [fund["holdings"] for fund in virtual_fund_holdings_from_plan(plan)]

    assert (holding["allocated_quantity"], holding["direction"]) == (5, -1)
    (direct_line,) = plan.direct_lines
    assert direct_line.assigned == 15


def test_the_lines_record_target_and_assigned_for_every_owner() -> None:
    plan = _reference_plan()

    lines = allocation_lines_from_plan(plan)

    assert {
        (
            line["owner_type"],
            line["fund_unique_identifier"],
            line["asset_identifier"],
        ): (line["target_quantity"], line["assigned_quantity"])
        for line in lines
    } == pytest.approx(
        {
            ("fund", _fund_key(FUND_A), "AAPL"): (1_000, 1_000),
            ("fund", _fund_key(FUND_A), "MSFT"): (500, 375),
            ("fund", _fund_key(FUND_B), "MSFT"): (300, 225),
            ("fund", _fund_key(FUND_B), "JNJ"): (750, 750),
            ("direct", None, "AAPL"): (0, 100),
            ("direct", None, "TSLA"): (0, 1_100),
        }
    )
    for line in lines:
        assert (line["target_direction"], line["assigned_direction"]) == (1, 1)
        assert line["allocation_strategy"] == "proportional_attribution"
        assert line["extra_details"]["plan_digest"] == plan.plan_digest


def test_a_target_the_account_holds_nothing_of_is_a_line_with_nothing_assigned() -> None:
    inputs = _inputs(holdings=[("Y", 10, 1)], targets=[_fund_row("A", "X", 5, direction=-1)])
    plan = plan_from_inputs(inputs, position_set_uid=POSITION_SET_UID, valuation_time=VALUATION_TIME)

    # The fund holds nothing, so it has no holdings row.
    assert [fund["holdings"] for fund in virtual_fund_holdings_from_plan(plan)] == [[]]
    fund_line, direct_line = sorted(
        allocation_lines_from_plan(plan), key=lambda line: line["owner_type"], reverse=True
    )
    assert (fund_line["target_quantity"], fund_line["target_direction"]) == (5, -1)
    # Nothing is assigned; the line takes its target's side.
    assert (fund_line["assigned_quantity"], fund_line["assigned_direction"]) == (0, -1)
    assert (direct_line["asset_identifier"], direct_line["assigned_quantity"]) == ("Y", 10)


def _fund_key(portfolio_uid) -> str:
    return virtual_fund_unique_identifier_for_target(
        account_uid=ACCOUNT_UID,
        target_portfolio_uid=portfolio_uid,
        account_target_allocation_uid=TARGET_ALLOCATION_UID,
    )


def test_a_fund_sized_to_nothing_is_a_fund_of_the_plan_with_no_row() -> None:
    inputs = _inputs(holdings=[("X", 10, 1)], targets=[], fund_portfolio_uids=[FUND_A])
    plan = plan_from_inputs(inputs, position_set_uid=POSITION_SET_UID, valuation_time=VALUATION_TIME)

    assert [fund.target_portfolio_uid for fund in plan.funds] == [str(FUND_A)]
    assert [fund["holdings"] for fund in virtual_fund_holdings_from_plan(plan)] == [[]]


# Sizing the exposure --------------------------------------------------------------------


def _exposure(target_type, uid, **exposure):
    key = "portfolio_uid" if target_type == "portfolio" else "asset_uid"
    return {"target_type": target_type, "target_uid": str(uid), key: str(uid), **exposure}


def _sizing(target_type, uid, positions):
    return {
        "target_type": target_type,
        "target_uid": str(uid),
        "positions": [
            {"asset_uid": str(ASSETS[asset]), "quantity": quantity, "direction": direction}
            for asset, quantity, direction in positions
        ],
    }


def test_sizing_gives_every_exposure_of_the_target_in_units() -> None:
    rows, portfolios = sized_target_rows(
        [
            _exposure("portfolio", FUND_A, weight_notional_exposure=0.4),
            _exposure("portfolio", FUND_B, constant_notional_exposure=300_000.0),
            _exposure("asset", ASSETS["TSLA"], single_asset_quantity=-40.0),
            _exposure("asset", ASSETS["X"], weight_notional_exposure=0.05),
        ],
        [
            _sizing("portfolio", FUND_A, [("AAPL", 1_200, 1), ("MSFT", 400, 1)]),
            _sizing("portfolio", FUND_B, []),
            _sizing("asset", ASSETS["X"], [("X", 7, 1)]),
        ],
        position_set_uid=POSITION_SET_UID,
    )

    assert portfolios == sorted([str(FUND_A), str(FUND_B)])
    assert sorted(
        (row["target_type"], row.get("portfolio_uid"), row["asset_uid"], row["quantity"], row["direction"])
        for row in rows
    ) == sorted(
        [
            # An asset target stated in units needs no sizing.
            ("asset", None, str(ASSETS["TSLA"]), 40.0, -1),
            ("asset", None, str(ASSETS["X"]), 7, 1),
            ("portfolio", str(FUND_A), str(ASSETS["AAPL"]), 1_200, 1),
            ("portfolio", str(FUND_A), str(ASSETS["MSFT"]), 400, 1),
        ]
    )


def test_sizing_lists_every_mismatch_with_the_target() -> None:
    with pytest.raises(AllocationError) as invalid:
        sized_target_rows(
            [
                _exposure("portfolio", FUND_A, weight_notional_exposure=0.4),
                _exposure("portfolio", FUND_B, weight_notional_exposure=0.2),
                _exposure("asset", ASSETS["TSLA"], single_asset_quantity=10.0),
                _exposure("asset", ASSETS["X"], constant_notional_exposure=500.0),
            ],
            [
                _sizing("portfolio", FUND_A, [("AAPL", 3, 1), ("AAPL", 4, 1), ("MSFT", 0, 1)]),
                _sizing("portfolio", FUND_A, []),
                _sizing("asset", ASSETS["TSLA"], [("TSLA", 1, 1)]),
                _sizing("asset", ASSETS["X"], [("Y", 1, 1)]),
            ],
            position_set_uid=POSITION_SET_UID,
        )

    assert (invalid.value.code, invalid.value.status_code) == ("invalid_sized_targets", 400)
    assert [(error["input"], error["message"]) for error in invalid.value.errors] == [
        ("sized_targets.0.positions.1", "The asset is named twice."),
        ("sized_targets.0.positions.2", "quantity must be positive."),
        ("sized_targets.1", "The target is sized twice."),
        (
            "sized_targets.2",
            f"PositionSet {POSITION_SET_UID} has no asset exposure to {ASSETS['TSLA']} that "
            "needs sizing.",
        ),
        ("sized_targets.3.positions.0", "An asset target is sized in its own asset."),
        ("sized_targets", f"The exposure to portfolio {FUND_B} is not sized."),
    ]


def test_deterministic_virtual_fund_unique_identifier_is_stable() -> None:
    first = virtual_fund_unique_identifier_for_target(
        account_uid=ACCOUNT_UID,
        target_portfolio_uid=FUND_A,
        account_target_allocation_uid=TARGET_ALLOCATION_UID,
    )
    second = virtual_fund_unique_identifier_for_target(
        account_uid=ACCOUNT_UID,
        target_portfolio_uid=FUND_A,
        account_target_allocation_uid=TARGET_ALLOCATION_UID,
    )
    other = virtual_fund_unique_identifier_for_target(
        account_uid=ACCOUNT_UID,
        target_portfolio_uid=FUND_A,
        account_target_allocation_uid=POSITION_SET_UID,
    )

    assert first == second
    assert first.startswith("account-virtual-fund-")
    assert first != other


# Helpers ------------------------------------------------------------------------------


def _asset_row(asset, quantity, *, direction=1, time_index=TARGET_TIME):
    return {
        "time_index": time_index,
        "position_set_uid": str(POSITION_SET_UID),
        "target_type": "asset",
        "target_uid": str(ASSETS[asset]),
        "asset_uid": str(ASSETS[asset]),
        "portfolio_uid": None,
        "quantity": quantity,
        "direction": direction,
    }


def _fund_row(fund, asset, quantity, *, direction=1, time_index=TARGET_TIME):
    return {
        "time_index": time_index,
        "position_set_uid": str(POSITION_SET_UID),
        "target_type": "portfolio",
        "target_uid": str(FUNDS[fund]),
        "asset_uid": str(ASSETS[asset]),
        "portfolio_uid": str(FUNDS[fund]),
        "quantity": quantity,
        "direction": direction,
    }


def _inputs(
    *,
    targets,
    holdings=(("AAPL", 10, 1), ("MSFT", 20, -1)),
    account_target_allocation_uid=TARGET_ALLOCATION_UID,
    fund_portfolio_uids=(),
):
    return build_account_virtual_fund_allocation_inputs(
        account_uid=ACCOUNT_UID,
        account_target_allocation_uid=account_target_allocation_uid,
        position_set_uid=POSITION_SET_UID,
        source_account_holdings_set_uid=HOLDINGS_SET_UID,
        account_holdings=[
            {"asset_identifier": name, "quantity": quantity, "direction": direction}
            for name, quantity, direction in holdings
        ],
        target_positions=targets,
        valuation_time=VALUATION_TIME,
        asset_uid_by_identifier=ASSETS,
        asset_identifier_by_uid={uid: name for name, uid in ASSETS.items()},
        fund_portfolio_uids=fund_portfolio_uids,
    )
