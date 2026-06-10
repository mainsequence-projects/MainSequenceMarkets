from __future__ import annotations

from fastapi import APIRouter, Request

from apps.v1.schemas.command_center_adapter import (
    ApiHealthResponse,
    CommandCenterConnectionContract,
)
from apps.v1.services.command_center_adapter import (
    build_command_center_connection_contract,
    get_api_health,
)

router = APIRouter(tags=["command-center"])


@router.get(
    "/health",
    response_model=ApiHealthResponse,
    summary="Get API health",
    description="Return a zero-argument health payload for API discovery.",
    operation_id="getApiHealth",
)
def get_health() -> ApiHealthResponse:
    return get_api_health()


@router.get(
    "/.well-known/command-center/connection-contract",
    response_model=CommandCenterConnectionContract,
    summary="Get Command Center connection contract",
    description=(
        "Return the Adapter from API discovery contract for the existing apps/v1 "
        "FastAPI operations."
    ),
    operation_id="getCommandCenterConnectionContract",
)
def get_command_center_connection_contract(
    request: Request,
) -> CommandCenterConnectionContract:
    openapi_url = request.app.openapi_url or "/openapi.json"
    return build_command_center_connection_contract(
        openapi_schema=request.app.openapi(),
        openapi_url=str(request.base_url.replace(path=openapi_url)),
    )
