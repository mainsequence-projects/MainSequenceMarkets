from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow, Payload, _payload_values
from msm.api.managers import refuse_managed_by, require_assigning_admin, validate_principal

from msm_portfolios.models import (
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
    managed_by: str | None = None

    @classmethod
    def create(cls, payload: Payload = None, **kwargs: Any) -> SignalMetadata:
        """Insert one signal's metadata; Markets records its manager (ADR 0060)."""

        return super().create(refuse_managed_by(_payload_values(payload, kwargs)))

    @classmethod
    def upsert(cls, payload: Payload = None, **kwargs: Any) -> SignalMetadata:
        """Insert or update one signal's metadata by ``signal_uid``; its manager never changes."""

        return super().upsert(refuse_managed_by(_payload_values(payload, kwargs)))

    @classmethod
    def update(cls, uid: uuid.UUID | str, payload: Payload = None, **kwargs: Any) -> SignalMetadata:
        """Update one signal's metadata by UID; ``assign_manager`` changes its manager."""

        return super().update(uid, refuse_managed_by(_payload_values(payload, kwargs)))

    @classmethod
    def upsert_many(cls, payloads: Sequence[BaseModel | Mapping[str, Any]]) -> list[SignalMetadata]:
        """Upsert many signals' metadata on ``signal_uid``; their managers never change."""

        for payload in payloads:
            if isinstance(payload, Mapping):
                refuse_managed_by(dict(payload))
        return super().upsert_many(payloads)

    @classmethod
    def assign_manager(cls, uid: uuid.UUID | str, managed_by: str) -> SignalMetadata:
        """Make ``managed_by`` (``branch:<uid>`` or ``user:<uid>``) the signal's manager.

        Only an Organization admin may call it through the Markets API (ADR 0060).
        """

        from msm.repositories.crud import update_model

        require_assigning_admin()
        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=uid,
            values={"managed_by": validate_principal(managed_by)},
        )
        return cls._from_operation_result(result)


class SignalMetadataCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_uid: str = Field(min_length=1, max_length=255)
    signal_description: str | None = Field(
        default=None,
        description=(
            "Plain-text or Markdown signal description. HTML tags are not part "
            "of the rendering contract."
        ),
    )


class SignalMetadataUpsert(SignalMetadataCreate):
    """Payload for inserting or updating signal metadata."""


class SignalMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_description: str | None = Field(
        default=None,
        description=(
            "Plain-text or Markdown signal description. HTML tags are not part "
            "of the rendering contract."
        ),
    )


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
