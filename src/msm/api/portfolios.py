from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from msm.api.base import MarketsMetaTableRow, operation_result_rows
from msm.models import (
    CalendarTable,
    IndexTable,
    IndexTypeTable,
    PortfolioGroupMembershipTable,
    PortfolioGroupTable,
    PortfolioTable,
    SignalMetadataTable,
)

Payload = BaseModel | Mapping[str, Any] | None


def _validate_payload(
    payload_model: type[BaseModel],
    payload: Payload,
    kwargs: Mapping[str, Any],
) -> BaseModel:
    if payload is None:
        return payload_model(**dict(kwargs))
    if kwargs:
        raise TypeError("Pass either a payload object or keyword fields, not both.")
    if isinstance(payload, payload_model):
        return payload
    if isinstance(payload, BaseModel):
        return payload_model.model_validate(payload.model_dump(exclude_unset=True))
    if isinstance(payload, Mapping):
        return payload_model.model_validate(dict(payload))
    raise TypeError("Payload must be a Pydantic model, mapping, or None.")


class Portfolio(MarketsMetaTableRow):
    """Typed portfolio identity and runtime configuration row."""

    __table__: ClassVar[type[PortfolioTable]] = PortfolioTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        CalendarTable,
        IndexTypeTable,
        IndexTable,
        SignalMetadataTable,
        PortfolioTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    calendar_uid: uuid.UUID
    published_index_uid: uuid.UUID | None = None
    portfolio_weights_data_node_uid: uuid.UUID | None = None
    signal_weights_data_node_uid: uuid.UUID | None = None
    signal_uid: str | None = None
    portfolio_data_node_uid: uuid.UUID | None = None
    backtest_table_price_column_name: str = "close"


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    calendar_uid: uuid.UUID | str
    published_index_uid: uuid.UUID | str | None = None
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None
    signal_weights_data_node_uid: uuid.UUID | str | None = None
    signal_uid: str | None = Field(default=None, max_length=255)
    portfolio_data_node_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str = "close"


class PortfolioUpsert(PortfolioCreate):
    """Payload for inserting or updating a portfolio."""


class PortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_uid: uuid.UUID | str | None = None
    published_index_uid: uuid.UUID | str | None = None
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None
    signal_weights_data_node_uid: uuid.UUID | str | None = None
    signal_uid: str | None = Field(default=None, max_length=255)
    portfolio_data_node_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_null_calendar_uid(cls, value: Any) -> Any:
        if isinstance(value, dict) and "calendar_uid" in value and value["calendar_uid"] is None:
            raise ValueError("calendar_uid cannot be null for Portfolio rows.")
        return value


