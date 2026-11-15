from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

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
class AccountHoldingInput:
    """One account holding in units: a positive quantity and its side."""

    asset_uid: uuid.UUID | str
    asset_identifier: str
    quantity: float
    direction: Literal[1, -1]
    source_row: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TargetQuantityDemand:
    """One target row as a signed quantity: quantity times direction (ADR 0052)."""

    target_row_key: str
    asset_uid: uuid.UUID | str
    asset_identifier: str
    requested_signed_quantity: float
    direction: Literal[1, -1]
    claim_type: str = CLAIM_TYPE_VIRTUAL_FUND_TARGET
    claim_uid: str | None = None
    source_target_uid: uuid.UUID | str | None = None
    target_type: str | None = None
    target_portfolio_uid: uuid.UUID | str | None = None
    virtual_fund_unique_identifier: str | None = None
    source_row: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AllocationDiagnostic:
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "info"
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AccountVirtualFundAllocationInputs:
    account_uid: uuid.UUID | str
    source_account_holdings_set_uid: uuid.UUID | str
    source_holdings: tuple[AccountHoldingInput, ...]
    direct_target_demands: tuple[TargetQuantityDemand, ...] = ()
    virtual_fund_demands: tuple[TargetQuantityDemand, ...] = ()
    diagnostics: tuple[AllocationDiagnostic, ...] = ()


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
    """An allocation of one holdings snapshot to the account's virtual funds, in units."""

    status: str
    valuation_time: dt.datetime
    allocation_policy: AllocationPolicy
    position_set_uid: str | None = None
    account_uid: str | None = None
    source_account_holdings_set_uid: str | None = None
    source_holdings: tuple[AccountHoldingInput, ...] = ()
    direct_target_demands: tuple[TargetQuantityDemand, ...] = ()
    virtual_fund_demands: tuple[TargetQuantityDemand, ...] = ()
    account_virtual_holding_lines: tuple[AccountVirtualHoldingLine, ...] = ()
    virtual_fund_allocations: tuple[AccountVirtualHoldingLine, ...] = ()
    residuals: tuple[AccountAllocationResidual, ...] = ()
    deficits: tuple[AccountAllocationDeficit, ...] = ()
    diagnostics: tuple[AllocationDiagnostic, ...] = ()
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
    holdings_selection_policy: HoldingsSelectionPolicy,
    allocation_policy: AllocationPolicy,
) -> AccountVirtualFundAllocationPlan:
    """Plan account-to-virtual-fund attribution from one PositionSet, in units.

    The targets and the holdings are both recorded in units (ADR 0052), so the
    plan needs no price, NAV or valuation. It writes nothing.
    """

    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    resolved_inputs = resolve_account_virtual_fund_allocation_inputs(
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
        holdings_selection_policy=holdings_selection_policy,
    )
    return _plan_account_virtual_fund_allocations_from_resolved_inputs(
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
        allocation_policy=allocation_policy,
        source_holdings=resolved_inputs.source_holdings,
        direct_target_demands=resolved_inputs.direct_target_demands,
        virtual_fund_demands=resolved_inputs.virtual_fund_demands,
        account_uid=resolved_inputs.account_uid,
        source_account_holdings_set_uid=resolved_inputs.source_account_holdings_set_uid,
        diagnostics=resolved_inputs.diagnostics,
    )


def _plan_account_virtual_fund_allocations_from_resolved_inputs(
    *,
    valuation_time: dt.datetime,
    source_holdings: Sequence[AccountHoldingInput | Mapping[str, Any]] | pd.DataFrame,
    virtual_fund_demands: Sequence[TargetQuantityDemand | Mapping[str, Any]] | pd.DataFrame | None,
    position_set_uid: uuid.UUID | str | None = None,
    allocation_policy: AllocationPolicy | None = None,
    direct_target_demands: Sequence[TargetQuantityDemand | Mapping[str, Any]]
    | pd.DataFrame
    | None = None,
    account_uid: uuid.UUID | str | None = None,
    source_account_holdings_set_uid: uuid.UUID | str | None = None,
    diagnostics: Sequence[AllocationDiagnostic] = (),
) -> AccountVirtualFundAllocationPlan:
    """Run the vector allocation engine from already-resolved inputs."""

    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    policy = allocation_policy or AllocationPolicy()
    holdings = _source_holdings(source_holdings)
    virtual_demands = (
        _target_quantity_demands(
            virtual_fund_demands,
            default_claim_type=CLAIM_TYPE_VIRTUAL_FUND_TARGET,
        )
        if virtual_fund_demands is not None
        else ()
    )
    direct_demands = _target_quantity_demands(
        direct_target_demands if direct_target_demands is not None else (),
        default_claim_type=CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
    )
    if not virtual_demands:
        raise ValueError(
            "plan_account_virtual_fund_allocations requires at least one virtual-fund demand."
        )

    return _plan_from_quantity_demands(
        position_set_uid=_optional_string(position_set_uid),
        account_uid=_optional_string(account_uid),
        source_account_holdings_set_uid=_optional_string(source_account_holdings_set_uid),
        valuation_time=normalized_time,
        allocation_policy=policy,
        source_holdings=holdings,
        direct_target_demands=tuple(direct_demands),
        virtual_fund_demands=tuple(virtual_demands),
        diagnostics=tuple(diagnostics),
    )


