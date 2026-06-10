from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

import pandas as pd

from msm.settings import ASSET_IDENTIFIER_DIMENSION

TARGET_TYPE_ASSET = "asset"
TARGET_TYPE_PORTFOLIO = "portfolio"
ALLOCATION_MODE_PROPORTIONAL_ATTRIBUTION = "proportional_attribution"
ALLOCATION_MODE_STRICT_FEASIBLE = "strict_feasible"
CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL = "direct_account_residual"
CLAIM_TYPE_VIRTUAL_FUND_TARGET = "virtual_fund_target"
PLAN_STATUS_ATTRIBUTED_WITH_TARGET_GAP = "attributed_with_target_gap"
PLAN_STATUS_FEASIBLE = "feasible"
PLAN_STATUS_INFEASIBLE = "infeasible"
DEFAULT_ALLOCATION_SCAN_LIMIT = 5_000
REQUIRED_ALLOCATION_METRICS = ("nav",)


@dataclass(frozen=True, slots=True)
class ValuationPolicy:
    stale_valuation_policy: Literal["reject", "allow_latest"] = "reject"
    valuation_tolerance: float = 1e-9
    rules: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AllocationPolicy:
    mode: Literal["proportional_attribution", "strict_feasible"] = (
        ALLOCATION_MODE_PROPORTIONAL_ATTRIBUTION
    )
    quantity_tolerance: float = 1e-9
    valuation_tolerance: float = 1e-9
    residual_policy: Literal["leave_as_account_residual"] = "leave_as_account_residual"
    leverage_policy: Literal["attribute_without_borrow", "reject"] = "attribute_without_borrow"
    shortage_policy: Literal["proportional_target_gap", "fail"] = "proportional_target_gap"
    stale_valuation_policy: Literal["reject", "allow_latest"] = "reject"
    stale_weight_policy: Literal["reject", "allow_latest"] = "reject"
    rounding_policy: Literal["none"] = "none"
    idempotency_mode: Literal["replace_same_allocation_run", "fail_if_existing"] = (
        "replace_same_allocation_run"
    )
    valuation_policy: ValuationPolicy = field(default_factory=ValuationPolicy)

    @classmethod
    def strict_feasible(cls, **kwargs: Any) -> AllocationPolicy:
        return cls(
            mode=ALLOCATION_MODE_STRICT_FEASIBLE,
            shortage_policy="fail",
            **kwargs,
        )


@dataclass(frozen=True, slots=True)
class HoldingsSelectionPolicy:
    mode: Literal["exact_valuation_time"] = "exact_valuation_time"


@dataclass(frozen=True, slots=True)
class HoldingValuationInput:
    asset_uid: uuid.UUID | str
    asset_identifier: str
    quantity: float
    direction: Literal[1, -1]
    source_row: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TargetNotionalDemand:
    target_row_key: str
    asset_uid: uuid.UUID | str
    asset_identifier: str
    notional_value: float
    direction: Literal[1, -1]
    claim_type: str
    claim_uid: str
    requested_notional: float | None = None
    source_target_uid: uuid.UUID | str | None = None
    target_type: str | None = None
    target_portfolio_uid: uuid.UUID | str | None = None
    virtual_fund_unique_identifier: str | None = None
    source_row: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TargetQuantityDemand:
    target_row_key: str
    asset_uid: uuid.UUID | str
    asset_identifier: str
    requested_signed_quantity: float
    direction: Literal[1, -1]
    requested_notional: float | None = None
    claim_type: str = CLAIM_TYPE_VIRTUAL_FUND_TARGET
    claim_uid: str | None = None
    source_target_uid: uuid.UUID | str | None = None
    target_type: str | None = None
    target_portfolio_uid: uuid.UUID | str | None = None
    virtual_fund_unique_identifier: str | None = None
    source_row: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValuationMetricValue:
    value: float | Mapping[str, Any]
    valuation_asset_uid: uuid.UUID | str | None
    as_of: dt.datetime
    source: str | None = None


@dataclass(frozen=True, slots=True)
class ValuationMetricLine:
    line_key: str
    value: float | Mapping[str, Any]
    valuation_asset_uid: uuid.UUID | str | None
    as_of: dt.datetime
    asset_uid: uuid.UUID | str | None = None
    asset_identifier: str | None = None
    source_row_key: str | None = None
    target_row_key: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class ValuationMetricResult:
    metric: str
    total: ValuationMetricValue
    lines: tuple[ValuationMetricLine, ...] = ()


