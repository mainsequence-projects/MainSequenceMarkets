"""Plan and apply the allocation of an account's holdings to its virtual funds (ADR 0053).

Targets and holdings are both recorded in units (ADR 0052), so an allocation reads
no price, NAV or valuation. A plan answers one line per owner and asset: what the
owner should hold (``target``), what it gets (``assigned``) and the difference
(``delta``). The owner is a virtual fund or the direct account sleeve.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pandas as pd

from msm.services.accounts.allocation_policies import (
    AllocationError,
    AllocationPolicyChoice,
    ResolvedAllocationPolicy,
    default_allocation_policy_choice,
    resolve_allocation_policy,
)
from msm.settings import ASSET_IDENTIFIER_DIMENSION

TARGET_TYPE_ASSET = "asset"
TARGET_TYPE_PORTFOLIO = "portfolio"
OWNER_FUND = "fund"
OWNER_DIRECT = "direct"
DEFAULT_ALLOCATION_SCAN_LIMIT = 5_000
APPLY_BLOCKER_PORTFOLIO_RETIRED = "portfolio_retired"


@dataclass(frozen=True, slots=True)
class AccountVirtualFundAllocationInputs:
    """What an allocation reads, as signed quantities: quantity times direction."""

    account_uid: str
    source_account_holdings_set_uid: str
    holdings: Mapping[str, float]
    fund_targets: Mapping[tuple[str, str], float]
    direct_targets: Mapping[str, float]
    asset_identifiers: Mapping[str, str]
    fund_unique_identifiers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class AllocationLine:
    """What one owner should hold of one asset, what it gets, and the difference.

    ``delta = target - assigned``, in signed units. Positive: units are missing.
    Negative: there are more units than the target asks for.
    """

    owner: Literal["fund", "direct"]
    asset_uid: str
    asset_identifier: str
    target: float
    assigned: float
    delta: float
    target_portfolio_uid: str | None = None
    virtual_fund_unique_identifier: str | None = None


@dataclass(frozen=True, slots=True)
class AccountAssetDelta:
    """One asset across the whole account: held, targeted, and the difference."""

    asset_uid: str
    asset_identifier: str
    held: float
    target: float
    delta: float


@dataclass(frozen=True, slots=True)
class AllocationFund:
    virtual_fund_unique_identifier: str
    target_portfolio_uid: str
    virtual_fund_uid: str | None = None
    holdings_set_uid: str | None = None


@dataclass(frozen=True, slots=True)
class AccountVirtualFundAllocationPlan:
    """The allocation of one holdings snapshot to the account's virtual funds, in units."""

    account_uid: str
    source_account_holdings_set_uid: str
    position_set_uid: str
    valuation_time: dt.datetime
    policy: ResolvedAllocationPolicy
    funds: tuple[AllocationFund, ...] = ()
    lines: tuple[AllocationLine, ...] = ()
    account_deltas: tuple[AccountAssetDelta, ...] = ()
    apply_blockers: tuple[Mapping[str, Any], ...] = ()
    plan_digest: str = ""

    @property
    def fund_lines(self) -> tuple[AllocationLine, ...]:
        return tuple(line for line in self.lines if line.owner == OWNER_FUND)

    @property
    def direct_lines(self) -> tuple[AllocationLine, ...]:
        return tuple(line for line in self.lines if line.owner == OWNER_DIRECT)

    def to_frames(self) -> dict[str, pd.DataFrame]:
        return {
            "lines": pd.DataFrame([asdict(line) for line in self.lines]),
            "account_deltas": pd.DataFrame([asdict(row) for row in self.account_deltas]),
        }


@dataclass(frozen=True, slots=True)
class AccountVirtualFundAllocationResult:
    """What the apply step did with a plan."""

    plan: AccountVirtualFundAllocationPlan
    applied: bool
    already_applied: bool
    funds: tuple[AllocationFund, ...]
    rows: tuple[Mapping[str, Any], ...] = field(default=())

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([dict(row) for row in self.rows])


