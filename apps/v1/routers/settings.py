from __future__ import annotations

from fastapi import APIRouter

from apps.v1.schemas.settings import ApiSettingsResponse
from apps.v1.services.settings import get_api_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get(
    "/",
    response_model=ApiSettingsResponse,
    summary="Get API settings",
    description=(
        "Return read-only public settings and runtime assumptions for the apps/v1 API. "
        "The response intentionally excludes request identity and secrets."
    ),
    operation_id="getApiSettings",
)
def get_settings() -> ApiSettingsResponse:
    return get_api_settings()