@dataclass(frozen=True, slots=True)
class ValuationDiagnostic:
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "info"
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AllocationValuation:
    metrics: Mapping[str, ValuationMetricResult]
    valuation_asset_uid: uuid.UUID | str
    valuation_asset_identifier: str | None = None
    target_quantity_demands: tuple[TargetQuantityDemand, ...] = ()
    diagnostics: tuple[ValuationDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class AccountVirtualFundAllocationInputs:
    account_uid: uuid.UUID | str
    source_account_holdings_set_uid: uuid.UUID | str
    source_holdings: tuple[HoldingValuationInput, ...]
    direct_target_demands: tuple[TargetQuantityDemand, ...] = ()
    virtual_fund_demands: tuple[TargetQuantityDemand, ...] = ()
    target_notional_demands: tuple[TargetNotionalDemand, ...] = ()
    account_nav: float | None = None
    diagnostics: tuple[ValuationDiagnostic, ...] = ()


class ValuationResolver(Protocol):
    def __call__(
        self,
        requested_metrics: Sequence[str],
        source_holdings: Sequence[HoldingValuationInput],
        target_notional_demands: Sequence[TargetNotionalDemand],
        *,
        valuation_time: dt.datetime,
        valuation_asset_uid: uuid.UUID | str,
        valuation_policy: ValuationPolicy,
    ) -> AllocationValuation: ...


PortfolioTargetExpander = Callable[
    [Sequence[Mapping[str, Any]]],
    Sequence[TargetNotionalDemand | TargetQuantityDemand | Mapping[str, Any]],
]


@dataclass(frozen=True, slots=True)
class AccountVirtualHoldingLine:
    claim_type: str
    claim_uid: str
    asset_uid: str
    asset_identifier: str
    requested_direction: Literal[1, -1]
    requested_signed_quantity: float
    allocated_signed_quantity: float
    target_gap_signed_quantity: float
    requested_abs_quantity: float
    allocated_abs_quantity: float
    target_gap_abs_quantity: float
    requested_notional: float | None
    allocated_notional: float | None
    target_gap_notional: float | None
    scale: float
    target_row_key: str | None = None
    source_target_uid: str | None = None
    target_type: str | None = None
    target_portfolio_uid: str | None = None
    virtual_fund_unique_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class AccountAllocationResidual:
    asset_uid: str
    asset_identifier: str
    signed_account_holding: float
    gross_source_capacity: float
    virtual_gross_demand: float
    virtual_allocated_signed_quantity: float
    direct_sleeve_signed_quantity: float
    direct_target_signed_quantity: float
    direct_target_gap_signed_quantity: float
    scale: float


@dataclass(frozen=True, slots=True)
class AccountAllocationDeficit:
    asset_uid: str
    asset_identifier: str
    gross_source_capacity: float
    virtual_gross_demand: float
    deficit_abs_quantity: float
    scale: float


@dataclass(frozen=True, slots=True)
class AccountVirtualFundAllocationPlan:
    status: str
    valuation_time: dt.datetime
    valuation_asset_uid: str
    allocation_policy: AllocationPolicy
    position_set_uid: str | None = None
    account_uid: str | None = None
    source_account_holdings_set_uid: str | None = None
    account_nav: float | None = None
    source_holdings: tuple[HoldingValuationInput, ...] = ()
    direct_target_demands: tuple[TargetQuantityDemand, ...] = ()
    virtual_fund_demands: tuple[TargetQuantityDemand, ...] = ()
    account_virtual_holding_lines: tuple[AccountVirtualHoldingLine, ...] = ()
    virtual_fund_allocations: tuple[AccountVirtualHoldingLine, ...] = ()
    residuals: tuple[AccountAllocationResidual, ...] = ()
    deficits: tuple[AccountAllocationDeficit, ...] = ()
    diagnostics: tuple[ValuationDiagnostic, ...] = ()
    virtual_fund_metadata: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_frames(self) -> dict[str, pd.DataFrame]:
        return {
            "account_virtual_holding_lines": pd.DataFrame(
                [asdict(line) for line in self.account_virtual_holding_lines]
            ),
            "virtual_fund_allocations": pd.DataFrame(
                [asdict(line) for line in self.virtual_fund_allocations]
            ),
            "residuals": pd.DataFrame([asdict(row) for row in self.residuals]),
            "deficits": pd.DataFrame([asdict(row) for row in self.deficits]),
            "diagnostics": pd.DataFrame([asdict(row) for row in self.diagnostics]),
        }


def plan_account_virtual_fund_allocations(
    *,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
    valuation_asset_uid: uuid.UUID | str,
    holdings_selection_policy: HoldingsSelectionPolicy,
    valuation_resolver: ValuationResolver,
    allocation_policy: AllocationPolicy,
) -> AccountVirtualFundAllocationPlan:
    """Plan account-to-virtual-fund attribution from one PositionSet."""

    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    resolved_inputs = resolve_account_virtual_fund_allocation_inputs(
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
        valuation_asset_uid=valuation_asset_uid,
        valuation_resolver=valuation_resolver,
        holdings_selection_policy=holdings_selection_policy,
        allocation_policy=allocation_policy,
    )
    return _plan_account_virtual_fund_allocations_from_resolved_inputs(
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
        valuation_asset_uid=valuation_asset_uid,
        requested_metrics=REQUIRED_ALLOCATION_METRICS,
        valuation_resolver=valuation_resolver,
        allocation_policy=allocation_policy,
        source_holdings=resolved_inputs.source_holdings,
        direct_target_demands=resolved_inputs.direct_target_demands,
        virtual_fund_demands=resolved_inputs.virtual_fund_demands,
        target_notional_demands=resolved_inputs.target_notional_demands,
        account_uid=resolved_inputs.account_uid,
        source_account_holdings_set_uid=resolved_inputs.source_account_holdings_set_uid,
        account_nav=resolved_inputs.account_nav,
        diagnostics=resolved_inputs.diagnostics,
    )


def _plan_account_virtual_fund_allocations_from_resolved_inputs(
    *,
    valuation_time: dt.datetime,
    valuation_asset_uid: uuid.UUID | str,
    source_holdings: Sequence[HoldingValuationInput | Mapping[str, Any]] | pd.DataFrame,
    virtual_fund_demands: Sequence[TargetQuantityDemand | Mapping[str, Any]] | pd.DataFrame | None,
    position_set_uid: uuid.UUID | str | None = None,
    requested_metrics: Sequence[str] | None = None,
    valuation_resolver: ValuationResolver | None = None,
    allocation_policy: AllocationPolicy | None = None,
    direct_target_demands: Sequence[TargetQuantityDemand | Mapping[str, Any]]
    | pd.DataFrame
    | None = None,
    target_notional_demands: Sequence[TargetNotionalDemand | Mapping[str, Any]]
    | pd.DataFrame
    | None = None,
    account_uid: uuid.UUID | str | None = None,
    source_account_holdings_set_uid: uuid.UUID | str | None = None,
    account_nav: float | None = None,
    diagnostics: Sequence[ValuationDiagnostic] = (),
) -> AccountVirtualFundAllocationPlan:
    """Run the vector allocation engine from already-resolved inputs."""

    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    policy = allocation_policy or AllocationPolicy()
    metric_requests = _requested_metric_names(requested_metrics)
    if "nav" not in metric_requests and account_nav is None:
        raise ValueError("Account virtual-fund planning requires the `nav` metric or account_nav.")
    if account_nav is None and valuation_resolver is None:
        raise ValueError(
            "Account virtual-fund planning requires account_nav or valuation_resolver."
        )

    holdings = _source_holdings(source_holdings)
    virtual_demands = list(
        _target_quantity_demands(
            virtual_fund_demands,
            default_claim_type=CLAIM_TYPE_VIRTUAL_FUND_TARGET,
        )
        if virtual_fund_demands is not None
        else ()
    )
    direct_demands = list(
        _target_quantity_demands(
            direct_target_demands if direct_target_demands is not None else (),
            default_claim_type=CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
        )
    )
    notional_demands = _target_notional_demands(
        target_notional_demands if target_notional_demands is not None else ()
    )

    valuation = _resolve_valuation(
        valuation_resolver=valuation_resolver,
        requested_metrics=requested_metrics or REQUIRED_ALLOCATION_METRICS,
        source_holdings=holdings,
        target_notional_demands=notional_demands,
        valuation_time=normalized_time,
        valuation_asset_uid=valuation_asset_uid,
        valuation_policy=policy.valuation_policy,
    )
    resolved_account_nav = account_nav
    resolved_diagnostics: list[ValuationDiagnostic] = list(diagnostics)
    if valuation is not None:
        resolved_diagnostics.extend(valuation.diagnostics)
        if resolved_account_nav is None:
            resolved_account_nav = _nav_total(valuation)
        valuation_demands = _target_quantity_demands(
            valuation.target_quantity_demands,
            default_claim_type=CLAIM_TYPE_VIRTUAL_FUND_TARGET,
        )
        for demand in valuation_demands:
            if demand.claim_type == CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL:
                direct_demands.append(demand)
            else:
                virtual_demands.append(demand)
    elif notional_demands:
        raise ValueError("target_notional_demands require valuation_resolver.")

    if not virtual_demands:
        raise ValueError(
            "plan_account_virtual_fund_allocations requires at least one virtual-fund demand."
        )

    return _plan_from_quantity_demands(
        position_set_uid=_optional_string(position_set_uid),
        account_uid=_optional_string(account_uid),
        source_account_holdings_set_uid=_optional_string(source_account_holdings_set_uid),
        valuation_time=normalized_time,
        valuation_asset_uid=str(valuation_asset_uid),
        allocation_policy=policy,
        account_nav=resolved_account_nav,
        source_holdings=holdings,
        direct_target_demands=tuple(direct_demands),
        virtual_fund_demands=tuple(virtual_demands),
        diagnostics=tuple(resolved_diagnostics),
    )


def apply_account_virtual_fund_allocation_plan(
    plan: AccountVirtualFundAllocationPlan,
    *,
    data_node: Any | None = None,
    run: bool = False,
) -> pd.DataFrame:
    from msm.api.virtual_funds import VirtualFund

    if plan.status == PLAN_STATUS_INFEASIBLE:
        raise ValueError("Cannot apply an infeasible virtual-fund allocation plan.")
    if plan.source_account_holdings_set_uid is None:
        raise ValueError("Plan requires source_account_holdings_set_uid before apply.")
    if plan.account_uid is None:
        raise ValueError("Plan requires account_uid before apply.")
    if not plan.virtual_fund_allocations:
        raise ValueError("Plan contains no virtual-fund allocations to apply.")

    frames: list[pd.DataFrame] = []
    for claim_uid, group_lines in _lines_by_claim(plan.virtual_fund_allocations).items():
        metadata = dict(plan.virtual_fund_metadata.get(claim_uid, {}))
        portfolio_uid = metadata.get("target_portfolio_uid") or _first_value(
            group_lines,
            "target_portfolio_uid",
        )
        if portfolio_uid in (None, ""):
            raise ValueError(f"Virtual-fund claim {claim_uid!r} is missing target_portfolio_uid.")
        virtual_fund = VirtualFund.upsert(
            {
                "unique_identifier": metadata.get("virtual_fund_unique_identifier") or claim_uid,
                "account_uid": plan.account_uid,
                "target_portfolio_uid": portfolio_uid,
            }
        )
        holdings_set_uid = _deterministic_holdings_set_uid(
            source_account_holdings_set_uid=plan.source_account_holdings_set_uid,
            virtual_fund_uid=str(virtual_fund.uid),
            valuation_time=plan.valuation_time,
        )
        allocations = [
            {
                ASSET_IDENTIFIER_DIMENSION: line.asset_identifier,
                "allocated_quantity": line.allocated_abs_quantity,
                "allocation_strategy": plan.allocation_policy.mode,
                "direction": line.requested_direction,
                "extra_details": {
                    "source": "account_virtual_allocation_plan",
                    "position_set_uid": plan.position_set_uid,
                    "target_row_key": line.target_row_key,
                    "target_gap_signed_quantity": line.target_gap_signed_quantity,
                    "scale": line.scale,
                },
            }
            for line in group_lines
            if line.allocated_abs_quantity > plan.allocation_policy.quantity_tolerance
        ]
        if not allocations:
            continue
        frames.append(
            virtual_fund.allocate_from_account_holdings_set(
                source_account_holdings_set_uid=plan.source_account_holdings_set_uid,
                allocation_time=plan.valuation_time,
                allocations=allocations,
                virtual_fund_holdings_set_uid=holdings_set_uid,
                data_node=None,
                run=False,
                validate_bounds=False,
            )
        )

    if not frames:
        raise ValueError("Plan produced no positive virtual-fund allocation rows to apply.")
    frame = pd.concat(frames).sort_index()
    if data_node is not None:
        data_node.set_frame(frame)
        if run:
            data_node.run(debug_mode=True, update_tree=False, force_update=True)
    return frame


def virtual_fund_unique_identifier_for_target(
    *,
    account_uid: uuid.UUID | str,
    target_portfolio_uid: uuid.UUID | str,
    account_target_allocation_uid: uuid.UUID | str,
) -> str:
    """Return the deterministic VirtualFund business key for one account sleeve."""

    key = (
        "msm.account_virtual_fund:"
        f"account={account_uid}:"
        f"portfolio={target_portfolio_uid}:"
        f"target_allocation={account_target_allocation_uid}"
    )
    return f"account-virtual-fund-{uuid.uuid5(uuid.NAMESPACE_URL, key)}"


def build_account_virtual_fund_allocation_inputs(
    *,
    account_uid: uuid.UUID | str,
    account_target_allocation_uid: uuid.UUID | str | None,
    position_set_uid: uuid.UUID | str,
    source_account_holdings_set_uid: uuid.UUID | str,
    account_holdings: Sequence[Mapping[str, Any]] | pd.DataFrame,
    target_positions: Sequence[Mapping[str, Any]] | pd.DataFrame,
    valuation_time: dt.datetime,
    account_nav: float | None,
    asset_uid_by_identifier: Mapping[str, uuid.UUID | str],
    asset_identifier_by_uid: Mapping[uuid.UUID | str, str],
    portfolio_target_expander: PortfolioTargetExpander | None = None,
) -> AccountVirtualFundAllocationInputs:
    """Build planner inputs from already-loaded account and target rows."""

    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    holdings = _holding_inputs_from_rows(
        account_holdings,
        asset_uid_by_identifier=asset_uid_by_identifier,
    )
    target_rows = _rows_from_records(target_positions)
    direct_demands: list[TargetQuantityDemand] = []
    virtual_demands: list[TargetQuantityDemand] = []
    notional_demands: list[TargetNotionalDemand] = []
    portfolio_rows: list[dict[str, Any]] = []

    for row in target_rows:
        if not _same_timestamp(row.get("time_index"), normalized_time):
            continue
        target_type = _required_string(row.get("target_type"), "target_type")
        if target_type == TARGET_TYPE_ASSET:
            _append_target_row_demands(
                row=row,
                claim_type=CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
                claim_uid=CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
                asset_identifier_by_uid=asset_identifier_by_uid,
                account_nav=account_nav,
                direct_demands=direct_demands,
                virtual_demands=virtual_demands,
                notional_demands=notional_demands,
            )
            continue
        if target_type != TARGET_TYPE_PORTFOLIO:
            raise ValueError("target_type must be asset or portfolio.")
        if not _is_missing(row.get("single_asset_quantity")):
            raise ValueError("Portfolio target rows cannot use single_asset_quantity directly.")
        portfolio_rows.append(row)

    if portfolio_rows:
        if account_target_allocation_uid in (None, ""):
            raise ValueError("Portfolio target rows require account_target_allocation_uid.")
        if portfolio_target_expander is None:
            raise ValueError("Portfolio target rows require portfolio_target_expander.")
        for row in _expanded_target_rows(portfolio_target_expander(portfolio_rows)):
            target_portfolio_uid = _required_string(
                row.get("portfolio_uid") or row.get("target_portfolio_uid"),
                "portfolio_uid",
            )
            asset_identifier = _optional_string(
                row.get("asset_identifier") or row.get(ASSET_IDENTIFIER_DIMENSION)
            )
            if _is_missing(row.get("asset_uid")) and asset_identifier is not None:
                row["asset_uid"] = asset_uid_by_identifier[asset_identifier]
            claim_uid = _required_string(
                row.get("claim_uid") or target_portfolio_uid,
                "claim_uid",
            )
            row.setdefault("target_type", TARGET_TYPE_PORTFOLIO)
            row.setdefault("target_portfolio_uid", target_portfolio_uid)
            row.setdefault(
                "virtual_fund_unique_identifier",
                virtual_fund_unique_identifier_for_target(
                    account_uid=account_uid,
                    target_portfolio_uid=target_portfolio_uid,
                    account_target_allocation_uid=account_target_allocation_uid,
                ),
            )
            _append_target_row_demands(
                row=row,
                claim_type=CLAIM_TYPE_VIRTUAL_FUND_TARGET,
                claim_uid=claim_uid,
                asset_identifier_by_uid=asset_identifier_by_uid,
                account_nav=account_nav,
                direct_demands=direct_demands,
                virtual_demands=virtual_demands,
                notional_demands=notional_demands,
            )

    return AccountVirtualFundAllocationInputs(
        account_uid=account_uid,
        source_account_holdings_set_uid=source_account_holdings_set_uid,
        source_holdings=tuple(holdings),
        direct_target_demands=tuple(direct_demands),
        virtual_fund_demands=tuple(virtual_demands),
        target_notional_demands=tuple(notional_demands),
        account_nav=account_nav,
    )


def resolve_account_virtual_fund_allocation_inputs(
    *,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
    valuation_asset_uid: uuid.UUID | str,
    holdings_selection_policy: HoldingsSelectionPolicy,
    valuation_resolver: ValuationResolver,
    allocation_policy: AllocationPolicy,
) -> AccountVirtualFundAllocationInputs:
    """Resolve planner inputs through the account MetaTable relationship graph."""

    from msm.api.base import operation_result_rows
    from msm.bootstrap import resolve_runtime
    from msm.data_nodes.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
    from msm.models.accounts import (
        AccountHoldingsSetTable,
        AccountTargetAllocationTable,
        PositionSetTable,
    )
    from msm.models.assets import AssetTable
    from msm.repositories.crud import search_model

    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    if holdings_selection_policy.mode != "exact_valuation_time":
        raise ValueError("Only exact_valuation_time holdings selection is currently supported.")
    context = resolve_runtime(
        models=[
            PositionSetTable,
            AccountTargetAllocationTable,
            AccountHoldingsSetTable,
            AccountHoldingsStorage,
            TargetPositionsStorage,
            AssetTable,
        ],
        row_model_name="Account virtual-fund allocation planner",
    ).context

    position_set_row = _one_row(
        operation_result_rows(
            search_model(
                context,
                model=PositionSetTable,
                filters={"uid": str(position_set_uid)},
                limit=2,
            )
        ),
        label="PositionSetTable",
        filters={"uid": str(position_set_uid)},
    )
    target_allocation_uid = _required_string(
        position_set_row.get("account_target_allocation_uid"),
        "PositionSetTable.account_target_allocation_uid",
    )
    target_allocation_row = _one_row(
        operation_result_rows(
            search_model(
                context,
                model=AccountTargetAllocationTable,
                filters={"uid": target_allocation_uid},
                limit=2,
            )
        ),
        label="AccountTargetAllocationTable",
        filters={"uid": target_allocation_uid},
    )
    account_uid = _required_string(
        target_allocation_row.get("account_uid"),
        "AccountTargetAllocationTable.account_uid",
    )
    holdings_set_row = _one_row(
        operation_result_rows(
            search_model(
                context,
                model=AccountHoldingsSetTable,
                filters={
                    "account_uid": account_uid,
                    "time_index": normalized_time,
                },
                limit=2,
            )
        ),
        label="AccountHoldingsSetTable",
        filters={"account_uid": account_uid, "time_index": normalized_time.isoformat()},
    )
    holdings_set_uid = _required_string(holdings_set_row.get("uid"), "AccountHoldingsSetTable.uid")
    account_holding_rows = operation_result_rows(
        search_model(
            context,
            model=AccountHoldingsStorage,
            filters={"holdings_set_uid": holdings_set_uid},
            limit=DEFAULT_ALLOCATION_SCAN_LIMIT,
        )
    )
    target_position_rows = [
        row
        for row in operation_result_rows(
            search_model(
                context,
                model=TargetPositionsStorage,
                filters={"position_set_uid": str(position_set_uid)},
                limit=DEFAULT_ALLOCATION_SCAN_LIMIT,
            )
        )
        if _same_timestamp(row.get("time_index"), normalized_time)
    ]
    if not target_position_rows:
        raise ValueError(
            "No TargetPositionsStorage rows found for "
            f"position_set_uid={position_set_uid!s} and valuation_time={normalized_time.isoformat()}."
        )

    expanded_portfolio_rows = _expand_portfolio_target_rows(
        target_position_rows,
        valuation_time=normalized_time,
    )
    asset_identifiers = {
        str(row[ASSET_IDENTIFIER_DIMENSION])
        for row in account_holding_rows
        if row.get(ASSET_IDENTIFIER_DIMENSION) not in (None, "")
    }
    asset_identifiers.update(
        str(row[ASSET_IDENTIFIER_DIMENSION])
        for row in expanded_portfolio_rows
        if row.get(ASSET_IDENTIFIER_DIMENSION) not in (None, "")
    )
    asset_uids = {
        str(row.get("asset_uid"))
        for row in [*target_position_rows, *expanded_portfolio_rows]
        if row.get("asset_uid") not in (None, "")
    }
    asset_rows: list[dict[str, Any]] = []
    if asset_identifiers:
        asset_rows.extend(
            operation_result_rows(
                search_model(
                    context,
                    model=AssetTable,
                    in_filters={"unique_identifier": sorted(asset_identifiers)},
                    limit=DEFAULT_ALLOCATION_SCAN_LIMIT,
                )
            )
        )
    if asset_uids:
        asset_rows.extend(
            operation_result_rows(
                search_model(
                    context,
                    model=AssetTable,
                    in_filters={"uid": sorted(asset_uids)},
                    limit=DEFAULT_ALLOCATION_SCAN_LIMIT,
                )
            )
        )
    asset_uid_by_identifier, asset_identifier_by_uid = _asset_identity_maps(asset_rows)
    missing_identifiers = sorted(asset_identifiers - set(asset_uid_by_identifier))
    missing_uids = sorted(asset_uids - set(asset_identifier_by_uid))
    if missing_identifiers or missing_uids:
        raise ValueError(
            "Could not resolve AssetTable identity for allocation inputs. "
            f"missing_identifiers={missing_identifiers}, missing_uids={missing_uids}."
        )

    nav_valuation = valuation_resolver(
        REQUIRED_ALLOCATION_METRICS,
        _holding_inputs_from_rows(
            account_holding_rows,
            asset_uid_by_identifier=asset_uid_by_identifier,
        ),
        (),
        valuation_time=normalized_time,
        valuation_asset_uid=valuation_asset_uid,
        valuation_policy=allocation_policy.valuation_policy,
    )
    return build_account_virtual_fund_allocation_inputs(
        account_uid=account_uid,
        account_target_allocation_uid=target_allocation_uid,
        position_set_uid=position_set_uid,
        source_account_holdings_set_uid=holdings_set_uid,
        account_holdings=account_holding_rows,
        target_positions=target_position_rows,
        valuation_time=normalized_time,
        account_nav=_nav_total(nav_valuation),
        asset_uid_by_identifier=asset_uid_by_identifier,
        asset_identifier_by_uid=asset_identifier_by_uid,
        portfolio_target_expander=lambda _rows: expanded_portfolio_rows,
    )


def _plan_from_quantity_demands(
    *,
    position_set_uid: str | None,
    account_uid: str | None,
    source_account_holdings_set_uid: str | None,
    valuation_time: dt.datetime,
    valuation_asset_uid: str,
    allocation_policy: AllocationPolicy,
    account_nav: float | None,
    source_holdings: tuple[HoldingValuationInput, ...],
    direct_target_demands: tuple[TargetQuantityDemand, ...],
    virtual_fund_demands: tuple[TargetQuantityDemand, ...],
    diagnostics: tuple[ValuationDiagnostic, ...],
) -> AccountVirtualFundAllocationPlan:
    holdings_frame = _holdings_vector(source_holdings)
    virtual_frame = _virtual_target_vector(virtual_fund_demands)
    direct_frame = _direct_target_vector(direct_target_demands)

    asset_frame = _asset_index_frame(holdings_frame, virtual_frame, direct_frame)
    if virtual_frame.empty:
        virtual_frame = pd.DataFrame(
            columns=[
                "claim_uid",
                "asset_uid",
                "asset_identifier",
                "requested_signed_quantity",
                "requested_notional",
                "target_row_key",
                "source_target_uid",
                "target_type",
                "target_portfolio_uid",
                "virtual_fund_unique_identifier",
            ]
        )

    demand_by_asset = (
        virtual_frame.assign(
            requested_abs_quantity=lambda frame: frame["requested_signed_quantity"].abs()
        )
        .groupby(["asset_uid", "asset_identifier"], as_index=False)["requested_abs_quantity"]
        .sum()
        .rename(columns={"requested_abs_quantity": "virtual_gross_demand"})
    )
    capacity = asset_frame.merge(
        demand_by_asset,
        on=["asset_uid", "asset_identifier"],
        how="left",
    )
    capacity["virtual_gross_demand"] = capacity["virtual_gross_demand"].fillna(0.0)
    capacity["scale"] = capacity.apply(
        lambda row: (
            min(1.0, row["gross_source_capacity"] / row["virtual_gross_demand"])
            if row["virtual_gross_demand"] > 0
            else 0.0
        ),
        axis=1,
    )

    virtual_allocations_frame = virtual_frame.merge(
        capacity[["asset_uid", "asset_identifier", "scale"]],
        on=["asset_uid", "asset_identifier"],
        how="left",
    )
    if not virtual_allocations_frame.empty:
        virtual_allocations_frame["scale"] = virtual_allocations_frame["scale"].fillna(0.0)
        virtual_allocations_frame["allocated_signed_quantity"] = (
            virtual_allocations_frame["requested_signed_quantity"]
            * virtual_allocations_frame["scale"]
        )
        virtual_allocations_frame["target_gap_signed_quantity"] = (
            virtual_allocations_frame["requested_signed_quantity"]
            - virtual_allocations_frame["allocated_signed_quantity"]
        )
        virtual_allocations_frame["requested_abs_quantity"] = virtual_allocations_frame[
            "requested_signed_quantity"
        ].abs()
        virtual_allocations_frame["allocated_abs_quantity"] = virtual_allocations_frame[
            "allocated_signed_quantity"
        ].abs()
        virtual_allocations_frame["target_gap_abs_quantity"] = virtual_allocations_frame[
            "target_gap_signed_quantity"
        ].abs()
        virtual_allocations_frame["allocated_notional"] = (
            virtual_allocations_frame["requested_notional"] * virtual_allocations_frame["scale"]
        )
        virtual_allocations_frame["target_gap_notional"] = (
            virtual_allocations_frame["requested_notional"]
            - virtual_allocations_frame["allocated_notional"]
        )

    virtual_allocated_by_asset = (
        virtual_allocations_frame.groupby(["asset_uid", "asset_identifier"], as_index=False)[
            "allocated_signed_quantity"
        ].sum()
        if not virtual_allocations_frame.empty
        else pd.DataFrame(columns=["asset_uid", "asset_identifier", "allocated_signed_quantity"])
    ).rename(columns={"allocated_signed_quantity": "virtual_allocated_signed_quantity"})

    direct_capacity = (
        capacity.merge(
            virtual_allocated_by_asset,
            on=["asset_uid", "asset_identifier"],
            how="left",
        )
        .merge(
            direct_frame,
            on=["asset_uid", "asset_identifier"],
            how="left",
        )
        .fillna(
            {
                "virtual_allocated_signed_quantity": 0.0,
                "direct_target_signed_quantity": 0.0,
            }
        )
    )
    direct_capacity["direct_sleeve_signed_quantity"] = (
        direct_capacity["signed_account_holding"]
        - direct_capacity["virtual_allocated_signed_quantity"]
    )
    direct_capacity["direct_target_gap_signed_quantity"] = (
        direct_capacity["direct_target_signed_quantity"]
        - direct_capacity["direct_sleeve_signed_quantity"]
    )

    virtual_lines = _virtual_lines(virtual_allocations_frame)
    direct_lines = _direct_lines(direct_capacity)
    residuals = _residuals(direct_capacity)
    deficits = _deficits(direct_capacity, allocation_policy.quantity_tolerance)
    status = _plan_status(
        allocation_policy=allocation_policy,
        virtual_lines=virtual_lines,
        deficits=deficits,
    )
    metadata = _virtual_fund_metadata(virtual_fund_demands)
    return AccountVirtualFundAllocationPlan(
        status=status,
        position_set_uid=position_set_uid,
        account_uid=account_uid,
        source_account_holdings_set_uid=source_account_holdings_set_uid,
        valuation_time=valuation_time,
        valuation_asset_uid=valuation_asset_uid,
        allocation_policy=allocation_policy,
        account_nav=account_nav,
        source_holdings=source_holdings,
        direct_target_demands=direct_target_demands,
        virtual_fund_demands=virtual_fund_demands,
        account_virtual_holding_lines=(*virtual_lines, *direct_lines),
        virtual_fund_allocations=virtual_lines,
        residuals=residuals,
        deficits=deficits,
        diagnostics=diagnostics,
        virtual_fund_metadata=metadata,
    )


def _source_holdings(
    value: Sequence[HoldingValuationInput | Mapping[str, Any]] | pd.DataFrame,
) -> tuple[HoldingValuationInput, ...]:
    frame = (
        value.reset_index()
        if isinstance(value, pd.DataFrame)
        else pd.DataFrame([_dataclass_or_mapping(row) for row in value])
    )
    if frame.empty:
        raise ValueError("At least one source holding is required.")
    rows = []
    for row in frame.to_dict("records"):
        payload = _dataclass_or_mapping(row)
        direction = _direction(payload.get("direction", 1))
        quantity = float(payload.get("quantity") or 0.0)
        if quantity <= 0:
            raise ValueError("Source holdings quantity must be positive.")
        rows.append(
            HoldingValuationInput(
                asset_uid=_required_string(payload.get("asset_uid"), "asset_uid"),
                asset_identifier=_required_string(
                    payload.get("asset_identifier") or payload.get(ASSET_IDENTIFIER_DIMENSION),
                    ASSET_IDENTIFIER_DIMENSION,
                ),
                quantity=quantity,
                direction=direction,
                source_row=payload.get("source_row") or payload,
            )
        )
    return tuple(rows)


def _target_quantity_demands(
    value: Sequence[TargetQuantityDemand | Mapping[str, Any]] | pd.DataFrame,
    *,
    default_claim_type: str,
) -> tuple[TargetQuantityDemand, ...]:
    frame = (
        value.reset_index()
        if isinstance(value, pd.DataFrame)
        else pd.DataFrame([_dataclass_or_mapping(row) for row in value])
    )
    if frame.empty:
        return ()
    rows = []
    for row in frame.to_dict("records"):
        payload = _dataclass_or_mapping(row)
        signed_quantity = float(payload.get("requested_signed_quantity") or 0.0)
        if signed_quantity == 0:
            raise ValueError("Target quantity demand cannot be zero.")
        direction = 1 if signed_quantity > 0 else -1
        claim_type = str(payload.get("claim_type") or default_claim_type)
        claim_uid = payload.get("claim_uid")
        if claim_type == CLAIM_TYPE_VIRTUAL_FUND_TARGET and claim_uid in (None, ""):
            raise ValueError("Virtual-fund demands require claim_uid.")
        rows.append(
            TargetQuantityDemand(
                target_row_key=_required_string(payload.get("target_row_key"), "target_row_key"),
                asset_uid=_required_string(payload.get("asset_uid"), "asset_uid"),
                asset_identifier=_required_string(
                    payload.get("asset_identifier") or payload.get(ASSET_IDENTIFIER_DIMENSION),
                    ASSET_IDENTIFIER_DIMENSION,
                ),
                requested_signed_quantity=signed_quantity,
                direction=direction,
                requested_notional=_optional_float(payload.get("requested_notional")),
                claim_type=claim_type,
                claim_uid=str(claim_uid) if claim_uid not in (None, "") else None,
                source_target_uid=_optional_string(payload.get("source_target_uid")),
                target_type=_optional_string(payload.get("target_type")),
                target_portfolio_uid=_optional_string(payload.get("target_portfolio_uid")),
                virtual_fund_unique_identifier=_optional_string(
                    payload.get("virtual_fund_unique_identifier")
                ),
                source_row=payload.get("source_row") or payload,
            )
        )
    return tuple(rows)


def _target_notional_demands(
    value: Sequence[TargetNotionalDemand | Mapping[str, Any]] | pd.DataFrame,
) -> tuple[TargetNotionalDemand, ...]:
    frame = (
        value.reset_index()
        if isinstance(value, pd.DataFrame)
        else pd.DataFrame([_dataclass_or_mapping(row) for row in value])
    )
    if frame.empty:
        return ()
    rows = []
    for row in frame.to_dict("records"):
        payload = _dataclass_or_mapping(row)
        notional_value = _optional_float(
            payload.get("notional_value", payload.get("requested_notional"))
        )
        if notional_value is None or notional_value == 0:
            raise ValueError("Target notional demand cannot be zero.")
        direction = 1 if notional_value > 0 else -1
        claim_type = str(payload.get("claim_type") or CLAIM_TYPE_VIRTUAL_FUND_TARGET)
        claim_uid = payload.get("claim_uid")
        if claim_type == CLAIM_TYPE_VIRTUAL_FUND_TARGET and claim_uid in (None, ""):
            raise ValueError("Virtual-fund notional demands require claim_uid.")
        rows.append(
            TargetNotionalDemand(
                target_row_key=_required_string(payload.get("target_row_key"), "target_row_key"),
                asset_uid=_required_string(payload.get("asset_uid"), "asset_uid"),
                asset_identifier=_required_string(
                    payload.get("asset_identifier") or payload.get(ASSET_IDENTIFIER_DIMENSION),
                    ASSET_IDENTIFIER_DIMENSION,
                ),
                notional_value=notional_value,
                direction=direction,
                claim_type=claim_type,
                claim_uid=str(claim_uid) if claim_uid not in (None, "") else claim_type,
                requested_notional=_optional_float(payload.get("requested_notional"))
                or notional_value,
                source_target_uid=_optional_string(payload.get("source_target_uid")),
                target_type=_optional_string(payload.get("target_type")),
                target_portfolio_uid=_optional_string(payload.get("target_portfolio_uid")),
                virtual_fund_unique_identifier=_optional_string(
                    payload.get("virtual_fund_unique_identifier")
                ),
                source_row=payload.get("source_row") or payload,
            )
        )
    return tuple(rows)


def _holding_inputs_from_rows(
    value: Sequence[Mapping[str, Any]] | pd.DataFrame,
    *,
    asset_uid_by_identifier: Mapping[str, uuid.UUID | str],
) -> tuple[HoldingValuationInput, ...]:
    rows = []
    uid_by_identifier = {
        str(identifier): uid for identifier, uid in asset_uid_by_identifier.items()
    }
    for row in _rows_from_records(value):
        asset_identifier = _required_string(
            row.get(ASSET_IDENTIFIER_DIMENSION) or row.get("asset_identifier"),
            ASSET_IDENTIFIER_DIMENSION,
        )
        asset_uid = uid_by_identifier.get(asset_identifier)
        if asset_uid in (None, ""):
            raise ValueError(f"Missing AssetTable.uid for asset_identifier={asset_identifier!r}.")
        quantity = float(row.get("quantity") or 0.0)
        if quantity <= 0:
            raise ValueError("Account holding quantity must be positive.")
        rows.append(
            HoldingValuationInput(
                asset_uid=asset_uid,
                asset_identifier=asset_identifier,
                quantity=quantity,
                direction=_direction(row.get("direction", 1)),
                source_row=row,
            )
        )
    if not rows:
        raise ValueError("At least one account holding row is required.")
    return tuple(rows)


def _append_target_row_demands(
    *,
    row: Mapping[str, Any],
    claim_type: str,
    claim_uid: str,
    asset_identifier_by_uid: Mapping[uuid.UUID | str, str],
    account_nav: float | None,
    direct_demands: list[TargetQuantityDemand],
    virtual_demands: list[TargetQuantityDemand],
    notional_demands: list[TargetNotionalDemand],
) -> None:
    payload = dict(row)
    asset_uid = _required_string(payload.get("asset_uid"), "asset_uid")
    asset_identifier = _optional_string(
        payload.get("asset_identifier") or payload.get(ASSET_IDENTIFIER_DIMENSION)
    )
    if asset_identifier is None:
        asset_identifier = _asset_identifier_by_uid(asset_identifier_by_uid, asset_uid)
    target_row_key = _target_row_key(payload, claim_uid=claim_uid, asset_uid=asset_uid)
    target_portfolio_uid = _optional_string(
        payload.get("target_portfolio_uid") or payload.get("portfolio_uid")
    )
    quantity = _optional_float(
        payload.get("requested_signed_quantity", payload.get("single_asset_quantity"))
    )
    if quantity is not None:
        demand = TargetQuantityDemand(
            target_row_key=target_row_key,
            asset_uid=asset_uid,
            asset_identifier=asset_identifier,
            requested_signed_quantity=quantity,
            direction=1 if quantity > 0 else -1,
            requested_notional=_optional_float(payload.get("requested_notional")),
            claim_type=claim_type,
            claim_uid=claim_uid,
            source_target_uid=_optional_string(
                payload.get("source_target_uid") or payload.get("target_uid")
            ),
            target_type=_optional_string(payload.get("target_type")),
            target_portfolio_uid=target_portfolio_uid,
            virtual_fund_unique_identifier=_optional_string(
                payload.get("virtual_fund_unique_identifier")
            ),
            source_row=payload,
        )
        if claim_type == CLAIM_TYPE_VIRTUAL_FUND_TARGET:
            virtual_demands.append(demand)
        else:
            direct_demands.append(demand)
        return

    notional = _target_row_notional(payload, account_nav=account_nav)
    if notional is None:
        raise ValueError(
            "Target row must provide requested_signed_quantity, single_asset_quantity, "
            "weight_notional_exposure, or constant_notional_exposure."
        )
    notional_demands.append(
        TargetNotionalDemand(
            target_row_key=target_row_key,
            asset_uid=asset_uid,
            asset_identifier=asset_identifier,
            notional_value=notional,
            direction=1 if notional > 0 else -1,
            claim_type=claim_type,
            claim_uid=claim_uid,
            requested_notional=notional,
            source_target_uid=_optional_string(
                payload.get("source_target_uid") or payload.get("target_uid")
            ),
            target_type=_optional_string(payload.get("target_type")),
            target_portfolio_uid=target_portfolio_uid,
            virtual_fund_unique_identifier=_optional_string(
                payload.get("virtual_fund_unique_identifier")
            ),
            source_row=payload,
        )
    )


def _target_row_notional(row: Mapping[str, Any], *, account_nav: float | None) -> float | None:
    notional_value = _optional_float(row.get("notional_value"))
    if notional_value is not None:
        return notional_value
    constant_notional = _optional_float(row.get("constant_notional_exposure"))
    if constant_notional is not None:
        return constant_notional
    weight = _optional_float(row.get("weight_notional_exposure"))
    if weight is None:
        return None
    if account_nav is None:
        raise ValueError("weight_notional_exposure requires resolved account_nav.")
    return weight * account_nav


def _expanded_target_rows(
    value: Sequence[TargetNotionalDemand | TargetQuantityDemand | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [_dataclass_or_mapping(row) for row in value]


def _expand_portfolio_target_rows(
    target_position_rows: Sequence[Mapping[str, Any]],
    *,
    valuation_time: dt.datetime,
) -> list[dict[str, Any]]:
    portfolio_rows = [
        dict(row) for row in target_position_rows if row.get("target_type") == TARGET_TYPE_PORTFOLIO
    ]
    if not portfolio_rows:
        return []

    from msm.api.base import operation_result_rows
    from msm.bootstrap import resolve_runtime
    from msm.models.portfolios import PortfolioTable
    from msm.repositories.crud import search_model
    from msm_portfolios.data_nodes.portfolios.storage import PortfolioWeightsStorage

    runtime = resolve_runtime(
        models=[PortfolioTable, PortfolioWeightsStorage],
        row_model_name="Account virtual-fund allocation portfolio expansion",
    )
    context = runtime.context
    portfolio_uids = sorted(
        {_required_string(row.get("portfolio_uid"), "portfolio_uid") for row in portfolio_rows}
    )
    portfolio_records = operation_result_rows(
        search_model(
            context,
            model=PortfolioTable,
            in_filters={"uid": portfolio_uids},
            limit=DEFAULT_ALLOCATION_SCAN_LIMIT,
        )
    )
    portfolio_by_uid = {str(row["uid"]): row for row in portfolio_records}
    missing_portfolios = sorted(set(portfolio_uids) - set(portfolio_by_uid))
    if missing_portfolios:
        raise ValueError(f"Could not resolve PortfolioTable rows for {missing_portfolios}.")

    portfolio_identifier_by_uid = {
        portfolio_uid: _required_string(portfolio_row.get("unique_identifier"), "unique_identifier")
        for portfolio_uid, portfolio_row in portfolio_by_uid.items()
    }
    weight_records = _latest_portfolio_weight_records(
        context,
        portfolio_weights_storage=PortfolioWeightsStorage,
        portfolio_identifiers=sorted(set(portfolio_identifier_by_uid.values())),
        valuation_time=valuation_time,
    )
    weights_by_portfolio_identifier: dict[str, list[dict[str, Any]]] = {}
    for row in weight_records:
        weights_by_portfolio_identifier.setdefault(str(row["portfolio_identifier"]), []).append(row)

    expanded_rows: list[dict[str, Any]] = []
    for row in portfolio_rows:
        portfolio_uid = _required_string(row.get("portfolio_uid"), "portfolio_uid")
        portfolio_identifier = portfolio_identifier_by_uid[portfolio_uid]
        portfolio_weights = weights_by_portfolio_identifier.get(portfolio_identifier, [])
        if not portfolio_weights:
            raise ValueError(
                "No PortfolioWeightsStorage rows found for "
                f"portfolio_uid={portfolio_uid}, portfolio_identifier={portfolio_identifier!r}, "
                f"at or before valuation_time={valuation_time.isoformat()}."
            )
        for weight_row in portfolio_weights:
            expanded = dict(row)
            expanded[ASSET_IDENTIFIER_DIMENSION] = _required_string(
                weight_row.get(ASSET_IDENTIFIER_DIMENSION),
                ASSET_IDENTIFIER_DIMENSION,
            )
            expanded["target_portfolio_uid"] = portfolio_uid
            expanded["portfolio_uid"] = portfolio_uid
            portfolio_weight = float(weight_row.get("weight") or 0.0)
            if expanded.get("weight_notional_exposure") is not None:
                expanded["weight_notional_exposure"] = (
                    float(expanded["weight_notional_exposure"]) * portfolio_weight
                )
            if expanded.get("constant_notional_exposure") is not None:
                expanded["constant_notional_exposure"] = (
                    float(expanded["constant_notional_exposure"]) * portfolio_weight
                )
            expanded_rows.append(expanded)
    return expanded_rows


def _latest_portfolio_weight_records(
    context: Any,
    *,
    portfolio_weights_storage: Any,
    portfolio_identifiers: Sequence[str],
    valuation_time: dt.datetime,
) -> list[dict[str, Any]]:
    if not portfolio_identifiers:
        return []

    from sqlalchemy import and_, func, select

    from msm.api.base import operation_result_rows
    from msm.repositories.base import compile_markets_statement, execute_markets_operation

    latest_times = (
        select(
            portfolio_weights_storage.portfolio_identifier.label("portfolio_identifier"),
            func.max(portfolio_weights_storage.time_index).label("time_index"),
        )
        .where(portfolio_weights_storage.portfolio_identifier.in_(list(portfolio_identifiers)))
        .where(portfolio_weights_storage.time_index <= valuation_time)
        .group_by(portfolio_weights_storage.portfolio_identifier)
        .subquery()
    )
    statement = (
        select(portfolio_weights_storage)
        .join(
            latest_times,
            and_(
                portfolio_weights_storage.portfolio_identifier
                == latest_times.c.portfolio_identifier,
                portfolio_weights_storage.time_index == latest_times.c.time_index,
            ),
        )
        .order_by(
            portfolio_weights_storage.portfolio_identifier,
            portfolio_weights_storage.asset_identifier,
        )
    )
    return operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                statement,
                context=context,
                operation="select",
                models=[portfolio_weights_storage],
                access="read",
            ),
            context=context,
        )
    )


