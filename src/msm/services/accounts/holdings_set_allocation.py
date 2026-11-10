"""Allocate one account holdings snapshot to its virtual funds inside the Markets API.

The planner and its apply (ADR 0029) need a valuation, the target portfolios'
weights and the core tables. This module runs them for an application that
reaches ms-markets only through the Markets API:

- the holdings snapshot is the ``AccountHoldingsSet`` the caller names, and its
  time is the valuation time;
- the target is the caller's ``PositionSet`` or, by default, the target in
  force at the snapshot's time: the latest ``PositionSet`` at or before it of
  the account's active target allocations;
- the valuation is ms-markets' own. The valuation asset (the account's cash) is
  worth one. Every other asset is worth the ``price_current`` of its latest
  target-portfolio weights row at or before the valuation time, the same rows
  that split each portfolio target across its assets. An asset with no such
  price fails the run;
- when applied, the funds and their holdings are written to the core
  ``VirtualFund``, ``VirtualFundHoldingsSet`` and ``VirtualFundHoldingsStorage``
  tables in one statement, replacing what the account's funds held for that
  snapshot.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from msm.repositories.base import MarketsRepositoryContext
from msm.settings import ASSET_IDENTIFIER_DIMENSION

from .account_virtual_allocations import (
    ALLOCATION_MODE_STRICT_FEASIBLE,
    CLAIM_TYPE_VIRTUAL_FUND_TARGET,
    PLAN_STATUS_INFEASIBLE,
    AccountVirtualFundAllocationPlan,
    AllocationPolicy,
    AllocationValuation,
    HoldingsSelectionPolicy,
    HoldingValuationInput,
    TargetNotionalDemand,
    TargetQuantityDemand,
    ValuationDiagnostic,
    ValuationMetricLine,
    ValuationMetricResult,
    ValuationMetricValue,
    ValuationPolicy,
    expand_portfolio_target_rows,
    plan_account_virtual_fund_allocations,
    virtual_fund_holdings_from_plan,
)

PortfolioWeightsReader = Callable[[Sequence[str], dt.datetime], Sequence[Mapping[str, Any]]]
"""``(portfolio identifiers, valuation_time)`` -> each portfolio's latest weights rows at or
before ``valuation_time``: ``time_index``, ``portfolio_identifier``, ``asset_identifier``,
``weight`` and ``price_current``."""

StaleDataPolicy = Literal["allow_latest", "reject"]
PORTFOLIO_PRICE_SOURCE = "portfolio_weights.price_current"
VALUATION_ASSET_SOURCE = "valuation_asset"
SCAN_LIMIT = 5_000


def account_allocation_policy(
    *,
    mode: str = "proportional_attribution",
    stale_data_policy: StaleDataPolicy = "allow_latest",
) -> AllocationPolicy:
    """The planner policy for one Markets API allocation request."""

    kwargs = {
        "stale_valuation_policy": stale_data_policy,
        "stale_weight_policy": stale_data_policy,
        "valuation_policy": ValuationPolicy(stale_valuation_policy=stale_data_policy),
    }
    if mode == ALLOCATION_MODE_STRICT_FEASIBLE:
        return AllocationPolicy.strict_feasible(**kwargs)
    if mode != "proportional_attribution":
        raise ValueError("allocation mode must be proportional_attribution or strict_feasible.")
    return AllocationPolicy(**kwargs)


def allocate_account_holdings_set(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    holdings_set_uid: str,
    valuation_asset_uid: str,
    allocation_policy: AllocationPolicy,
    portfolio_weights_reader: PortfolioWeightsReader,
    position_set_uid: str | None = None,
    apply: bool = False,
) -> dict[str, Any] | None:
    """Plan, and optionally apply, the virtual-fund allocation of one holdings snapshot.

    Returns ``None`` when the account does not exist. Raises ``LookupError``
    when the holdings set or the PositionSet is not the account's, and
    ``ValueError`` when the allocation cannot be planned or applied.
    """

    from msm.models import AccountHoldingsSetTable, AccountTable

    if not _is_uuid(account_uid):
        return None
    if not _is_uuid(holdings_set_uid):
        raise LookupError(f"Account holdings set {holdings_set_uid} was not found.")
    account_row = _first_row(context, AccountTable, {"uid": str(account_uid)})
    if account_row is None:
        return None
    resolved_account_uid = str(account_row["uid"])

    holdings_set_row = _first_row(context, AccountHoldingsSetTable, {"uid": str(holdings_set_uid)})
    if holdings_set_row is None or str(holdings_set_row.get("account_uid")) != resolved_account_uid:
        raise LookupError(
            f"Account holdings set {holdings_set_uid} was not found for account "
            f"{resolved_account_uid}."
        )
    valuation_time = _utc_datetime(holdings_set_row.get("time_index"), field_name="time_index")

    if position_set_uid is None:
        position_set_uid = _position_set_in_force(
            context,
            account_uid=resolved_account_uid,
            valuation_time=valuation_time,
        )
    elif not _is_uuid(position_set_uid):
        raise LookupError(f"PositionSet {position_set_uid} was not found.")
    else:
        _require_account_position_set(
            context,
            account_uid=resolved_account_uid,
            position_set_uid=position_set_uid,
        )

    pricing = _PortfolioPricing(
        context=context,
        reader=portfolio_weights_reader,
        valuation_time=valuation_time,
        valuation_asset_uid=str(valuation_asset_uid),
        stale_weight_policy=allocation_policy.stale_weight_policy,
    )
    plan = plan_account_virtual_fund_allocations(
        position_set_uid=position_set_uid,
        valuation_time=valuation_time,
        valuation_asset_uid=str(valuation_asset_uid),
        holdings_selection_policy=HoldingsSelectionPolicy(),
        valuation_resolver=pricing.resolve,
        allocation_policy=allocation_policy,
        portfolio_target_expander=pricing.expand,
    )
    if plan.source_account_holdings_set_uid != str(holdings_set_row["uid"]):
        raise ValueError(
            f"The planner selected holdings set {plan.source_account_holdings_set_uid}, "
            f"not {holdings_set_row['uid']}."
        )

    written_funds: dict[str, dict[str, str]] = {}
    if apply:
        written_funds = _apply_plan(context, plan)
    return _plan_response(plan, applied=apply, written_funds=written_funds)


@dataclass
class _PortfolioPrice:
    price: float
    as_of: dt.datetime
    portfolio_identifier: str


@dataclass
class _PortfolioPricing:
    """Expands portfolio targets and values assets from the same weights rows."""

    context: MarketsRepositoryContext
    reader: PortfolioWeightsReader
    valuation_time: dt.datetime
    valuation_asset_uid: str
    stale_weight_policy: str
    prices: dict[str, _PortfolioPrice] = field(default_factory=dict)
    diagnostics: list[ValuationDiagnostic] = field(default_factory=list)

    def expand(self, portfolio_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        from msm.models import PortfolioTable

        portfolio_uids = sorted({str(row["portfolio_uid"]) for row in portfolio_rows})
        portfolio_identifier_by_uid = {
            str(row["uid"]): str(row["unique_identifier"])
            for row in _rows(
                context=self.context, model=PortfolioTable, in_filters={"uid": portfolio_uids}
            )
        }
        missing = sorted(set(portfolio_uids) - set(portfolio_identifier_by_uid))
        if missing:
            raise ValueError(f"Could not resolve PortfolioTable rows for {missing}.")
        weight_rows = list(
            self.reader(sorted(set(portfolio_identifier_by_uid.values())), self.valuation_time)
        )
        self._record_weights(weight_rows)
        return expand_portfolio_target_rows(
            portfolio_rows,
            portfolio_identifier_by_uid=portfolio_identifier_by_uid,
            weight_rows=weight_rows,
            valuation_time=self.valuation_time,
        )

    def resolve(
        self,
        requested_metrics: Sequence[str],
        source_holdings: Sequence[HoldingValuationInput],
        target_notional_demands: Sequence[TargetNotionalDemand],
        *,
        valuation_time: dt.datetime,
        valuation_asset_uid: Any,
        valuation_policy: ValuationPolicy,
    ) -> AllocationValuation:
        unsupported = sorted(set(requested_metrics) - {"nav"})
        if unsupported:
            raise ValueError(f"The Markets API valuation does not compute {unsupported}.")

        missing: set[str] = set()
        stale: set[str] = set()

        def price_of(
            asset_uid: Any, asset_identifier: str
        ) -> tuple[float, dt.datetime, str] | None:
            if str(asset_uid) == self.valuation_asset_uid:
                return 1.0, valuation_time, VALUATION_ASSET_SOURCE
            price = self.prices.get(asset_identifier)
            if price is None:
                missing.add(asset_identifier)
                return None
            if (
                valuation_policy.stale_valuation_policy == "reject"
                and price.as_of != valuation_time
            ):
                stale.add(asset_identifier)
            return (
                price.price,
                price.as_of,
                f"{PORTFOLIO_PRICE_SOURCE}:{price.portfolio_identifier}",
            )

        nav_lines: list[ValuationMetricLine] = []
        for holding in source_holdings:
            priced = price_of(holding.asset_uid, holding.asset_identifier)
            if priced is None:
                continue
            price, as_of, source = priced
            nav_lines.append(
                ValuationMetricLine(
                    line_key=f"holding:{holding.asset_identifier}",
                    value=holding.quantity * holding.direction * price,
                    valuation_asset_uid=valuation_asset_uid,
                    as_of=as_of,
                    asset_uid=holding.asset_uid,
                    asset_identifier=holding.asset_identifier,
                    source=source,
                )
            )
        quantity_demands: list[TargetQuantityDemand] = []
        for demand in target_notional_demands:
            priced = price_of(demand.asset_uid, demand.asset_identifier)
            if priced is None:
                continue
            quantity_demands.append(
                TargetQuantityDemand(
                    target_row_key=demand.target_row_key,
                    asset_uid=demand.asset_uid,
                    asset_identifier=demand.asset_identifier,
                    requested_signed_quantity=demand.notional_value / priced[0],
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
            )
        if missing:
            raise ValueError(
                f"ms-markets has no price for {sorted(missing)} at or before "
                f"{valuation_time.isoformat()}. The Markets API values the valuation asset at one "
                "and every other asset at its target portfolios' latest weights price "
                "(PortfolioWeights.price_current)."
            )
        if stale:
            raise ValueError(
                f"The latest prices of {sorted(stale)} are older than "
                f"{valuation_time.isoformat()} and stale_data_policy is reject."
            )
        return AllocationValuation(
            metrics={
                "nav": ValuationMetricResult(
                    metric="nav",
                    total=ValuationMetricValue(
                        value=sum(float(line.value) for line in nav_lines),
                        valuation_asset_uid=valuation_asset_uid,
                        as_of=valuation_time,
                        source=PORTFOLIO_PRICE_SOURCE,
                    ),
                    lines=tuple(nav_lines),
                )
            },
            valuation_asset_uid=valuation_asset_uid,
            target_quantity_demands=tuple(quantity_demands),
            diagnostics=tuple(self.diagnostics),
        )

    def _record_weights(self, weight_rows: Sequence[Mapping[str, Any]]) -> None:
        valuation_time = self.valuation_time
        times_by_portfolio: dict[str, dt.datetime] = {}
        for row in weight_rows:
            portfolio_identifier = str(row["portfolio_identifier"])
            as_of = _utc_datetime(row.get("time_index"), field_name="time_index")
            times_by_portfolio[portfolio_identifier] = as_of
            price = _positive_float(row.get("price_current"))
            if price is None:
                continue
            asset_identifier = str(row[ASSET_IDENTIFIER_DIMENSION])
            current = self.prices.get(asset_identifier)
            if current is None or as_of > current.as_of:
                self.prices[asset_identifier] = _PortfolioPrice(price, as_of, portfolio_identifier)
        for portfolio_identifier, as_of in sorted(times_by_portfolio.items()):
            if as_of == valuation_time:
                continue
            if self.stale_weight_policy == "reject":
                raise ValueError(
                    f"Portfolio {portfolio_identifier!r} has no weights at "
                    f"{valuation_time.isoformat()} (latest {as_of.isoformat()}) and "
                    "stale_data_policy is reject."
                )
            self.diagnostics.append(
                ValuationDiagnostic(
                    code="portfolio_weights_as_of",
                    message=(
                        f"Portfolio {portfolio_identifier!r} was expanded and priced with its "
                        f"weights from {as_of.isoformat()}, before the holdings snapshot."
                    ),
                    severity="warning",
                    details={
                        "portfolio_identifier": portfolio_identifier,
                        "weights_time": as_of.isoformat(),
                    },
                )
            )


def _apply_plan(
    context: MarketsRepositoryContext,
    plan: AccountVirtualFundAllocationPlan,
) -> dict[str, dict[str, str]]:
    from msm.models import VirtualFundTable
    from msm.repositories.virtual_funds import replace_account_virtual_fund_holdings

    if plan.status == PLAN_STATUS_INFEASIBLE:
        raise ValueError(
            f"The allocation is infeasible under strict_feasible ({len(plan.deficits)} asset "
            "deficits); nothing was written. Run it without apply to see the deficits."
        )
    funds = virtual_fund_holdings_from_plan(plan)
    _refuse_retired_portfolios(context, plan, funds)
    written = _rows_of(
        replace_account_virtual_fund_holdings(
            context,
            account_uid=plan.account_uid,
            source_account_holdings_set_uid=plan.source_account_holdings_set_uid,
            allocation_time=plan.valuation_time,
            funds=funds,
        )
    )
    expected = sum(len(fund["holdings"]) for fund in funds)
    if len(written) != expected:
        raise RuntimeError(
            f"The virtual-fund holdings write stored {len(written)} of {expected} rows; a virtual "
            "fund with one of these identifiers may belong to another account."
        )
    holdings_set_by_fund_uid = {
        str(row["virtual_fund_uid"]): str(row["virtual_fund_holdings_set_uid"]) for row in written
    }
    fund_rows = _rows(
        context=context,
        model=VirtualFundTable,
        in_filters={"uid": sorted(holdings_set_by_fund_uid)},
    )
    return {
        str(row["unique_identifier"]): {
            "virtual_fund_uid": str(row["uid"]),
            "holdings_set_uid": holdings_set_by_fund_uid[str(row["uid"])],
        }
        for row in fund_rows
    }


def _plan_response(
    plan: AccountVirtualFundAllocationPlan,
    *,
    applied: bool,
    written_funds: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    lines_by_fund: dict[str, list[Any]] = {}
    portfolio_by_fund: dict[str, str | None] = {}
    for line in plan.virtual_fund_allocations:
        metadata = plan.virtual_fund_metadata.get(line.claim_uid, {})
        unique_identifier = str(metadata.get("virtual_fund_unique_identifier") or line.claim_uid)
        lines_by_fund.setdefault(unique_identifier, []).append(line)
        portfolio_by_fund[unique_identifier] = (
            str(metadata.get("target_portfolio_uid") or line.target_portfolio_uid or "") or None
        )

    funds = []
    for unique_identifier, lines in sorted(lines_by_fund.items()):
        written = written_funds.get(unique_identifier, {})
        funds.append(
            {
                "virtual_fund_unique_identifier": unique_identifier,
                "target_portfolio_uid": portfolio_by_fund[unique_identifier],
                "virtual_fund_uid": written.get("virtual_fund_uid"),
                "holdings_set_uid": written.get("holdings_set_uid"),
                "requested_notional": _sum_known(line.requested_notional for line in lines),
                "allocated_notional": _sum_known(line.allocated_notional for line in lines),
            }
        )

    return {
        "account_uid": plan.account_uid,
        "holdings_set_uid": plan.source_account_holdings_set_uid,
        "position_set_uid": plan.position_set_uid,
        "valuation_time": plan.valuation_time,
        "valuation_asset_uid": plan.valuation_asset_uid,
        "allocation_mode": plan.allocation_policy.mode,
        "status": plan.status,
        "account_nav": plan.account_nav,
        "applied": applied,
        "funds": funds,
        "allocations": [
            {
                "claim_type": line.claim_type,
                "claim_uid": line.claim_uid,
                "virtual_fund_unique_identifier": (
                    line.virtual_fund_unique_identifier
                    if line.claim_type == CLAIM_TYPE_VIRTUAL_FUND_TARGET
                    else None
                ),
                "target_portfolio_uid": line.target_portfolio_uid,
                "target_row_key": line.target_row_key,
                "asset_uid": line.asset_uid,
                "asset_identifier": line.asset_identifier,
                "requested_direction": line.requested_direction,
                "requested_signed_quantity": line.requested_signed_quantity,
                "allocated_signed_quantity": line.allocated_signed_quantity,
                "target_gap_signed_quantity": line.target_gap_signed_quantity,
                "requested_notional": line.requested_notional,
                "allocated_notional": line.allocated_notional,
                "target_gap_notional": line.target_gap_notional,
                "scale": line.scale,
            }
            for line in plan.account_virtual_holding_lines
        ],
        "residuals": [
            {
                "asset_uid": row.asset_uid,
                "asset_identifier": row.asset_identifier,
                "signed_account_holding": row.signed_account_holding,
                "virtual_allocated_signed_quantity": row.virtual_allocated_signed_quantity,
                "direct_sleeve_signed_quantity": row.direct_sleeve_signed_quantity,
                "direct_target_signed_quantity": row.direct_target_signed_quantity,
                "direct_target_gap_signed_quantity": row.direct_target_gap_signed_quantity,
                "scale": row.scale,
            }
            for row in plan.residuals
        ],
        "deficits": [
            {
                "asset_uid": row.asset_uid,
                "asset_identifier": row.asset_identifier,
                "gross_source_capacity": row.gross_source_capacity,
                "virtual_gross_demand": row.virtual_gross_demand,
                "deficit_abs_quantity": row.deficit_abs_quantity,
                "scale": row.scale,
            }
            for row in plan.deficits
        ],
        "warnings": [
            {
                "code": diagnostic.code,
                "message": diagnostic.message,
                "severity": diagnostic.severity,
                "details": dict(diagnostic.details),
            }
            for diagnostic in plan.diagnostics
        ],
    }


def _position_set_in_force(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    valuation_time: dt.datetime,
) -> str:
    from msm.models import AccountTargetAllocationTable, PositionSetTable

    allocation_uids = [
        str(row["uid"])
        for row in _rows(
            context=context,
            model=AccountTargetAllocationTable,
            filters={"account_uid": account_uid, "is_active": True},
        )
    ]
    candidates: list[tuple[dt.datetime, str]] = []
    if allocation_uids:
        for row in _rows(
            context=context,
            model=PositionSetTable,
            in_filters={"account_target_allocation_uid": allocation_uids},
        ):
            position_set_time = _utc_datetime(
                row.get("position_set_time"), field_name="position_set_time"
            )
            if position_set_time <= valuation_time:
                candidates.append((position_set_time, str(row["uid"])))
    if not candidates:
        raise ValueError(
            f"Account {account_uid} has no active target in force at {valuation_time.isoformat()}; "
            "pass position_set_uid to allocate against a specific target."
        )
    return max(candidates)[1]


def _require_account_position_set(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    position_set_uid: str,
) -> None:
    from msm.models import AccountTargetAllocationTable, PositionSetTable

    position_set_row = _first_row(context, PositionSetTable, {"uid": str(position_set_uid)})
    allocation_row = (
        _first_row(
            context,
            AccountTargetAllocationTable,
            {"uid": str(position_set_row.get("account_target_allocation_uid"))},
        )
        if position_set_row is not None
        else None
    )
    if allocation_row is None or str(allocation_row.get("account_uid")) != account_uid:
        raise LookupError(
            f"PositionSet {position_set_uid} is not a target of account {account_uid}."
        )


def _first_row(
    context: MarketsRepositoryContext,
    model: Any,
    filters: Mapping[str, Any],
) -> dict[str, Any] | None:
    rows = _rows(context=context, model=model, filters=filters, limit=1)
    return rows[0] if rows else None


def _refuse_retired_portfolios(
    context: MarketsRepositoryContext,
    plan: AccountVirtualFundAllocationPlan,
    funds: Sequence[Mapping[str, Any]],
) -> None:
    """No fund or fund holdings for a portfolio retired at or before the snapshot (ADR 0049)."""

    from msm.services.portfolio_lifecycle import PortfolioRetiredError, retired_portfolios

    retired = retired_portfolios(
        context,
        (fund["target_portfolio_uid"] for fund in funds),
        as_of=plan.valuation_time,
    )
    if retired:
        raise PortfolioRetiredError(
            retired,
            action=(
                f"The virtual-fund allocation of account {plan.account_uid} at "
                f"{plan.valuation_time.isoformat()}"
            ),
        )


def _rows(
    *,
    context: MarketsRepositoryContext,
    model: Any,
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    limit: int = SCAN_LIMIT,
) -> list[dict[str, Any]]:
    from msm.repositories.crud import search_model

    kwargs: dict[str, Any] = {"model": model, "limit": limit}
    if filters:
        kwargs["filters"] = dict(filters)
    if in_filters:
        kwargs["in_filters"] = dict(in_filters)
    return _rows_of(search_model(context, **kwargs))


def _rows_of(result: Any) -> list[dict[str, Any]]:
    from msm.api.base import operation_result_rows

    return [dict(row) for row in operation_result_rows(result) if isinstance(row, Mapping)]


def _utc_datetime(value: Any, *, field_name: str) -> dt.datetime:
    """Read a stored timestamp as UTC, as the planner does (naive values are UTC)."""

    if value in (None, ""):
        raise ValueError(f"{field_name} is required.")
    return pd.to_datetime(value, utc=True).to_pydatetime()


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number) or number <= 0:
        return None
    return number


def _sum_known(values: Any) -> float | None:
    known = [float(value) for value in values if value is not None]
    return sum(known) if known else None


__all__ = [
    "PortfolioWeightsReader",
    "account_allocation_policy",
    "allocate_account_holdings_set",
]
