from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Body, HTTPException, Query, status

from apps.v1.schemas.accounts import (
    AccountAddHoldingsRequest,
    AccountAddTargetPositionsRequest,
    Account,
    AccountCreate,
    AccountUpdate,
    AccountWithIncludes,
    AccountHoldingsByFundResponse,
    AccountHoldingsSnapshotResponse,
    AccountTargetAllocationCandidate,
    AccountTargetAllocationTargetSearchType,
    AccountTargetPositionsSnapshotResponse,
    AccountBulkDeleteResponse,
    AccountDeletePreflightResponse,
    AccountDeleteResponse,
    AccountRegistrationRequest,
    AccountRegistrationResponse,
    AccountVirtualFundAllocateRequest,
    AccountVirtualFundAllocationPlanRequest,
    AccountVirtualFundAllocationPlanResponse,
    AccountVirtualFundAllocationRecordResponse,
    AccountVirtualFundAllocationResponse,
    VirtualFundAllocationPolicyDescription,
    VirtualFundAllocationPolicyList,
)
from apps.v1.schemas.common import FrontEndDetailSummary
from apps.v1.services.accounts import (
    add_account_holdings,
    add_account_target_positions,
    allocate_account_virtual_funds,
    bulk_delete_accounts,
    create_account,
    delete_account,
    get_account_holdings,
    get_account_virtual_fund_allocation,
    get_account_holdings_by_fund,
    get_account,
    get_account_summary,
    get_account_target_positions,
    get_accounts_by_uids,
    get_virtual_fund_allocation_policy,
    list_accounts,
    list_virtual_fund_allocation_policies,
    plan_account_virtual_funds,
    preflight_bulk_delete_accounts,
    register_account,
    search_account_target_allocation_targets,
    update_account,
)
from apps.v1.services.includes import SidecarReadError
from apps.v1.services.resource_discovery import ACCOUNT_DELETE_PORTFOLIOS_OPTION
from msm.services.accounts.allocation_policies import AllocationError
from msm.api.http import (
    BULK_ACTION_PREFLIGHT_CONTRACT,
    RESOURCE_COLLECTION_CONTRACT,
    ApiErrorWithInputsResponse,
    BulkActionExecutionRequest,
    ErrorResponse,
    ResourceCollection,
    api_error_with_inputs,
    blocked_preflight_detail,
    bulk_action_option_values,
    explicit_uuid_selection,
    resource_collection_response,
)

router = APIRouter(prefix="/account", tags=["account"])


@router.get(
    "/",
    response_model=ResourceCollection[Account],
    summary="List accounts",
    description=("Return accounts in the canonical Command Center resource collection contract."),
    operation_id="listAccounts",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid account list request.",
        }
    },
)
def get_accounts(
    search: Annotated[
        str,
        Query(
            description="Case-insensitive search across account uid, unique identifier, and display name.",
        ),
    ] = "",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Maximum number of accounts to return.",
        ),
    ] = 25,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Zero-based starting offset into the filtered account list.",
        ),
    ] = 0,
) -> ResourceCollection[Account]:
    response = list_accounts(search=search, limit=limit, offset=offset)
    return resource_collection_response(
        items=response["results"],
        total_items=int(response["count"]),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/",
    response_model=Account,
    status_code=status.HTTP_201_CREATED,
    summary="Create account",
    description=(
        "Create one account identity row. Providers register accounts through this route "
        "instead of writing the Account table directly (ADR 0047)."
    ),
    operation_id="createAccount",
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_account_record(payload: AccountCreate) -> Account:
    try:
        return create_account(payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/registration/",
    response_model=AccountRegistrationResponse,
    summary="Register account with holdings",
    description=(
        "Register an account and write one holdings snapshot in one MetaTables transaction "
        "(ADR 0051). Creates the missing asset types, assets and cash currency asset, "
        "writes asset snapshots whose values changed, creates or updates the account, and "
        "writes the holdings. Idempotent on `(account.unique_identifier, holdings_date)`: "
        "holdings equal to the stored ones are not written again, and different ones are "
        "replaced only with `overwrite`. A provider writes its own account sidecar "
        "afterwards, with the returned account uid."
    ),
    operation_id="registerAccount",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid payload, or a position names an unknown asset.",
        },
        409: {
            "model": ErrorResponse,
            "description": (
                "An existing asset has another asset_type, or different holdings exist at "
                "holdings_date and overwrite is false. Nothing was written."
            ),
        },
    },
)
def register_account_with_holdings(payload: AccountRegistrationRequest) -> AccountRegistrationResponse:
    try:
        return register_account(payload=payload)
    except ValueError as exc:
        conflict = exc.__class__.__name__ in {
            "AssetTypeConflictError",
            "AccountHoldingsSnapshotExistsError",
        }
        raise HTTPException(status_code=409 if conflict else 400, detail=str(exc)) from exc