class PortfolioGroup(MarketsMetaTableRow):
    """Typed portfolio group row for many-to-many portfolio classification."""

    __table__: ClassVar[type[PortfolioGroupTable]] = PortfolioGroupTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        CalendarTable,
        IndexTypeTable,
        IndexTable,
        SignalMetadataTable,
        PortfolioTable,
        PortfolioGroupTable,
        PortfolioGroupMembershipTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    display_name: str
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        payload: PortfolioGroupCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PortfolioGroup:
        return super().create(_validate_payload(PortfolioGroupCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: PortfolioGroupUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PortfolioGroup:
        return super().upsert(_validate_payload(PortfolioGroupUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: PortfolioGroupUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PortfolioGroup:
        return super().update(uid, _validate_payload(PortfolioGroupUpdate, payload, kwargs))

    @classmethod
    def add(
        cls,
        payload: PortfolioGroupUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PortfolioGroup:
        """Idempotently create or update a portfolio group by unique identifier."""

        return cls.upsert(payload, **kwargs)

    @classmethod
    def bulk_delete(
        cls,
        *,
        uids: Sequence[uuid.UUID | str] | None = None,
        unique_identifiers: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        from msm.services import bulk_delete_portfolio_groups

        return bulk_delete_portfolio_groups(
            cls._active_context(),
            uids=[str(uid) for uid in (uids or [])],
            unique_identifiers=list(unique_identifiers or []),
        )

    @classmethod
    def add_portfolio(
        cls,
        *,
        portfolio_group_uid: uuid.UUID | str | None = None,
        portfolio_group_unique_identifier: str | None = None,
        portfolio_uid: uuid.UUID | str | None = None,
        portfolio_unique_identifier: str | None = None,
    ) -> PortfolioGroupMembership:
        """Idempotently add one portfolio to one group."""

        resolved_group_uid = _resolve_portfolio_group_uid(
            portfolio_group_uid=portfolio_group_uid,
            portfolio_group_unique_identifier=portfolio_group_unique_identifier,
        )
        resolved_portfolio_uid = _resolve_portfolio_uid(
            portfolio_uid=portfolio_uid,
            portfolio_unique_identifier=portfolio_unique_identifier,
        )
        return PortfolioGroupMembership.add(
            portfolio_group_uid=resolved_group_uid,
            portfolio_uid=resolved_portfolio_uid,
        )

    @classmethod
    def remove_portfolio(
        cls,
        *,
        portfolio_group_uid: uuid.UUID | str | None = None,
        portfolio_group_unique_identifier: str | None = None,
        portfolio_uid: uuid.UUID | str | None = None,
        portfolio_unique_identifier: str | None = None,
    ) -> dict[str, Any]:
        """Remove one portfolio membership from one group."""

        from msm.services import delete_portfolio_group_membership_by_pair

        resolved_group_uid = _resolve_portfolio_group_uid(
            portfolio_group_uid=portfolio_group_uid,
            portfolio_group_unique_identifier=portfolio_group_unique_identifier,
        )
        resolved_portfolio_uid = _resolve_portfolio_uid(
            portfolio_uid=portfolio_uid,
            portfolio_unique_identifier=portfolio_unique_identifier,
        )
        existing = PortfolioGroupMembership.filter(
            portfolio_group_uid=resolved_group_uid,
            portfolio_uid=resolved_portfolio_uid,
            limit=1,
        )
        if not existing:
            return {
                "detail": "No portfolio group membership matched the deletion request.",
                "deleted_count": 0,
            }
        delete_portfolio_group_membership_by_pair(
            cls._active_context(),
            portfolio_group_uid=resolved_group_uid,
            portfolio_uid=resolved_portfolio_uid,
        )
        return {"detail": "Deleted 1 portfolio group membership.", "deleted_count": 1}

    @classmethod
    def get_portfolios(
        cls,
        *,
        portfolio_group_uid: uuid.UUID | str | None = None,
        portfolio_group_unique_identifier: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[Portfolio]:
        """Return all portfolios assigned to one group."""

        from msm.services import list_portfolios_for_group

        resolved_group_uid = _resolve_portfolio_group_uid(
            portfolio_group_uid=portfolio_group_uid,
            portfolio_group_unique_identifier=portfolio_group_unique_identifier,
        )
        result = list_portfolios_for_group(
            cls._active_context(),
            portfolio_group_uid=resolved_group_uid,
            limit=limit,
            offset=offset,
        )
        return [Portfolio.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def get_groups_for_portfolio(
        cls,
        *,
        portfolio_uid: uuid.UUID | str | None = None,
        portfolio_unique_identifier: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[PortfolioGroup]:
        """Return all groups containing one portfolio."""

        from msm.services import list_portfolio_groups_for_portfolio

        resolved_portfolio_uid = _resolve_portfolio_uid(
            portfolio_uid=portfolio_uid,
            portfolio_unique_identifier=portfolio_unique_identifier,
        )
        result = list_portfolio_groups_for_portfolio(
            cls._active_context(),
            portfolio_uid=resolved_portfolio_uid,
            limit=limit,
            offset=offset,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]


class PortfolioGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class PortfolioGroupUpsert(PortfolioGroupCreate):
    """Payload for inserting or updating a portfolio group row."""


class PortfolioGroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class PortfolioGroupMembership(MarketsMetaTableRow):
    """Typed membership row between a portfolio group and a portfolio."""

    __table__: ClassVar[type[PortfolioGroupMembershipTable]] = PortfolioGroupMembershipTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        CalendarTable,
        IndexTypeTable,
        IndexTable,
        SignalMetadataTable,
        PortfolioTable,
        PortfolioGroupTable,
        PortfolioGroupMembershipTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("portfolio_group_uid", "portfolio_uid")

    portfolio_group_uid: uuid.UUID
    portfolio_uid: uuid.UUID

    @classmethod
    def add(
        cls,
        payload: PortfolioGroupMembershipUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PortfolioGroupMembership:
        """Idempotently create one portfolio group membership."""

        return cls.upsert(_validate_payload(PortfolioGroupMembershipUpsert, payload, kwargs))

    @classmethod
    def bulk_delete(
        cls,
        *,
        uids: Sequence[uuid.UUID | str] | None = None,
        portfolio_group_uids: Sequence[uuid.UUID | str] | None = None,
        portfolio_uids: Sequence[uuid.UUID | str] | None = None,
    ) -> dict[str, Any]:
        from msm.services import bulk_delete_portfolio_group_memberships

        return bulk_delete_portfolio_group_memberships(
            cls._active_context(),
            uids=[str(uid) for uid in (uids or [])],
            portfolio_group_uids=[str(uid) for uid in (portfolio_group_uids or [])],
            portfolio_uids=[str(uid) for uid in (portfolio_uids or [])],
        )


class PortfolioGroupMembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_group_uid: uuid.UUID | str
    portfolio_uid: uuid.UUID | str


class PortfolioGroupMembershipUpsert(PortfolioGroupMembershipCreate):
    """Payload for inserting or updating one portfolio group membership row."""


def _resolve_portfolio_group_uid(
    *,
    portfolio_group_uid: uuid.UUID | str | None,
    portfolio_group_unique_identifier: str | None,
) -> str:
    if portfolio_group_uid not in (None, "") and portfolio_group_unique_identifier not in (
        None,
        "",
    ):
        raise ValueError(
            "Pass either portfolio_group_uid or portfolio_group_unique_identifier, not both."
        )
    if portfolio_group_uid not in (None, ""):
        return str(portfolio_group_uid)
    if portfolio_group_unique_identifier in (None, ""):
        raise ValueError("portfolio_group_uid or portfolio_group_unique_identifier is required.")
    group = PortfolioGroup.get_by_unique_identifier(str(portfolio_group_unique_identifier))
    if group is None:
        raise LookupError(f"PortfolioGroup {portfolio_group_unique_identifier!r} was not found.")
    return str(group.uid)


def _resolve_portfolio_uid(
    *,
    portfolio_uid: uuid.UUID | str | None,
    portfolio_unique_identifier: str | None,
) -> str:
    if portfolio_uid not in (None, "") and portfolio_unique_identifier not in (None, ""):
        raise ValueError("Pass either portfolio_uid or portfolio_unique_identifier, not both.")
    if portfolio_uid not in (None, ""):
        return str(portfolio_uid)
    if portfolio_unique_identifier in (None, ""):
        raise ValueError("portfolio_uid or portfolio_unique_identifier is required.")
    portfolio = Portfolio.get_by_unique_identifier(str(portfolio_unique_identifier))
    if portfolio is None:
        raise LookupError(f"Portfolio {portfolio_unique_identifier!r} was not found.")
    return str(portfolio.uid)


__all__ = [
    "Portfolio",
    "PortfolioCreate",
    "PortfolioGroup",
    "PortfolioGroupCreate",
    "PortfolioGroupMembership",
    "PortfolioGroupMembershipCreate",
    "PortfolioGroupMembershipUpsert",
    "PortfolioGroupUpdate",
    "PortfolioGroupUpsert",
    "PortfolioUpdate",
    "PortfolioUpsert",
]