def apply_account_virtual_fund_allocation_plan(
    plan: AccountVirtualFundAllocationPlan,
    *,
    updater: Any | None = None,
    run: bool = False,
    data_node: Any | None = None,
) -> pd.DataFrame:
    from msm.api.virtual_funds import VirtualFund, _renamed_updater_argument

    updater = _renamed_updater_argument(updater, data_node)

    if plan.status == PLAN_STATUS_INFEASIBLE:
        raise ValueError("Cannot apply an infeasible virtual-fund allocation plan.")
    if plan.source_account_holdings_set_uid is None:
        raise ValueError("Plan requires source_account_holdings_set_uid before apply.")
    if plan.account_uid is None:
        raise ValueError("Plan requires account_uid before apply.")
    if not plan.virtual_fund_allocations:
        raise ValueError("Plan contains no virtual-fund allocations to apply.")

    funds = virtual_fund_holdings_from_plan(plan)
    _refuse_retired_portfolios(plan, funds)
    frames: list[pd.DataFrame] = []
    for fund in funds:
        virtual_fund = VirtualFund.upsert(
            {
                "unique_identifier": fund["unique_identifier"],
                "account_uid": plan.account_uid,
                "target_portfolio_uid": fund["target_portfolio_uid"],
            }
        )
        holdings_set_uid = _deterministic_holdings_set_uid(
            source_account_holdings_set_uid=plan.source_account_holdings_set_uid,
            virtual_fund_uid=str(virtual_fund.uid),
            valuation_time=plan.valuation_time,
        )
        frames.append(
            virtual_fund.allocate_from_account_holdings_set(
                source_account_holdings_set_uid=plan.source_account_holdings_set_uid,
                allocation_time=plan.valuation_time,
                allocations=fund["holdings"],
                virtual_fund_holdings_set_uid=holdings_set_uid,
                updater=None,
                run=False,
                validate_bounds=False,
            )
        )

    frame = pd.concat(frames).sort_index()
    if updater is not None:
        updater.set_frame(frame)
        if run:
            updater.run(update_tree=False)
    return frame