ALLOCATION_ERROR_RESPONSES = {
    400: {
        "model": ApiErrorWithInputsResponse,
        "description": "The allocation cannot be planned or applied.",
    },
    404: {
        "model": ApiErrorWithInputsResponse,
        "description": (
            "The account, its PositionSet, its holdings snapshot at valuation_time, or the "
            "policy was not found."
        ),
    },
    409: {
        "model": ApiErrorWithInputsResponse,
        "description": "The request conflicts with the registry or with what is stored.",
    },
}


def _allocation_http_error(exc: Exception) -> HTTPException:
    """Map the allocation services' refusals to their structured HTTP errors (ADR 0053)."""

    if isinstance(exc, AllocationError):
        return api_error_with_inputs(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            errors=exc.errors,
        )
    if exc.__class__.__name__ == "PortfolioRetiredError":
        return api_error_with_inputs(status_code=409, code="portfolio_retired", message=str(exc))
    if isinstance(exc, LookupError):
        return api_error_with_inputs(status_code=404, code="not_found", message=str(exc))
    return api_error_with_inputs(status_code=400, code="bad_request", message=str(exc))


@router.get(
    "/virtual-fund-allocation-policies/",
    response_model=VirtualFundAllocationPolicyList,
    summary="List the virtual-fund allocation policies",
    description=(
        "Every policy that can allocate an account's holdings to its virtual funds: its id, "
        "version, title, description and the path of its description (ADR 0053). It holds "
        "no account data."
    ),
    operation_id="getVirtualFundAllocationPolicies",
)
def list_virtual_fund_allocation_policies_route() -> VirtualFundAllocationPolicyList:
    return list_virtual_fund_allocation_policies()


@router.get(
    "/virtual-fund-allocation-policies/{policy_id}/",
    response_model=VirtualFundAllocationPolicyDescription,
    summary="Describe one virtual-fund allocation policy",
    description=(
        "One policy and its arguments. Each argument's JSON Schema 2020-12, and "
        "`arguments_schema` over all of them, are generated from the class that validates a "
        "request's `policy.arguments`, so the description cannot drift from what runs. A "
        "change to an argument, a bound, a default or a behaviour bumps `version`."
    ),
    operation_id="getVirtualFundAllocationPolicy",
    responses={404: {"model": ErrorResponse, "description": "No policy has this id."}},
)
def get_virtual_fund_allocation_policy_route(
    policy_id: str,
) -> VirtualFundAllocationPolicyDescription:
    policy = get_virtual_fund_allocation_policy(policy_id=policy_id)
    if policy is None:
        raise HTTPException(
            status_code=404,
            detail=f"No virtual-fund allocation policy has the id {policy_id!r}.",
        )
    return policy


