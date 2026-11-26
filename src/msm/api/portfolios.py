from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from msm.api.base import (
    MarketsMetaTableRow,
    _payload_values,
    operation_result_rows,
)
from msm.api.managers import (
    refuse_managed_by,
    register_managed_rows,
    require_assigning_admin,
    validate_principal,
)
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
    """Typed portfolio identity and runtime configuration row.

    ``delete`` raises ``MarketsOperationUnsupported`` under both backends and deletes
    nothing. A portfolio is deleted with its rows in its seven datasets, which belong
    to the portfolio package that core ``msm`` does not import (ADR 0019), so only the
    Markets API's portfolio routes delete it (ADR 0049).
    ``MarketsClient.delete_portfolio`` and ``MarketsClient.bulk_delete_portfolios``
    call them.
    """

    __table__: ClassVar[type[PortfolioTable]] = PortfolioTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        CalendarTable,
        IndexTypeTable,
        IndexTable,
        SignalMetadataTable,
        PortfolioTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)
    __delete_refusal__: ClassVar[str | None] = (
        "a portfolio is deleted with its rows in its seven datasets, in one transaction, "
        "only through the Markets API: MarketsClient.delete_portfolio and "
        "MarketsClient.bulk_delete_portfolios call DELETE /api/v1/portfolio/{uid}/ and "
        "POST /api/v1/portfolio/bulk-delete/ (ADR 0049)."
    )

    unique_identifier: str
    calendar_uid: uuid.UUID
    published_index_uid: uuid.UUID | None = None
    portfolio_weights_table_update_uid: uuid.UUID | None = None
    signal_weights_table_update_uid: uuid.UUID | None = None
    signal_uid: str | None = None
    portfolio_table_update_uid: uuid.UUID | None = None
    backtest_table_price_column_name: str = "close"
    retired_at: dt.datetime | None = None
    managed_by: str | None = None

    @classmethod
    def create(cls, payload: Payload = None, **kwargs: Any) -> Portfolio:
        """Insert one portfolio; Markets records its manager (ADR 0060)."""

        return super().create(refuse_managed_by(_payload_values(payload, kwargs)))

    @classmethod
    def upsert(cls, payload: Payload = None, **kwargs: Any) -> Portfolio:
        """Insert or update one portfolio by ``unique_identifier``; its manager never changes."""

        return super().upsert(refuse_managed_by(_payload_values(payload, kwargs)))

    @classmethod
    def update(cls, uid: uuid.UUID | str, payload: Payload = None, **kwargs: Any) -> Portfolio:
        """Update one portfolio by UID; ``assign_manager`` changes its manager."""

        return super().update(uid, refuse_managed_by(_payload_values(payload, kwargs)))

    @classmethod
    def upsert_many(cls, payloads: Sequence[BaseModel | Mapping[str, Any]]) -> list[Portfolio]:
        """Upsert many portfolios on ``unique_identifier``; their managers never change."""

        for payload in payloads:
            if isinstance(payload, Mapping):
                refuse_managed_by(dict(payload))
        return super().upsert_many(payloads)

    @classmethod
    def assign_manager(cls, uid: uuid.UUID | str, managed_by: str) -> Portfolio:
        """Make ``managed_by`` (``branch:<uid>`` or ``user:<uid>``) the portfolio's manager.

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


register_managed_rows("portfolio", Portfolio, "unique_identifier")


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    calendar_uid: uuid.UUID | str
    published_index_uid: uuid.UUID | str | None = None
    portfolio_weights_table_update_uid: uuid.UUID | str | None = None
    signal_weights_table_update_uid: uuid.UUID | str | None = None
    signal_uid: str | None = Field(default=None, max_length=255)
    portfolio_table_update_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str = "close"


class PortfolioUpsert(PortfolioCreate):
    """Payload for inserting or updating a portfolio."""


class PortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_uid: uuid.UUID | str | None = None
    published_index_uid: uuid.UUID | str | None = None
    portfolio_weights_table_update_uid: uuid.UUID | str | None = None
    signal_weights_table_update_uid: uuid.UUID | str | None = None
    signal_uid: str | None = Field(default=None, max_length=255)
    portfolio_table_update_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_null_calendar_uid(cls, value: Any) -> Any:
        if isinstance(value, dict) and "calendar_uid" in value and value["calendar_uid"] is None:
            raise ValueError("calendar_uid cannot be null for Portfolio rows.")
        return value


PortfolioDeletedRows = dict[str, int]


class PortfolioDeleteResponse(BaseModel):
    """One portfolio deleted with its datasets in one transaction (ADR 0049, issue 93)."""

    model_config = ConfigDict(extra="ignore")

    detail: str
    uid: str
    unique_identifier: str
    deleted_count: int = 1
    deleted_rows: PortfolioDeletedRows = Field(
        default_factory=dict,
        description=(
            "The portfolio's rows deleted with it, per dataset: weights, values, "
            "rebalance_state, analytics, event_ledger, state and cash_flows. Counted "
            "just before the delete ran."
        ),
    )


class PortfolioDeleteFailure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str
    detail: str


class PortfolioBulkDeleteResponse(BaseModel):
    """What a bulk delete did: the portfolios deleted with their datasets, in one
    transaction, and each selected portfolio it did not delete, with the reason."""

    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int = 0
    deleted: list[PortfolioDeleteResponse] = Field(default_factory=list)
    failed: list[PortfolioDeleteFailure] = Field(default_factory=list)


class PortfolioBulkRetireRequest(BaseModel):
    """The portfolios to retire in one call (issue 124)."""

    model_config = ConfigDict(extra="forbid")

    uids: list[str] = Field(min_length=1, description="Portfolio uids to retire.")


class PortfolioRetireFailure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str
    detail: str


class PortfolioBulkRetireResponse(BaseModel):
    """What a bulk retirement did: the portfolios retired by it or already retired, and
    each selected portfolio it did not retire, with the reason (issue 124)."""

    model_config = ConfigDict(extra="ignore")

    retired: list[Portfolio] = Field(default_factory=list)
    failed: list[PortfolioRetireFailure] = Field(default_factory=list)


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
        """Delete the selected memberships in one statement and report the rest.

        The selection is the memberships of ``uids``, and those whose group is in
        ``portfolio_group_uids`` and whose portfolio is in ``portfolio_uids``; an empty
        filter does not narrow the match. The answer has ``detail``, ``deleted_count``,
        ``deleted`` (each deleted membership's ``uid``) and ``failed`` (each of ``uids``
        that was not deleted, with its ``uid`` and ``detail``).
        """

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
    "PortfolioBulkDeleteResponse",
    "PortfolioBulkRetireRequest",
    "PortfolioBulkRetireResponse",
    "PortfolioCreate",
    "PortfolioDeleteFailure",
    "PortfolioRetireFailure",
    "PortfolioDeleteResponse",
    "PortfolioDeletedRows",
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