def plan_account_virtual_fund_allocations(
    *,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
    policy: AllocationPolicyChoice | Mapping[str, Any] | None = None,
) -> AccountVirtualFundAllocationPlan:
    """Plan the allocation of one holdings snapshot against one PositionSet.

    The snapshot is the account's holdings set at exactly ``valuation_time``.
    ``policy`` names a policy of the registry, its version and its arguments; it
    defaults to ``proportional_attribution`` at its current version. Nothing is
    written.
    """

    return plan_account_virtual_fund_allocations_in_context(
        _allocation_context(),
        position_set_uid=position_set_uid,
        valuation_time=valuation_time,
        policy=policy,
    )


def plan_account_virtual_fund_allocations_in_context(
    context: Any,
    *,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
    policy: AllocationPolicyChoice | Mapping[str, Any] | None = None,
    account_uid: uuid.UUID | str | None = None,
) -> AccountVirtualFundAllocationPlan:
    """``plan_account_virtual_fund_allocations`` on a repository context.

    With ``account_uid``, a PositionSet of another account is not found.
    """

    resolved_policy = resolve_allocation_policy(policy or default_allocation_policy_choice())
    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    inputs = resolve_account_virtual_fund_allocation_inputs(
        context,
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
        account_uid=account_uid,
    )
    plan = plan_from_inputs(
        inputs,
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
        policy=resolved_policy,
    )
    return _with_apply_blockers(context, plan)


def plan_from_inputs(
    inputs: AccountVirtualFundAllocationInputs,
    *,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
    policy: ResolvedAllocationPolicy | AllocationPolicyChoice | Mapping[str, Any] | None = None,
) -> AccountVirtualFundAllocationPlan:
    """Run a policy on already-resolved inputs and build the plan's lines."""

    resolved_policy = (
        policy
        if isinstance(policy, ResolvedAllocationPolicy)
        else resolve_allocation_policy(policy or default_allocation_policy_choice())
    )
    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    allocation = resolved_policy.allocate(inputs.holdings, inputs.fund_targets)
    tolerance = resolved_policy.quantity_tolerance

    lines: list[AllocationLine] = []
    for (portfolio_uid, asset_uid), target in sorted(inputs.fund_targets.items()):
        assigned = float(allocation.fills.get((portfolio_uid, asset_uid), 0.0))
        lines.append(
            AllocationLine(
                owner=OWNER_FUND,
                asset_uid=asset_uid,
                asset_identifier=inputs.asset_identifiers[asset_uid],
                target=float(target),
                assigned=assigned,
                delta=float(target) - assigned,
                target_portfolio_uid=portfolio_uid,
                virtual_fund_unique_identifier=inputs.fund_unique_identifiers[portfolio_uid],
            )
        )

    assets = sorted(
        {*inputs.holdings, *inputs.direct_targets, *(asset for _, asset in inputs.fund_targets)},
        key=lambda asset_uid: inputs.asset_identifiers[asset_uid],
    )
    account_deltas: list[AccountAssetDelta] = []
    for asset_uid in assets:
        held = float(inputs.holdings.get(asset_uid, 0.0))
        direct_target = float(inputs.direct_targets.get(asset_uid, 0.0))
        direct_assigned = float(allocation.direct.get(asset_uid, held))
        if direct_target != 0.0 or abs(direct_assigned) > tolerance:
            lines.append(
                AllocationLine(
                    owner=OWNER_DIRECT,
                    asset_uid=asset_uid,
                    asset_identifier=inputs.asset_identifiers[asset_uid],
                    target=direct_target,
                    assigned=direct_assigned,
                    delta=direct_target - direct_assigned,
                )
            )
        total_target = direct_target + sum(
            float(target)
            for (_, target_asset), target in inputs.fund_targets.items()
            if target_asset == asset_uid
        )
        account_deltas.append(
            AccountAssetDelta(
                asset_uid=asset_uid,
                asset_identifier=inputs.asset_identifiers[asset_uid],
                held=held,
                target=total_target,
                delta=total_target - held,
            )
        )

    funds = tuple(
        AllocationFund(
            virtual_fund_unique_identifier=inputs.fund_unique_identifiers[portfolio_uid],
            target_portfolio_uid=portfolio_uid,
        )
        for portfolio_uid in sorted({portfolio_uid for portfolio_uid, _ in inputs.fund_targets})
    )
    plan = AccountVirtualFundAllocationPlan(
        account_uid=str(inputs.account_uid),
        source_account_holdings_set_uid=str(inputs.source_account_holdings_set_uid),
        position_set_uid=_uid(position_set_uid),
        valuation_time=normalized_time,
        policy=resolved_policy,
        funds=funds,
        lines=tuple(lines),
        account_deltas=tuple(account_deltas),
    )
    return _replace(plan, plan_digest=_plan_digest(plan))


