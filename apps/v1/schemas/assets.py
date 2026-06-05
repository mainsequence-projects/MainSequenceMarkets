from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace
from apps.v1.schemas.common import (
    FrontEndDetailSummaryBadge,
    FrontEndDetailSummaryField,
    FrontEndDetailSummaryLabelManagement,
    FrontEndDetailSummaryStat,
)


def _asset_contract():
    prepare_apps_v1_import_namespace()
    from msm.api.assets import Asset

    return Asset


Asset = _asset_contract()


class AssetFrontEndDetailSummaryEntity(BaseModel):
    uid: str
    type: str
    title: str


class AssetFrontEndDetailSummary(BaseModel):
    entity: AssetFrontEndDetailSummaryEntity
    badges: list[FrontEndDetailSummaryBadge]
    inline_fields: list[FrontEndDetailSummaryField]
    highlight_fields: list[FrontEndDetailSummaryField]
    stats: list[FrontEndDetailSummaryStat]
    label_management: FrontEndDetailSummaryLabelManagement | None = None
    summary_warning: str | None = None
    extensions: dict[str, Any]


class AssetCurrentPricingDetailsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asset_uid: UUID
    instrument_type: str
    instrument_dump: dict[str, Any]
    pricing_details_date: dt.datetime
    serialization_format: str
    pricing_package_version: str | None = None
    source: str | None = None
    metadata_json: dict[str, Any] | None = None
