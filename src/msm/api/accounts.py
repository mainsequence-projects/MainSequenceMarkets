from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from msm.api.base import MarketsRow
from msm.models import (
    AccountGroupTable,
    AccountModelPortfolioTable,
    AccountTable,
    AccountTargetPositionAssignmentTable,
)


class AccountModelPortfolio(MarketsRow):
    """Typed account model-portfolio row."""

    __table__: ClassVar[type[AccountModelPortfolioTable]] = AccountModelPortfolioTable
    __required_tables__: ClassVar[list[type[AccountModelPortfolioTable]]] = [
        AccountModelPortfolioTable
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("model_portfolio_name",)

    model_portfolio_name: str
    model_portfolio_description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountModelPortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_portfolio_name: str = Field(min_length=1, max_length=100)
    model_portfolio_description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountModelPortfolioUpsert(AccountModelPortfolioCreate):
    """Payload for inserting or updating an account model portfolio."""


class AccountModelPortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_portfolio_description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountGroup(MarketsRow):
    """Typed account group row."""

    __table__: ClassVar[type[AccountGroupTable]] = AccountGroupTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountModelPortfolioTable,
        AccountGroupTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("group_name",)

    group_name: str | None = None
    group_description: str | None = None
    account_model_portfolio_uid: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None


class AccountGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_name: str | None = Field(default=None, max_length=100)
    group_description: str | None = None
    account_model_portfolio_uid: uuid.UUID | str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountGroupUpsert(AccountGroupCreate):
    """Payload for inserting or updating an account group."""


class AccountGroupUpdate(AccountGroupCreate):
    """Payload for updating mutable account group fields."""


class Account(MarketsRow):
    """Typed account row."""

    __table__: ClassVar[type[AccountTable]] = AccountTable
    __required_tables__: ClassVar[list[type[AccountTable]]] = [AccountTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    account_name: str
    is_paper: bool = True
    account_is_active: bool = False
    holdings_data_node_uid: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None

    def pretty_print_positions(
        self,
        holdings_frame: Any,
        *,
        asset_resolver: Callable[[str], Any] | None = None,
        output: Callable[[str], None] = print,
    ) -> Any:
        """Print and return account positions with resolved asset display fields."""

        import pandas as pd

        from msm.api.assets import Asset

        flat = _flat_holdings_frame(holdings_frame)
        if "account_uid" in flat.columns:
            flat = flat[flat["account_uid"].map(str) == str(self.uid)]

        resolve_asset = asset_resolver or Asset.get_by_unique_identifier
        rows = []
        for _, position in flat.iterrows():
            unique_identifier = position.get("unique_identifier")
            if _is_missing(unique_identifier):
                raise ValueError("Holdings positions require a unique_identifier column.")

            asset = resolve_asset(str(unique_identifier))
            extra_details = _position_extra_details(position)
            position_type, position_value = _position_type_and_value(position)
            rows.append(
                {
                    "asset_uid": getattr(asset, "uid", None),
                    "ticker": extra_details.get("ticker") or str(unique_identifier),
                    "position_type": position_type,
                    "position_value": position_value,
                }
            )

        positions = pd.DataFrame(
            rows,
            columns=["asset_uid", "ticker", "position_type", "position_value"],
        )
        output(positions.to_string(index=False))
        return positions


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    account_name: str = Field(min_length=1, max_length=255)
    is_paper: bool = True
    account_is_active: bool = False
    holdings_data_node_uid: uuid.UUID | str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountUpsert(AccountCreate):
    """Payload for inserting or updating an account."""


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_name: str | None = Field(default=None, max_length=255)
    is_paper: bool | None = None
    account_is_active: bool | None = None
    holdings_data_node_uid: uuid.UUID | str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountTargetPositionAssignment(MarketsRow):
    """Typed binding from an account to a target-position set."""

    __table__: ClassVar[type[AccountTargetPositionAssignmentTable]] = (
        AccountTargetPositionAssignmentTable
    )
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountTable,
        AccountTargetPositionAssignmentTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "account_uid",
        "target_positions_time",
    )

    account_uid: uuid.UUID
    target_positions_time: dt.datetime
    position_set_uid: uuid.UUID

    @classmethod
    def create(
        cls,
        payload: AccountTargetPositionAssignmentCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountTargetPositionAssignment:
        values = _validated_payload_values(AccountTargetPositionAssignmentCreate, payload, kwargs)
        return super().create(values)

    @classmethod
    def upsert(
        cls,
        payload: AccountTargetPositionAssignmentUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountTargetPositionAssignment:
        values = _validated_payload_values(AccountTargetPositionAssignmentUpsert, payload, kwargs)
        return super().upsert(values)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: AccountTargetPositionAssignmentUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountTargetPositionAssignment:
        values = _validated_payload_values(AccountTargetPositionAssignmentUpdate, payload, kwargs)
        return super().update(uid, values)


class AccountTargetPositionAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_uid: uuid.UUID | str
    target_positions_time: dt.datetime
    position_set_uid: uuid.UUID | str

    @field_validator("target_positions_time")
    @classmethod
    def _validate_target_positions_time(cls, value: dt.datetime) -> dt.datetime:
        return _utc_timestamp(value, field_name="target_positions_time")


class AccountTargetPositionAssignmentUpsert(AccountTargetPositionAssignmentCreate):
    """Payload for inserting or updating a target-position assignment."""


class AccountTargetPositionAssignmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_set_uid: uuid.UUID | str | None = None


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


def _flat_holdings_frame(holdings_frame: Any) -> Any:
    import pandas as pd

    if not isinstance(holdings_frame, pd.DataFrame):
        raise TypeError(
            "Holdings positions require a pandas DataFrame. Unpack DataNode run results "
            "before calling Account.pretty_print_positions(...)."
        )

    if isinstance(holdings_frame.index, pd.MultiIndex) or holdings_frame.index.name is not None:
        return holdings_frame.reset_index()
    return holdings_frame.copy()


def _position_extra_details(position: Any) -> dict[str, Any]:
    value = position.get("extra_details")
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _position_type_and_value(position: Any) -> tuple[str, Any]:
    for column_name, position_type in (
        ("quantity", "quantity"),
        ("target_weight", "target_weight"),
        ("weight_notional_exposure", "weight_notional_exposure"),
    ):
        if column_name in position and not _is_missing(position.get(column_name)):
            return position_type, position.get(column_name)
    raise ValueError(
        "Holdings positions require one of quantity, target_weight, or weight_notional_exposure."
    )


def _is_missing(value: Any) -> bool:
    import pandas as pd

    if value is None:
        return True
    if isinstance(value, (dict, list, tuple, set)):
        return False
    return bool(pd.isna(value))


__all__ = [
    "Account",
    "AccountCreate",
    "AccountGroup",
    "AccountGroupCreate",
    "AccountGroupUpdate",
    "AccountGroupUpsert",
    "AccountModelPortfolio",
    "AccountModelPortfolioCreate",
    "AccountModelPortfolioUpdate",
    "AccountModelPortfolioUpsert",
    "AccountTargetPositionAssignment",
    "AccountTargetPositionAssignmentCreate",
    "AccountTargetPositionAssignmentUpdate",
    "AccountTargetPositionAssignmentUpsert",
    "AccountUpdate",
    "AccountUpsert",
]
