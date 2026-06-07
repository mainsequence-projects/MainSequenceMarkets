from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from msm.api.base import MarketsMetaTableRow
from msm.data_nodes.accounts.storage import AccountHoldingsStorage
from msm.models import AccountGroupTable, AccountHoldingsSetTable, AccountTable, PortfolioTable

from msm_portfolios.data_nodes.virtual_funds.storage import VirtualFundHoldingsStorage
from msm_portfolios.models import (
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)
from msm_portfolios.services.holdings import (
    build_virtual_fund_holdings_frame,
    validate_virtual_fund_allocation_bounds,
)


class VirtualFund(MarketsMetaTableRow):
    """Typed virtual-fund row bound to an account and portfolio."""

    __table__: ClassVar[type[VirtualFundTable]] = VirtualFundTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountGroupTable,
        AccountTable,
        PortfolioTable,
        VirtualFundTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    account_uid: uuid.UUID
    target_portfolio_uid: uuid.UUID

    @classmethod
    def create(
        cls,
        payload: VirtualFundCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> VirtualFund:
        values = _validated_payload_values(VirtualFundCreate, payload, kwargs)
        return super().create(values)

    @classmethod
    def upsert(
        cls,
        payload: VirtualFundUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> VirtualFund:
        values = _validated_payload_values(VirtualFundUpsert, payload, kwargs)
        return super().upsert(values)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: VirtualFundUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> VirtualFund:
        values = _validated_payload_values(VirtualFundUpdate, payload, kwargs)
        return super().update(uid, values)

    def allocate_from_account_holdings_set(
        self,
        *,
        source_account_holdings_set_uid: uuid.UUID | str,
        allocation_time: dt.datetime | str,
        allocations: Sequence[VirtualFundAllocation | Mapping[str, Any] | Any],
        virtual_fund_holdings_set_uid: uuid.UUID | str | None = None,
        target_trade_time: dt.datetime | str | None = None,
        data_node: Any | None = None,
        run: bool = False,
        validate_bounds: bool = True,
    ) -> pd.DataFrame:
        resolved_holdings_set_uid = virtual_fund_holdings_set_uid or uuid.uuid4()
        frame = build_virtual_fund_holdings_frame(
            allocation_time=allocation_time,
            virtual_fund_uid=self.uid,
            source_account_holdings_set_uid=source_account_holdings_set_uid,
            virtual_fund_holdings_set_uid=resolved_holdings_set_uid,
            allocations=allocations,
            target_trade_time=target_trade_time,
        )
        if validate_bounds:
            validate_virtual_fund_allocation_bounds(_allocation_context(), frame)
        VirtualFundHoldingsSet.upsert(
            {
                "uid": resolved_holdings_set_uid,
                "virtual_fund_uid": self.uid,
                "source_account_holdings_set_uid": source_account_holdings_set_uid,
                "time_index": allocation_time,
            }
        )
        if data_node is not None:
            data_node.set_frame(frame)
            if run:
                data_node.run(debug_mode=True, update_tree=False, force_update=True)
        return frame


class VirtualFundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    account_uid: uuid.UUID | str
    target_portfolio_uid: uuid.UUID | str


class VirtualFundUpsert(VirtualFundCreate):
    """Payload for inserting or updating a virtual fund."""


class VirtualFundUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_uid: uuid.UUID | str | None = None
    target_portfolio_uid: uuid.UUID | str | None = None


class VirtualFundHoldingsSet(MarketsMetaTableRow):
    """Typed virtual-fund allocation set row."""

    __table__: ClassVar[type[VirtualFundHoldingsSetTable]] = VirtualFundHoldingsSetTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountGroupTable,
        AccountTable,
        AccountHoldingsSetTable,
        PortfolioTable,
        VirtualFundTable,
        VirtualFundHoldingsSetTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "virtual_fund_uid",
        "source_account_holdings_set_uid",
    )

    virtual_fund_uid: uuid.UUID
    source_account_holdings_set_uid: uuid.UUID
    time_index: dt.datetime

    @classmethod
    def create(
        cls,
        payload: VirtualFundHoldingsSetCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> VirtualFundHoldingsSet:
        values = _validated_payload_values(VirtualFundHoldingsSetCreate, payload, kwargs)
        return super().create(values)

    @classmethod
    def upsert(
        cls,
        payload: VirtualFundHoldingsSetUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> VirtualFundHoldingsSet:
        values = _validated_payload_values(VirtualFundHoldingsSetUpsert, payload, kwargs)
        return super().upsert(values)


class VirtualFundHoldingsSetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: uuid.UUID | str | None = None
    virtual_fund_uid: uuid.UUID | str
    source_account_holdings_set_uid: uuid.UUID | str
    time_index: dt.datetime

    @field_validator("time_index")
    @classmethod
    def _validate_time_index(cls, value: dt.datetime) -> dt.datetime:
        return _utc_timestamp(value, field_name="time_index")


class VirtualFundHoldingsSetUpsert(VirtualFundHoldingsSetCreate):
    """Payload for inserting or updating a virtual-fund holdings set."""


class VirtualFundAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_identifier: str = Field(min_length=1, max_length=255)
    allocated_quantity: float = Field(gt=0)
    direction: int = Field(default=1)
    target_trade_time: dt.datetime | None = None
    extra_details: dict[str, Any] | None = None

    @field_validator("direction")
    @classmethod
    def _validate_direction(cls, value: int) -> int:
        if value not in {1, -1}:
            raise ValueError("direction must be 1 for long or -1 for short.")
        return value

    @field_validator("target_trade_time")
    @classmethod
    def _validate_target_trade_time(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is None:
            return None
        return _utc_timestamp(value, field_name="target_trade_time")


def _validated_payload_values(
    payload_model: type[BaseModel],
    payload: BaseModel | Mapping[str, Any] | None,
    kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    if payload is None:
        return payload_model(**dict(kwargs)).model_dump(exclude_unset=True)
    if kwargs:
        raise TypeError("Pass either a payload object or keyword fields, not both.")
    if isinstance(payload, payload_model):
        return payload.model_dump(exclude_unset=True)
    if isinstance(payload, BaseModel):
        return payload_model.model_validate(payload.model_dump(exclude_unset=True)).model_dump(
            exclude_unset=True,
        )
    if isinstance(payload, Mapping):
        return payload_model.model_validate(dict(payload)).model_dump(exclude_unset=True)
    raise TypeError("Payload must be a Pydantic model, mapping, or None.")


def _utc_timestamp(value: dt.datetime, *, field_name: str) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware UTC timestamp.")
    return value.astimezone(dt.UTC)


def _allocation_context():
    from msm.bootstrap import resolve_runtime

    return resolve_runtime(
        models=[
            AccountGroupTable,
            AccountTable,
            AccountHoldingsSetTable,
            AccountHoldingsStorage,
            PortfolioTable,
            VirtualFundTable,
            VirtualFundHoldingsSetTable,
            VirtualFundHoldingsStorage,
        ],
        row_model_name="VirtualFundAllocation",
    ).context


__all__ = [
    "VirtualFund",
    "VirtualFundAllocation",
    "VirtualFundCreate",
    "VirtualFundHoldingsSet",
    "VirtualFundHoldingsSetCreate",
    "VirtualFundHoldingsSetUpsert",
    "VirtualFundUpdate",
    "VirtualFundUpsert",
]
