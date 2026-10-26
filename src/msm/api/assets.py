from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from msm.api.remote import RemoteRowOperations
from msm.api.base import (
    MarketsMetaTableRow,
    _dedupe_models,
    _warn_deprecated_create_schemas,
    operation_result_rows,
)
from msm.constants import (
    ASSET_TYPE_BOND,
    ASSET_TYPE_BOND_DEFINITION,
    ASSET_TYPE_CRYPTO,
    ASSET_TYPE_CURRENCY,
    ASSET_TYPE_CURRENCY_SPOT,
    ASSET_TYPE_CURRENCY_SPOT_DEFINITION,
    ASSET_TYPE_EQUITY,
)
from msm.models import (
    AssetCategoryMembershipTable,
    AssetCategoryTable,
    AssetTypeTable,
    AssetTable,
    BondAssetDetailsTable,
    CurrencySpotAssetDetailsTable,
    IssuerTable,
    OpenFigiAssetDetailsTable,
)
from msm.repositories.crud import bulk_upsert_model, get_model_by_uid, search_model, upsert_model

if TYPE_CHECKING:
    from msm.services.indices import RelatedMetaTable

_operation_result_rows = operation_result_rows
CURRENCY_ASSET_TYPE = ASSET_TYPE_CURRENCY
CURRENCY_SPOT_ASSET_TYPE = ASSET_TYPE_CURRENCY_SPOT
BOND_ASSET_TYPE = ASSET_TYPE_BOND
CRYPTO_ASSET_TYPE = ASSET_TYPE_CRYPTO
EQUITY_ASSET_TYPE = ASSET_TYPE_EQUITY


def normalize_asset_type(asset_type: str | None) -> str | None:
    """Return the canonical asset type key stored by the typed API."""

    if asset_type is None:
        return None

    normalized = re.sub(r"\s+", "_", str(asset_type).strip().lower())
    if not normalized:
        raise ValueError("asset_type cannot be empty.")
    return normalized