@router.get(
    "/by-uids/",
    response_model=ResourceCollection[AccountWithIncludes],
    summary="Look up accounts by uid",
    description=(
        "Return the accounts whose uid is listed in `uid__in` (repeated or comma-separated, "
        "at most 500), in request order. Unknown uids are omitted. A bounded batch lookup for "
        "consumers that hydrate core columns from their own rows; not a browsable collection."
    ),
    operation_id="getAccountsByUids",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid `uid__in` or `include`."},
        404: {"model": ErrorResponse, "description": "An included MetaTable is not visible."},
        409: {"model": ErrorResponse, "description": "An included sidecar could not be read."},
    },
)
def get_accounts_by_uid_list(
    uid__in: Annotated[
        list[str],
        Query(alias="uid__in", description="Account uids, repeated or comma-separated."),
    ],
    include: Annotated[
        list[str] | None,
        Query(
            description=(
                "Provider sidecar MetaTable uids (repeated or comma-separated, at most 10) keyed "
                "by this resource's uid; their rows are attached under `includes`. The Markets "
                "workload needs `data_viewer` on each sidecar."
            ),
        ),
    ] = None,
) -> ResourceCollection[AccountWithIncludes]:
    try:
        items = get_accounts_by_uids(uids=uid__in, include=include)
    except SidecarReadError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return resource_collection_response(
        items=items, total_items=len(items), limit=max(len(items), 1), offset=0
    )


@router.patch(
    "/{uid}/",
    response_model=Account,
    summary="Update account",
    description="Update the mutable fields of one account identity row.",
    operation_id="updateAccount",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse, "description": "Account not found."},
        409: {"model": ErrorResponse},
    },
)
def update_account_record(uid: str, payload: AccountUpdate) -> Account:
    try:
        account = update_account(uid=uid, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account {uid!r} was not found.")
    return account


@router.get(
    "/{uid}/",
    response_model=Account,
    summary="Get account",
    description="Return one canonical account row by uid.",
    operation_id="getAccount",
    responses={404: {"model": ErrorResponse, "description": "Account not found."}},
)
def get_account_by_uid(uid: str) -> Account:
    account = get_account(uid=uid)
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account {uid!r} was not found.")
    return account


_ACCOUNT_DELETE_DESCRIPTION = (
    "Each account is deleted with its whole history in one transaction: its orders, "
    "trades and their order events, order managers, virtual funds, target allocations, "
    "position sets, holdings sets and their rows (ADR 0050). Only Markets tables receive "
    "statements. A table in another namespace loses rows only through its own foreign key: "
    "a CASCADE key deletes them, and a RESTRICT key refuses the delete. With "
    "`delete_portfolios`, the same transaction also deletes, with all their data, the "
    "portfolios the account's virtual funds or target rows name and nothing else uses; "
    "the answer lists them in `deleted_portfolios`, and in `kept_portfolios`, with the "
    "reason, those another account uses, whose values or weights another application's "
    "table holds, or whose delete a foreign key refuses (then the account is deleted "
    "alone). One delete sends MetaTables one read and one transaction; after it commits, "
    "the stored update statistics of the order, trade and event tables and portfolio "
    "datasets that lost rows are rebuilt, and `statistics_not_refreshed` lists any that "
    "could not be."
)
_ACCOUNT_DELETE_OPTIONS = (ACCOUNT_DELETE_PORTFOLIOS_OPTION,)


def _account_bulk_selection(payload: BulkActionExecutionRequest) -> tuple[list[str], bool]:
    try:
        uids = explicit_uuid_selection(payload, options=_ACCOUNT_DELETE_OPTIONS)
        options = bulk_action_option_values(payload, _ACCOUNT_DELETE_OPTIONS)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return uids, options[ACCOUNT_DELETE_PORTFOLIOS_OPTION.key]


@router.post(
    "/bulk-delete/",
    response_model=AccountBulkDeleteResponse,
    summary="Bulk delete accounts",
    description=(
        "Delete the selected accounts. " + _ACCOUNT_DELETE_DESCRIPTION + " The option "
        "`delete_portfolios` in `options` applies it to every selected account. The route "
        "runs the preflight first and answers 409 when it reports a blocker; MetaTables' "
        "delete impact is asked for at most once."
    ),
    operation_id="bulkDeleteAccounts",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid account bulk-delete payload."},
        409: {"model": ErrorResponse, "description": "One or more accounts could not be deleted."},
    },
)
def bulk_delete_account_rows(
    payload: Annotated[
        BulkActionExecutionRequest,
        Body(description="Command Center bulk-action execution request."),
    ],
) -> AccountBulkDeleteResponse:
    uids, delete_portfolios = _account_bulk_selection(payload)
    preflight = preflight_bulk_delete_accounts(uids=uids, delete_portfolios=delete_portfolios)
    if not preflight.allowed:
        raise HTTPException(status_code=409, detail=blocked_preflight_detail(preflight))
    response = bulk_delete_accounts(uids=uids, delete_portfolios=delete_portfolios)
    if response.failed:
        details = "; ".join(f"{failure.uid}: {failure.detail}" for failure in response.failed)
        raise HTTPException(
            status_code=409,
            detail=f"{response.detail} Not deleted: {details}",
        )
    return response


