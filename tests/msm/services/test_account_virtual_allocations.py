from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest

import msm.services.accounts.account_virtual_allocations as account_allocations
from msm.services.accounts.account_virtual_allocations import (
    ALLOCATION_MODE_STRICT_FEASIBLE,
    CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
    CLAIM_TYPE_VIRTUAL_FUND_TARGET,
    PLAN_STATUS_ATTRIBUTED_WITH_TARGET_GAP,
    PLAN_STATUS_FEASIBLE,
    PLAN_STATUS_INFEASIBLE,
    AccountHoldingInput,
    AccountVirtualFundAllocationInputs,
    AllocationPolicy,
    HoldingsSelectionPolicy,
    TargetQuantityDemand,
    _plan_account_virtual_fund_allocations_from_resolved_inputs,
    build_account_virtual_fund_allocation_inputs,
    virtual_fund_unique_identifier_for_target,
)


BTC_UID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ETH_UID = uuid.UUID("00000000-0000-0000-0000-000000000002")
PORTFOLIO_UID = uuid.UUID("00000000-0000-0000-0000-000000000201")
PORTFOLIO_B_UID = uuid.UUID("00000000-0000-0000-0000-000000000202")
ACCOUNT_UID = uuid.UUID("00000000-0000-0000-0000-000000000301")
TARGET_ALLOCATION_UID = uuid.UUID("00000000-0000-0000-0000-000000000302")
POSITION_SET_UID = uuid.UUID("00000000-0000-0000-0000-000000000303")
HOLDINGS_SET_UID = uuid.UUID("00000000-0000-0000-0000-000000000304")
VALUATION_TIME = dt.datetime(2026, 6, 7, tzinfo=dt.UTC)
TARGET_TIME = VALUATION_TIME - dt.timedelta(days=1)
ASSET_UID_BY_IDENTIFIER = {"example-asset-btc": BTC_UID, "example-asset-eth": ETH_UID}
ASSET_IDENTIFIER_BY_UID = {BTC_UID: "example-asset-btc", ETH_UID: "example-asset-eth"}


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


def test_deterministic_virtual_fund_unique_identifier_is_stable() -> None:
    first = virtual_fund_unique_identifier_for_target(
        account_uid=ACCOUNT_UID,
        target_portfolio_uid=PORTFOLIO_UID,
        account_target_allocation_uid=TARGET_ALLOCATION_UID,
    )
    second = virtual_fund_unique_identifier_for_target(
        account_uid=ACCOUNT_UID,
        target_portfolio_uid=PORTFOLIO_UID,
        account_target_allocation_uid=TARGET_ALLOCATION_UID,
    )
    different_target_allocation = virtual_fund_unique_identifier_for_target(
        account_uid=ACCOUNT_UID,
        target_portfolio_uid=PORTFOLIO_UID,
        account_target_allocation_uid=POSITION_SET_UID,
    )

    assert first == second
    assert first.startswith("account-virtual-fund-")
    assert first != different_target_allocation


def test_build_inputs_reads_unit_targets_without_any_valuation() -> None:
    inputs = _build_inputs(
        target_positions=[
            _asset_target_row(BTC_UID, quantity=4),
            _fund_target_row(PORTFOLIO_UID, BTC_UID, quantity=3),
            _fund_target_row(PORTFOLIO_UID, ETH_UID, quantity=12, direction=-1),
        ],
    )

    assert inputs.account_uid == ACCOUNT_UID
    assert [demand.requested_signed_quantity for demand in inputs.direct_target_demands] == [4]
    assert inputs.direct_target_demands[0].claim_type == CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL
    claims = {
        demand.asset_identifier: demand.requested_signed_quantity
        for demand in inputs.virtual_fund_demands
    }
    assert claims == {"example-asset-btc": 3, "example-asset-eth": -12}
    fund = virtual_fund_unique_identifier_for_target(
        account_uid=ACCOUNT_UID,
        target_portfolio_uid=PORTFOLIO_UID,
        account_target_allocation_uid=TARGET_ALLOCATION_UID,
    )
    for demand in inputs.virtual_fund_demands:
        assert demand.claim_uid == str(PORTFOLIO_UID)
        assert demand.target_portfolio_uid == str(PORTFOLIO_UID)
        assert demand.virtual_fund_unique_identifier == fund
    assert len({demand.target_row_key for demand in inputs.virtual_fund_demands}) == 2


