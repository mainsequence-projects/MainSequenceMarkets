from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow, Payload, _payload_values
from msm.api.managers import (
    refuse_managed_by,
    register_managed_rows,
    require_assigning_admin,
    validate_principal,
)

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

    @classmethod
    def delete(cls, uid: uuid.UUID | str) -> dict[str, Any]:
        """Delete the signal's weights and this row in one transaction (ADR 0060).

        Only the signal's manager may delete it. A portfolio that still names the signal
        refuses the delete (``SignalDeleteConflictError``, 409) and nothing is deleted.
        """

        from msm_portfolios.services.public_api import delete_signal_metadata_record

        deleted = delete_signal_metadata_record(cls._series_context(), uid=str(uid))
        if deleted is None:
            raise LookupError(f"SignalMetadata {uid} was not found.")
        return deleted

    @classmethod
    def end(cls, signal_uid: str) -> dict[str, Any]:
        """Delete signal ``signal_uid``: its weights and its metadata row, in one transaction.

        As ``delete``, by ``signal_uid``. ``msm_portfolios.recipes.end_signal`` calls it.
        """

        from msm_portfolios.services.public_api import delete_signal_metadata_record

        deleted = delete_signal_metadata_record(cls._series_context(), signal_uid=signal_uid)
        if deleted is None:
            raise LookupError(f"No SignalMetadata row has signal_uid {signal_uid!r}.")
        return deleted

    @classmethod
    def end_many(cls, signal_uids: Sequence[str]) -> dict[str, Any]:
        """End several signals in one call: each one's weights and metadata row (issue 126).

        Every signal that may go is deleted in one transaction. A signal that is missing,
        that the caller does not manage, or that a ``Portfolio`` names is listed in
        ``failed`` with the reason and never stops the others; ``ended`` holds each ended
        signal as ``end`` answers it. ``msm_portfolios.recipes.end_signals`` calls it.
        """

        from msm_portfolios.services.public_api import end_signal_metadata_records

        return end_signal_metadata_records(
            cls._series_context(), signal_uids=[str(uid) for uid in signal_uids]
        )

    @classmethod
    def _series_context(cls):
        from msm.bootstrap import resolve_runtime
        from msm_portfolios.time_index.signals.storage import SignalWeightsStorage

        return resolve_runtime(
            models=[SignalMetadataTable, SignalWeightsStorage], row_model_name=cls.__name__
        ).context


register_managed_rows("signal", SignalMetadata, "signal_uid")


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