def apply_account_virtual_fund_allocation_plan(
    plan: AccountVirtualFundAllocationPlan,
) -> AccountVirtualFundAllocationResult:
    """Write a plan's virtual funds and their holdings in one transaction."""

    return apply_account_virtual_fund_allocation_plan_in_context(_allocation_context(), plan)


def apply_account_virtual_fund_allocation_plan_in_context(
    context: Any,
    plan: AccountVirtualFundAllocationPlan,
) -> AccountVirtualFundAllocationResult:
    """Write the plan's funds, holdings sets and holdings rows atomically.

    An applied allocation is account history: applying the same plan again
    writes nothing and answers ``already_applied``, and a different allocation
    of the same snapshot is refused (``allocation_exists``). No fund is written
    for a portfolio retired at or before the plan's time (ADR 0049).
    """

    from msm.api.base import operation_result_rows
    from msm.repositories.virtual_funds import (
        search_account_virtual_fund_allocation,
        search_virtual_funds_by_unique_identifiers,
        write_account_virtual_fund_allocation,
    )
    from msm.services.portfolio_lifecycle import PortfolioRetiredError, retired_portfolios

    funds = virtual_fund_holdings_from_plan(plan)
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

    def existing_allocation() -> list[dict[str, Any]]:
        return operation_result_rows(
            search_account_virtual_fund_allocation(
                context,
                account_uid=plan.account_uid,
                source_account_holdings_set_uid=plan.source_account_holdings_set_uid,
            )
        )

    existing = existing_allocation()
    if existing:
        return _already_applied_or_refused(plan, existing)

    known_funds = {
        str(row["unique_identifier"]): row
        for row in operation_result_rows(
            search_virtual_funds_by_unique_identifiers(
                context,
                unique_identifiers=[fund["unique_identifier"] for fund in funds],
            )
        )
    }
    for unique_identifier, row in known_funds.items():
        if not _same_uid(row.get("account_uid"), plan.account_uid):
            raise AllocationError(
                "allocation_exists",
                f"Virtual fund {unique_identifier!r} belongs to another account.",
                status_code=409,
            )

    fund_writes = []
    for fund in funds:
        known = known_funds.get(fund["unique_identifier"])
        virtual_fund_uid = str(uuid.UUID(str(known["uid"]))) if known else str(uuid.uuid4())
        fund_writes.append(
            {
                **fund,
                "virtual_fund_uid": virtual_fund_uid,
                "holdings_set_uid": str(
                    _deterministic_holdings_set_uid(
                        source_account_holdings_set_uid=plan.source_account_holdings_set_uid,
                        virtual_fund_uid=virtual_fund_uid,
                        valuation_time=plan.valuation_time,
                    )
                ),
            }
        )

    rows = operation_result_rows(
        write_account_virtual_fund_allocation(
            context,
            account_uid=plan.account_uid,
            source_account_holdings_set_uid=plan.source_account_holdings_set_uid,
            allocation_time=plan.valuation_time,
            funds=fund_writes,
        )
    )
    if not rows:
        # Another writer allocated the snapshot between the read and the write.
        existing = existing_allocation()
        if existing:
            return _already_applied_or_refused(plan, existing)
        raise AllocationError(
            "allocation_exists",
            "The allocation was not written: one of its virtual funds belongs to another "
            "account.",
            status_code=409,
        )

    return AccountVirtualFundAllocationResult(
        plan=plan,
        applied=True,
        already_applied=False,
        funds=tuple(
            AllocationFund(
                virtual_fund_unique_identifier=fund["unique_identifier"],
                target_portfolio_uid=fund["target_portfolio_uid"],
                virtual_fund_uid=fund["virtual_fund_uid"],
                holdings_set_uid=fund["holdings_set_uid"],
            )
            for fund in fund_writes
        ),
        rows=tuple(dict(row) for row in rows),
    )