def test_build_inputs_gives_each_portfolio_its_own_fund() -> None:
    inputs = _build_inputs(
        target_positions=[
            _fund_target_row(PORTFOLIO_UID, BTC_UID, quantity=3),
            _fund_target_row(PORTFOLIO_B_UID, BTC_UID, quantity=2),
        ],
    )

    funds = {
        demand.claim_uid: demand.virtual_fund_unique_identifier
        for demand in inputs.virtual_fund_demands
    }
    assert set(funds) == {str(PORTFOLIO_UID), str(PORTFOLIO_B_UID)}
    assert len(set(funds.values())) == 2


@pytest.mark.parametrize("quantity", [0, -3, None])
def test_build_inputs_refuses_a_target_row_without_a_positive_quantity(quantity) -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        _build_inputs(
            target_positions=[_fund_target_row(PORTFOLIO_UID, BTC_UID, quantity=quantity)],
        )


def test_build_inputs_refuses_a_fund_target_without_a_target_allocation() -> None:
    with pytest.raises(ValueError, match="account_target_allocation_uid"):
        _build_inputs(
            account_target_allocation_uid=None,
            target_positions=[_fund_target_row(PORTFOLIO_UID, BTC_UID, quantity=3)],
        )


def test_reference_case_two_funds_share_one_asset_and_one_asset_is_in_no_fund() -> None:
    """ADR 0053's reference case, in units."""

    assets = {name: uuid.uuid4() for name in ("AAPL", "MSFT", "JNJ", "TSLA")}

    def holding(name: str, quantity: float) -> AccountHoldingInput:
        return AccountHoldingInput(
            asset_uid=assets[name], asset_identifier=name, quantity=quantity, direction=1
        )

    def claim(fund: str, name: str, quantity: float) -> TargetQuantityDemand:
        return TargetQuantityDemand(
            target_row_key=f"{fund}:{name}",
            claim_uid=fund,
            asset_uid=assets[name],
            asset_identifier=name,
            requested_signed_quantity=quantity,
            direction=1,
            target_portfolio_uid=PORTFOLIO_UID,
            virtual_fund_unique_identifier=fund,
        )

    plan = _plan_account_virtual_fund_allocations_from_resolved_inputs(
        account_uid=ACCOUNT_UID,
        source_account_holdings_set_uid=HOLDINGS_SET_UID,
        position_set_uid=POSITION_SET_UID,
        valuation_time=VALUATION_TIME,
        source_holdings=[
            holding("AAPL", 1_100),
            holding("MSFT", 600),
            holding("JNJ", 750),
            holding("TSLA", 1_100),
        ],
        virtual_fund_demands=[
            claim("fund-a", "AAPL", 1_000),
            claim("fund-a", "MSFT", 500),
            claim("fund-b", "MSFT", 300),
            claim("fund-b", "JNJ", 750),
        ],
    )

    fills = {
        (line.claim_uid, line.asset_identifier): line.allocated_signed_quantity
        for line in plan.virtual_fund_allocations
    }
    assert fills == pytest.approx(
        {
            ("fund-a", "AAPL"): 1_000,
            ("fund-a", "MSFT"): 375,
            ("fund-b", "MSFT"): 225,
            ("fund-b", "JNJ"): 750,
        }
    )
    direct = {row.asset_identifier: row.direct_sleeve_signed_quantity for row in plan.residuals}
    assert direct == pytest.approx({"AAPL": 100, "MSFT": 0, "JNJ": 0, "TSLA": 1_100})
    assert [(row.asset_identifier, row.deficit_abs_quantity) for row in plan.deficits] == [
        ("MSFT", pytest.approx(200))
    ]
    for row in plan.residuals:
        assert row.direct_sleeve_signed_quantity + row.virtual_allocated_signed_quantity == (
            pytest.approx(row.signed_account_holding)
        )


