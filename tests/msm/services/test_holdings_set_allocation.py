"""The Markets API allocation of one holdings snapshot (plan, ms-markets valuation, apply)."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from msm.services.accounts.holdings_set_allocation import (
    account_allocation_policy,
    allocate_account_holdings_set,
)

ACCOUNT_UID = "00000000-0000-0000-0000-000000000301"
TARGET_ALLOCATION_UID = "00000000-0000-0000-0000-000000000302"
POSITION_SET_UID = "00000000-0000-0000-0000-000000000303"
HOLDINGS_SET_UID = "00000000-0000-0000-0000-000000000304"
PORTFOLIO_UID = "00000000-0000-0000-0000-000000000201"
BTC_UID = "00000000-0000-0000-0000-000000000001"
ETH_UID = "00000000-0000-0000-0000-000000000002"
USD_UID = "00000000-0000-0000-0000-000000000840"
TARGET_TIME = dt.datetime(2026, 11, 2, 14, 30, tzinfo=dt.UTC)
WEIGHTS_TIME = dt.datetime(2026, 11, 9, 0, 0, tzinfo=dt.UTC)
CAPTURE_TIME = dt.datetime(2026, 11, 9, 15, 0, tzinfo=dt.UTC)
CONTEXT = object()


class FakeMarkets:
    """The core tables the planner and the allocation read, and the holdings write."""

    def __init__(self) -> None:
        self.accounts = [{"uid": ACCOUNT_UID, "account_name": "Paper"}]
        self.holdings_sets = [
            {"uid": HOLDINGS_SET_UID, "account_uid": ACCOUNT_UID, "time_index": CAPTURE_TIME}
        ]
        self.allocations = [
            {"uid": TARGET_ALLOCATION_UID, "account_uid": ACCOUNT_UID, "is_active": True}
        ]
        self.position_sets = [
            {
                "uid": POSITION_SET_UID,
                "account_target_allocation_uid": TARGET_ALLOCATION_UID,
                "position_set_time": TARGET_TIME,
            }
        ]
        self.target_rows = [
            {
                "time_index": TARGET_TIME,
                "position_set_uid": POSITION_SET_UID,
                "target_type": "portfolio",
                "target_uid": PORTFOLIO_UID,
                "portfolio_uid": PORTFOLIO_UID,
                "weight_notional_exposure": 0.10,
            }
        ]
        self.holdings = [
            {"asset_identifier": "BTC", "quantity": 10, "direction": 1},
            {"asset_identifier": "ETH", "quantity": 20, "direction": 1},
            {"asset_identifier": "USD", "quantity": 5_000, "direction": 1},
        ]
        self.assets = [
            {"uid": BTC_UID, "unique_identifier": "BTC"},
            {"uid": ETH_UID, "unique_identifier": "ETH"},
            {"uid": USD_UID, "unique_identifier": "USD"},
        ]
        self.weights = [
            {
                "time_index": WEIGHTS_TIME,
                "portfolio_identifier": "example-portfolio",
                "asset_identifier": "BTC",
                "weight": 0.4,
                "price_current": 60_000.0,
            },
            {
                "time_index": WEIGHTS_TIME,
                "portfolio_identifier": "example-portfolio",
                "asset_identifier": "ETH",
                "weight": 0.6,
                "price_current": 2_000.0,
            },
        ]
        self.funds: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []
        self.weight_reads: list[tuple[list[str], dt.datetime]] = []

    def search_model(self, context, *, model, filters=None, in_filters=None, limit=500, **kwargs):
        filters = dict(filters or {})
        in_filters = {
            key: [str(value) for value in values] for key, values in (in_filters or {}).items()
        }
        tables = {
            "AccountTable": self.accounts,
            "AccountHoldingsSetTable": self.holdings_sets,
            "AccountTargetAllocationTable": self.allocations,
            "PositionSetTable": self.position_sets,
            "TargetPositionsStorage": self.target_rows,
            "AssetTable": self.assets,
            "PortfolioTable": [{"uid": PORTFOLIO_UID, "unique_identifier": "example-portfolio"}],
            "VirtualFundTable": self.funds,
        }
        if model.__name__ == "AccountHoldingsStorage":
            assert filters == {"holdings_set_uid": HOLDINGS_SET_UID}
            return {"rows": self.holdings}
        rows = [
            row
            for row in tables[model.__name__]
            if all(row.get(key) == value for key, value in filters.items())
            and all(str(row.get(key)) in values for key, values in in_filters.items())
        ]
        return {"rows": rows[:limit]}

    def read_weights(self, identifiers, valuation_time):
        self.weight_reads.append((list(identifiers), valuation_time))
        return self.weights

    def replace(self, context, **kwargs):
        self.writes.append(kwargs)
        rows = []
        for fund in kwargs["funds"]:
            fund_uid = str(uuid.uuid5(uuid.NAMESPACE_URL, fund["unique_identifier"]))
            self.funds.append({"uid": fund_uid, "unique_identifier": fund["unique_identifier"]})
            set_uid = str(uuid.uuid4())
            rows.extend(
                {"virtual_fund_uid": fund_uid, "virtual_fund_holdings_set_uid": set_uid}
                for _ in fund["holdings"]
            )
        return {"rows": rows}


@pytest.fixture
def markets(monkeypatch) -> FakeMarkets:
    fake = FakeMarkets()
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime", lambda **kwargs: SimpleNamespace(context=CONTEXT)
    )
    monkeypatch.setattr("msm.repositories.crud.search_model", fake.search_model)
    monkeypatch.setattr(
        "msm.repositories.virtual_funds.replace_account_virtual_fund_holdings", fake.replace
    )
    return fake


def _allocate(markets: FakeMarkets, **overrides: Any) -> dict[str, Any] | None:
    arguments = {
        "account_uid": ACCOUNT_UID,
        "holdings_set_uid": HOLDINGS_SET_UID,
        "valuation_asset_uid": USD_UID,
        "allocation_policy": account_allocation_policy(),
        "portfolio_weights_reader": markets.read_weights,
        **overrides,
    }
    return allocate_account_holdings_set(CONTEXT, **arguments)


def test_dry_run_plans_a_later_capture_against_the_target_in_force(markets) -> None:
    result = _allocate(markets)

    assert result is not None
    assert markets.writes == []
    assert result["applied"] is False
    assert result["position_set_uid"] == POSITION_SET_UID
    assert result["valuation_time"] == CAPTURE_TIME
    assert markets.weight_reads == [(["example-portfolio"], CAPTURE_TIME)]
    # 10 BTC at 60,000 + 20 ETH at 2,000 + 5,000 USD at one.
    assert result["account_nav"] == pytest.approx(645_000)
    allocated = {
        line["asset_identifier"]: line["allocated_signed_quantity"]
        for line in result["allocations"]
        if line["claim_type"] == "virtual_fund_target"
    }
    assert allocated == pytest.approx({"BTC": 64_500 * 0.4 / 60_000, "ETH": 64_500 * 0.6 / 2_000})
    [fund] = result["funds"]
    assert fund["target_portfolio_uid"] == PORTFOLIO_UID
    assert fund["virtual_fund_uid"] is None
    assert fund["allocated_notional"] == pytest.approx(64_500)
    assert [warning["code"] for warning in result["warnings"]] == ["portfolio_weights_as_of"]
    assert {residual["asset_identifier"] for residual in result["residuals"]} == {
        "BTC",
        "ETH",
        "USD",
    }


def test_apply_writes_each_fund_for_the_snapshot(markets) -> None:
    result = _allocate(markets, apply=True)

    assert result is not None and result["applied"] is True
    [write] = markets.writes
    assert write["account_uid"] == ACCOUNT_UID
    assert write["source_account_holdings_set_uid"] == HOLDINGS_SET_UID
    assert write["allocation_time"] == CAPTURE_TIME
    [fund] = write["funds"]
    assert fund["target_portfolio_uid"] == PORTFOLIO_UID
    assert fund["unique_identifier"].startswith("account-virtual-fund-")
    assert {row["asset_identifier"]: row["direction"] for row in fund["holdings"]} == {
        "BTC": 1,
        "ETH": 1,
    }
    assert {row["allocation_strategy"] for row in fund["holdings"]} == {"proportional_attribution"}
    [answered] = result["funds"]
    assert answered["virtual_fund_uid"] == markets.funds[0]["uid"]
    assert answered["holdings_set_uid"] is not None


def test_an_asset_without_an_ms_markets_price_fails(markets) -> None:
    markets.holdings.append({"asset_identifier": "SOL", "quantity": 3, "direction": 1})
    markets.assets.append({"uid": str(uuid.uuid4()), "unique_identifier": "SOL"})

    with pytest.raises(ValueError, match=r"no price for \['SOL'\]"):
        _allocate(markets)


def test_reject_requires_weights_at_the_capture_time(markets) -> None:
    with pytest.raises(ValueError, match="stale_data_policy is reject"):
        _allocate(markets, allocation_policy=account_allocation_policy(stale_data_policy="reject"))


def test_a_strict_infeasible_plan_is_answered_but_never_applied(markets) -> None:
    markets.target_rows[0]["weight_notional_exposure"] = 2.0
    policy = account_allocation_policy(mode="strict_feasible")

    dry_run = _allocate(markets, allocation_policy=policy)
    assert dry_run is not None and dry_run["status"] == "infeasible" and dry_run["deficits"]

    with pytest.raises(ValueError, match="infeasible"):
        _allocate(markets, allocation_policy=policy, apply=True)
    assert markets.writes == []


def test_the_default_target_is_the_latest_at_or_before_the_capture(markets) -> None:
    later_uid = str(uuid.uuid4())
    markets.position_sets.append(
        {
            "uid": later_uid,
            "account_target_allocation_uid": TARGET_ALLOCATION_UID,
            "position_set_time": CAPTURE_TIME + dt.timedelta(minutes=1),
        }
    )

    result = _allocate(markets)

    assert result is not None and result["position_set_uid"] == POSITION_SET_UID


def test_a_cleared_target_leaves_nothing_in_force(markets) -> None:
    markets.allocations[0]["is_active"] = False

    with pytest.raises(ValueError, match="no active target in force"):
        _allocate(markets)


def test_another_accounts_snapshot_or_target_is_not_found(markets) -> None:
    markets.holdings_sets[0]["account_uid"] = str(uuid.uuid4())
    with pytest.raises(LookupError, match="holdings set"):
        _allocate(markets)

    markets.holdings_sets[0]["account_uid"] = ACCOUNT_UID
    markets.allocations[0]["account_uid"] = str(uuid.uuid4())
    with pytest.raises(LookupError, match="is not a target of account"):
        _allocate(markets, position_set_uid=POSITION_SET_UID)


def test_an_unknown_account_answers_none(markets) -> None:
    assert _allocate(markets, account_uid=str(uuid.uuid4())) is None
    assert _allocate(markets, account_uid="missing-account") is None