def allocate_account_virtual_funds_in_context(
    context: Any,
    *,
    account_uid: uuid.UUID | str,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
    policy: AllocationPolicyChoice | Mapping[str, Any] | None = None,
    plan_digest: str | None = None,
) -> AccountVirtualFundAllocationResult:
    """Plan again from the same inputs, then apply.

    With ``plan_digest``, a recomputed plan with another digest is refused
    (``plan_changed``) and nothing is written.
    """

    plan = plan_account_virtual_fund_allocations_in_context(
        context,
        position_set_uid=position_set_uid,
        valuation_time=valuation_time,
        policy=policy,
        account_uid=account_uid,
    )
    if plan_digest not in (None, "") and plan_digest != plan.plan_digest:
        raise AllocationError(
            "plan_changed",
            "The target or the holdings changed since the plan was made; plan again.",
            status_code=409,
        )
    return apply_account_virtual_fund_allocation_plan_in_context(context, plan)


def plan_response(plan: AccountVirtualFundAllocationPlan) -> dict[str, Any]:
    """A plan as the Markets API answers it."""

    return {
        "account_uid": plan.account_uid,
        "holdings_set_uid": plan.source_account_holdings_set_uid,
        "position_set_uid": plan.position_set_uid,
        "valuation_time": plan.valuation_time,
        "policy": plan.policy.as_choice(),
        "funds": [asdict(fund) for fund in plan.funds],
        "lines": [asdict(line) for line in plan.lines],
        "account_deltas": [asdict(row) for row in plan.account_deltas],
        "apply_blockers": [dict(blocker) for blocker in plan.apply_blockers],
        "plan_digest": plan.plan_digest,
    }


def allocation_response(result: AccountVirtualFundAllocationResult) -> dict[str, Any]:
    """An apply result as the Markets API answers it: the plan and what was written."""

    return {
        **plan_response(result.plan),
        "funds": [asdict(fund) for fund in result.funds],
        "applied": result.applied,
        "already_applied": result.already_applied,
    }


