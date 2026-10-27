from __future__ import annotations

import datetime as dt

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _signal_metadata_contracts():
    prepare_apps_v1_import_namespace()
    from msm_portfolios.api.market_metadata import (
        SignalMetadata,
        SignalMetadataCreate,
        SignalMetadataUpdate,
    )

    return SignalMetadata, SignalMetadataCreate, SignalMetadataUpdate


SignalMetadata, SignalMetadataCreate, SignalMetadataUpdate = _signal_metadata_contracts()


class RetainedSignalDataset(BaseModel):
    """Signal weights a delete left in a table another application owns (ADR 0047)."""

    model_config = ConfigDict(extra="ignore")

    signal_uid: str | None = None
    dataset: Literal["signal_weights"] = "signal_weights"
    meta_table_uid: str = Field(
        description=(
            "TimeIndexMetaTable uid of the SignalWeightsTS instance. Markets does not delete its "
            "rows; the application that owns the table does."
        )
    )


class PortfolioSignalDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    signal_metadata_uid: str
    signal_uid: str | None = None
    deleted_count: int = 0
    deleted_weights_count: int = 0
    retained_datasets: list[RetainedSignalDataset] = Field(
        default_factory=list,
        description=(
            "Signal weights that stay in a table another application owns. "
            "deleted_weights_count covers only the Markets core table."
        ),
    )


class PortfolioSignalWeightsDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    signal_metadata_uid: str
    signal_uid: str | None = None
    weights_date: dt.datetime | None = None
    deleted_count: int = 0
