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
    AccountVirtualFundAllocationInputs,
    AllocationPolicy,
    AllocationValuation,
    HoldingValuationInput,
    HoldingsSelectionPolicy,
    TargetNotionalDemand,
    TargetQuantityDemand,
    ValuationMetricResult,
    ValuationMetricValue,
    _plan_account_virtual_fund_allocations_from_resolved_inputs,
    build_account_virtual_fund_allocation_inputs,
    virtual_fund_unique_identifier_for_target,
)


BTC_UID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ETH_UID = uuid.UUID("00000000-0000-0000-0000-000000000002")
PORTFOLIO_UID = uuid.UUID("00000000-0000-0000-0000-000000000201")
USD_UID = uuid.UUID("00000000-0000-0000-0000-000000000840")
ACCOUNT_UID = uuid.UUID("00000000-0000-0000-0000-000000000301")
TARGET_ALLOCATION_UID = uuid.UUID("00000000-0000-0000-0000-000000000302")
POSITION_SET_UID = uuid.UUID("00000000-0000-0000-0000-000000000303")
HOLDINGS_SET_UID = uuid.UUID("00000000-0000-0000-0000-000000000304")
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


def test_build_inputs_expands_portfolio_targets_and_valuation_converts_notional() -> None:
    inputs = build_account_virtual_fund_allocation_inputs(
        account_uid=ACCOUNT_UID,
        account_target_allocation_uid=TARGET_ALLOCATION_UID,
        position_set_uid=POSITION_SET_UID,
        source_account_holdings_set_uid=HOLDINGS_SET_UID,
        account_holdings=[
            {
                "asset_identifier": "example-asset-btc",
                "quantity": 10,
                "direction": 1,
            },
            {
                "asset_identifier": "example-asset-eth",
                "quantity": 20,
                "direction": 1,
            },
        ],
        target_positions=[
            {
                "time_index": VALUATION_TIME,
                "target_type": "asset",
                "target_uid": BTC_UID,
                "asset_uid": BTC_UID,
                "single_asset_quantity": 7,
            },
            {
                "time_index": VALUATION_TIME,
                "target_type": "portfolio",
                "target_uid": PORTFOLIO_UID,
                "portfolio_uid": PORTFOLIO_UID,
                "weight_notional_exposure": 0.10,
            },
        ],
        valuation_time=VALUATION_TIME,
        account_nav=640_000,
        asset_uid_by_identifier={
            "example-asset-btc": BTC_UID,
            "example-asset-eth": ETH_UID,
        },
        asset_identifier_by_uid={
            BTC_UID: "example-asset-btc",
            ETH_UID: "example-asset-eth",
        },
        portfolio_target_expander=lambda rows: [
            {
                **rows[0],
                "asset_uid": BTC_UID,
                "weight_notional_exposure": rows[0]["weight_notional_exposure"] * 0.40,
            },
            {
                **rows[0],
                "asset_uid": ETH_UID,
                "weight_notional_exposure": rows[0]["weight_notional_exposure"] * 0.60,
            },
        ],
    )

    assert inputs.account_uid == ACCOUNT_UID
    assert len(inputs.direct_target_demands) == 1
    assert len(inputs.virtual_fund_demands) == 0
    assert len(inputs.target_notional_demands) == 2

    plan = _plan_account_virtual_fund_allocations_from_resolved_inputs(
        position_set_uid=POSITION_SET_UID,
        valuation_time=VALUATION_TIME,
        valuation_asset_uid=USD_UID,
        valuation_resolver=_spot_valuation_resolver,
        account_uid=inputs.account_uid,
        source_account_holdings_set_uid=inputs.source_account_holdings_set_uid,
        account_nav=inputs.account_nav,
        source_holdings=inputs.source_holdings,
        direct_target_demands=inputs.direct_target_demands,
        virtual_fund_demands=inputs.virtual_fund_demands,
        target_notional_demands=inputs.target_notional_demands,
    )

    assert plan.account_nav == pytest.approx(640_000)
    assert plan.status == PLAN_STATUS_FEASIBLE
    assert _line(
        plan,
        CLAIM_TYPE_VIRTUAL_FUND_TARGET,
        str(PORTFOLIO_UID),
    ).requested_signed_quantity == pytest.approx(25_600 / 60_000)


