from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace
from apps.v1.schemas.common import PaginatedResponse


def _signal_metadata_contracts():
    prepare_apps_v1_import_namespace()
    from msm_portfolios.api.market_metadata import (
        SignalMetadata,
        SignalMetadataCreate,
        SignalMetadataUpdate,
    )

    return SignalMetadata, SignalMetadataCreate, SignalMetadataUpdate


SignalMetadata, SignalMetadataCreate, SignalMetadataUpdate = _signal_metadata_contracts()


class PortfolioSignalDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    signal_metadata_uid: str
    signal_uid: str | None = None
    deleted_count: int = 0
    deleted_weights_count: int = 0


class PortfolioSignalWeightsDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    signal_metadata_uid: str
    signal_uid: str | None = None
    weights_date: dt.datetime | None = None
    deleted_count: int = 0


PortfolioSignalListResponse = PaginatedResponse[SignalMetadata]
