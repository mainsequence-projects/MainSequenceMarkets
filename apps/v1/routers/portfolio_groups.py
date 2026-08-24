from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, status

from apps.v1.schemas.common import ErrorResponse
from apps.v1.schemas.bulk_actions import (
    BULK_ACTION_PREFLIGHT_CONTRACT,
    BulkActionExecutionRequest,
    BulkActionPreflightResponse,
)
from apps.v1.schemas.portfolio_groups import (
    PortfolioGroup,
    PortfolioGroupDeleteResponse,
    PortfolioGroupMembership,
    PortfolioGroupMembershipBulkDeleteRequest,
    PortfolioGroupMembershipRequest,
    Portfolio,
    PortfolioGroupCreateRequest,
    PortfolioGroupUpdateRequest,
)
from apps.v1.schemas.resource_contracts import (
    RESOURCE_COLLECTION_CONTRACT,
    ResourceCollection,
)
from apps.v1.services.portfolio_groups import (
    add_portfolio_to_group,
    bulk_delete_portfolio_group_memberships,
    bulk_delete_portfolio_groups,
    create_portfolio_group,
    delete_portfolio_group,
    get_portfolio_group,
    list_groups_for_portfolio,
    list_portfolio_groups,
    list_portfolios_in_group,
    preflight_bulk_delete_portfolio_groups,
    remove_portfolio_from_group,
    update_portfolio_group,
)
from apps.v1.services.resource_collections import resource_collection_response
from apps.v1.services.bulk_actions import (
    blocked_preflight_detail,
    explicit_uuid_selection,
)

router = APIRouter(prefix="/portfolio-group", tags=["portfolio-group"])


@router.get(
    "/",
    response_model=ResourceCollection[PortfolioGroup],
    summary="List portfolio groups",
    description=(
        "Return named portfolio group identities in the canonical Command Center resource "
        "collection contract. Groups organize portfolios through separate membership rows."
    ),
    operation_id="listPortfolioGroups",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid resource collection request.",
        }
    },
)
def get_portfolio_groups(
    search: Annotated[
        str,
        Query(description="Case-insensitive search across unique identifier and display name."),
    ] = "",
    unique_identifier: Annotated[
        str | None,
        Query(description="Optional exact portfolio group unique identifier."),
    ] = None,
    display_name: Annotated[
        str | None,
        Query(description="Optional exact portfolio group display name."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of portfolio group rows to return."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Zero-based starting offset into the filtered group list."),
    ] = 0,
) -> ResourceCollection[PortfolioGroup]:
    response = list_portfolio_groups(
        search=search,
        unique_identifier=unique_identifier,
        display_name=display_name,
        limit=limit,
        offset=offset,
    )
    return resource_collection_response(
        items=response["results"],
        total_items=response["count"],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/",
    response_model=PortfolioGroup,
    summary="Create portfolio group",
    description="Create or idempotently upsert one named portfolio grouping.",
    operation_id="createPortfolioGroup",
)
def post_portfolio_group(
    request: Annotated[
        PortfolioGroupCreateRequest,
        Body(description="Create or upsert payload for a portfolio group."),
    ],
) -> PortfolioGroup:
    return create_portfolio_group(payload=request.model_dump(exclude_none=True))