def test_public_planner_uses_required_service_inputs(monkeypatch) -> None:
    inputs = AccountVirtualFundAllocationInputs(
        account_uid=ACCOUNT_UID,
        source_account_holdings_set_uid=HOLDINGS_SET_UID,
        account_nav=600_000,
        source_holdings=(
            HoldingValuationInput(
                asset_uid=BTC_UID,
                asset_identifier="example-asset-btc",
                quantity=10,
                direction=1,
            ),
        ),
        target_notional_demands=(
            TargetNotionalDemand(
                target_row_key="portfolio-btc",
                asset_uid=BTC_UID,
                asset_identifier="example-asset-btc",
                notional_value=300_000,
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
            "valuation_asset_uid": USD_UID,
            "valuation_resolver": _spot_valuation_resolver,
            "holdings_selection_policy": HoldingsSelectionPolicy(),
            "allocation_policy": AllocationPolicy(),
            "portfolio_target_expander": None,
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
        valuation_asset_uid=USD_UID,
        holdings_selection_policy=HoldingsSelectionPolicy(),
        valuation_resolver=_spot_valuation_resolver,
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

    account_allocations.apply_account_virtual_fund_allocation_plan(plan)

    assert captured["virtual_fund_payload"]["unique_identifier"] == "fund-a"
    assert captured["allocations"][0]["allocation_strategy"] == ("proportional_attribution")
    assert "allocation_strategy" not in captured["allocations"][0]["extra_details"]


def test_portfolio_target_requires_expander() -> None:
    with pytest.raises(ValueError, match="portfolio_target_expander"):
        build_account_virtual_fund_allocation_inputs(
            account_uid=ACCOUNT_UID,
            account_target_allocation_uid=TARGET_ALLOCATION_UID,
            position_set_uid=POSITION_SET_UID,
            source_account_holdings_set_uid=HOLDINGS_SET_UID,
            account_holdings=[
                {
                    "asset_identifier": "example-asset-btc",
                    "quantity": 10,
                    "direction": 1,
                }
            ],
            target_positions=[
                {
                    "time_index": VALUATION_TIME,
                    "target_type": "portfolio",
                    "target_uid": PORTFOLIO_UID,
                    "portfolio_uid": PORTFOLIO_UID,
                    "weight_notional_exposure": 0.10,
                }
            ],
            valuation_time=VALUATION_TIME,
            account_nav=600_000,
            asset_uid_by_identifier={"example-asset-btc": BTC_UID},
            asset_identifier_by_uid={BTC_UID: "example-asset-btc"},
        )


def test_portfolio_expansion_uses_latest_weights_at_or_before_valuation_time(monkeypatch) -> None:
    from msm_portfolios.data_nodes.portfolios.storage import PortfolioWeightsStorage

    context = object()

    def fake_resolve_runtime(**kwargs):
        assert kwargs["row_model_name"] == "Account virtual-fund allocation portfolio expansion"
        return type("Runtime", (), {"context": context})()

    def fake_search_model(search_context, *, model, **kwargs):
        assert search_context is context
        if model.__name__ == "PortfolioTable":
            assert kwargs["in_filters"] == {"uid": [str(PORTFOLIO_UID)]}
            return {
                "rows": [
                    {
                        "uid": str(PORTFOLIO_UID),
                        "unique_identifier": "example-equal-weight-portfolio",
                    }
                ]
            }
        raise AssertionError(f"Unexpected model lookup: {model.__name__}")

    def fake_latest_portfolio_weight_records(
        latest_context,
        *,
        portfolio_weights_storage,
        portfolio_identifiers,
        valuation_time,
    ):
        assert latest_context is context
        assert portfolio_weights_storage.__name__ == "PortfolioWeightsStorage"
        assert portfolio_identifiers == ["example-equal-weight-portfolio"]
        assert valuation_time == VALUATION_TIME
        return [
            {
                "time_index": VALUATION_TIME - dt.timedelta(minutes=5),
                "portfolio_identifier": "example-equal-weight-portfolio",
                "asset_identifier": "example-asset-btc",
                "weight": 0.40,
            },
            {
                "time_index": VALUATION_TIME - dt.timedelta(minutes=5),
                "portfolio_identifier": "example-equal-weight-portfolio",
                "asset_identifier": "example-asset-eth",
                "weight": 0.60,
            },
        ]

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr("msm.repositories.crud.search_model", fake_search_model)
    monkeypatch.setattr(
        account_allocations,
        "_latest_portfolio_weight_records",
        fake_latest_portfolio_weight_records,
    )

    expanded = account_allocations._expand_portfolio_target_rows(
        [
            {
                "time_index": VALUATION_TIME,
                "target_type": "portfolio",
                "target_uid": str(PORTFOLIO_UID),
                "portfolio_uid": str(PORTFOLIO_UID),
                "weight_notional_exposure": 0.25,
            }
        ],
        valuation_time=VALUATION_TIME,
        portfolio_weights_storage=PortfolioWeightsStorage,
    )

    assert [row["asset_identifier"] for row in expanded] == [
        "example-asset-btc",
        "example-asset-eth",
    ]
    assert [row["weight_notional_exposure"] for row in expanded] == pytest.approx([0.10, 0.15])
    assert {row["target_portfolio_uid"] for row in expanded} == {str(PORTFOLIO_UID)}


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


def _spot_valuation_resolver(
    requested_metrics,
    source_holdings,
    target_notional_demands,
    *,
    valuation_time,
    valuation_asset_uid,
    valuation_policy,
):
    assert tuple(requested_metrics) == ("nav",)
    del valuation_policy
    prices = {
        str(BTC_UID): 60_000,
        str(ETH_UID): 2_000,
    }
    nav = sum(
        holding.quantity * holding.direction * prices[str(holding.asset_uid)]
        for holding in source_holdings
    )
    quantity_demands = tuple(
        TargetQuantityDemand(
            target_row_key=demand.target_row_key,
            asset_uid=demand.asset_uid,
            asset_identifier=demand.asset_identifier,
            requested_signed_quantity=demand.notional_value / prices[str(demand.asset_uid)],
            direction=demand.direction,
            requested_notional=demand.notional_value,
            claim_type=demand.claim_type,
            claim_uid=demand.claim_uid,
            source_target_uid=demand.source_target_uid,
            target_type=demand.target_type,
            target_portfolio_uid=demand.target_portfolio_uid,
            virtual_fund_unique_identifier=demand.virtual_fund_unique_identifier,
            source_row=demand.source_row,
        )
        for demand in target_notional_demands
    )
    return AllocationValuation(
        metrics={
            "nav": ValuationMetricResult(
                metric="nav",
                total=ValuationMetricValue(
                    value=nav,
                    valuation_asset_uid=valuation_asset_uid,
                    as_of=valuation_time,
                    source="test_spot_prices",
                ),
            )
        },
        valuation_asset_uid=valuation_asset_uid,
        target_quantity_demands=quantity_demands,
    )


def _line(plan, claim_type: str, claim_uid: str | None = None):
    for line in plan.account_virtual_holding_lines:
        if line.claim_type != claim_type:
            continue
        if claim_uid is not None and line.claim_uid != claim_uid:
            continue
        return line
    raise AssertionError(f"Missing line for {claim_type=} {claim_uid=}.")