def _refuse_retired_portfolios(
    plan: AccountVirtualFundAllocationPlan,
    funds: Sequence[Mapping[str, Any]],
) -> None:
    """No fund or fund holdings for a portfolio retired at or before the plan (ADR 0049)."""

    from msm.services.portfolio_lifecycle import (
        PortfolioRetiredError,
        retired_portfolios_from_rows,
    )

    retired = retired_portfolios_from_rows(
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


def virtual_fund_holdings_from_plan(
    plan: AccountVirtualFundAllocationPlan,
) -> list[dict[str, Any]]:
    """Return the virtual funds an applied plan writes, each with its holdings rows.

    One entry per virtual-fund claim with a positive allocation:
    ``unique_identifier``, ``target_portfolio_uid`` and ``holdings`` (the
    ``VirtualFundHoldingsStorage`` values of each allocated asset). Claims whose
    allocations are all within ``quantity_tolerance`` are left out.
    """

    funds: list[dict[str, Any]] = []
    for claim_uid, group_lines in _lines_by_claim(plan.virtual_fund_allocations).items():
        metadata = dict(plan.virtual_fund_metadata.get(claim_uid, {}))
        portfolio_uid = metadata.get("target_portfolio_uid") or _first_value(
            group_lines,
            "target_portfolio_uid",
        )
        if portfolio_uid in (None, ""):
            raise ValueError(f"Virtual-fund claim {claim_uid!r} is missing target_portfolio_uid.")
        holdings = [
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
        if not holdings:
            continue
        funds.append(
            {
                "unique_identifier": metadata.get("virtual_fund_unique_identifier") or claim_uid,
                "target_portfolio_uid": str(portfolio_uid),
                "holdings": holdings,
            }
        )
    if not funds:
        raise ValueError("Plan produced no positive virtual-fund allocation rows to apply.")
    return funds


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
    asset_uid_by_identifier: Mapping[str, uuid.UUID | str],
    asset_identifier_by_uid: Mapping[uuid.UUID | str, str],
) -> AccountVirtualFundAllocationInputs:
    """Build planner inputs from already-loaded account and target rows.

    Every target row is a quantity of one asset with a direction (ADR 0052). An
    asset row is a direct target; the portfolio rows of one portfolio are that
    virtual fund's unit basket, one claim per asset.
    """

    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    holdings = _holding_inputs_from_rows(
        account_holdings,
        asset_uid_by_identifier=asset_uid_by_identifier,
    )
    target_rows = _position_set_target_rows(
        _rows_from_records(target_positions),
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
    )
    identifier_by_uid = {str(uid): identifier for uid, identifier in asset_identifier_by_uid.items()}
    direct_demands: list[TargetQuantityDemand] = []
    virtual_demands: list[TargetQuantityDemand] = []

    for row in target_rows:
        target_type = _required_string(row.get("target_type"), "target_type")
        if target_type not in (TARGET_TYPE_ASSET, TARGET_TYPE_PORTFOLIO):
            raise ValueError("target_type must be asset or portfolio.")
        asset_uid = _required_string(row.get("asset_uid"), "asset_uid")
        asset_identifier = identifier_by_uid.get(asset_uid)
        if asset_identifier is None:
            raise ValueError(f"Missing AssetTable identity for asset_uid={asset_uid!r}.")
        quantity = float(row.get("quantity") or 0.0)
        if quantity <= 0:
            raise ValueError("Target row quantity must be positive.")
        direction = _direction(row.get("direction", 1))

        if target_type == TARGET_TYPE_ASSET:
            direct_demands.append(
                TargetQuantityDemand(
                    target_row_key=f"{CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL}:{asset_uid}",
                    asset_uid=asset_uid,
                    asset_identifier=asset_identifier,
                    requested_signed_quantity=quantity * direction,
                    direction=direction,
                    claim_type=CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
                    claim_uid=CLAIM_TYPE_DIRECT_ACCOUNT_RESIDUAL,
                    source_target_uid=asset_uid,
                    target_type=TARGET_TYPE_ASSET,
                    source_row=row,
                )
            )
            continue

        if account_target_allocation_uid in (None, ""):
            raise ValueError("Portfolio target rows require account_target_allocation_uid.")
        portfolio_uid = _required_string(row.get("portfolio_uid"), "portfolio_uid")
        virtual_demands.append(
            TargetQuantityDemand(
                target_row_key=f"{portfolio_uid}:{asset_uid}",
                asset_uid=asset_uid,
                asset_identifier=asset_identifier,
                requested_signed_quantity=quantity * direction,
                direction=direction,
                claim_type=CLAIM_TYPE_VIRTUAL_FUND_TARGET,
                claim_uid=portfolio_uid,
                source_target_uid=portfolio_uid,
                target_type=TARGET_TYPE_PORTFOLIO,
                target_portfolio_uid=portfolio_uid,
                virtual_fund_unique_identifier=virtual_fund_unique_identifier_for_target(
                    account_uid=account_uid,
                    target_portfolio_uid=portfolio_uid,
                    account_target_allocation_uid=account_target_allocation_uid,
                ),
                source_row=row,
            )
        )

    return AccountVirtualFundAllocationInputs(
        account_uid=account_uid,
        source_account_holdings_set_uid=source_account_holdings_set_uid,
        source_holdings=tuple(holdings),
        direct_target_demands=tuple(direct_demands),
        virtual_fund_demands=tuple(virtual_demands),
    )


def resolve_account_virtual_fund_allocation_inputs(
    *,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
    holdings_selection_policy: HoldingsSelectionPolicy,
) -> AccountVirtualFundAllocationInputs:
    """Resolve planner inputs through the account MetaTable relationship graph."""

    from msm.api.base import operation_result_rows
    from msm.bootstrap import resolve_runtime
    from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
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
    _require_target_in_force(
        position_set_row.get("position_set_time"),
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
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
    target_position_rows = _position_set_target_rows(
        operation_result_rows(
            search_model(
                context,
                model=TargetPositionsStorage,
                filters={"position_set_uid": str(position_set_uid)},
                limit=DEFAULT_ALLOCATION_SCAN_LIMIT,
            )
        ),
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
    )
    if not target_position_rows:
        raise ValueError(
            f"No TargetPositionsStorage rows found for position_set_uid={position_set_uid!s}."
        )

    asset_identifiers = {
        str(row[ASSET_IDENTIFIER_DIMENSION])
        for row in account_holding_rows
        if row.get(ASSET_IDENTIFIER_DIMENSION) not in (None, "")
    }
    asset_uids = {
        str(row.get("asset_uid"))
        for row in target_position_rows
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

    return build_account_virtual_fund_allocation_inputs(
        account_uid=account_uid,
        account_target_allocation_uid=target_allocation_uid,
        position_set_uid=position_set_uid,
        source_account_holdings_set_uid=holdings_set_uid,
        account_holdings=account_holding_rows,
        target_positions=target_position_rows,
        valuation_time=normalized_time,
        asset_uid_by_identifier=asset_uid_by_identifier,
        asset_identifier_by_uid=asset_identifier_by_uid,
    )


def _plan_from_quantity_demands(
    *,
    position_set_uid: str | None,
    account_uid: str | None,
    source_account_holdings_set_uid: str | None,
    valuation_time: dt.datetime,
    allocation_policy: AllocationPolicy,
    source_holdings: tuple[AccountHoldingInput, ...],
    direct_target_demands: tuple[TargetQuantityDemand, ...],
    virtual_fund_demands: tuple[TargetQuantityDemand, ...],
    diagnostics: tuple[AllocationDiagnostic, ...],
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
        allocation_policy=allocation_policy,
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
    value: Sequence[AccountHoldingInput | Mapping[str, Any]] | pd.DataFrame,
) -> tuple[AccountHoldingInput, ...]:
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
            AccountHoldingInput(
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
        quantity = float(payload.get("requested_signed_quantity") or 0.0)
        claim_type = _optional_string(payload.get("claim_type")) or default_claim_type
        claim_uid = _optional_string(payload.get("claim_uid")) or claim_type
        asset_uid = _required_string(payload.get("asset_uid"), "asset_uid")
        rows.append(
            TargetQuantityDemand(
                target_row_key=_optional_string(payload.get("target_row_key"))
                or f"{claim_uid}:{asset_uid}",
                asset_uid=asset_uid,
                asset_identifier=_required_string(
                    payload.get("asset_identifier") or payload.get(ASSET_IDENTIFIER_DIMENSION),
                    ASSET_IDENTIFIER_DIMENSION,
                ),
                requested_signed_quantity=quantity,
                direction=1 if quantity >= 0 else -1,
                claim_type=claim_type,
                claim_uid=claim_uid,
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
) -> tuple[AccountHoldingInput, ...]:
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
            AccountHoldingInput(
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


def _rows_from_records(value: Sequence[Mapping[str, Any]] | pd.DataFrame) -> list[dict[str, Any]]:
    if isinstance(value, pd.DataFrame):
        return [dict(row) for row in value.reset_index().to_dict("records")]
    return [dict(row) for row in value]


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


def _position_set_target_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
) -> list[dict[str, Any]]:
    """Return the target rows of the caller's PositionSet, as they are.

    The caller chose the snapshot, so its rows are used whatever their time. A
    target is in force from its own time on: a holdings capture taken after the
    target was written is attributed against it, but a target written after the
    capture cannot apply to it.
    """

    expected_uid = str(position_set_uid)
    selected: list[dict[str, Any]] = []
    snapshot_times: set[dt.datetime] = set()
    for row in rows:
        row_uid = row.get("position_set_uid")
        if not _is_missing(row_uid) and str(row_uid) != expected_uid:
            raise ValueError(
                f"Target row belongs to position_set_uid={row_uid!s}, not {expected_uid}."
            )
        if not _is_missing(row.get("time_index")):
            snapshot_times.add(pd.to_datetime(row["time_index"], utc=True).to_pydatetime())
        _require_target_in_force(
            row.get("time_index"),
            position_set_uid=expected_uid,
            valuation_time=valuation_time,
        )
        selected.append(dict(row))
    if len(snapshot_times) > 1:
        raise ValueError(
            f"Target rows for position_set_uid={expected_uid} span {len(snapshot_times)} "
            "snapshot times; pass only that PositionSet's rows."
        )
    return selected


def _require_target_in_force(
    target_time: Any,
    *,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
) -> None:
    if _is_missing(target_time):
        return
    timestamp = pd.to_datetime(target_time, utc=True).to_pydatetime()
    if timestamp > valuation_time:
        raise ValueError(
            f"PositionSet {position_set_uid!s} was written at {timestamp.isoformat()}, after "
            f"valuation_time={valuation_time.isoformat()}; a target cannot apply to holdings "
            "captured before it."
        )


def _holdings_vector(source_holdings: tuple[AccountHoldingInput, ...]) -> pd.DataFrame:
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
        .agg(requested_signed_quantity=("requested_signed_quantity", "sum"))
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
    "AccountHoldingInput",
    "AccountVirtualFundAllocationPlan",
    "AccountVirtualHoldingLine",
    "AllocationDiagnostic",
    "AllocationPolicy",
    "HoldingsSelectionPolicy",
    "TargetQuantityDemand",
    "apply_account_virtual_fund_allocation_plan",
    "plan_account_virtual_fund_allocations",
    "virtual_fund_holdings_from_plan",
    "virtual_fund_unique_identifier_for_target",
]
