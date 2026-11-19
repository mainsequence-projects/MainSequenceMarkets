from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.base import MarketsMetaTableRow, PayloadWithRenamedFields, pre_3_0_field
from msm.api.remote import RemoteRowOperations
from msm.models import (
    AccountGroupTable,
    AccountHoldingsSetTable,
    AccountAllocationModelTable,
    AccountTable,
    AccountTargetAllocationTable,
    PositionSetTable,
)

ACCOUNT_HISTORY_DELETE_REFUSAL = (
    "its rows are account history, kept for as long as the account exists; "
    "Account.delete removes them together with the account (ADR 0049, ADR 0050)."
)
"""Why the account-history row classes refuse ``delete`` under every backend."""


class AccountAllocationModel(MarketsMetaTableRow):
    """Typed reusable account allocation-model row."""

    __table__: ClassVar[type[AccountAllocationModelTable]] = AccountAllocationModelTable
    __required_tables__: ClassVar[list[type[AccountAllocationModelTable]]] = [
        AccountAllocationModelTable
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("allocation_model_name",)

    allocation_model_name: str
    allocation_model_description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        payload: AccountAllocationModelCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountAllocationModel:
        values = _validated_payload_values(AccountAllocationModelCreate, payload, kwargs)
        return super().create(values)

    @classmethod
    def upsert(
        cls,
        payload: AccountAllocationModelUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountAllocationModel:
        values = _validated_payload_values(AccountAllocationModelUpsert, payload, kwargs)
        return super().upsert(values)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: AccountAllocationModelUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountAllocationModel:
        values = _validated_payload_values(AccountAllocationModelUpdate, payload, kwargs)
        return super().update(uid, values)


class AccountAllocationModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allocation_model_name: str = Field(min_length=1, max_length=100)
    allocation_model_description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountAllocationModelUpsert(AccountAllocationModelCreate):
    """Payload for inserting or updating an account allocation model."""


class AccountAllocationModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allocation_model_description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountGroup(MarketsMetaTableRow):
    """Typed account group row."""

    __table__: ClassVar[type[AccountGroupTable]] = AccountGroupTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountGroupTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("group_name",)

    group_name: str | None = None
    group_description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        payload: AccountGroupCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountGroup:
        values = _validated_payload_values(AccountGroupCreate, payload, kwargs)
        return super().create(values)

    @classmethod
    def upsert(
        cls,
        payload: AccountGroupUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountGroup:
        values = _validated_payload_values(AccountGroupUpsert, payload, kwargs)
        return super().upsert(values)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: AccountGroupUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountGroup:
        values = _validated_payload_values(AccountGroupUpdate, payload, kwargs)
        return super().update(uid, values)


class AccountGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_name: str | None = Field(default=None, max_length=100)
    group_description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountGroupUpsert(AccountGroupCreate):
    """Payload for inserting or updating an account group."""


class AccountGroupUpdate(AccountGroupCreate):
    """Payload for updating mutable account group fields."""


class Account(MarketsMetaTableRow):
    """Typed account row."""

    __table__: ClassVar[type[AccountTable]] = AccountTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountGroupTable,
        AccountTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    account_name: str
    is_paper: bool = True
    account_is_active: bool = False
    account_group_uid: uuid.UUID | None = None
    holdings_storage_table_uid: uuid.UUID | None = None
    holdings_data_node_uid: uuid.UUID | None = pre_3_0_field("holdings_storage_table_uid")
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def create(
        cls, payload: AccountCreate | Mapping[str, Any] | None = None, **kwargs: Any
    ) -> Account:
        values = _validated_payload_values(AccountCreate, payload, kwargs)
        return super().create(values)

    @classmethod
    def upsert(
        cls,
        payload: AccountUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Account:
        values = _validated_payload_values(AccountUpsert, payload, kwargs)
        return super().upsert(values)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: AccountUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Account:
        values = _validated_payload_values(AccountUpdate, payload, kwargs)
        return super().update(uid, values)

    @classmethod
    def delete(
        cls,
        uid: uuid.UUID | str,
        *,
        delete_portfolios: bool = False,
    ) -> dict[str, Any] | None:
        """Delete the account with its whole history, in one transaction (ADR 0050).

        Removes its orders, trades and their order events, order managers, virtual
        funds, target allocations, position sets, holdings sets and their rows, then
        the account. Only Markets tables receive statements; rows in another
        application's table go only through a foreign key that table declares, and a
        `RESTRICT` key there refuses the delete. Returns `None` when the account does
        not exist and raises `AccountDeleteConflictError` when a key refuses it. The
        same call does the same under the runtime and the remote backend.

        With ``delete_portfolios=True`` the same transaction also deletes, with all
        their data, the portfolios the account's virtual funds or target rows name and
        nothing else uses. The answer lists them in ``deleted_portfolios``, and in
        ``kept_portfolios``, with the reason, those that another account uses, whose
        values or weights another application's table holds, or whose delete a foreign
        key refuses; then the account is deleted alone.
        """

        from msm.services import delete_account

        return delete_account(cls._active_context(), uid=uid, delete_portfolios=delete_portfolios)

    @classmethod
    def bulk_delete(
        cls,
        *,
        uids: Sequence[uuid.UUID | str],
        delete_portfolios: bool = False,
    ) -> dict[str, Any]:
        """Delete each account as `delete` does, each in its own transaction.

        Accounts that are missing or refused are listed in `failed`; the others are
        deleted.
        """

        from msm.services import bulk_delete_accounts

        return bulk_delete_accounts(
            cls._active_context(),
            uids=[str(uid) for uid in uids],
            delete_portfolios=delete_portfolios,
        )

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
            unique_identifier = position.get("asset_identifier")
            if _is_missing(unique_identifier):
                raise ValueError("Holdings positions require an asset_identifier column.")

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


class AccountCreate(PayloadWithRenamedFields):
    model_config = ConfigDict(extra="forbid")
    __renamed_fields__: ClassVar[dict[str, str]] = {
        "holdings_storage_table_uid": "holdings_data_node_uid",
    }

    unique_identifier: str = Field(min_length=1, max_length=255)
    account_name: str = Field(min_length=1, max_length=255)
    is_paper: bool = True
    account_is_active: bool = False
    account_group_uid: uuid.UUID | str | None = None
    holdings_storage_table_uid: uuid.UUID | str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountUpsert(AccountCreate):
    """Payload for inserting or updating an account."""


class AccountUpdate(PayloadWithRenamedFields):
    model_config = ConfigDict(extra="forbid")
    __renamed_fields__: ClassVar[dict[str, str]] = {
        "holdings_storage_table_uid": "holdings_data_node_uid",
    }

    account_name: str | None = Field(default=None, max_length=255)
    is_paper: bool | None = None
    account_is_active: bool | None = None
    account_group_uid: uuid.UUID | str | None = None
    holdings_storage_table_uid: uuid.UUID | str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountHoldingsSet(MarketsMetaTableRow):
    """Typed account holdings-set row."""

    __table__: ClassVar[type[AccountHoldingsSetTable]] = AccountHoldingsSetTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountGroupTable,
        AccountTable,
        AccountHoldingsSetTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("account_uid", "time_index")
    __delete_refusal__: ClassVar[str | None] = ACCOUNT_HISTORY_DELETE_REFUSAL

    account_uid: uuid.UUID
    time_index: dt.datetime
    source_storage_table_uid: uuid.UUID | None = None
    source_data_node_uid: uuid.UUID | None = pre_3_0_field("source_storage_table_uid")

    @classmethod
    def create(
        cls,
        payload: AccountHoldingsSetCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountHoldingsSet:
        values = _validated_payload_values(AccountHoldingsSetCreate, payload, kwargs)
        return super().create(values)

    @classmethod
    def upsert(
        cls,
        payload: AccountHoldingsSetUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountHoldingsSet:
        values = _validated_payload_values(AccountHoldingsSetUpsert, payload, kwargs)
        return super().upsert(values)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: AccountHoldingsSetUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountHoldingsSet:
        values = _validated_payload_values(AccountHoldingsSetUpdate, payload, kwargs)
        return super().update(uid, values)


class AccountHoldingsSetCreate(PayloadWithRenamedFields):
    model_config = ConfigDict(extra="forbid")
    __renamed_fields__: ClassVar[dict[str, str]] = {
        "source_storage_table_uid": "source_data_node_uid",
    }

    account_uid: uuid.UUID | str
    time_index: dt.datetime
    source_storage_table_uid: uuid.UUID | str | None = None

    @field_validator("time_index")
    @classmethod
    def _validate_time_index(cls, value: dt.datetime) -> dt.datetime:
        return _utc_timestamp(value, field_name="time_index")


class AccountHoldingsSetUpsert(AccountHoldingsSetCreate):
    """Payload for inserting or updating an account holdings set."""


class AccountHoldingsSetUpdate(PayloadWithRenamedFields):
    model_config = ConfigDict(extra="forbid")
    __renamed_fields__: ClassVar[dict[str, str]] = {
        "source_storage_table_uid": "source_data_node_uid",
    }

    source_storage_table_uid: uuid.UUID | str | None = None


class AccountTargetAllocation(MarketsMetaTableRow):
    """Typed account target-allocation row."""

    __table__: ClassVar[type[AccountTargetAllocationTable]] = AccountTargetAllocationTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountAllocationModelTable,
        AccountGroupTable,
        AccountTable,
        AccountTargetAllocationTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)
    __delete_refusal__: ClassVar[str | None] = ACCOUNT_HISTORY_DELETE_REFUSAL

    unique_identifier: str
    account_uid: uuid.UUID
    account_allocation_model_uid: uuid.UUID
    display_name: str | None = None
    is_active: bool = True
    source: str | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        payload: AccountTargetAllocationCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountTargetAllocation:
        values = _validated_payload_values(AccountTargetAllocationCreate, payload, kwargs)
        return super().create(values)

    @classmethod
    def upsert(
        cls,
        payload: AccountTargetAllocationUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountTargetAllocation:
        values = _validated_payload_values(AccountTargetAllocationUpsert, payload, kwargs)
        return super().upsert(values)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: AccountTargetAllocationUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AccountTargetAllocation:
        values = _validated_payload_values(AccountTargetAllocationUpdate, payload, kwargs)
        return super().update(uid, values)


class AccountTargetAllocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    account_uid: uuid.UUID | str
    account_allocation_model_uid: uuid.UUID | str
    display_name: str | None = Field(default=None, max_length=255)
    is_active: bool = True
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class AccountTargetAllocationUpsert(AccountTargetAllocationCreate):
    """Payload for inserting or updating an account target allocation."""


class AccountTargetAllocationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_allocation_model_uid: uuid.UUID | str | None = None
    display_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class PositionSet(MarketsMetaTableRow):
    """Typed target position-set row."""

    __table__: ClassVar[type[PositionSetTable]] = PositionSetTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountAllocationModelTable,
        AccountGroupTable,
        AccountTable,
        AccountTargetAllocationTable,
        PositionSetTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "account_target_allocation_uid",
        "position_set_time",
    )
    __delete_refusal__: ClassVar[str | None] = ACCOUNT_HISTORY_DELETE_REFUSAL

    account_target_allocation_uid: uuid.UUID
    position_set_time: dt.datetime
    source: str | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        payload: PositionSetCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PositionSet:
        values = _validated_payload_values(PositionSetCreate, payload, kwargs)
        return super().create(values)

    @classmethod
    def upsert(
        cls,
        payload: PositionSetUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PositionSet:
        values = _validated_payload_values(PositionSetUpsert, payload, kwargs)
        return super().upsert(values)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: PositionSetUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PositionSet:
        values = _validated_payload_values(PositionSetUpdate, payload, kwargs)
        return super().update(uid, values)


class PositionSetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_target_allocation_uid: uuid.UUID | str
    position_set_time: dt.datetime
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("position_set_time")
    @classmethod
    def _validate_position_set_time(cls, value: dt.datetime) -> dt.datetime:
        return _utc_timestamp(value, field_name="position_set_time")


class PositionSetUpsert(PositionSetCreate):
    """Payload for inserting or updating a target position set."""


class PositionSetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


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
            "Holdings positions require a pandas DataFrame. Unpack TimeIndexTableUpdater run results "
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
            if column_name == "quantity":
                return position_type, _signed_quantity_value(position)
            return position_type, position.get(column_name)
    raise ValueError(
        "Holdings positions require one of quantity, target_weight, or weight_notional_exposure."
    )


def _signed_quantity_value(position: Any) -> Any:
    value = position.get("quantity")
    direction = _position_direction(position)
    if isinstance(value, str):
        try:
            return float(Decimal(value) * Decimal(direction))
        except InvalidOperation as exc:
            raise ValueError(f"Invalid holdings quantity {value!r}.") from exc
    return value * direction


def _position_direction(position: Any) -> int:
    value = position.get("direction", 1)
    if _is_missing(value):
        return 1
    try:
        direction = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid holdings direction {value!r}.") from exc
    if direction not in {1, -1}:
        raise ValueError("Holdings direction must be 1 for long or -1 for short.")
    return direction


def _is_missing(value: Any) -> bool:
    import pandas as pd

    if value is None:
        return True
    if isinstance(value, (dict, list, tuple, set)):
        return False
    return bool(pd.isna(value))



class AccountHoldingsSnapshots(RemoteRowOperations, BaseModel):
    """Publish and read account holdings snapshots through Markets (ADR 0047).

    Holdings rows live in the Markets ``AccountHoldingsStorage`` table, which an
    application does not write directly: ``publish`` creates the holdings set and
    its rows in one Markets operation, as ``POST /account/{uid}/add-holdings/``
    does, and ``get`` returns one snapshot. Under the remote backend both run on
    the Markets API.
    """

    __resource__: ClassVar[str] = "account-holdings"
    __required_tables__: ClassVar[list[str]] = [
        "Account",
        "Asset",
        "AccountHoldingsSet",
        "AccountHoldingsStorage",
        "AssetSnapshotsStorage",
    ]

    @classmethod
    def publish(
        cls,
        *,
        account_uid: uuid.UUID | str,
        holdings_date: dt.datetime,
        positions: list[dict[str, Any]],
        overwrite: bool = False,
        include_asset_detail: bool = False,
    ) -> dict[str, Any] | None:
        """Write one holdings snapshot; ``None`` when the account does not exist.

        Each position has ``asset_identifier`` (or ``asset_uid``), ``quantity``
        and optionally ``direction``, ``position_type``, ``target_trade_time``
        and ``extra_details``. Without ``overwrite`` an existing snapshot at
        ``holdings_date`` raises ``ValueError``.
        """

        from msm.services import add_account_holdings_snapshot_response

        return add_account_holdings_snapshot_response(
            cls._context(),
            account_uid=str(account_uid),
            holdings_date=holdings_date,
            positions=[dict(position) for position in positions],
            overwrite=overwrite,
            include_asset_detail=include_asset_detail,
        )

    @classmethod
    def get(
        cls,
        *,
        account_uid: uuid.UUID | str,
        holdings_date: dt.datetime | None = None,
        order: str = "desc",
        include_asset_detail: bool = False,
    ) -> dict[str, Any] | None:
        """One holdings snapshot: at ``holdings_date``, or the latest (``order="desc"``) or earliest."""

        from msm.services import get_account_holdings_snapshot_response

        return get_account_holdings_snapshot_response(
            cls._context(),
            account_uid=str(account_uid),
            order=order,
            limit=1,
            include_asset_detail=include_asset_detail,
            holdings_date=holdings_date,
        )

    @classmethod
    def get_many(
        cls,
        *,
        account_uid: uuid.UUID | str,
        holdings_dates: list[dt.datetime] | None = None,
        order: str = "desc",
        limit: int = 10,
        include_asset_detail: bool = False,
    ) -> list[dict[str, Any]] | None:
        """Several snapshots in one call: at ``holdings_dates``, or the latest or earliest ``limit``."""

        from msm.services import get_account_holdings_snapshots_response

        return get_account_holdings_snapshots_response(
            cls._context(),
            account_uid=str(account_uid),
            holdings_dates=holdings_dates,
            order=order,
            limit=limit,
            include_asset_detail=include_asset_detail,
        )

    @classmethod
    def _context(cls):
        from msm.bootstrap import resolve_runtime

        return resolve_runtime(models=cls.__required_tables__, row_model_name=cls.__name__).context



# Markets API wire contracts for account target positions
# (`GET /account/{account_uid}/target-positions/`, `POST .../add-target-positions/`).


class HoldingAssetCurrentSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    ticker: str | None = None


class AccountTargetPositionAssetReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str | None = None
    unique_identifier: str | None = None
    current_snapshot: HoldingAssetCurrentSnapshot = Field(
        default_factory=HoldingAssetCurrentSnapshot,
    )


class AccountTargetPositionPortfolioReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str | None = None
    unique_identifier: str | None = None
    published_index_uid: str | None = None


class AccountTargetPositionRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_type: Literal["asset", "portfolio"]
    target_uid: str
    asset_uid: str | None = None
    portfolio_uid: str | None = None
    unique_identifier: str
    weight_notional_exposure: str | None = None
    constant_notional_exposure: str | None = None
    single_asset_quantity: str | None = None
    asset: AccountTargetPositionAssetReference | None = None
    portfolio: AccountTargetPositionPortfolioReference | None = None


class AccountTargetPositionsSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    related_account_uid: str | None = None
    target_positions_date: dt.datetime | None = None
    position_set_uid: str | None = None
    positions: list[AccountTargetPositionRow] = Field(default_factory=list)


class PortfolioAccountTarget(BaseModel):
    """One account whose current target names a portfolio (``listPortfolioAccountTargets``).

    The exposure is the portfolio row's ``weight_notional_exposure`` or
    ``constant_notional_exposure``; portfolio rows never use ``single_asset_quantity``.
    ``position_set_uid`` identifies the snapshot read, so a caller can tell that
    the account's target changed before a later write.
    """

    model_config = ConfigDict(extra="ignore")

    account_uid: str
    account_target_allocation_uid: str
    position_set_uid: str
    target_positions_date: dt.datetime
    weight_notional_exposure: str | None = None
    constant_notional_exposure: str | None = None


class _AccountAddTargetPositionBaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_uid: str = Field(min_length=1)
    weight_notional_exposure: str | int | float | None = None
    constant_notional_exposure: str | int | float | None = None
    single_asset_quantity: str | int | float | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_single_exposure(self):
        provided_fields = [
            field_name
            for field_name in (
                "weight_notional_exposure",
                "constant_notional_exposure",
                "single_asset_quantity",
            )
            if getattr(self, field_name) is not None
        ]
        if len(provided_fields) != 1:
            raise ValueError("Each target position must provide exactly one exposure field.")
        return self


class AccountAddAssetTargetPositionRequest(_AccountAddTargetPositionBaseRequest):
    target_type: Literal["asset"]
    asset_uid: str = Field(min_length=1)
    portfolio_uid: None = None


class AccountAddPortfolioTargetPositionRequest(_AccountAddTargetPositionBaseRequest):
    target_type: Literal["portfolio"]
    asset_uid: None = None
    portfolio_uid: str = Field(min_length=1)

    @model_validator(mode="after")
    def _reject_portfolio_units(self):
        if self.single_asset_quantity is not None:
            raise ValueError("Portfolio target positions cannot use single_asset_quantity.")
        return self


AccountAddTargetPositionRequest = Annotated[
    AccountAddAssetTargetPositionRequest | AccountAddPortfolioTargetPositionRequest,
    Field(discriminator="target_type"),
]


class AccountAddTargetPositionsRequest(BaseModel):
    """One account target snapshot; an empty ``positions`` list clears the target."""

    model_config = ConfigDict(extra="forbid")

    target_positions_date: dt.datetime
    overwrite: bool
    positions: list[AccountAddTargetPositionRequest] = Field(
        description=(
            "The whole target at target_positions_date. An empty list clears the "
            "account's target: it writes an empty snapshot and sets the account's target "
            "allocation inactive."
        ),
    )


# Markets API wire contracts for virtual-fund allocation (ADR 0053).


class VirtualFundAllocationPolicySummary(BaseModel):
    """One allocation policy as `getVirtualFundAllocationPolicies` lists it."""

    model_config = ConfigDict(extra="ignore")

    id: str
    version: str
    title: str
    description: str
    path: str = Field(description="The path of the policy's description.")


class VirtualFundAllocationPolicyList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    policies: list[VirtualFundAllocationPolicySummary] = Field(default_factory=list)


class VirtualFundAllocationPolicyArgument(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    title: str
    description: str
    required: bool = Field(description="True when the argument has no default.")
    json_schema: dict[str, Any] = Field(
        alias="schema",
        description="The argument's JSON Schema 2020-12: type, bounds and default.",
    )


class VirtualFundAllocationPolicyDescription(BaseModel):
    """One allocation policy, described from the class that validates its arguments."""

    model_config = ConfigDict(extra="ignore")

    id: str
    version: str
    title: str
    description: str
    arguments: dict[str, VirtualFundAllocationPolicyArgument] = Field(default_factory=dict)
    arguments_schema: dict[str, Any] = Field(
        description=(
            "One JSON Schema 2020-12 object over every argument: what a form renders and what "
            "a request's `policy.arguments` is validated against."
        )
    )


class AccountVirtualFundAllocationPolicyChoice(BaseModel):
    """The policy a request runs: its id, the version it was built against, its arguments."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    version: str = Field(
        min_length=1,
        description=(
            "The policy version the request was built against. Any other version than the "
            "registry's answers 409 `policy_version_mismatch`."
        ),
    )
    arguments: dict[str, Any] = Field(default_factory=dict)


class AccountVirtualFundSizedPosition(BaseModel):
    """One asset of a sized target: a positive quantity with a side, in units."""

    model_config = ConfigDict(extra="forbid")

    asset_uid: str = Field(min_length=1, description="`Asset.uid`.")
    quantity: float = Field(
        gt=0,
        allow_inf_nan=False,
        description="Units of the asset: shares, contracts or currency units.",
    )
    direction: Literal[1, -1] = Field(default=1, description="`1` long, `-1` short.")


class AccountVirtualFundSizedTarget(BaseModel):
    """One exposure of the account's target, sized into units by the caller.

    ms-markets stores exposure as a share of NAV or an amount and reads no price,
    so the caller turns each exposure into units with its own prices and rules.
    """

    model_config = ConfigDict(extra="forbid")

    target_type: Literal["portfolio", "asset"] = Field(
        default="portfolio",
        description="The kind of target row that is sized.",
    )
    target_uid: str = Field(
        min_length=1,
        description=(
            "`Portfolio.uid` for a portfolio exposure, `Asset.uid` for an asset exposure. It "
            "must be a target of the `PositionSet`."
        ),
    )
    positions: list[AccountVirtualFundSizedPosition] = Field(
        default_factory=list,
        description=(
            "The target in units, one entry per asset. Empty for a target sized to nothing. "
            "An asset exposure has at most one entry, in its own asset."
        ),
    )


class AccountVirtualFundAllocationPlanRequest(BaseModel):
    """Plan the allocation of one holdings snapshot against one target."""

    model_config = ConfigDict(extra="forbid")

    position_set_uid: str = Field(
        min_length=1,
        description=(
            "The account's `PositionSet` to allocate against, used as it is. It states the "
            "account's exposure."
        ),
    )
    sized_targets: list[AccountVirtualFundSizedTarget] = Field(
        default_factory=list,
        description=(
            "The exposures of the `PositionSet` in units. Every portfolio exposure, and every "
            "asset exposure stated as a share or an amount, must be sized; an asset target "
            "stated as `single_asset_quantity` is already in units and is not sized. Any "
            "mismatch answers 400 `invalid_sized_targets`."
        ),
    )
    valuation_time: dt.datetime = Field(
        description=(
            "The time of the account's holdings snapshot: the `AccountHoldingsSet` at exactly "
            "this time is allocated."
        ),
    )
    policy: AccountVirtualFundAllocationPolicyChoice | None = Field(
        default=None,
        description=(
            "By default, `proportional_attribution` at its current version with its default "
            "arguments."
        ),
    )


class AccountVirtualFundAllocateRequest(AccountVirtualFundAllocationPlanRequest):
    """Plan again from the same inputs, then write the allocation."""

    plan_digest: str | None = Field(
        default=None,
        description=(
            "The `plan_digest` of a plan the caller saw. When given, a recomputed plan with "
            "another digest answers 409 `plan_changed` and nothing is written."
        ),
    )


class AccountVirtualFundAllocationFund(BaseModel):
    model_config = ConfigDict(extra="ignore")

    virtual_fund_unique_identifier: str
    target_portfolio_uid: str
    virtual_fund_uid: str | None = Field(default=None, description="Set when applied.")
    holdings_set_uid: str | None = Field(
        default=None,
        description="The fund's `VirtualFundHoldingsSet` for the snapshot; set when applied.",
    )


class AccountVirtualFundAllocationLine(BaseModel):
    """What one owner should hold of one asset, what it gets, and the difference, in units.

    ``delta = target - assigned``. Positive: units are missing. Negative: there are more
    units than the target asks for.
    """

    model_config = ConfigDict(extra="ignore")

    owner: Literal["fund", "direct"]
    asset_uid: str
    asset_identifier: str
    target: float
    assigned: float
    delta: float
    target_portfolio_uid: str | None = None
    virtual_fund_unique_identifier: str | None = None


class AccountVirtualFundAssetDelta(BaseModel):
    """One asset across the whole account: held, targeted, and ``target - held``."""

    model_config = ConfigDict(extra="ignore")

    asset_uid: str
    asset_identifier: str
    held: float
    target: float
    delta: float


class AccountVirtualFundAllocationPlanResponse(BaseModel):
    """The allocation of one holdings snapshot to the account's virtual funds, in units."""

    model_config = ConfigDict(extra="ignore")

    account_uid: str
    holdings_set_uid: str
    position_set_uid: str
    valuation_time: dt.datetime
    policy: AccountVirtualFundAllocationPolicyChoice
    funds: list[AccountVirtualFundAllocationFund] = Field(default_factory=list)
    lines: list[AccountVirtualFundAllocationLine] = Field(default_factory=list)
    account_deltas: list[AccountVirtualFundAssetDelta] = Field(default_factory=list)
    apply_blockers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="What would stop the allocate route but not the plan.",
    )
    plan_digest: str


class AccountVirtualFundAllocationResponse(AccountVirtualFundAllocationPlanResponse):
    """A plan and what the allocate route did with it."""

    applied: bool = Field(description="True when this call wrote the allocation.")
    already_applied: bool = Field(
        description="True when the same plan was already written and this call wrote nothing."
    )


class AccountAllocationRecordPolicy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    version: str | None = None


class AccountAllocationRecordLine(BaseModel):
    """One stored line of an allocation: an owner's target, what it was assigned, the delta.

    ``delta = target - assigned``, in signed units. Positive: units are missing. Negative:
    there are more units than the target asks for.
    """

    model_config = ConfigDict(extra="ignore")

    owner: Literal["fund", "direct"] = Field(
        description="`fund` for a virtual fund; `direct` for what the account holds outside its funds."
    )
    asset_identifier: str
    target: float
    assigned: float
    delta: float
    virtual_fund_uid: str | None = None
    virtual_fund_unique_identifier: str | None = None
    target_portfolio_uid: str | None = None


class AccountVirtualFundAllocationRecordResponse(BaseModel):
    """The stored record of one allocation of an account's holdings (ADR 0054).

    One per holdings snapshot. Every field but ``account_uid`` is empty when the account
    has no allocation at the requested time.
    """

    model_config = ConfigDict(extra="ignore")

    account_uid: str
    holdings_set_uid: str | None = Field(
        default=None, description="The `AccountHoldingsSet` that was allocated."
    )
    valuation_time: dt.datetime | None = Field(
        default=None, description="The time of that holdings snapshot."
    )
    position_set_uid: str | None = Field(
        default=None, description="The `PositionSet` the allocation was measured against."
    )
    policy: AccountAllocationRecordPolicy | None = None
    plan_digest: str | None = None
    lines: list[AccountAllocationRecordLine] = Field(default_factory=list)


# Markets API wire contracts for account registration
# (`POST /account/registration/`, ADR 0051).

ACCOUNT_REGISTRATION_MAX_ASSETS = 1000
"""Most distinct asset identifiers one registration names: one MetaTables read page."""

ACCOUNT_REGISTRATION_MAX_POSITIONS = 1000
"""Most positions one registration writes."""

ACCOUNT_REGISTRATION_TABLES: tuple[str, ...] = (
    "asset_types",
    "assets",
    "asset_snapshots",
    "asset_calendars",
    "accounts",
    "holdings_sets",
    "holdings",
)
"""The tables a registration writes, as keys of its ``written`` counts."""


class AccountRegistrationAccount(BaseModel):
    """The account to register. A flag left out keeps an existing account's value."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    account_name: str = Field(min_length=1, max_length=255)
    is_paper: bool | None = None
    account_is_active: bool | None = None


class AccountRegistrationAssetType(BaseModel):
    """The asset type an asset is created with; created too when it is missing."""

    model_config = ConfigDict(extra="forbid")

    asset_type: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None

    @field_validator("asset_type")
    @classmethod
    def _normalize_asset_type(cls, value: str) -> str:
        from msm.api.assets import normalize_asset_type

        return normalize_asset_type(value)


class AccountRegistrationAssetSnapshot(BaseModel):
    """The asset's display values; written when they differ from its latest snapshot."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None
    asset_ticker_group_id: str | None = None


class AccountRegistrationAsset(BaseModel):
    """An asset the registration creates when it is missing."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    asset_type: AccountRegistrationAssetType
    snapshot: AccountRegistrationAssetSnapshot | None = None
    calendar_identifier: str | None = Field(default=None, min_length=1, max_length=255)
    """``unique_identifier`` of the asset's trading calendar. The asset is linked to it in
    the registration's transaction when it has no trading calendar; an asset that has one
    keeps it (ADR 0057)."""


class AccountRegistrationPosition(BaseModel):
    """One holdings position: a positive quantity of an asset, long (1) or short (-1)."""

    model_config = ConfigDict(extra="forbid")

    asset_identifier: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(gt=0)
    direction: Literal[-1, 1] = 1
    extra_details: dict[str, Any] = Field(default_factory=dict)


class AccountRegistrationRequest(BaseModel):
    """Register an account and write one holdings snapshot (``registerAccount``, ADR 0051).

    ``assets`` are created when missing, with their asset types; ``cash_currency`` names a
    currency asset created the same way. A position may name one of them or an asset that
    already exists. The call is idempotent on ``(account.unique_identifier,
    holdings_date)``: stored holdings equal to ``positions`` are not written again, and
    different ones are replaced only with ``overwrite``.
    """

    model_config = ConfigDict(extra="forbid")

    account: AccountRegistrationAccount
    assets: list[AccountRegistrationAsset] = Field(
        default_factory=list,
        max_length=ACCOUNT_REGISTRATION_MAX_ASSETS,
    )
    cash_currency: str | None = Field(default=None, min_length=1, max_length=255)
    holdings_date: dt.datetime
    overwrite: bool = False
    positions: list[AccountRegistrationPosition] = Field(
        min_length=1,
        max_length=ACCOUNT_REGISTRATION_MAX_POSITIONS,
    )


class AccountRegistrationWriteCount(BaseModel):
    """Rows of one table a registration created, and existing rows it changed."""

    model_config = ConfigDict(extra="ignore")

    created: int = 0
    changed: int = 0


class AccountRegistrationResponse(BaseModel):
    """The registered account, its assets' uids, its holdings set and what was written."""

    model_config = ConfigDict(extra="ignore")

    account: Account
    asset_uids: dict[str, uuid.UUID]
    holdings_set_uid: uuid.UUID
    holdings_date: dt.datetime
    written: dict[str, AccountRegistrationWriteCount] = Field(
        default_factory=lambda: {
            table: AccountRegistrationWriteCount() for table in ACCOUNT_REGISTRATION_TABLES
        }
    )

    @property
    def uid(self) -> uuid.UUID:
        """The registered account's uid."""

        return self.account.uid


__all__ = [
    "PortfolioAccountTarget",
    "AccountAddAssetTargetPositionRequest",
    "AccountAddPortfolioTargetPositionRequest",
    "AccountAddTargetPositionRequest",
    "AccountAddTargetPositionsRequest",
    "AccountHoldingsSnapshots",
    "ACCOUNT_REGISTRATION_MAX_ASSETS",
    "ACCOUNT_REGISTRATION_MAX_POSITIONS",
    "ACCOUNT_REGISTRATION_TABLES",
    "AccountRegistrationAccount",
    "AccountRegistrationAsset",
    "AccountRegistrationAssetSnapshot",
    "AccountRegistrationAssetType",
    "AccountRegistrationPosition",
    "AccountRegistrationRequest",
    "AccountRegistrationResponse",
    "AccountRegistrationWriteCount",
    "Account",
    "AccountCreate",
    "AccountGroup",
    "AccountGroupCreate",
    "AccountGroupUpdate",
    "AccountGroupUpsert",
    "AccountHoldingsSet",
    "AccountHoldingsSetCreate",
    "AccountHoldingsSetUpdate",
    "AccountHoldingsSetUpsert",
    "AccountAllocationModel",
    "AccountAllocationModelCreate",
    "AccountAllocationModelUpdate",
    "AccountAllocationModelUpsert",
    "AccountTargetAllocation",
    "AccountTargetAllocationCreate",
    "AccountTargetAllocationUpdate",
    "AccountTargetAllocationUpsert",
    "AccountTargetPositionAssetReference",
    "AccountTargetPositionPortfolioReference",
    "AccountTargetPositionRow",
    "AccountTargetPositionsSnapshotResponse",
    "AccountUpdate",
    "AccountUpsert",
    "AccountVirtualFundAllocateRequest",
    "AccountVirtualFundAllocationFund",
    "AccountVirtualFundAllocationLine",
    "AccountVirtualFundAllocationPlanRequest",
    "AccountVirtualFundAllocationPlanResponse",
    "AccountVirtualFundAllocationPolicyChoice",
    "AccountVirtualFundAllocationResponse",
    "AccountVirtualFundAssetDelta",
    "VirtualFundAllocationPolicyArgument",
    "VirtualFundAllocationPolicyDescription",
    "VirtualFundAllocationPolicyList",
    "VirtualFundAllocationPolicySummary",
    "HoldingAssetCurrentSnapshot",
    "PositionSet",
    "PositionSetCreate",
    "PositionSetUpdate",
    "PositionSetUpsert",
]