def _validate_payload(
    payload_model: type[BaseModel],
    payload: BaseModel | Mapping[str, Any] | None,
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


class Asset(MarketsMetaTableRow):
    """User-facing asset row returned by typed markets API helpers."""

    __table__: ClassVar[type[AssetTable]] = AssetTable
    __required_tables__: ClassVar[list[type[AssetTable]]] = [AssetTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    asset_type: str | None = None

    @field_validator("asset_type", mode="before")
    @classmethod
    def _normalize_row_asset_type(cls, value: str | None) -> str | None:
        return normalize_asset_type(value)

    @classmethod
    def create(cls, payload: AssetCreate | Mapping[str, Any] | None = None, **kwargs: Any) -> Asset:
        return super().create(_validate_payload(AssetCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: AssetUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Asset:
        return super().upsert(_validate_payload(AssetUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: AssetUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Asset:
        return super().update(uid, _validate_payload(AssetUpdate, payload, kwargs))

    @classmethod
    def list_related_meta_tables(
        cls,
        uid: uuid.UUID | str,
        *,
        numeric: bool = True,
        timestamped: bool = True,
    ) -> tuple[RelatedMetaTable, ...]:
        """List MetaTables whose registered FK targets Asset.unique_identifier."""

        if cls.get_by_uid(uid) is None:
            raise LookupError(f"Asset {uid!s} was not found")
        from msm.services.related_meta_tables import list_reference_meta_tables

        return list_reference_meta_tables(
            reference_type="asset",
            numeric=numeric,
            timestamped=timestamped,
        )


class AssetCreate(BaseModel):
    """Payload for creating an asset row."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    asset_type: str | None = Field(default=None, max_length=64)

    @field_validator("asset_type", mode="before")
    @classmethod
    def _normalize_asset_type(cls, value: str | None) -> str | None:
        return normalize_asset_type(value)


class AssetUpsert(AssetCreate):
    """Payload for inserting or updating an asset row by unique identifier."""


class AssetUpdate(BaseModel):
    """Payload for updating mutable asset fields."""

    model_config = ConfigDict(extra="forbid")

    asset_type: str | None = Field(default=None, max_length=64)

    @field_validator("asset_type", mode="before")
    @classmethod
    def _normalize_asset_type(cls, value: str | None) -> str | None:
        return normalize_asset_type(value)


class AssetType(MarketsMetaTableRow):
    """Typed row for the asset type registry."""

    __table__: ClassVar[type[AssetTypeTable]] = AssetTypeTable
    __required_tables__: ClassVar[list[type[AssetTypeTable]]] = [AssetTypeTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("asset_type",)

    asset_type: str
    display_name: str | None = None
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("asset_type", mode="before")
    @classmethod
    def _normalize_row_asset_type(cls, value: str) -> str:
        normalized = normalize_asset_type(value)
        if normalized is None:
            raise ValueError("asset_type cannot be empty.")
        return normalized

    @classmethod
    def create(
        cls,
        payload: AssetTypeCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AssetType:
        return super().create(_validate_payload(AssetTypeCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: AssetTypeUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AssetType:
        return super().upsert(_validate_payload(AssetTypeUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: AssetTypeUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AssetType:
        return super().update(uid, _validate_payload(AssetTypeUpdate, payload, kwargs))


class AssetTypeCreate(BaseModel):
    """Payload for creating an asset type registry row."""

    model_config = ConfigDict(extra="forbid")

    asset_type: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("asset_type", mode="before")
    @classmethod
    def _normalize_asset_type(cls, value: str) -> str:
        normalized = normalize_asset_type(value)
        if normalized is None:
            raise ValueError("asset_type cannot be empty.")
        return normalized


class AssetTypeUpsert(AssetTypeCreate):
    """Payload for inserting or updating an asset type by registry key."""


class AssetTypeUpdate(BaseModel):
    """Payload for updating mutable asset type fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class CurrencySpot(RemoteRowOperations, BaseModel):
    """Typed currency spot asset with base and quote currency references."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTypeTable,
        AssetTable,
        CurrencySpotAssetDetailsTable,
    ]

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
    unique_identifier: str
    asset_type: str = CURRENCY_SPOT_ASSET_TYPE
    base_currency_uid: uuid.UUID
    quote_currency_uid: uuid.UUID

    @classmethod
    def start_engine(cls, **kwargs: Any):
        """Attach the runtime tables required by the currency spot API."""

        from msm.bootstrap import start_engine

        requested_models = kwargs.pop("models", None)
        models = _dedupe_models([*cls.__required_tables__, *(requested_models or [])])
        return start_engine(models=models, **kwargs)

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        """Deprecated compatibility alias for :meth:`start_engine`."""

        _warn_deprecated_create_schemas(cls.__name__)
        return cls.start_engine(**kwargs)

    @classmethod
    def upsert(
        cls,
        payload: CurrencySpotUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> CurrencySpot:
        """Upsert a currency spot asset and its base/quote relationship."""

        values = _validate_payload(CurrencySpotUpsert, payload, kwargs).model_dump()
        context = cls._active_context()

        upsert_model(
            context,
            model=AssetTypeTable,
            values=ASSET_TYPE_CURRENCY_SPOT_DEFINITION.as_payload(),
            conflict_columns=("asset_type",),
        )
        pair_asset = Asset._from_operation_result(
            upsert_model(
                context,
                model=AssetTable,
                values={
                    "unique_identifier": values["unique_identifier"],
                    "asset_type": CURRENCY_SPOT_ASSET_TYPE,
                },
                conflict_columns=("unique_identifier",),
            )
        )
        detail_rows = operation_result_rows(
            upsert_model(
                context,
                model=CurrencySpotAssetDetailsTable,
                values={
                    "asset_uid": pair_asset.uid,
                    "base_currency_uid": values["base_currency_uid"],
                    "quote_currency_uid": values["quote_currency_uid"],
                },
                conflict_columns=("asset_uid",),
            )
        )
        if not detail_rows:
            raise LookupError("CurrencySpot upsert did not return a row.")

        return cls.model_validate(
            {
                **detail_rows[0],
                "uid": detail_rows[0].get("asset_uid"),
                "unique_identifier": pair_asset.unique_identifier,
                "asset_type": pair_asset.asset_type,
            }
        )

    @classmethod
    def upsert_many(
        cls,
        payloads: Sequence[CurrencySpotUpsert | Mapping[str, Any]],
    ) -> list[CurrencySpot]:
        """Upsert many currency spots: one statement for the assets, one for their details."""

        values = _last_by_identifier(
            _validate_payload(CurrencySpotUpsert, payload, {}).model_dump() for payload in payloads
        )
        if not values:
            return []
        context = cls._active_context()
        upsert_model(
            context,
            model=AssetTypeTable,
            values=ASSET_TYPE_CURRENCY_SPOT_DEFINITION.as_payload(),
            conflict_columns=("asset_type",),
        )
        assets = _bulk_upsert_composite_assets(context, values, asset_type=CURRENCY_SPOT_ASSET_TYPE)
        details = operation_result_rows(
            bulk_upsert_model(
                context,
                model=CurrencySpotAssetDetailsTable,
                values=[
                    {
                        "asset_uid": assets[item["unique_identifier"]]["uid"],
                        "base_currency_uid": item["base_currency_uid"],
                        "quote_currency_uid": item["quote_currency_uid"],
                    }
                    for item in values
                ],
                conflict_columns=("asset_uid",),
            )
        )
        return _composite_rows(cls, details, {row["uid"]: row for row in assets.values()})

    @classmethod
    def filter(
        cls,
        *,
        asset_uids: list[uuid.UUID] | None = None,
        base_currency_uids: list[uuid.UUID] | None = None,
        quote_currency_uids: list[uuid.UUID] | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[CurrencySpot]:
        """Currency spots by asset, base or quote currency uids, ordered by asset uid."""

        return _filter_composites(
            cls,
            CurrencySpotAssetDetailsTable,
            {
                "asset_uid": asset_uids,
                "base_currency_uid": base_currency_uids,
                "quote_currency_uid": quote_currency_uids,
            },
            limit=limit,
            offset=offset,
        )

    @classmethod
    def _active_context(cls):
        from msm.bootstrap import resolve_runtime

        runtime = resolve_runtime(
            models=cls.__required_tables__,
            row_model_name=cls.__name__,
        )
        return runtime.context


def _last_by_identifier(values: Any) -> list[dict[str, Any]]:
    """Keep the last payload per ``unique_identifier``; one statement cannot write a row twice."""

    return list({item["unique_identifier"]: item for item in values}.values())


def _bulk_upsert_composite_assets(
    context: Any,
    values: Sequence[Mapping[str, Any]],
    *,
    asset_type: str,
) -> dict[str, dict[str, Any]]:
    rows = operation_result_rows(
        bulk_upsert_model(
            context,
            model=AssetTable,
            values=[
                {"unique_identifier": item["unique_identifier"], "asset_type": asset_type}
                for item in values
            ],
            conflict_columns=("unique_identifier",),
        )
    )
    return {str(row["unique_identifier"]): row for row in rows}


def _filter_composites(
    cls: Any,
    details_table: Any,
    uid_filters: Mapping[str, Sequence[Any] | None],
    *,
    limit: int,
    offset: int,
    extra_in_filters: Mapping[str, Sequence[Any] | None] | None = None,
) -> list[Any]:
    in_filters = {
        column: [uuid.UUID(str(value)) for value in values]
        for column, values in uid_filters.items()
        if values
    }
    in_filters.update({column: list(values) for column, values in (extra_in_filters or {}).items() if values})
    context = cls._active_context()
    details = operation_result_rows(
        search_model(
            context,
            model=details_table,
            in_filters=in_filters,
            limit=limit,
            offset=offset,
            order_by=["asset_uid"],
        )
    )
    asset_uids = [detail["asset_uid"] for detail in details]
    assets = operation_result_rows(
        search_model(
            context,
            model=AssetTable,
            in_filters={"uid": asset_uids},
            limit=len(asset_uids),
        )
    ) if asset_uids else []
    return _composite_rows(cls, details, {row["uid"]: row for row in assets})


def _composite_rows(
    cls: Any,
    details: Sequence[Mapping[str, Any]],
    assets_by_uid: Mapping[Any, Mapping[str, Any]],
) -> list[Any]:
    by_text = {str(uid): row for uid, row in assets_by_uid.items()}
    rows = []
    for detail in details:
        asset = by_text.get(str(detail.get("asset_uid")))
        if asset is None:
            continue
        rows.append(
            cls.model_validate(
                {
                    **detail,
                    "uid": detail.get("asset_uid"),
                    "unique_identifier": asset["unique_identifier"],
                    "asset_type": asset["asset_type"],
                }
            )
        )
    return rows


class CurrencySpotCreate(BaseModel):
    """Payload for creating a currency spot asset and relationship row."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    base_currency_uid: uuid.UUID
    quote_currency_uid: uuid.UUID

    @model_validator(mode="after")
    def _base_and_quote_must_differ(self) -> CurrencySpotCreate:
        if self.base_currency_uid == self.quote_currency_uid:
            raise ValueError("CurrencySpot base_currency_uid and quote_currency_uid must differ.")
        return self


class CurrencySpotUpsert(CurrencySpotCreate):
    """Payload for inserting or updating a currency spot pair by unique identifier."""


class BondStatus(str, Enum):
    """Canonical bond lifecycle status values."""

    ACTIVE = "ACTIVE"
    MATURED = "MATURED"
    DEFAULTED = "DEFAULTED"
    CALLED = "CALLED"
    REDEEMED = "REDEEMED"
    UNKNOWN = "UNKNOWN"


def _normalize_bond_status(value: BondStatus | str) -> str:
    if isinstance(value, BondStatus):
        return str(value.value)
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError("Bond status cannot be empty.")
    valid_values = {str(member.value) for member in BondStatus}
    if normalized not in valid_values:
        valid_display = ", ".join(sorted(valid_values))
        raise ValueError(f"Bond status must be one of: {valid_display}.")
    return normalized


class Bond(RemoteRowOperations, BaseModel):
    """Typed bond asset with issuer, currency, and lifecycle detail."""

    model_config = ConfigDict(extra="ignore", frozen=True, use_enum_values=True)

    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTypeTable,
        AssetTable,
        IssuerTable,
        BondAssetDetailsTable,
    ]

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
    unique_identifier: str
    asset_type: str = BOND_ASSET_TYPE
    issuer_uid: uuid.UUID
    currency_asset_uid: uuid.UUID
    issue_date: dt.date
    maturity_date: dt.date | None = None
    status: BondStatus

    @classmethod
    def start_engine(cls, **kwargs: Any):
        """Attach the runtime tables required by the bond API."""

        from msm.bootstrap import start_engine

        requested_models = kwargs.pop("models", None)
        models = _dedupe_models([*cls.__required_tables__, *(requested_models or [])])
        return start_engine(models=models, **kwargs)

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        """Deprecated compatibility alias for :meth:`start_engine`."""

        _warn_deprecated_create_schemas(cls.__name__)
        return cls.start_engine(**kwargs)

    @classmethod
    def upsert(
        cls,
        payload: BondUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Bond:
        """Upsert a bond asset and its detail row."""

        values = _validate_payload(BondUpsert, payload, kwargs).model_dump()
        context = cls._active_context()

        _require_existing_reference(
            context,
            model=IssuerTable,
            uid=values["issuer_uid"],
            field_name="issuer_uid",
        )
        _require_existing_reference(
            context,
            model=AssetTable,
            uid=values["currency_asset_uid"],
            field_name="currency_asset_uid",
        )
        upsert_model(
            context,
            model=AssetTypeTable,
            values=ASSET_TYPE_BOND_DEFINITION.as_payload(),
            conflict_columns=("asset_type",),
        )
        bond_asset = Asset._from_operation_result(
            upsert_model(
                context,
                model=AssetTable,
                values={
                    "unique_identifier": values["unique_identifier"],
                    "asset_type": BOND_ASSET_TYPE,
                },
                conflict_columns=("unique_identifier",),
            )
        )
        detail_rows = operation_result_rows(
            upsert_model(
                context,
                model=BondAssetDetailsTable,
                values={
                    "asset_uid": bond_asset.uid,
                    "issuer_uid": values["issuer_uid"],
                    "currency_asset_uid": values["currency_asset_uid"],
                    "issue_date": values["issue_date"],
                    "maturity_date": values["maturity_date"],
                    "status": values["status"],
                },
                conflict_columns=("asset_uid",),
            )
        )
        if not detail_rows:
            raise LookupError("Bond upsert did not return a row.")

        return cls.model_validate(
            {
                **detail_rows[0],
                "uid": detail_rows[0].get("asset_uid"),
                "unique_identifier": bond_asset.unique_identifier,
                "asset_type": bond_asset.asset_type,
            }
        )

    @classmethod
    def _active_context(cls):
        from msm.bootstrap import resolve_runtime

        runtime = resolve_runtime(
            models=cls.__required_tables__,
            row_model_name=cls.__name__,
        )
        return runtime.context


class BondCreate(BaseModel):
    """Payload for creating a bond asset and detail row."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    unique_identifier: str = Field(min_length=1, max_length=255)
    issuer_uid: uuid.UUID | str
    currency_asset_uid: uuid.UUID | str
    issue_date: dt.date
    maturity_date: dt.date | None = None
    status: BondStatus

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: BondStatus | str) -> str:
        return _normalize_bond_status(value)

    @model_validator(mode="after")
    def _maturity_must_not_precede_issue(self) -> BondCreate:
        if self.maturity_date is not None and self.maturity_date < self.issue_date:
            raise ValueError("Bond maturity_date must not be earlier than issue_date.")
        return self


class BondUpsert(BondCreate):
    """Payload for inserting or updating a bond by unique identifier."""


def _require_existing_reference(
    context: Any,
    *,
    model: type[Any],
    uid: uuid.UUID | str,
    field_name: str,
) -> None:
    if operation_result_rows(get_model_by_uid(context, model=model, uid=uid)):
        return
    raise LookupError(f"Bond {field_name}={uid!s} does not reference an existing row.")


class AssetCategory(MarketsMetaTableRow):
    """Typed asset universe row."""

    __table__: ClassVar[type[AssetCategoryTable]] = AssetCategoryTable
    __required_tables__: ClassVar[list[type[AssetCategoryTable]]] = [AssetCategoryTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    display_name: str
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def replace_memberships(
        cls,
        *,
        category_uid: uuid.UUID | str,
        asset_uids: list[uuid.UUID | str],
    ) -> list[AssetCategoryMembership]:
        """Replace the asset membership set for one category."""

        from msm.repositories.asset_categories import (
            replace_asset_category_memberships,
        )

        context = AssetCategoryMembership._active_context()
        results = replace_asset_category_memberships(
            context,
            category_uid=category_uid,
            asset_uids=asset_uids,
        )
        return [
            AssetCategoryMembership.model_validate(row)
            for result in results
            for row in operation_result_rows(result)
        ]


class AssetCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AssetCategoryUpsert(AssetCategoryCreate):
    """Payload for inserting or updating an asset category row."""


class AssetCategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AssetCategoryMembership(MarketsMetaTableRow):
    """Typed membership row between an asset category and an asset."""

    __table__: ClassVar[type[AssetCategoryMembershipTable]] = AssetCategoryMembershipTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        AssetCategoryTable,
        AssetCategoryMembershipTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("category_uid", "asset_uid")

    category_uid: uuid.UUID
    asset_uid: uuid.UUID


class AssetCategoryMembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_uid: uuid.UUID | str
    asset_uid: uuid.UUID | str


class AssetCategoryMembershipUpsert(AssetCategoryMembershipCreate):
    """Payload for inserting or updating an asset category membership row."""


class OpenFigiDetails(MarketsMetaTableRow):
    """Typed OpenFIGI/provider detail row linked to an asset."""

    __table__: ClassVar[type[OpenFigiAssetDetailsTable]] = OpenFigiAssetDetailsTable
    __required_tables__: ClassVar[list[type[Any]]] = [AssetTable, OpenFigiAssetDetailsTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("asset_uid",)

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
    figi: str | None = None
    composite: str | None = None
    share_class: str | None = None
    isin: str | None = None
    ticker: str | None = None
    name: str | None = None
    exchange_code: str | None = None
    security_type: str | None = None
    security_type_2: str | None = None
    security_market_sector: str | None = None
    security_description: str | None = None
    unique_id: str | None = None
    unique_id_fut_opt: str | None = None
    metadata_text: str | None = None
    raw_payload: dict[str, Any] | None = None


class OpenFigiDetailsCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_uid: uuid.UUID | str
    figi: str | None = Field(default=None, max_length=12)
    composite: str | None = Field(default=None, max_length=12)
    share_class: str | None = Field(default=None, max_length=12)
    isin: str | None = Field(default=None, max_length=12)
    ticker: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=255)
    exchange_code: str | None = Field(default=None, max_length=50)
    security_type: str | None = Field(default=None, max_length=50)
    security_type_2: str | None = Field(default=None, max_length=50)
    security_market_sector: str | None = Field(default=None, max_length=50)
    security_description: str | None = Field(default=None, max_length=255)
    unique_id: str | None = Field(default=None, max_length=255)
    unique_id_fut_opt: str | None = Field(default=None, max_length=255)
    metadata_text: str | None = None
    raw_payload: dict[str, Any] | None = None


class OpenFigiDetailsUpsert(OpenFigiDetailsCreate):
    """Payload for inserting or updating OpenFIGI details by asset UID."""


class OpenFigiDetailsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    figi: str | None = Field(default=None, max_length=12)
    composite: str | None = Field(default=None, max_length=12)
    share_class: str | None = Field(default=None, max_length=12)
    isin: str | None = Field(default=None, max_length=12)
    ticker: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=255)
    exchange_code: str | None = Field(default=None, max_length=50)
    security_type: str | None = Field(default=None, max_length=50)
    security_type_2: str | None = Field(default=None, max_length=50)
    security_market_sector: str | None = Field(default=None, max_length=50)
    security_description: str | None = Field(default=None, max_length=255)
    unique_id: str | None = Field(default=None, max_length=255)
    unique_id_fut_opt: str | None = Field(default=None, max_length=255)
    metadata_text: str | None = None
    raw_payload: dict[str, Any] | None = None



class AssetSnapshotReference(BaseModel):
    """An asset with its latest snapshot; the snapshot fields are ``None`` without one."""

    asset_uid: uuid.UUID
    asset_identifier: str
    asset_type: str | None = None
    snapshot_time: dt.datetime | None = None
    name: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None
    asset_ticker_group_id: str | None = None


_SNAPSHOT_READ_BATCH = 500


class AssetSnapshots(RemoteRowOperations, BaseModel):
    """Publish and read asset snapshots (display name, ticker ...) (ADR 0047).

    Snapshots live in the Markets ``AssetSnapshotsStorage`` table, which Markets
    reads for asset details. An application publishes them with ``publish`` and
    reads the latest one per asset with ``latest``; under the remote backend both
    run on the Markets API, so the application needs no grant on the table.
    """

    __resource__: ClassVar[str] = "asset-snapshots"

    @classmethod
    def latest(
        cls,
        *,
        asset_identifiers: list[str] | None = None,
        asset_uids: list[uuid.UUID] | None = None,
        tickers: list[str] | None = None,
    ) -> list[AssetSnapshotReference]:
        """Return each requested asset with its latest snapshot.

        Pass exactly one of ``asset_identifiers``, ``asset_uids`` or ``tickers``.
        Assets that do not exist are left out; an asset without a snapshot has
        ``snapshot_time`` ``None``. ``tickers`` selects the assets that have any
        snapshot with one of those tickers: compare each result's latest
        ``ticker`` to find the assets that still carry it.
        """

        from msm.bootstrap import resolve_runtime
        from msm.services.assets import (
            asset_identifiers_by_ticker,
            asset_reference_details,
            asset_reference_details_by_uids,
        )

        selectors = [value for value in (asset_identifiers, asset_uids, tickers) if value is not None]
        if len(selectors) != 1:
            raise ValueError("Pass exactly one of asset_identifiers, asset_uids or tickers.")
        context = resolve_runtime(
            models=["Asset", "AssetSnapshotsStorage"],
            row_model_name=cls.__name__,
        ).context
        if tickers is not None:
            asset_identifiers = sorted(
                {
                    identifier
                    for batch in _batches(tickers)
                    for identifier in asset_identifiers_by_ticker(batch, repository_context=context)
                }
            )
        rows: list[dict[str, Any]] = []
        if asset_uids is not None:
            for batch in _batches(asset_uids):
                rows.extend(asset_reference_details_by_uids(batch, repository_context=context))
        else:
            for batch in _batches(asset_identifiers or []):
                rows.extend(asset_reference_details(batch, repository_context=context))
        return [AssetSnapshotReference.model_validate(row) for row in rows]

    @classmethod
    def publish(cls, snapshots: list[dict[str, Any]]) -> int:
        """Write snapshot rows (``asset_identifier``, ``time_index``, ``name``, ``ticker`` ...).

        Returns the number of rows written.
        """

        if not snapshots:
            return 0
        from msm.bootstrap import resolve_runtime
        from msm.time_index.assets import AssetSnapshot

        resolve_runtime(models=["Asset", "AssetSnapshotsStorage"], row_model_name=cls.__name__)
        error, _ = AssetSnapshot().set_snapshots([dict(row) for row in snapshots]).run()
        if error:
            raise RuntimeError("Asset snapshot publication failed.")
        return len(snapshots)


def _batches(values: list[Any]) -> list[list[Any]]:
    unique = list(dict.fromkeys(values))
    return [unique[i : i + _SNAPSHOT_READ_BATCH] for i in range(0, len(unique), _SNAPSHOT_READ_BATCH)]


__all__ = [
    "AssetSnapshotReference",
    "AssetSnapshots",
    "Asset",
    "AssetCategory",
    "AssetCategoryCreate",
    "AssetCategoryMembership",
    "AssetCategoryMembershipCreate",
    "AssetCategoryMembershipUpsert",
    "AssetCategoryUpdate",
    "AssetCategoryUpsert",
    "AssetCreate",
    "AssetType",
    "AssetTypeCreate",
    "AssetTypeUpdate",
    "AssetTypeUpsert",
    "AssetUpdate",
    "AssetUpsert",
    "BOND_ASSET_TYPE",
    "Bond",
    "BondCreate",
    "BondStatus",
    "BondUpsert",
    "CRYPTO_ASSET_TYPE",
    "CURRENCY_ASSET_TYPE",
    "CurrencySpot",
    "CurrencySpotCreate",
    "CurrencySpotUpsert",
    "CURRENCY_SPOT_ASSET_TYPE",
    "EQUITY_ASSET_TYPE",
    "OpenFigiDetails",
    "OpenFigiDetailsCreate",
    "OpenFigiDetailsUpdate",
    "OpenFigiDetailsUpsert",
    "normalize_asset_type",
]
