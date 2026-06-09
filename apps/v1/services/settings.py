from __future__ import annotations

from importlib.metadata import version

from apps.v1.schemas.settings import ApiSettingsResponse

API_SETTINGS_APP_NAME = "MainSequence Markets Public API"
API_SETTINGS_APP_SCOPE = "apps/v1"
API_SETTINGS_OPENAPI_URL = "/openapi.json"
API_SETTINGS_SWAGGER_URL = "/docs"
API_SETTINGS_REDOC_URL = "/redoc"


def get_api_settings() -> ApiSettingsResponse:
    payload = _get_public_api_settings(
        app_name=API_SETTINGS_APP_NAME,
        app_scope=API_SETTINGS_APP_SCOPE,
        app_version=version("ms-markets"),
        openapi_url=API_SETTINGS_OPENAPI_URL,
        swagger_url=API_SETTINGS_SWAGGER_URL,
        redoc_url=API_SETTINGS_REDOC_URL,
    )
    return ApiSettingsResponse.model_validate(payload)


def _get_public_api_settings(**kwargs):
    from msm.services import get_public_api_settings

    return get_public_api_settings(**kwargs)