@router.post(
    "/bulk-delete/preflight/",
    response_model=AccountDeletePreflightResponse,
    summary="Preflight account bulk deletion",
    description=(
        "Report, without deleting, the Markets rows each selected account's delete would "
        "remove, the rows of other accounts that block it, and the tables in other "
        "namespaces it reaches through their own foreign keys. With the option "
        "`delete_portfolios`, each account also lists the portfolios its delete would "
        "remove (`portfolios`) and the ones it would keep, with the reason "
        "(`kept_portfolios`); warnings name both."
    ),
    operation_id="preflightBulkDeleteAccounts",
    openapi_extra={"x-ui-contract": BULK_ACTION_PREFLIGHT_CONTRACT},
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def preflight_account_bulk_delete(
    payload: Annotated[
        BulkActionExecutionRequest,
        Body(description="Command Center bulk-action execution request to preflight."),
    ],
) -> AccountDeletePreflightResponse:
    uids, delete_portfolios = _account_bulk_selection(payload)
    return preflight_bulk_delete_accounts(uids=uids, delete_portfolios=delete_portfolios)


@router.delete(
    "/{uid}/",
    response_model=AccountDeleteResponse,
    summary="Delete account",
    description="Delete one account. " + _ACCOUNT_DELETE_DESCRIPTION,
    operation_id="deleteAccount",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid account uid."},
        404: {"model": ErrorResponse, "description": "Account not found."},
        409: {"model": ErrorResponse, "description": "A foreign key refuses the delete."},
    },
)
def remove_account(
    uid: str,
    delete_portfolios: Annotated[
        bool,
        Query(
            description=(
                "Also delete, in the same transaction and with all their data, the "
                "portfolios the account's virtual funds or target rows name and nothing "
                "else uses."
            ),
        ),
    ] = False,
) -> AccountDeleteResponse:
    try:
        response = delete_account(uid=uid, delete_portfolios=delete_portfolios)
    except ValueError as exc:
        status_code = 409 if exc.__class__.__name__ == "AccountDeleteConflictError" else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(status_code=404, detail=f"Account {uid!r} was not found.")
    return response


@router.get(
    "/{uid}/summary/",
    response_model=FrontEndDetailSummary,
    summary="Get account summary",
    description=("Return the reusable frontend detail summary payload for one account."),
    operation_id="getAccountSummary",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        }
    },
)
def get_account_summary_by_uid(uid: str) -> FrontEndDetailSummary:
    summary = get_account_summary(uid=uid)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Account {uid!r} was not found.")
    return summary


