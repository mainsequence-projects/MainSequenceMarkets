from __future__ import annotations

import datetime as dt
import uuid

import pytest

from msm.services.accounts.account_virtual_allocations import (
    ALLOCATION_MODE_STRICT_FEASIBLE,
    CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
    CLAIM_TYPE_VIRTUAL_FUND_TARGET,
    PLAN_STATUS_ATTRIBUTED_WITH_TARGET_GAP,
    PLAN_STATUS_FEASIBLE,
    PLAN_STATUS_INFEASIBLE,
    AllocationPolicy,
    HoldingValuationInput,
    TargetQuantityDemand,
    plan_account_virtual_fund_allocations,
)


BTC_UID = uuid.UUID("00000000-0000-0000-0000-000000000001")
PORTFOLIO_UID = uuid.UUID("00000000-0000-0000-0000-000000000201")
USD_UID = uuid.UUID("00000000-0000-0000-0000-000000000840")
VALUATION_TIME = dt.datetime(2026, 6, 7, tzinfo=dt.UTC)


def test_proportional_attribution_keeps_direct_as_residual() -> None:
    plan = _plan(
        holdings_quantity=10,
        direct_target=7,
        virtual_targets=[("fund-a", 5)],
    )

    assert plan.status == PLAN_STATUS_FEASIBLE
    virtual_line = _line(plan, CLAIM_TYPE_VIRTUAL_FUND_TARGET, "fund-a")
    direct_line = _line(plan, CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL)
    assert virtual_line.allocated_signed_quantity == pytest.approx(5)
    assert virtual_line.target_gap_signed_quantity == pytest.approx(0)
    assert direct_line.allocated_signed_quantity == pytest.approx(5)
    assert direct_line.target_gap_signed_quantity == pytest.approx(2)


def test_opposite_signed_direct_target_does_not_net_with_virtual_demand() -> None:
    plan = _plan(
        holdings_quantity=10,
        direct_target=-7,
        virtual_targets=[("fund-a", 5)],
    )

    virtual_line = _line(plan, CLAIM_TYPE_VIRTUAL_FUND_TARGET, "fund-a")
    direct_line = _line(plan, CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL)
    assert virtual_line.allocated_signed_quantity == pytest.approx(5)
    assert direct_line.allocated_signed_quantity == pytest.approx(5)
    assert direct_line.target_gap_signed_quantity == pytest.approx(-12)


def test_proportional_attribution_scales_virtual_funds_when_underfunded() -> None:
    plan = _plan(
        holdings_quantity=10,
        direct_target=0,
        virtual_targets=[("fund-a", 7), ("fund-b", 5)],
    )

    assert plan.status == PLAN_STATUS_ATTRIBUTED_WITH_TARGET_GAP
    assert _line(plan, CLAIM_TYPE_VIRTUAL_FUND_TARGET, "fund-a").allocated_signed_quantity == (
        pytest.approx(7 / 12 * 10)
    )
    assert _line(plan, CLAIM_TYPE_VIRTUAL_FUND_TARGET, "fund-b").allocated_signed_quantity == (
        pytest.approx(5 / 12 * 10)
    )
    assert _line(plan, CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL).allocated_signed_quantity == (
        pytest.approx(0)
    )
    assert plan.deficits[0].deficit_abs_quantity == pytest.approx(2)


def test_strict_feasible_fails_underfunded_virtual_demand() -> None:
    plan = _plan(
        holdings_quantity=10,
        direct_target=0,
        virtual_targets=[("fund-a", 7), ("fund-b", 5)],
        allocation_policy=AllocationPolicy.strict_feasible(),
    )

    assert plan.allocation_policy.mode == ALLOCATION_MODE_STRICT_FEASIBLE
    assert plan.status == PLAN_STATUS_INFEASIBLE
    assert len(plan.deficits) == 1


def test_short_virtual_target_balances_against_direct_residual() -> None:
    plan = _plan(
        holdings_quantity=10,
        direct_target=0,
        virtual_targets=[("fund-a", -5)],
    )

    virtual_line = _line(plan, CLAIM_TYPE_VIRTUAL_FUND_TARGET, "fund-a")
    direct_line = _line(plan, CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL)
    assert virtual_line.requested_direction == -1
    assert virtual_line.allocated_signed_quantity == pytest.approx(-5)
    assert virtual_line.allocated_abs_quantity == pytest.approx(5)
    assert direct_line.allocated_signed_quantity == pytest.approx(15)


def _plan(
    *,
    holdings_quantity: float,
    direct_target: float,
    virtual_targets: list[tuple[str, float]],
    allocation_policy: AllocationPolicy | None = None,
):
    return plan_account_virtual_fund_allocations(
        account_uid=uuid.uuid4(),
        source_account_holdings_set_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        valuation_time=VALUATION_TIME,
        valuation_asset_uid=USD_UID,
        account_nav=holdings_quantity * 60_000,
        allocation_policy=allocation_policy,
        source_holdings=[
            HoldingValuationInput(
                asset_uid=BTC_UID,
                asset_identifier="example-asset-btc",
                quantity=holdings_quantity,
                direction=1,
            )
        ],
        direct_target_demands=(
            [
                TargetQuantityDemand(
                    target_row_key="direct-btc",
                    claim_type=CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
                    claim_uid="direct",
                    asset_uid=BTC_UID,
                    asset_identifier="example-asset-btc",
                    requested_signed_quantity=direct_target,
                    direction=1 if direct_target >= 0 else -1,
                )
            ]
            if direct_target
            else []
        ),
        virtual_fund_demands=[
            TargetQuantityDemand(
                target_row_key=f"{claim_uid}-btc",
                claim_type=CLAIM_TYPE_VIRTUAL_FUND_TARGET,
                claim_uid=claim_uid,
                asset_uid=BTC_UID,
                asset_identifier="example-asset-btc",
                requested_signed_quantity=target,
                direction=1 if target >= 0 else -1,
                target_portfolio_uid=PORTFOLIO_UID,
                virtual_fund_unique_identifier=claim_uid,
            )
            for claim_uid, target in virtual_targets
        ],
    )


def _line(plan, claim_type: str, claim_uid: str | None = None):
    for line in plan.account_virtual_holding_lines:
        if line.claim_type != claim_type:
            continue
        if claim_uid is not None and line.claim_uid != claim_uid:
            continue
        return line
    raise AssertionError(f"Missing line for {claim_type=} {claim_uid=}.")