def test_plan_carries_no_valuation() -> None:
    plan = _plan(holdings_quantity=10, direct_target=0, virtual_targets=[("fund-a", 5)])

    for frame in plan.to_frames().values():
        assert not [
            column for column in frame.columns if "notional" in column or "nav" in column
        ]
    assert not hasattr(plan, "account_nav")
    assert not hasattr(plan, "valuation_asset_uid")


def test_public_planner_uses_required_service_inputs(monkeypatch) -> None:
    inputs = AccountVirtualFundAllocationInputs(
        account_uid=ACCOUNT_UID,
        source_account_holdings_set_uid=HOLDINGS_SET_UID,
        source_holdings=(
            AccountHoldingInput(
                asset_uid=BTC_UID,
                asset_identifier="example-asset-btc",
                quantity=10,
                direction=1,
            ),
        ),
        virtual_fund_demands=(
            TargetQuantityDemand(
                target_row_key="portfolio-btc",
                asset_uid=BTC_UID,
                asset_identifier="example-asset-btc",
                requested_signed_quantity=5,
                direction=1,
                claim_type=CLAIM_TYPE_VIRTUAL_FUND_TARGET,
                claim_uid=str(PORTFOLIO_UID),
                target_portfolio_uid=PORTFOLIO_UID,
                virtual_fund_unique_identifier="example-vf",
            ),
        ),
    )

    def fake_resolve_account_virtual_fund_allocation_inputs(**kwargs):
        assert kwargs == {
            "position_set_uid": POSITION_SET_UID,
            "valuation_time": VALUATION_TIME,
            "holdings_selection_policy": HoldingsSelectionPolicy(),
        }
        return inputs

    monkeypatch.setattr(
        account_allocations,
        "resolve_account_virtual_fund_allocation_inputs",
        fake_resolve_account_virtual_fund_allocation_inputs,
    )

    plan = account_allocations.plan_account_virtual_fund_allocations(
        position_set_uid=POSITION_SET_UID,
        valuation_time=VALUATION_TIME,
        holdings_selection_policy=HoldingsSelectionPolicy(),
        allocation_policy=AllocationPolicy(),
    )

    assert plan.account_uid == str(ACCOUNT_UID)
    assert plan.source_account_holdings_set_uid == str(HOLDINGS_SET_UID)
    assert _line(
        plan,
        CLAIM_TYPE_VIRTUAL_FUND_TARGET,
        str(PORTFOLIO_UID),
    ).requested_signed_quantity == pytest.approx(5)