@router.get(
    "/target-allocation/targets/",
    response_model=ResourceCollection[AccountTargetAllocationCandidate],
    summary="Search account target-allocation targets",
    description=(
        "Search asset and portfolio rows that can be assigned as account target "
        "positions. Returned rows include the concrete target fields needed by "
        "TargetPositionsStorage."
    ),
    operation_id="searchAccountTargetAllocationTargets",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid target-allocation target search request.",
        }
    },
)
def search_account_target_allocation_target_rows(
    search: Annotated[
        str,
        Query(
            description=(
                "Case-insensitive search across asset identifiers, latest asset "
                "snapshot labels, portfolio identifiers, and target UIDs."
            ),
        ),
    ] = "",
    target_type: Annotated[
        AccountTargetAllocationTargetSearchType,
        Query(description="Candidate kind to return: all, asset, or portfolio."),
    ] = "all",
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of target candidates to return."),
    ] = 25,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the filtered candidate list."),
    ] = 0,
    include_retired: Annotated[
        bool,
        Query(description="Include retired portfolios (ADR 0049). Off by default."),
    ] = False,
) -> ResourceCollection[AccountTargetAllocationCandidate]:
    try:
        response = search_account_target_allocation_targets(
            search=search,
            target_type=target_type,
            limit=limit,
            offset=offset,
            include_retired=include_retired,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return resource_collection_response(
        items=response["results"],
        total_items=int(response["count"]),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{account_uid}/holdings/",
    response_model=AccountHoldingsSnapshotResponse,
    summary="Get account holdings snapshot",
    description=(
        "Return one account holdings snapshot. When the account exists but no holdings "
        "snapshot matches the request, the response is 200 with an empty holdings list."
    ),
    operation_id="getAccountHoldings",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        }
    },
)
def get_account_holdings_by_uid(
    account_uid: str,
    order: Annotated[
        Literal["asc", "desc"],
        Query(
            description="Snapshot ordering used when holdings_date is omitted.",
        ),
    ] = "desc",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=1,
            description="Number of snapshots to return. The current contract returns one snapshot.",
        ),
    ] = 1,
    include_asset_detail: Annotated[
        bool,
        Query(
            description=(
                "When true, include asset.uid, asset_identifier, and current_snapshot labels "
                "when the asset registry rows are available."
            ),
        ),
    ] = True,
    holdings_date: Annotated[
        dt.datetime | None,
        Query(
            description="Exact holdings snapshot timestamp to fetch. Use ISO 8601.",
        ),
    ] = None,
) -> AccountHoldingsSnapshotResponse:
    snapshot = get_account_holdings(
        account_uid=account_uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        holdings_date=holdings_date,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot


@router.get(
    "/{account_uid}/holdings/by-fund/",
    response_model=AccountHoldingsByFundResponse,
    summary="Get account holdings grouped by virtual fund",
    description=(
        "Return one account holdings snapshot grouped by persisted virtual-fund "
        "allocation rows. The response uses VirtualFundHoldingsStorage for fund "
        "allocations and the selected source AccountHoldingsStorage snapshot to "
        "derive residual signed quantities. It does not rerun or apply the "
        "allocation planner."
    ),
    operation_id="getAccountHoldingsByFund",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid account holdings by fund request.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        },
    },
)
def get_account_holdings_by_fund_by_uid(
    account_uid: str,
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Snapshot ordering used when holdings_date is omitted."),
    ] = "desc",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=1,
            description="Number of snapshots to return. The current contract returns one snapshot.",
        ),
    ] = 1,
    include_asset_detail: Annotated[
        bool,
        Query(
            description=(
                "When true, include asset.uid, asset_identifier, and latest "
                "AssetSnapshotsStorage name/ticker labels for grouped holdings "
                "and residual rows."
            ),
        ),
    ] = True,
    holdings_date: Annotated[
        dt.datetime | None,
        Query(description="Exact source account holdings timestamp to fetch. Use ISO 8601."),
    ] = None,
) -> AccountHoldingsByFundResponse:
    try:
        snapshot = get_account_holdings_by_fund(
            account_uid=account_uid,
            order=order,
            limit=limit,
            include_asset_detail=include_asset_detail,
            holdings_date=holdings_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot


@router.get(
    "/{account_uid}/virtual-fund-allocations/",
    response_model=AccountVirtualFundAllocationRecordResponse,
    summary="Get the stored lines of an account's allocation",
    description=(
        "Return the record of one allocation of the account's holdings: one line per owner "
        "and asset, with the sized `target`, what was `assigned` and `delta = target - "
        "assigned`, in signed units. The owner is a virtual fund, or `direct` for what the "
        "account holds outside its funds. There is one allocation per holdings snapshot. "
        "Without `valuation_time` the account's latest allocation is answered. An account "
        "with no allocation at that time answers 200 with no line."
    ),
    operation_id="getAccountVirtualFundAllocation",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        }
    },
)
def get_account_virtual_fund_allocation_by_uid(
    account_uid: str,
    valuation_time: Annotated[
        dt.datetime | None,
        Query(
            description=(
                "Exact time of the allocated holdings snapshot. Use ISO 8601. Omit it for "
                "the latest allocation."
            ),
        ),
    ] = None,
) -> AccountVirtualFundAllocationRecordResponse:
    try:
        record = get_account_virtual_fund_allocation(
            account_uid=account_uid,
            valuation_time=valuation_time,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return record


@router.post(
    "/{account_uid}/virtual-fund-allocations/plan/",
    response_model=AccountVirtualFundAllocationPlanResponse,
    summary="Plan the allocation of an account's holdings to its virtual funds",
    description=(
        "Run an allocation policy for one holdings snapshot against one target and answer the "
        "plan. Nothing is written. The snapshot is the account's holdings set at exactly "
        "`valuation_time`; the target is `position_set_uid`, which must not be later. The "
        "target states exposure, as a share of NAV or an amount; `sized_targets` gives each "
        "exposure in units, sized by the caller with its own prices (ADR 0054). The request "
        "carries no price, NAV or valuation. The plan has one line per owner and asset, "
        "where the owner is a virtual fund or the direct account sleeve: `target`, "
        "`assigned` and `delta = target - assigned`. A positive delta means units are "
        "missing; a negative one means more units than the target asks for. "
        "`account_deltas` gives each asset's total target minus what the account holds."
    ),
    operation_id="planAccountVirtualFunds",
    responses=ALLOCATION_ERROR_RESPONSES,
)
def plan_account_virtual_funds_by_uid(
    account_uid: str,
    payload: AccountVirtualFundAllocationPlanRequest,
) -> AccountVirtualFundAllocationPlanResponse:
    try:
        return plan_account_virtual_funds(account_uid=account_uid, payload=payload)
    except (LookupError, ValueError) as exc:
        raise _allocation_http_error(exc) from exc


@router.post(
    "/{account_uid}/virtual-fund-allocations/",
    response_model=AccountVirtualFundAllocationResponse,
    summary="Allocate an account's holdings to its virtual funds",
    description=(
        "Plan again from the same inputs and write the allocation in one transaction: the "
        "virtual funds, one holdings set per fund, what each fund was assigned, and the "
        "allocation's lines. A line records an owner's sized target and what it was "
        "assigned, for every fund and for what the account holds outside its funds, so the "
        "delta of the sync is kept (ADR 0054). A plan is never accepted from the client. "
        "With `plan_digest`, which covers the sized targets, a recomputed plan with another "
        "digest answers 409 `plan_changed` and nothing is written. A shortfall is not a "
        "refusal. An applied allocation is account history: the same plan again writes "
        "nothing and answers `already_applied`, and a different allocation of the same "
        "snapshot answers 409 `allocation_exists`. A fund whose portfolio was retired at or "
        "before the snapshot answers 409 `portfolio_retired` (ADR 0049). The `GET` of this "
        "path reads the lines back."
    ),
    operation_id="allocateAccountVirtualFunds",
    responses=ALLOCATION_ERROR_RESPONSES,
)
def allocate_account_virtual_funds_by_uid(
    account_uid: str,
    payload: AccountVirtualFundAllocateRequest,
) -> AccountVirtualFundAllocationResponse:
    try:
        return allocate_account_virtual_funds(account_uid=account_uid, payload=payload)
    except (LookupError, ValueError) as exc:
        raise _allocation_http_error(exc) from exc


@router.post(
    "/{account_uid}/add-holdings/",
    response_model=AccountHoldingsSnapshotResponse,
    summary="Add account holdings snapshot",
    description=(
        "Create or replace one account holdings snapshot and return it using the "
        "same response contract as the holdings read endpoint."
    ),
    operation_id="addAccountHoldings",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid holdings payload.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": "A holdings snapshot already exists and overwrite is false.",
        },
    },
)
def add_account_holdings_by_uid(
    account_uid: str,
    payload: AccountAddHoldingsRequest,
) -> AccountHoldingsSnapshotResponse:
    try:
        snapshot = add_account_holdings(account_uid=account_uid, payload=payload)
    except ValueError as exc:
        if exc.__class__.__name__ == "AccountHoldingsSnapshotExistsError":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot


