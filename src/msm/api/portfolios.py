from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow, Payload
from msm.models import (
    AccountTable,
    AssetTable,
    FundTable,
    PortfolioAssetDetailTable,
    PortfolioMetadataTable,
    PortfolioTable,
)


class PortfolioAssetDetail(MarketsMetaTableRow):
    """Typed portfolio-to-asset detail row."""

    __table__: ClassVar[type[PortfolioAssetDetailTable]] = PortfolioAssetDetailTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        PortfolioTable,
        PortfolioAssetDetailTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("portfolio_uid",)

    portfolio_uid: uuid.UUID
    asset_uid: uuid.UUID | None = None
    asset_unique_identifier: str | None = None
    metadata_json: dict[str, Any] | None = None


class PortfolioAssetDetailCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_uid: uuid.UUID | str
    asset_uid: uuid.UUID | str | None = None
    asset_unique_identifier: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class PortfolioAssetDetailUpsert(PortfolioAssetDetailCreate):
    """Payload for inserting or updating portfolio asset detail by portfolio."""


class PortfolioAssetDetailUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_uid: uuid.UUID | str | None = None
    asset_unique_identifier: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class Portfolio(MarketsMetaTableRow):
    """Typed portfolio identity and runtime configuration row."""

    __table__: ClassVar[type[PortfolioTable]] = PortfolioTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        PortfolioTable,
        PortfolioAssetDetailTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    calendar_name: str | None = None
    portfolio_index_asset_uid: uuid.UUID | None = None
    portfolio_index_asset_unique_identifier: str | None = None
    portfolio_weights_data_node_uid: uuid.UUID | None = None
    signal_weights_data_node_uid: uuid.UUID | None = None
    portfolio_data_node_uid: uuid.UUID | None = None
    backtest_table_price_column_name: str = "close"
    builds_from_target_weights: bool = True
    builds_from_predictions: bool = False
    builds_from_target_positions: bool = False
    tracking_funds_expected_exposure_from_latest_holdings: bool = False
    stats_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def upsert(cls, payload: Payload = None, **kwargs: Any) -> Portfolio:
        values = _portfolio_payload_values(payload, kwargs)
        asset_detail = values.pop("asset_detail", None)
        portfolio = super().upsert(values)
        if asset_detail is not None:
            detail_values = dict(asset_detail)
            detail_values["portfolio_uid"] = portfolio.uid
            PortfolioAssetDetail.upsert(detail_values)
        return portfolio


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    calendar_name: str | None = Field(default=None, max_length=255)
    portfolio_index_asset_uid: uuid.UUID | str | None = None
    portfolio_index_asset_unique_identifier: str | None = Field(default=None, max_length=255)
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None
    signal_weights_data_node_uid: uuid.UUID | str | None = None
    portfolio_data_node_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str = "close"
    builds_from_target_weights: bool = True
    builds_from_predictions: bool = False
    builds_from_target_positions: bool = False
    tracking_funds_expected_exposure_from_latest_holdings: bool = False
    stats_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None


class PortfolioUpsert(PortfolioCreate):
    """Payload for inserting or updating a portfolio.

    `asset_detail` is optional domain payload. When provided, `Portfolio.upsert`
    also upserts the portfolio asset-detail row after the portfolio row exists.
    """

    asset_detail: PortfolioAssetDetailUpdate | None = None


class PortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_name: str | None = Field(default=None, max_length=255)
    portfolio_index_asset_uid: uuid.UUID | str | None = None
    portfolio_index_asset_unique_identifier: str | None = Field(default=None, max_length=255)
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None
    signal_weights_data_node_uid: uuid.UUID | str | None = None
    portfolio_data_node_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str | None = None
    builds_from_target_weights: bool | None = None
    builds_from_predictions: bool | None = None
    builds_from_target_positions: bool | None = None
    tracking_funds_expected_exposure_from_latest_holdings: bool | None = None
    stats_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None


class PortfolioMetadata(MarketsMetaTableRow):
    """Typed human-facing portfolio metadata row."""

    __table__: ClassVar[type[PortfolioMetadataTable]] = PortfolioMetadataTable
    __required_tables__: ClassVar[list[type[PortfolioMetadataTable]]] = [PortfolioMetadataTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    description: str | None = None


class PortfolioMetadataCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    description: str | None = None


class PortfolioMetadataUpsert(PortfolioMetadataCreate):
    """Payload for inserting or updating portfolio metadata."""


class PortfolioMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None


class Fund(MarketsMetaTableRow):
    """Typed fund row bound to an account and portfolio."""

    __table__: ClassVar[type[FundTable]] = FundTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        AccountTable,
        PortfolioTable,
        FundTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    target_account_uid: uuid.UUID
    target_portfolio_uid: uuid.UUID
    requires_nav_adjustment: bool = False
    metadata_json: dict[str, Any] | None = None


class FundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    target_account_uid: uuid.UUID | str
    target_portfolio_uid: uuid.UUID | str
    requires_nav_adjustment: bool = False
    metadata_json: dict[str, Any] | None = None


class FundUpsert(FundCreate):
    """Payload for inserting or updating a fund."""


class FundUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_account_uid: uuid.UUID | str | None = None
    target_portfolio_uid: uuid.UUID | str | None = None
    requires_nav_adjustment: bool | None = None
    metadata_json: dict[str, Any] | None = None


def _portfolio_payload_values(payload: Payload, kwargs: dict[str, Any]) -> dict[str, Any]:
    if payload is None:
        return dict(kwargs)
    if kwargs:
        raise TypeError("Pass either a payload object or keyword fields, not both.")
    if isinstance(payload, BaseModel):
        return payload.model_dump(exclude_unset=True)
    if isinstance(payload, Mapping):
        return dict(payload)
    raise TypeError("Payload must be a Pydantic model, mapping, or None.")


__all__ = [
    "Fund",
    "FundCreate",
    "FundUpdate",
    "FundUpsert",
    "Portfolio",
    "PortfolioAssetDetail",
    "PortfolioAssetDetailCreate",
    "PortfolioAssetDetailUpdate",
    "PortfolioAssetDetailUpsert",
    "PortfolioCreate",
    "PortfolioMetadata",
    "PortfolioMetadataCreate",
    "PortfolioMetadataUpdate",
    "PortfolioMetadataUpsert",
    "PortfolioUpdate",
    "PortfolioUpsert",
]