def virtual_fund_holdings_from_plan(
    plan: AccountVirtualFundAllocationPlan,
) -> list[dict[str, Any]]:
    """Return the virtual funds an applied plan writes, each with its holdings rows.

    One entry per fund with a fill above the policy's quantity tolerance:
    ``unique_identifier``, ``target_portfolio_uid`` and ``holdings`` (the
    ``VirtualFundHoldingsStorage`` values of each allocated asset).
    """

    tolerance = plan.policy.quantity_tolerance
    funds: dict[str, dict[str, Any]] = {}
    for line in plan.fund_lines:
        if abs(line.assigned) <= tolerance:
            continue
        fund = funds.setdefault(
            str(line.virtual_fund_unique_identifier),
            {
                "unique_identifier": str(line.virtual_fund_unique_identifier),
                "target_portfolio_uid": str(line.target_portfolio_uid),
                "holdings": [],
            },
        )
        fund["holdings"].append(
            {
                ASSET_IDENTIFIER_DIMENSION: line.asset_identifier,
                "allocated_quantity": abs(line.assigned),
                "allocation_strategy": plan.policy.id,
                "direction": 1 if line.assigned > 0 else -1,
                "extra_details": {
                    "source": "account_virtual_allocation_plan",
                    "policy_version": plan.policy.version,
                    "position_set_uid": plan.position_set_uid,
                    "plan_digest": plan.plan_digest,
                },
            }
        )
    if not funds:
        raise AllocationError(
            "nothing_to_apply",
            "The plan gives no virtual fund any units, so there is nothing to write.",
        )
    return [funds[unique_identifier] for unique_identifier in sorted(funds)]


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

    Every row is a positive quantity of one asset with a direction (ADR 0052).
    An asset target row is a direct target; the portfolio rows of one portfolio
    are that virtual fund's unit basket.
    """

    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    uid_by_identifier = {
        str(identifier): _uid(uid) for identifier, uid in asset_uid_by_identifier.items()
    }
    identifier_by_uid = {
        _uid(uid): str(identifier) for uid, identifier in asset_identifier_by_uid.items()
    }

    holdings: dict[str, float] = {}
    for row in _rows_from_records(account_holdings):
        asset_identifier = _required_string(
            row.get(ASSET_IDENTIFIER_DIMENSION) or row.get("asset_identifier"),
            ASSET_IDENTIFIER_DIMENSION,
        )
        asset_uid = uid_by_identifier.get(asset_identifier)
        if asset_uid is None:
            raise ValueError(f"Missing AssetTable.uid for asset_identifier={asset_identifier!r}.")
        holdings[asset_uid] = holdings.get(asset_uid, 0.0) + _signed_quantity(
            row, label="Account holding"
        )

    fund_targets: dict[tuple[str, str], float] = {}
    direct_targets: dict[str, float] = {}
    fund_unique_identifiers: dict[str, str] = {}
    for row in _position_set_target_rows(
        _rows_from_records(target_positions),
        position_set_uid=position_set_uid,
        valuation_time=normalized_time,
    ):
        target_type = _required_string(row.get("target_type"), "target_type")
        if target_type not in (TARGET_TYPE_ASSET, TARGET_TYPE_PORTFOLIO):
            raise ValueError("target_type must be asset or portfolio.")
        asset_uid = _uid(_required_string(row.get("asset_uid"), "asset_uid"))
        if asset_uid not in identifier_by_uid:
            raise ValueError(f"Missing AssetTable identity for asset_uid={asset_uid!r}.")
        signed = _signed_quantity(row, label="Target row")

        if target_type == TARGET_TYPE_ASSET:
            direct_targets[asset_uid] = direct_targets.get(asset_uid, 0.0) + signed
            continue

        if account_target_allocation_uid in (None, ""):
            raise ValueError("Portfolio target rows require account_target_allocation_uid.")
        portfolio_uid = _uid(_required_string(row.get("portfolio_uid"), "portfolio_uid"))
        if (portfolio_uid, asset_uid) in fund_targets:
            raise ValueError(
                f"Portfolio {portfolio_uid} names asset {asset_uid} twice in its basket."
            )
        fund_targets[(portfolio_uid, asset_uid)] = signed
        fund_unique_identifiers.setdefault(
            portfolio_uid,
            virtual_fund_unique_identifier_for_target(
                account_uid=account_uid,
                target_portfolio_uid=portfolio_uid,
                account_target_allocation_uid=account_target_allocation_uid,
            ),
        )

    return AccountVirtualFundAllocationInputs(
        account_uid=_uid(account_uid),
        source_account_holdings_set_uid=_uid(source_account_holdings_set_uid),
        holdings=holdings,
        fund_targets=fund_targets,
        direct_targets=direct_targets,
        asset_identifiers=identifier_by_uid,
        fund_unique_identifiers=fund_unique_identifiers,
    )


def resolve_account_virtual_fund_allocation_inputs(
    context: Any,
    *,
    position_set_uid: uuid.UUID | str,
    valuation_time: dt.datetime,
    account_uid: uuid.UUID | str | None = None,
) -> AccountVirtualFundAllocationInputs:
    """Resolve planner inputs through the account MetaTable relationship graph."""

    from msm.api.base import operation_result_rows
    from msm.models.accounts import (
        AccountHoldingsSetTable,
        AccountTargetAllocationTable,
        PositionSetTable,
    )
    from msm.models.assets import AssetTable
    from msm.repositories.crud import search_model
    from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage

    normalized_time = _utc_timestamp(valuation_time, field_name="valuation_time")
    position_set_row = _one_row(
        operation_result_rows(
            search_model(
                context,
                model=PositionSetTable,
                filters={"uid": str(position_set_uid)},
                limit=2,
            )
        ),
        label="PositionSet",
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
        label="AccountTargetAllocation",
        filters={"uid": target_allocation_uid},
    )
    resolved_account_uid = _required_string(
        target_allocation_row.get("account_uid"),
        "AccountTargetAllocationTable.account_uid",
    )
    if account_uid not in (None, "") and not _same_uid(account_uid, resolved_account_uid):
        raise AllocationError(
            "not_found",
            f"PositionSet {position_set_uid!s} was not found for account {account_uid!s}.",
            status_code=404,
        )
    holdings_set_row = _one_row(
        operation_result_rows(
            search_model(
                context,
                model=AccountHoldingsSetTable,
                filters={
                    "account_uid": resolved_account_uid,
                    "time_index": normalized_time,
                },
                limit=2,
            )
        ),
        label="AccountHoldingsSet",
        filters={"account_uid": resolved_account_uid, "time_index": normalized_time.isoformat()},
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
    target_position_rows = operation_result_rows(
        search_model(
            context,
            model=TargetPositionsStorage,
            filters={"position_set_uid": str(position_set_uid)},
            limit=DEFAULT_ALLOCATION_SCAN_LIMIT,
        )
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
    missing_uids = sorted(
        uid for uid in asset_uids if not any(_same_uid(uid, known) for known in asset_identifier_by_uid)
    )
    if missing_identifiers or missing_uids:
        raise ValueError(
            "Could not resolve AssetTable identity for allocation inputs. "
            f"missing_identifiers={missing_identifiers}, missing_uids={missing_uids}."
        )

    return build_account_virtual_fund_allocation_inputs(
        account_uid=resolved_account_uid,
        account_target_allocation_uid=target_allocation_uid,
        position_set_uid=position_set_uid,
        source_account_holdings_set_uid=holdings_set_uid,
        account_holdings=account_holding_rows,
        target_positions=target_position_rows,
        valuation_time=normalized_time,
        asset_uid_by_identifier=asset_uid_by_identifier,
        asset_identifier_by_uid=asset_identifier_by_uid,
    )


def _allocation_context() -> Any:
    from msm.bootstrap import resolve_runtime
    from msm.models import (
        PortfolioTable,
        VirtualFundHoldingsSetTable,
        VirtualFundTable,
    )
    from msm.models.accounts import (
        AccountHoldingsSetTable,
        AccountTargetAllocationTable,
        PositionSetTable,
    )
    from msm.models.assets import AssetTable
    from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
    from msm.time_index.accounts.virtual_funds.storage import VirtualFundHoldingsStorage

    return resolve_runtime(
        models=[
            PositionSetTable,
            AccountTargetAllocationTable,
            AccountHoldingsSetTable,
            AccountHoldingsStorage,
            TargetPositionsStorage,
            AssetTable,
            PortfolioTable,
            VirtualFundTable,
            VirtualFundHoldingsSetTable,
            VirtualFundHoldingsStorage,
        ],
        row_model_name="Account virtual-fund allocation",
    ).context


def _with_apply_blockers(
    context: Any,
    plan: AccountVirtualFundAllocationPlan,
) -> AccountVirtualFundAllocationPlan:
    from msm.services.portfolio_lifecycle import retired_portfolios

    retired = retired_portfolios(
        context,
        (fund.target_portfolio_uid for fund in plan.funds),
        as_of=plan.valuation_time,
    )
    if not retired:
        return plan
    return _replace(
        plan,
        apply_blockers=tuple(
            {"code": APPLY_BLOCKER_PORTFOLIO_RETIRED, "portfolio_uid": portfolio_uid}
            for portfolio_uid in sorted(_uid(value) for value in retired)
        ),
    )


def _already_applied_or_refused(
    plan: AccountVirtualFundAllocationPlan,
    existing: Sequence[Mapping[str, Any]],
) -> AccountVirtualFundAllocationResult:
    digests = {str(_mapping(row.get("extra_details")).get("plan_digest") or "") for row in existing}
    if digests != {plan.plan_digest}:
        raise AllocationError(
            "allocation_exists",
            f"The holdings snapshot of account {plan.account_uid} at "
            f"{plan.valuation_time.isoformat()} already has a different virtual-fund "
            "allocation. An applied allocation is account history and is not replaced.",
            status_code=409,
        )
    funds: dict[str, AllocationFund] = {}
    for row in existing:
        funds[str(row["unique_identifier"])] = AllocationFund(
            virtual_fund_unique_identifier=str(row["unique_identifier"]),
            target_portfolio_uid=str(uuid.UUID(str(row["target_portfolio_uid"]))),
            virtual_fund_uid=str(uuid.UUID(str(row["virtual_fund_uid"]))),
            holdings_set_uid=str(uuid.UUID(str(row["holdings_set_uid"]))),
        )
    return AccountVirtualFundAllocationResult(
        plan=plan,
        applied=False,
        already_applied=True,
        funds=tuple(funds[unique_identifier] for unique_identifier in sorted(funds)),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _plan_digest(plan: AccountVirtualFundAllocationPlan) -> str:
    """The SHA-256 of the request and of the plan's lines, as canonical JSON."""

    payload = {
        "account_uid": plan.account_uid,
        "source_account_holdings_set_uid": plan.source_account_holdings_set_uid,
        "position_set_uid": plan.position_set_uid,
        "valuation_time": plan.valuation_time.isoformat(),
        "policy": plan.policy.as_choice(),
        "lines": [
            [
                line.owner,
                line.target_portfolio_uid,
                line.asset_uid,
                repr(line.target),
                repr(line.assigned),
            ]
            for line in plan.lines
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replace(
    plan: AccountVirtualFundAllocationPlan, **changes: Any
) -> AccountVirtualFundAllocationPlan:
    values = {name: getattr(plan, name) for name in plan.__dataclass_fields__}
    return AccountVirtualFundAllocationPlan(**{**values, **changes})


def _signed_quantity(row: Mapping[str, Any], *, label: str) -> float:
    quantity = _optional_float(row.get("quantity"))
    if quantity is None or quantity <= 0:
        raise ValueError(f"{label} quantity must be positive.")
    return quantity * _direction(row.get("direction", 1))


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
        raise AllocationError(
            "not_found",
            f"Expected one {label} row for {dict(filters)!r}, found {len(rows)}.",
            status_code=404,
        )
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
        if not _is_missing(row_uid) and not _same_uid(row_uid, expected_uid):
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
        raise AllocationError(
            "target_after_snapshot",
            f"PositionSet {position_set_uid!s} was written at {timestamp.isoformat()}, after "
            f"valuation_time={valuation_time.isoformat()}; a target cannot apply to holdings "
            "captured before it.",
        )


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


def _uid(value: Any) -> str:
    """A uid as dashed text, whatever form the backend returned it in."""

    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return str(value)


def _same_uid(left: Any, right: Any) -> bool:
    try:
        return uuid.UUID(str(left)) == uuid.UUID(str(right))
    except ValueError:
        return str(left) == str(right)


def _utc_timestamp(value: dt.datetime, *, field_name: str) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")
    return value.astimezone(dt.UTC)


def _direction(value: Any) -> Literal[1, -1]:
    direction = int(value)
    if direction not in {1, -1}:
        raise ValueError("direction must be 1 or -1.")
    return 1 if direction == 1 else -1


def _required_string(value: Any, field_name: str) -> str:
    if _is_missing(value):
        raise ValueError(f"{field_name} is required.")
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
    "OWNER_DIRECT",
    "OWNER_FUND",
    "AccountAssetDelta",
    "AccountVirtualFundAllocationInputs",
    "AccountVirtualFundAllocationPlan",
    "AccountVirtualFundAllocationResult",
    "AllocationFund",
    "AllocationLine",
    "allocate_account_virtual_funds_in_context",
    "allocation_response",
    "apply_account_virtual_fund_allocation_plan",
    "apply_account_virtual_fund_allocation_plan_in_context",
    "build_account_virtual_fund_allocation_inputs",
    "plan_account_virtual_fund_allocations",
    "plan_account_virtual_fund_allocations_in_context",
    "plan_from_inputs",
    "plan_response",
    "virtual_fund_holdings_from_plan",
    "virtual_fund_unique_identifier_for_target",
]