@router.post(
    "/{account_uid}/add-target-positions/",
    response_model=AccountTargetPositionsSnapshotResponse,
    summary="Add account target positions snapshot",
    description=(
        "Create or replace one account target-position snapshot and return it using "
        "the same response contract as the target-positions read endpoint. Parent "
        "allocation rows are derived from the account uid in the path. A snapshot that "
        "names a retired portfolio is refused with 409, whatever its date (ADR 0049)."
    ),
    operation_id="addAccountTargetPositions",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid target-position payload.",
        },
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        },
        409: {
            "model": ErrorResponse,
            "description": (
                "A target-position snapshot already exists and overwrite is false, or the "
                "snapshot names a retired portfolio."
            ),
        },
    },
)
def add_account_target_positions_by_uid(
    account_uid: str,
    payload: AccountAddTargetPositionsRequest,
) -> AccountTargetPositionsSnapshotResponse:
    try:
        snapshot = add_account_target_positions(account_uid=account_uid, payload=payload)
    except ValueError as exc:
        if exc.__class__.__name__ in {
            "AccountTargetPositionsSnapshotExistsError",
            "PortfolioRetiredError",
        }:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot


@router.get(
    "/{account_uid}/target-positions/",
    response_model=AccountTargetPositionsSnapshotResponse,
    summary="Get account target positions snapshot",
    description=(
        "Return one account target-position snapshot. When the account exists but no "
        "target-position snapshot matches the request, the response is 200 with an "
        "empty positions list."
    ),
    operation_id="getAccountTargetPositions",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested account uid was not found.",
        }
    },
)
def get_account_target_positions_by_uid(
    account_uid: str,
    order: Annotated[
        Literal["asc", "desc"],
        Query(
            description="Position-set ordering used when target_positions_date is omitted.",
        ),
    ] = "desc",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=1,
            description="Number of snapshots to return. The current contract returns one snapshot.",
        ),
    ] = 1,
    include_asset_detail: Annotated[
        bool,
        Query(
            description=(
                "When true, include asset.uid, asset.unique_identifier, and the latest "
                "AssetSnapshotsStorage name/ticker labels when available."
            ),
        ),
    ] = True,
    target_positions_date: Annotated[
        dt.datetime | None,
        Query(
            description="Exact target-position snapshot timestamp to fetch. Use ISO 8601.",
        ),
    ] = None,
) -> AccountTargetPositionsSnapshotResponse:
    snapshot = get_account_target_positions(
        account_uid=account_uid,
        order=order,
        limit=limit,
        include_asset_detail=include_asset_detail,
        target_positions_date=target_positions_date,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Account {account_uid!r} was not found.")
    return snapshot
