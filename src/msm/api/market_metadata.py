from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow
from msm.models import (
    RebalanceStrategyMetadataTable,
    SignalMetadataTable,
)


class SignalMetadata(MarketsMetaTableRow):
    """Typed metadata row for a canonical portfolio signal."""

    __table__: ClassVar[type[SignalMetadataTable]] = SignalMetadataTable
    __required_tables__: ClassVar[list[type[SignalMetadataTable]]] = [SignalMetadataTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("signal_uid",)

    signal_uid: str
    signal_description: str | None = None


class SignalMetadataCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_uid: str = Field(min_length=1, max_length=255)
    signal_description: str | None = None


class SignalMetadataUpsert(SignalMetadataCreate):
    """Payload for inserting or updating signal metadata."""


class SignalMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_description: str | None = None


class RebalanceStrategyMetadata(MarketsMetaTableRow):
    """Typed metadata row for a rebalance strategy."""

    __table__: ClassVar[type[RebalanceStrategyMetadataTable]] = RebalanceStrategyMetadataTable
    __required_tables__: ClassVar[list[type[RebalanceStrategyMetadataTable]]] = [
        RebalanceStrategyMetadataTable
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("rebalance_strategy_uid",)

    rebalance_strategy_uid: str
    rebalance_strategy_description: str | None = None
    configuration_json: dict[str, Any] | None = None


class RebalanceStrategyMetadataCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rebalance_strategy_uid: str = Field(min_length=1, max_length=255)
    rebalance_strategy_description: str | None = None
    configuration_json: dict[str, Any] | None = None


class RebalanceStrategyMetadataUpsert(RebalanceStrategyMetadataCreate):
    """Payload for inserting or updating rebalance-strategy metadata."""


class RebalanceStrategyMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rebalance_strategy_description: str | None = None
    configuration_json: dict[str, Any] | None = None


__all__ = [
    "RebalanceStrategyMetadata",
    "RebalanceStrategyMetadataCreate",
    "RebalanceStrategyMetadataUpdate",
    "RebalanceStrategyMetadataUpsert",
    "SignalMetadata",
    "SignalMetadataCreate",
    "SignalMetadataUpdate",
    "SignalMetadataUpsert",
]
