from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow
from msm_portfolios.models import PortfolioMetadataTable


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


__all__ = [
    "PortfolioMetadata",
    "PortfolioMetadataCreate",
    "PortfolioMetadataUpdate",
    "PortfolioMetadataUpsert",
]