def test_apply_virtual_fund_allocation_plan_writes_allocation_strategy(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    virtual_fund_uid = uuid.uuid4()
    plan = _plan(
        holdings_quantity=10,
        direct_target=0,
        virtual_targets=[("fund-a", 5)],
    )

    class FakeVirtualFund:
        uid = virtual_fund_uid

        def allocate_from_account_holdings_set(self, **kwargs):
            captured.update(kwargs)
            return pd.DataFrame(
                [
                    {
                        "asset_identifier": "example-asset-btc",
                        "allocated_quantity": 5.0,
                    }
                ]
            )

    def fake_upsert(payload):
        captured["virtual_fund_payload"] = payload
        return FakeVirtualFund()

    import msm.api.virtual_funds as virtual_funds_api

    monkeypatch.setattr(
        virtual_funds_api,
        "VirtualFund",
        SimpleNamespace(upsert=fake_upsert),
    )
    monkeypatch.setattr(
        "msm.services.portfolio_lifecycle.retired_portfolios_from_rows",
        lambda portfolio_uids, *, as_of=None: {},
    )

    account_allocations.apply_account_virtual_fund_allocation_plan(plan)

    assert captured["virtual_fund_payload"]["unique_identifier"] == "fund-a"
    assert captured["allocations"][0]["allocation_strategy"] == ("proportional_attribution")
    assert captured["allocations"][0]["allocated_quantity"] == pytest.approx(5)
    assert captured["allocations"][0]["direction"] == 1
    assert "allocation_strategy" not in captured["allocations"][0]["extra_details"]


def test_build_inputs_uses_a_target_written_before_the_holdings_capture() -> None:
    inputs = _build_inputs(
        target_positions=[
            _fund_target_row(PORTFOLIO_UID, BTC_UID, quantity=3, time_index=TARGET_TIME),
            _fund_target_row(PORTFOLIO_UID, ETH_UID, quantity=12, time_index=TARGET_TIME),
        ],
    )

    assert [demand.requested_signed_quantity for demand in inputs.virtual_fund_demands] == [3, 12]


def test_build_inputs_refuses_a_target_written_after_the_holdings_capture() -> None:
    with pytest.raises(ValueError, match="after valuation_time"):
        _build_inputs(
            target_positions=[
                _fund_target_row(
                    PORTFOLIO_UID,
                    BTC_UID,
                    quantity=3,
                    time_index=VALUATION_TIME + dt.timedelta(minutes=1),
                )
            ],
        )


def test_build_inputs_refuses_rows_of_another_position_set() -> None:
    with pytest.raises(ValueError, match="belongs to position_set_uid"):
        _build_inputs(
            target_positions=[
                {
                    **_fund_target_row(PORTFOLIO_UID, BTC_UID, quantity=3),
                    "position_set_uid": str(uuid.uuid4()),
                }
            ],
        )


def test_build_inputs_refuses_rows_from_several_snapshots() -> None:
    with pytest.raises(ValueError, match="span 2 snapshot times"):
        _build_inputs(
            target_positions=[
                {
                    **_fund_target_row(PORTFOLIO_UID, BTC_UID, quantity=3, time_index=TARGET_TIME),
                    "position_set_uid": None,
                },
                {
                    **_fund_target_row(
                        PORTFOLIO_UID, ETH_UID, quantity=12, time_index=VALUATION_TIME
                    ),
                    "position_set_uid": None,
                },
            ],
        )


def _fake_allocation_tables(monkeypatch, *, position_set_time: dt.datetime) -> None:
    context = object()
    rows_by_model = {
        "PositionSetTable": [
            {
                "uid": str(POSITION_SET_UID),
                "account_target_allocation_uid": str(TARGET_ALLOCATION_UID),
                "position_set_time": position_set_time,
            }
        ],
        "AccountTargetAllocationTable": [
            {"uid": str(TARGET_ALLOCATION_UID), "account_uid": str(ACCOUNT_UID)}
        ],
        "AccountHoldingsSetTable": [
            {"uid": str(HOLDINGS_SET_UID), "account_uid": str(ACCOUNT_UID)}
        ],
        "AccountHoldingsStorage": [
            {"asset_identifier": "example-asset-btc", "quantity": 10, "direction": 1},
            {"asset_identifier": "example-asset-eth", "quantity": 20, "direction": 1},
        ],
        "TargetPositionsStorage": [
            _fund_target_row(PORTFOLIO_UID, BTC_UID, quantity=4, time_index=position_set_time),
            _fund_target_row(PORTFOLIO_UID, ETH_UID, quantity=25, time_index=position_set_time),
        ],
    }
    assets = [
        {"uid": str(BTC_UID), "unique_identifier": "example-asset-btc"},
        {"uid": str(ETH_UID), "unique_identifier": "example-asset-eth"},
    ]

    def fake_resolve_runtime(**kwargs):
        return SimpleNamespace(context=context)

    def fake_search_model(search_context, *, model, filters=None, in_filters=None, limit=None):
        assert search_context is context
        if model.__name__ == "AccountHoldingsSetTable":
            assert filters == {"account_uid": str(ACCOUNT_UID), "time_index": VALUATION_TIME}
        if model.__name__ == "AssetTable":
            return {"rows": assets}
        return {"rows": rows_by_model[model.__name__]}

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.repositories.crud.search_model", fake_search_model)


def test_planner_attributes_a_later_capture_against_an_earlier_target(monkeypatch) -> None:
    _fake_allocation_tables(monkeypatch, position_set_time=TARGET_TIME)

    plan = account_allocations.plan_account_virtual_fund_allocations(
        position_set_uid=POSITION_SET_UID,
        valuation_time=VALUATION_TIME,
        holdings_selection_policy=HoldingsSelectionPolicy(),
        allocation_policy=AllocationPolicy(),
    )

    assert plan.status == PLAN_STATUS_ATTRIBUTED_WITH_TARGET_GAP
    assert plan.valuation_time == VALUATION_TIME
    assert plan.position_set_uid == str(POSITION_SET_UID)
    assert plan.source_account_holdings_set_uid == str(HOLDINGS_SET_UID)
    allocated = {
        line.asset_identifier: line.allocated_signed_quantity
        for line in plan.virtual_fund_allocations
    }
    assert allocated == pytest.approx({"example-asset-btc": 4, "example-asset-eth": 20})
    assert [(row.asset_identifier, row.deficit_abs_quantity) for row in plan.deficits] == [
        ("example-asset-eth", pytest.approx(5))
    ]


def test_planner_refuses_a_target_written_after_the_capture(monkeypatch) -> None:
    _fake_allocation_tables(monkeypatch, position_set_time=VALUATION_TIME + dt.timedelta(hours=1))

    with pytest.raises(ValueError, match="after valuation_time"):
        account_allocations.plan_account_virtual_fund_allocations(
            position_set_uid=POSITION_SET_UID,
            valuation_time=VALUATION_TIME,
            holdings_selection_policy=HoldingsSelectionPolicy(),
            allocation_policy=AllocationPolicy(),
        )


def _asset_target_row(
    asset_uid: uuid.UUID,
    *,
    quantity: float | None,
    direction: int = 1,
    time_index: dt.datetime = TARGET_TIME,
) -> dict[str, object]:
    return {
        "time_index": time_index,
        "position_set_uid": str(POSITION_SET_UID),
        "target_type": "asset",
        "target_uid": str(asset_uid),
        "asset_uid": str(asset_uid),
        "portfolio_uid": None,
        "quantity": quantity,
        "direction": direction,
    }


def _fund_target_row(
    portfolio_uid: uuid.UUID,
    asset_uid: uuid.UUID,
    *,
    quantity: float | None,
    direction: int = 1,
    time_index: dt.datetime = TARGET_TIME,
) -> dict[str, object]:
    return {
        "time_index": time_index,
        "position_set_uid": str(POSITION_SET_UID),
        "target_type": "portfolio",
        "target_uid": str(portfolio_uid),
        "asset_uid": str(asset_uid),
        "portfolio_uid": str(portfolio_uid),
        "quantity": quantity,
        "direction": direction,
    }


def _build_inputs(
    *,
    target_positions: list[dict[str, object]],
    account_target_allocation_uid: uuid.UUID | None = TARGET_ALLOCATION_UID,
):
    return build_account_virtual_fund_allocation_inputs(
        account_uid=ACCOUNT_UID,
        account_target_allocation_uid=account_target_allocation_uid,
        position_set_uid=POSITION_SET_UID,
        source_account_holdings_set_uid=HOLDINGS_SET_UID,
        account_holdings=[
            {"asset_identifier": "example-asset-btc", "quantity": 10, "direction": 1},
            {"asset_identifier": "example-asset-eth", "quantity": 20, "direction": 1},
        ],
        target_positions=target_positions,
        valuation_time=VALUATION_TIME,
        asset_uid_by_identifier=ASSET_UID_BY_IDENTIFIER,
        asset_identifier_by_uid=ASSET_IDENTIFIER_BY_UID,
    )


def _plan(
    *,
    holdings_quantity: float,
    direct_target: float,
    virtual_targets: list[tuple[str, float]],
    allocation_policy: AllocationPolicy | None = None,
):
    return _plan_account_virtual_fund_allocations_from_resolved_inputs(
        account_uid=uuid.uuid4(),
        source_account_holdings_set_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        valuation_time=VALUATION_TIME,
        allocation_policy=allocation_policy,
        source_holdings=[
            AccountHoldingInput(
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