@router.post(
    "/bulk-delete/",
    response_model=PortfolioGroupDeleteResponse,
    summary="Bulk delete portfolio groups",
    description=(
        "Delete the explicitly selected portfolio groups after server-side preflight and "
        "authorization. Membership rows follow their database relationship policy."
    ),
    operation_id="bulkDeletePortfolioGroups",
)
def post_portfolio_group_bulk_delete(
    request: Annotated[
        BulkActionExecutionRequest,
        Body(description="Command Center bulk-action execution request."),
    ],
) -> PortfolioGroupDeleteResponse:
    try:
        uids = explicit_uuid_selection(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    preflight = BulkActionPreflightResponse.model_validate(
        preflight_bulk_delete_portfolio_groups(uids=uids)
    )
    if not preflight.allowed:
        raise HTTPException(status_code=409, detail=blocked_preflight_detail(preflight))
    return bulk_delete_portfolio_groups(payload={"uids": uids})


@router.post(
    "/bulk-delete/preflight/",
    response_model=BulkActionPreflightResponse,
    summary="Preflight portfolio-group bulk deletion",
    description="Reauthorize and resolve an explicit group selection without deleting rows.",
    operation_id="preflightBulkDeletePortfolioGroups",
    openapi_extra={"x-ui-contract": BULK_ACTION_PREFLIGHT_CONTRACT},
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def preflight_portfolio_group_bulk_delete(
    request: Annotated[
        BulkActionExecutionRequest,
        Body(description="Command Center bulk-action execution request to preflight."),
    ],
) -> BulkActionPreflightResponse:
    try:
        uids = explicit_uuid_selection(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BulkActionPreflightResponse.model_validate(
        preflight_bulk_delete_portfolio_groups(uids=uids)
    )


@router.post(
    "/membership/bulk-delete/",
    response_model=PortfolioGroupDeleteResponse,
    summary="Bulk delete portfolio group memberships",
    description=(
        "Delete membership rows selected by membership uid, portfolio-group uid, or portfolio "
        "uid without deleting the referenced Portfolio or PortfolioGroup identities."
    ),
    operation_id="bulkDeletePortfolioGroupMemberships",
)
def post_portfolio_group_membership_bulk_delete(
    request: Annotated[
        PortfolioGroupMembershipBulkDeleteRequest,
        Body(description="Bulk delete request for portfolio group memberships."),
    ],
) -> PortfolioGroupDeleteResponse:
    return bulk_delete_portfolio_group_memberships(payload=request.model_dump(mode="json"))


@router.get(
    "/by-portfolio/{portfolio_uid}/",
    response_model=ResourceCollection[PortfolioGroup],
    summary="List groups for portfolio",
    description=(
        "Return the groups containing one Portfolio in the canonical Command Center resource "
        "collection contract."
    ),
    operation_id="listGroupsForPortfolio",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
)
def get_groups_for_portfolio(
    portfolio_uid: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResourceCollection[PortfolioGroup]:
    response = list_groups_for_portfolio(
        portfolio_uid=portfolio_uid,
        limit=limit,
        offset=offset,
    )
    return resource_collection_response(
        items=response["results"],
        total_items=response["count"],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{uid}/",
    response_model=PortfolioGroup,
    summary="Get portfolio group",
    description="Return one PortfolioGroup identity by uid.",
    operation_id="getPortfolioGroup",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio group uid was not found.",
        }
    },
)
def get_portfolio_group_by_uid(uid: str) -> PortfolioGroup:
    group = get_portfolio_group(uid=uid)
    if group is None:
        raise HTTPException(status_code=404, detail=f"Portfolio group {uid!r} was not found.")
    return group


@router.patch(
    "/{uid}/",
    response_model=PortfolioGroup,
    summary="Update portfolio group",
    description="Update mutable display and metadata fields for one PortfolioGroup identity.",
    operation_id="updatePortfolioGroup",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "The requested portfolio group uid was not found.",
        }
    },
)
def patch_portfolio_group(
    uid: str,
    request: Annotated[
        PortfolioGroupUpdateRequest,
        Body(description="Patch payload for an existing portfolio group."),
    ],
) -> PortfolioGroup:
    group = update_portfolio_group(
        uid=uid,
        payload=request.model_dump(exclude_unset=True, exclude_none=False),
    )
    if group is None:
        raise HTTPException(status_code=404, detail=f"Portfolio group {uid!r} was not found.")
    return group


@router.delete(
    "/{uid}/",
    response_model=PortfolioGroupDeleteResponse,
    summary="Delete portfolio group",
    description=(
        "Delete one PortfolioGroup identity and report the number of removed rows. This does not "
        "delete Portfolio identities."
    ),
    operation_id="deletePortfolioGroup",
    status_code=status.HTTP_200_OK,
)
def remove_portfolio_group(uid: str) -> PortfolioGroupDeleteResponse:
    return delete_portfolio_group(uid=uid)


@router.get(
    "/{uid}/portfolios/",
    response_model=ResourceCollection[Portfolio],
    summary="List portfolios in group",
    description=(
        "Return the Portfolios assigned to one group in the canonical Command Center resource "
        "collection contract."
    ),
    operation_id="listPortfoliosInGroup",
    openapi_extra={"x-ui-contract": RESOURCE_COLLECTION_CONTRACT},
)
def get_portfolios_in_group(
    uid: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResourceCollection[Portfolio]:
    response = list_portfolios_in_group(
        portfolio_group_uid=uid,
        limit=limit,
        offset=offset,
    )
    return resource_collection_response(
        items=response["results"],
        total_items=response["count"],
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{uid}/portfolios/",
    response_model=PortfolioGroupMembership,
    summary="Add portfolio to group",
    description=(
        "Create the many-to-many membership between one PortfolioGroup and one Portfolio, "
        "resolving the portfolio by uid or stable unique identifier."
    ),
    operation_id="addPortfolioToGroup",
)
def post_portfolio_to_group(
    uid: str,
    request: Annotated[
        PortfolioGroupMembershipRequest,
        Body(description="Membership payload referencing one portfolio."),
    ],
) -> PortfolioGroupMembership:
    return add_portfolio_to_group(
        portfolio_group_uid=uid,
        payload=request.model_dump(exclude_none=True),
    )


@router.delete(
    "/{uid}/portfolios/{portfolio_uid}/",
    response_model=PortfolioGroupDeleteResponse,
    summary="Remove portfolio from group",
    description=(
        "Delete only the membership between the selected PortfolioGroup and Portfolio; both "
        "resource identities remain intact."
    ),
    operation_id="removePortfolioFromGroup",
)
def delete_portfolio_from_group(
    uid: str,
    portfolio_uid: str,
) -> PortfolioGroupDeleteResponse:
    return remove_portfolio_from_group(
        portfolio_group_uid=uid,
        portfolio_uid=portfolio_uid,
    )