def _rows_from_records(value: Sequence[Mapping[str, Any]] | pd.DataFrame) -> list[dict[str, Any]]:
    if isinstance(value, pd.DataFrame):
        return [dict(row) for row in value.reset_index().to_dict("records")]
    return [dict(row) for row in value]


def _asset_identifier_by_uid(
    asset_identifier_by_uid: Mapping[uuid.UUID | str, str],
    asset_uid: uuid.UUID | str,
) -> str:
    normalized = {str(uid): identifier for uid, identifier in asset_identifier_by_uid.items()}
    asset_identifier = normalized.get(str(asset_uid))
    if asset_identifier in (None, ""):
        raise ValueError(f"Missing AssetTable.unique_identifier for asset_uid={asset_uid!s}.")
    return str(asset_identifier)


def _target_row_key(row: Mapping[str, Any], *, claim_uid: str, asset_uid: str) -> str:
    for key in ("target_row_key", "uid", "source_target_uid", "target_uid"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return f"{claim_uid}:{asset_uid}"


def _asset_identity_maps(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    uid_by_identifier: dict[str, str] = {}
    identifier_by_uid: dict[str, str] = {}
    for row in rows:
        uid = row.get("uid")
        identifier = row.get("unique_identifier")
        if uid in (None, "") or identifier in (None, ""):
            continue
        uid_by_identifier[str(identifier)] = str(uid)
        identifier_by_uid[str(uid)] = str(identifier)
    return uid_by_identifier, identifier_by_uid


def _one_row(
    rows: Sequence[Mapping[str, Any]],
    *,
    label: str,
    filters: Mapping[str, Any],
) -> dict[str, Any]:
    if len(rows) != 1:
        raise LookupError(f"Expected one {label} row for {dict(filters)!r}, found {len(rows)}.")
    return dict(rows[0])


def _same_timestamp(value: Any, expected: dt.datetime) -> bool:
    if value in (None, ""):
        return False
    timestamp = pd.to_datetime(value, utc=True).to_pydatetime()
    return timestamp == expected


def _holdings_vector(source_holdings: tuple[HoldingValuationInput, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "asset_uid": str(row.asset_uid),
            "asset_identifier": row.asset_identifier,
            "signed_quantity": row.quantity * row.direction,
            "abs_quantity": abs(row.quantity),
        }
        for row in source_holdings
    )
    return (
        frame.groupby(["asset_uid", "asset_identifier"], as_index=False)
        .agg(
            signed_account_holding=("signed_quantity", "sum"),
            gross_source_capacity=("abs_quantity", "sum"),
        )
        .astype(
            {
                "signed_account_holding": "float64",
                "gross_source_capacity": "float64",
            }
        )
    )


def _virtual_target_vector(virtual_fund_demands: tuple[TargetQuantityDemand, ...]) -> pd.DataFrame:
    if not virtual_fund_demands:
        return pd.DataFrame()
    frame = pd.DataFrame(
        {
            "claim_uid": _required_string(row.claim_uid, "claim_uid"),
            "asset_uid": str(row.asset_uid),
            "asset_identifier": row.asset_identifier,
            "requested_signed_quantity": row.requested_signed_quantity,
            "requested_notional": row.requested_notional,
            "target_row_key": row.target_row_key,
            "source_target_uid": _optional_string(row.source_target_uid),
            "target_type": row.target_type or TARGET_TYPE_PORTFOLIO,
            "target_portfolio_uid": _optional_string(row.target_portfolio_uid),
            "virtual_fund_unique_identifier": row.virtual_fund_unique_identifier,
        }
        for row in virtual_fund_demands
    )
    grouped = (
        frame.groupby(
            [
                "claim_uid",
                "asset_uid",
                "asset_identifier",
                "target_row_key",
                "source_target_uid",
                "target_type",
                "target_portfolio_uid",
                "virtual_fund_unique_identifier",
            ],
            as_index=False,
            dropna=False,
        )
        .agg(
            requested_signed_quantity=("requested_signed_quantity", "sum"),
            requested_notional=("requested_notional", "sum"),
        )
        .astype({"requested_signed_quantity": "float64"})
    )
    return grouped


def _direct_target_vector(direct_demands: tuple[TargetQuantityDemand, ...]) -> pd.DataFrame:
    if not direct_demands:
        return pd.DataFrame(
            columns=["asset_uid", "asset_identifier", "direct_target_signed_quantity"]
        )
    frame = pd.DataFrame(
        {
            "asset_uid": str(row.asset_uid),
            "asset_identifier": row.asset_identifier,
            "direct_target_signed_quantity": row.requested_signed_quantity,
        }
        for row in direct_demands
    )
    return frame.groupby(["asset_uid", "asset_identifier"], as_index=False)[
        "direct_target_signed_quantity"
    ].sum()


def _asset_index_frame(
    holdings_frame: pd.DataFrame,
    virtual_frame: pd.DataFrame,
    direct_frame: pd.DataFrame,
) -> pd.DataFrame:
    frames = [
        holdings_frame[["asset_uid", "asset_identifier"]],
        direct_frame[["asset_uid", "asset_identifier"]],
    ]
    if not virtual_frame.empty:
        frames.append(virtual_frame[["asset_uid", "asset_identifier"]])
    assets = pd.concat(frames).drop_duplicates()
    return assets.merge(
        holdings_frame,
        on=["asset_uid", "asset_identifier"],
        how="left",
    ).fillna({"signed_account_holding": 0.0, "gross_source_capacity": 0.0})


def _virtual_lines(frame: pd.DataFrame) -> tuple[AccountVirtualHoldingLine, ...]:
    if frame.empty:
        return ()
    lines = []
    for row in frame.to_dict("records"):
        requested = float(row["requested_signed_quantity"])
        allocated = float(row["allocated_signed_quantity"])
        gap = float(row["target_gap_signed_quantity"])
        requested_notional = _optional_float(row.get("requested_notional"))
        lines.append(
            AccountVirtualHoldingLine(
                claim_type=CLAIM_TYPE_VIRTUAL_FUND_TARGET,
                claim_uid=str(row["claim_uid"]),
                asset_uid=str(row["asset_uid"]),
                asset_identifier=str(row["asset_identifier"]),
                requested_direction=1 if requested >= 0 else -1,
                requested_signed_quantity=requested,
                allocated_signed_quantity=allocated,
                target_gap_signed_quantity=gap,
                requested_abs_quantity=abs(requested),
                allocated_abs_quantity=abs(allocated),
                target_gap_abs_quantity=abs(gap),
                requested_notional=requested_notional,
                allocated_notional=_optional_float(row.get("allocated_notional")),
                target_gap_notional=_optional_float(row.get("target_gap_notional")),
                scale=float(row["scale"]),
                target_row_key=_optional_string(row.get("target_row_key")),
                source_target_uid=_optional_string(row.get("source_target_uid")),
                target_type=_optional_string(row.get("target_type")),
                target_portfolio_uid=_optional_string(row.get("target_portfolio_uid")),
                virtual_fund_unique_identifier=_optional_string(
                    row.get("virtual_fund_unique_identifier")
                ),
            )
        )
    return tuple(lines)


def _direct_lines(frame: pd.DataFrame) -> tuple[AccountVirtualHoldingLine, ...]:
    lines = []
    for row in frame.to_dict("records"):
        requested = float(row["direct_target_signed_quantity"])
        allocated = float(row["direct_sleeve_signed_quantity"])
        gap = float(row["direct_target_gap_signed_quantity"])
        lines.append(
            AccountVirtualHoldingLine(
                claim_type=CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
                claim_uid=CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
                asset_uid=str(row["asset_uid"]),
                asset_identifier=str(row["asset_identifier"]),
                requested_direction=1 if requested >= 0 else -1,
                requested_signed_quantity=requested,
                allocated_signed_quantity=allocated,
                target_gap_signed_quantity=gap,
                requested_abs_quantity=abs(requested),
                allocated_abs_quantity=abs(allocated),
                target_gap_abs_quantity=abs(gap),
                requested_notional=None,
                allocated_notional=None,
                target_gap_notional=None,
                scale=float(row["scale"]),
                target_type=TARGET_TYPE_ASSET,
            )
        )
    return tuple(lines)


def _residuals(frame: pd.DataFrame) -> tuple[AccountAllocationResidual, ...]:
    return tuple(
        AccountAllocationResidual(
            asset_uid=str(row["asset_uid"]),
            asset_identifier=str(row["asset_identifier"]),
            signed_account_holding=float(row["signed_account_holding"]),
            gross_source_capacity=float(row["gross_source_capacity"]),
            virtual_gross_demand=float(row["virtual_gross_demand"]),
            virtual_allocated_signed_quantity=float(row["virtual_allocated_signed_quantity"]),
            direct_sleeve_signed_quantity=float(row["direct_sleeve_signed_quantity"]),
            direct_target_signed_quantity=float(row["direct_target_signed_quantity"]),
            direct_target_gap_signed_quantity=float(row["direct_target_gap_signed_quantity"]),
            scale=float(row["scale"]),
        )
        for row in frame.to_dict("records")
    )


def _deficits(
    frame: pd.DataFrame, quantity_tolerance: float
) -> tuple[AccountAllocationDeficit, ...]:
    deficit_frame = frame.assign(
        deficit_abs_quantity=lambda values: (
            values["virtual_gross_demand"] - values["gross_source_capacity"]
        )
    )
    deficit_frame = deficit_frame[deficit_frame["deficit_abs_quantity"] > quantity_tolerance]
    return tuple(
        AccountAllocationDeficit(
            asset_uid=str(row["asset_uid"]),
            asset_identifier=str(row["asset_identifier"]),
            gross_source_capacity=float(row["gross_source_capacity"]),
            virtual_gross_demand=float(row["virtual_gross_demand"]),
            deficit_abs_quantity=float(row["deficit_abs_quantity"]),
            scale=float(row["scale"]),
        )
        for row in deficit_frame.to_dict("records")
    )


def _plan_status(
    *,
    allocation_policy: AllocationPolicy,
    virtual_lines: tuple[AccountVirtualHoldingLine, ...],
    deficits: tuple[AccountAllocationDeficit, ...],
) -> str:
    if allocation_policy.mode == ALLOCATION_MODE_STRICT_FEASIBLE:
        return PLAN_STATUS_INFEASIBLE if deficits else PLAN_STATUS_FEASIBLE
    has_gap = any(
        line.target_gap_abs_quantity > allocation_policy.quantity_tolerance
        for line in virtual_lines
    )
    return PLAN_STATUS_ATTRIBUTED_WITH_TARGET_GAP if has_gap else PLAN_STATUS_FEASIBLE


def _virtual_fund_metadata(
    demands: tuple[TargetQuantityDemand, ...],
) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for demand in demands:
        claim_uid = _required_string(demand.claim_uid, "claim_uid")
        metadata.setdefault(claim_uid, {})
        if demand.target_portfolio_uid is not None:
            metadata[claim_uid]["target_portfolio_uid"] = str(demand.target_portfolio_uid)
        if demand.virtual_fund_unique_identifier is not None:
            metadata[claim_uid]["virtual_fund_unique_identifier"] = (
                demand.virtual_fund_unique_identifier
            )
    return metadata


def _resolve_valuation(
    *,
    valuation_resolver: ValuationResolver | None,
    requested_metrics: Sequence[str],
    source_holdings: tuple[HoldingValuationInput, ...],
    target_notional_demands: Sequence[TargetNotionalDemand],
    valuation_time: dt.datetime,
    valuation_asset_uid: uuid.UUID | str,
    valuation_policy: ValuationPolicy,
) -> AllocationValuation | None:
    if valuation_resolver is None:
        return None
    return valuation_resolver(
        requested_metrics,
        source_holdings,
        target_notional_demands,
        valuation_time=valuation_time,
        valuation_asset_uid=valuation_asset_uid,
        valuation_policy=valuation_policy,
    )


def _nav_total(valuation: AllocationValuation) -> float:
    nav = valuation.metrics.get("nav")
    if nav is None:
        raise ValueError("valuation_resolver must return metrics['nav'].")
    value = nav.total.value
    if isinstance(value, Mapping):
        raise ValueError("NAV total metric must be numeric for allocation planning.")
    return float(value)


def _requested_metric_names(requested_metrics: Sequence[str] | None) -> set[str]:
    if requested_metrics is None:
        return {"nav"}
    return {_required_string(metric, "requested_metrics[]") for metric in requested_metrics}


def _lines_by_claim(
    lines: Sequence[AccountVirtualHoldingLine],
) -> dict[str, list[AccountVirtualHoldingLine]]:
    grouped: dict[str, list[AccountVirtualHoldingLine]] = {}
    for line in lines:
        grouped.setdefault(line.claim_uid, []).append(line)
    return grouped


def _first_value(lines: Sequence[AccountVirtualHoldingLine], field_name: str) -> Any:
    for line in lines:
        value = getattr(line, field_name)
        if value not in (None, ""):
            return value
    return None


def _deterministic_holdings_set_uid(
    *,
    source_account_holdings_set_uid: str,
    virtual_fund_uid: str,
    valuation_time: dt.datetime,
) -> uuid.UUID:
    key = (
        "msm.account_virtual_allocation:"
        f"{source_account_holdings_set_uid}:{virtual_fund_uid}:"
        f"{valuation_time.isoformat()}"
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, key)


def _utc_timestamp(value: dt.datetime, *, field_name: str) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")
    return value.astimezone(dt.UTC).replace(microsecond=value.astimezone(dt.UTC).microsecond)


def _dataclass_or_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    raise TypeError("Expected a dataclass, Pydantic model, mapping, or DataFrame row.")


def _direction(value: Any) -> Literal[1, -1]:
    direction = int(value)
    if direction not in {1, -1}:
        raise ValueError("direction must be 1 or -1.")
    return 1 if direction == 1 else -1


def _required_string(value: Any, field_name: str) -> str:
    if _is_missing(value):
        raise ValueError(f"{field_name} is required.")
    return str(value)


def _optional_string(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    return float(value)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, Mapping | Sequence) and not isinstance(value, str | bytes):
        return False
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, bool) else False


__all__ = [
    "ALLOCATION_MODE_PROPORTIONAL_ATTRIBUTION",
    "ALLOCATION_MODE_STRICT_FEASIBLE",
    "CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL",
    "CLAIM_TYPE_VIRTUAL_FUND_TARGET",
    "PLAN_STATUS_ATTRIBUTED_WITH_TARGET_GAP",
    "PLAN_STATUS_FEASIBLE",
    "PLAN_STATUS_INFEASIBLE",
    "AccountAllocationDeficit",
    "AccountAllocationResidual",
    "AccountVirtualFundAllocationPlan",
    "AccountVirtualHoldingLine",
    "AllocationPolicy",
    "AllocationValuation",
    "HoldingValuationInput",
    "HoldingsSelectionPolicy",
    "TargetNotionalDemand",
    "TargetQuantityDemand",
    "ValuationDiagnostic",
    "ValuationMetricLine",
    "ValuationMetricResult",
    "ValuationMetricValue",
    "ValuationPolicy",
    "ValuationResolver",
    "apply_account_virtual_fund_allocation_plan",
    "plan_account_virtual_fund_allocations",
    "virtual_fund_unique_identifier_for_target",
]
