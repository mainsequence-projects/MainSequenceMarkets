from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, Request, status

from apps.v1.schemas.common import ErrorResponse, build_paginated_response
from apps.v1.schemas.portfolio_groups import (
    PortfolioGroup,
    PortfolioGroupBulkDeleteRequest,
    PortfolioGroupDeleteResponse,
    PortfolioGroupListResponse,
    PortfolioGroupMembership,
    PortfolioGroupMembershipBulkDeleteRequest,
    PortfolioGroupMembershipRequest,
    PortfolioGroupPortfolioListResponse,
    PortfolioGroupsForPortfolioResponse,
    PortfolioGroupCreateRequest,
    PortfolioGroupUpdateRequest,
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
    remove_portfolio_from_group,
    update_portfolio_group,
)

router = APIRouter(prefix="/portfolio-group", tags=["portfolio-group"])


@router.get(
    "/",
    response_model=PortfolioGroupListResponse,
    summary="List portfolio groups",
    operation_id="listPortfolioGroups",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Unsupported response format or invalid portfolio group request.",
        }
    },
)
def get_portfolio_groups(
    request: Request,
    response_format: Annotated[
        str,
        Query(description="Supported value for this endpoint is `frontend_list`."),
    ] = "frontend_list",
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
) -> PortfolioGroupListResponse:
    if response_format != "frontend_list":
        raise HTTPException(
            status_code=400,
            detail=(
                "Only response_format=frontend_list is implemented for "
                "GET /api/v1/portfolio-group/."
            ),
        )
    rows = list_portfolio_groups(
        search=search,
        unique_identifier=unique_identifier,
        display_name=display_name,
        limit=limit + 1,
        offset=offset,
    )
    return PortfolioGroupListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=rows,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.post(
    "/",
    response_model=PortfolioGroup,
    summary="Create portfolio group",
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
    operation_id="bulkDeletePortfolioGroups",
)
def post_portfolio_group_bulk_delete(
    request: Annotated[
        PortfolioGroupBulkDeleteRequest,
        Body(description="Bulk delete request for portfolio groups."),
    ],
) -> PortfolioGroupDeleteResponse:
    return bulk_delete_portfolio_groups(payload=request.model_dump(mode="json"))


@router.post(
    "/membership/bulk-delete/",
    response_model=PortfolioGroupDeleteResponse,
    summary="Bulk delete portfolio group memberships",
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
    response_model=PortfolioGroupsForPortfolioResponse,
    summary="List groups for portfolio",
    operation_id="listGroupsForPortfolio",
)
def get_groups_for_portfolio(
    request: Request,
    portfolio_uid: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PortfolioGroupsForPortfolioResponse:
    rows = list_groups_for_portfolio(
        portfolio_uid=portfolio_uid,
        limit=limit + 1,
        offset=offset,
    )
    return PortfolioGroupsForPortfolioResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=rows,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.get(
    "/{uid}/",
    response_model=PortfolioGroup,
    summary="Get portfolio group",
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
    operation_id="deletePortfolioGroup",
    status_code=status.HTTP_200_OK,
)
def remove_portfolio_group(uid: str) -> PortfolioGroupDeleteResponse:
    return delete_portfolio_group(uid=uid)


@router.get(
    "/{uid}/portfolios/",
    response_model=PortfolioGroupPortfolioListResponse,
    summary="List portfolios in group",
    operation_id="listPortfoliosInGroup",
)
def get_portfolios_in_group(
    request: Request,
    uid: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PortfolioGroupPortfolioListResponse:
    rows = list_portfolios_in_group(
        portfolio_group_uid=uid,
        limit=limit + 1,
        offset=offset,
    )
    return PortfolioGroupPortfolioListResponse.model_validate(
        build_paginated_response(
            request_url=str(request.url),
            results=rows,
            limit=limit,
            offset=offset,
        ).model_dump()
    )


@router.post(
    "/{uid}/portfolios/",
    response_model=PortfolioGroupMembership,
    summary="Add portfolio to group",
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
