from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from msm.api.base import _warn_deprecated_create_schemas, operation_result_rows
from msm.repositories.crud import (
    count_model,
    create_model,
    delete_model,
    get_model_by_uid,
    search_model,
    update_model,
    upsert_model,
)

from msm_pricing.bootstrap import attach_pricing_schemas, resolve_pricing_runtime
from msm_pricing.models.curves import CurveTable
from msm_pricing.models.market_data_bindings import (
    PricingMarketDataSetBindingTable,
    PricingMarketDataSetCurveBindingTable,
    PricingMarketDataSetTable,
)
from msm_pricing.settings import PRICING_MARKET_DATA_SET_DEFAULT

PricingMarketDataSetSelector = Any


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


class PricingMarketDataSet(BaseModel):
    """Named market-data source set used by pricing workflows."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[PricingMarketDataSetTable]] = PricingMarketDataSetTable
    __required_tables__: ClassVar[list[type[Any]]] = [PricingMarketDataSetTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("set_key",)

    uid: uuid.UUID
    set_key: str
    display_name: str
    description: str | None = None
    status: str = "ACTIVE"
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )

    @classmethod
    def start_engine(cls, **kwargs: Any):
        requested_models = kwargs.pop("models", None)
        models = [*cls.__required_tables__, *(requested_models or [])]
        return attach_pricing_schemas(models=models, **kwargs)

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        _warn_deprecated_create_schemas(cls.__name__)
        return cls.start_engine(**kwargs)

    @classmethod
    def create(
        cls,
        payload: PricingMarketDataSetCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataSet:
        values = _validate_payload(PricingMarketDataSetCreate, payload, kwargs).model_dump()
        result = create_model(cls._active_context(), model=cls.__table__, values=values)
        return cls._from_operation_result(result)

    @classmethod
    def upsert(
        cls,
        payload: PricingMarketDataSetUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataSet:
        values = _validate_payload(PricingMarketDataSetUpsert, payload, kwargs).model_dump()
        result = upsert_model(
            cls._active_context(),
            model=cls.__table__,
            values=values,
            conflict_columns=cls.__upsert_keys__,
        )
        return cls._from_operation_result(result)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: PricingMarketDataSetUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataSet:
        values = _validate_payload(PricingMarketDataSetUpdate, payload, kwargs).model_dump(
            exclude_unset=True,
        )
        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=uid,
            values=values,
        )
        return cls._from_operation_result(result)

    @classmethod
    def delete(cls, uid: uuid.UUID | str) -> dict[str, Any]:
        return delete_model(cls._active_context(), model=cls.__table__, uid=uid)

    @classmethod
    def get_by_uid(cls, uid: uuid.UUID | str) -> PricingMarketDataSet | None:
        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=uid)
        return cls._from_operation_result(result, required=False)

    @classmethod
    def get_by_key(cls, set_key: str) -> PricingMarketDataSet | None:
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={"set_key": _normalize_set_key(set_key)},
            limit=1,
        )
        return cls._from_operation_result(result, required=False)

    @classmethod
    def filter(cls, *, limit: int = 500, **filters: Any) -> list[PricingMarketDataSet]:
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={key: value for key, value in filters.items() if value is not None},
            limit=limit,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def list(
        cls,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> dict[str, Any]:
        limit, offset = _validate_pagination(limit=limit, offset=offset)
        exact_filters = {key: value for key, value in filters.items() if value is not None}
        context = cls._active_context()
        count_result = count_model(context, model=cls.__table__, filters=exact_filters)
        result = search_model(
            context,
            model=cls.__table__,
            filters=exact_filters,
            limit=limit,
            offset=offset,
        )
        return {
            "count": _count_from_operation_result(count_result),
            "limit": limit,
            "offset": offset,
            "results": [cls.model_validate(row) for row in operation_result_rows(result)],
        }

    @classmethod
    def resolve_uid(cls, market_data_set: PricingMarketDataSetSelector = None) -> uuid.UUID:
        if market_data_set is None:
            market_data_set = PRICING_MARKET_DATA_SET_DEFAULT
        if isinstance(market_data_set, PricingMarketDataSet):
            return market_data_set.uid
        try:
            return _coerce_uuid(market_data_set)
        except (TypeError, ValueError):
            set_key = _normalize_set_key(str(market_data_set))
            row = cls.get_by_key(set_key)
            if row is None:
                raise LookupError(f"No pricing market-data set found for set_key={set_key!r}.")
            return row.uid

    @classmethod
    def _active_context(cls):
        runtime = resolve_pricing_runtime(
            models=cls.__required_tables__,
            row_model_name=cls.__name__,
        )
        return runtime.context

    @classmethod
    def _from_operation_result(
        cls,
        result: Mapping[str, Any],
        *,
        required: bool = True,
    ) -> PricingMarketDataSet | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError(
                "MetaTable operation result did not include a PricingMarketDataSet row."
            )
        return None


class PricingMarketDataSetBinding(BaseModel):
    """Binding from a pricing market-data set and concept to a storage table UID."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[PricingMarketDataSetBindingTable]] = PricingMarketDataSetBindingTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        PricingMarketDataSetTable,
        PricingMarketDataSetBindingTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("market_data_set_uid", "concept_key")

    uid: uuid.UUID
    market_data_set_uid: uuid.UUID
    concept_key: str
    data_node_uid: uuid.UUID
    storage_table_identifier: str | None = None
    source: str | None = None
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )

    @classmethod
    def start_engine(cls, **kwargs: Any):
        requested_models = kwargs.pop("models", None)
        models = [*cls.__required_tables__, *(requested_models or [])]
        return attach_pricing_schemas(models=models, **kwargs)

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        _warn_deprecated_create_schemas(cls.__name__)
        return cls.start_engine(**kwargs)

    @classmethod
    def create(
        cls,
        payload: PricingMarketDataSetBindingCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataSetBinding:
        values = _validate_payload(PricingMarketDataSetBindingCreate, payload, kwargs).model_dump()
        result = create_model(cls._active_context(), model=cls.__table__, values=values)
        return cls._from_operation_result(result)

    @classmethod
    def upsert(
        cls,
        payload: PricingMarketDataSetBindingUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataSetBinding:
        values = _validate_payload(PricingMarketDataSetBindingUpsert, payload, kwargs).model_dump()
        result = upsert_model(
            cls._active_context(),
            model=cls.__table__,
            values=values,
            conflict_columns=cls.__upsert_keys__,
        )
        return cls._from_operation_result(result)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: PricingMarketDataSetBindingUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataSetBinding:
        values = _validate_payload(PricingMarketDataSetBindingUpdate, payload, kwargs).model_dump(
            exclude_unset=True,
        )
        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=uid,
            values=values,
        )
        return cls._from_operation_result(result)

    @classmethod
    def delete(cls, uid: uuid.UUID | str) -> dict[str, Any]:
        return delete_model(cls._active_context(), model=cls.__table__, uid=uid)

    @classmethod
    def get_by_uid(cls, uid: uuid.UUID | str) -> PricingMarketDataSetBinding | None:
        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=uid)
        return cls._from_operation_result(result, required=False)

    @classmethod
    def get_by_set_and_concept(
        cls,
        *,
        market_data_set_uid: uuid.UUID | str,
        concept_key: str,
    ) -> PricingMarketDataSetBinding | None:
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={
                "market_data_set_uid": _coerce_uuid(market_data_set_uid),
                "concept_key": _normalize_concept_key(concept_key),
            },
            limit=1,
        )
        return cls._from_operation_result(result, required=False)

    @classmethod
    def filter_for_set_and_concepts(
        cls,
        *,
        market_data_set_uid: uuid.UUID | str,
        concept_keys: list[str] | tuple[str, ...] | set[str],
    ) -> list[PricingMarketDataSetBinding]:
        normalized_concept_keys = list(
            dict.fromkeys(_normalize_concept_key(value) for value in concept_keys)
        )
        if not normalized_concept_keys:
            return []
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={"market_data_set_uid": _coerce_uuid(market_data_set_uid)},
            in_filters={"concept_key": normalized_concept_keys},
            limit=len(normalized_concept_keys),
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def resolve_data_node_uid(
        cls,
        *,
        market_data_set: PricingMarketDataSetSelector = None,
        concept_key: str,
    ) -> uuid.UUID:
        market_data_set_uid = PricingMarketDataSet.resolve_uid(market_data_set)
        binding = cls.get_by_set_and_concept(
            market_data_set_uid=market_data_set_uid,
            concept_key=concept_key,
        )
        if binding is None:
            raise LookupError(
                "No pricing market-data binding found for "
                f"market_data_set_uid={market_data_set_uid}, concept_key={concept_key!r}."
            )
        return binding.data_node_uid

    @classmethod
    def filter(cls, *, limit: int = 500, **filters: Any) -> list[PricingMarketDataSetBinding]:
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={key: value for key, value in filters.items() if value is not None},
            limit=limit,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def list(
        cls,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> dict[str, Any]:
        limit, offset = _validate_pagination(limit=limit, offset=offset)
        exact_filters = {key: value for key, value in filters.items() if value is not None}
        context = cls._active_context()
        count_result = count_model(context, model=cls.__table__, filters=exact_filters)
        result = search_model(
            context,
            model=cls.__table__,
            filters=exact_filters,
            limit=limit,
            offset=offset,
        )
        return {
            "count": _count_from_operation_result(count_result),
            "limit": limit,
            "offset": offset,
            "results": [cls.model_validate(row) for row in operation_result_rows(result)],
        }

    @classmethod
    def _active_context(cls):
        runtime = resolve_pricing_runtime(
            models=cls.__required_tables__,
            row_model_name=cls.__name__,
        )
        return runtime.context

    @classmethod
    def _from_operation_result(
        cls,
        result: Mapping[str, Any],
        *,
        required: bool = True,
    ) -> PricingMarketDataSetBinding | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError(
                "MetaTable operation result did not include a PricingMarketDataSetBinding row."
            )
        return None


class PricingMarketDataSetCurveBinding(BaseModel):
    """Binding from a pricing market-data set valuation role to a curve identity."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[PricingMarketDataSetCurveBindingTable]] = (
        PricingMarketDataSetCurveBindingTable
    )
    __required_tables__: ClassVar[list[type[Any]]] = [
        PricingMarketDataSetTable,
        CurveTable,
        PricingMarketDataSetCurveBindingTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("market_data_set_uid", "binding_key")

    uid: uuid.UUID
    market_data_set_uid: uuid.UUID
    binding_key: str
    role_key: str
    selector_type: str
    selector_key: str
    quote_side: str | None = None
    curve_uid: uuid.UUID
    source: str | None = None
    priority: int = 0
    status: str = "ACTIVE"
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )

    @classmethod
    def start_engine(cls, **kwargs: Any):
        requested_models = kwargs.pop("models", None)
        models = [*cls.__required_tables__, *(requested_models or [])]
        return attach_pricing_schemas(models=models, **kwargs)

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        _warn_deprecated_create_schemas(cls.__name__)
        return cls.start_engine(**kwargs)

    @classmethod
    def create(
        cls,
        payload: PricingMarketDataSetCurveBindingCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataSetCurveBinding:
        payload_row = _validate_payload(PricingMarketDataSetCurveBindingCreate, payload, kwargs)
        values = _curve_binding_values(payload_row.model_dump())
        result = create_model(cls._active_context(), model=cls.__table__, values=values)
        return cls._from_operation_result(result)

    @classmethod
    def upsert(
        cls,
        payload: PricingMarketDataSetCurveBindingUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataSetCurveBinding:
        payload_row = _validate_payload(PricingMarketDataSetCurveBindingUpsert, payload, kwargs)
        values = _curve_binding_values(payload_row.model_dump())
        result = upsert_model(
            cls._active_context(),
            model=cls.__table__,
            values=values,
            conflict_columns=cls.__upsert_keys__,
        )
        return cls._from_operation_result(result)

    @classmethod
    def create_index_curve_selection(
        cls,
        payload: IndexCurveSelectionCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexCurveSelection:
        """Create an index-scoped curve selection without exposing selector plumbing."""

        selection = _validate_payload(IndexCurveSelectionCreate, payload, kwargs)
        binding = cls.create(_index_curve_selection_values(selection))
        return IndexCurveSelection.from_curve_binding(binding)

    @classmethod
    def upsert_index_curve_selection(
        cls,
        payload: IndexCurveSelectionUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexCurveSelection:
        """Upsert an index-scoped curve selection without exposing selector plumbing."""

        selection = _validate_payload(IndexCurveSelectionUpsert, payload, kwargs)
        binding = cls.upsert(_index_curve_selection_values(selection))
        return IndexCurveSelection.from_curve_binding(binding)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: PricingMarketDataSetCurveBindingUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataSetCurveBinding:
        values = _validate_payload(
            PricingMarketDataSetCurveBindingUpdate,
            payload,
            kwargs,
        ).model_dump(exclude_unset=True)
        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=uid,
            values=values,
        )
        return cls._from_operation_result(result)

    @classmethod
    def delete(cls, uid: uuid.UUID | str) -> dict[str, Any]:
        return delete_model(cls._active_context(), model=cls.__table__, uid=uid)

    @classmethod
    def get_by_uid(cls, uid: uuid.UUID | str) -> PricingMarketDataSetCurveBinding | None:
        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=uid)
        return cls._from_operation_result(result, required=False)

    @classmethod
    def get_by_set_and_binding_key(
        cls,
        *,
        market_data_set_uid: uuid.UUID | str,
        binding_key: str,
        status: str | None = "ACTIVE",
    ) -> PricingMarketDataSetCurveBinding | None:
        filters: dict[str, Any] = {
            "market_data_set_uid": _coerce_uuid(market_data_set_uid),
            "binding_key": _normalize_binding_key(binding_key),
        }
        if status is not None:
            filters["status"] = status
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters=filters,
            limit=2,
        )
        rows = [cls.model_validate(row) for row in operation_result_rows(result)]
        if len(rows) > 1:
            raise ValueError(
                "Multiple pricing market-data curve bindings found for "
                f"market_data_set_uid={market_data_set_uid}, binding_key={binding_key!r}."
            )
        return rows[0] if rows else None

    @classmethod
    def filter_by_binding_keys(
        cls,
        *,
        market_data_set_uid: uuid.UUID | str,
        binding_keys: list[str] | tuple[str, ...] | set[str],
        status: str | None = "ACTIVE",
    ) -> list[PricingMarketDataSetCurveBinding]:
        normalized_binding_keys = list(
            dict.fromkeys(_normalize_binding_key(value) for value in binding_keys)
        )
        if not normalized_binding_keys:
            return []

        filters: dict[str, Any] = {
            "market_data_set_uid": _coerce_uuid(market_data_set_uid),
        }
        if status is not None:
            filters["status"] = status
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters=filters,
            in_filters={"binding_key": normalized_binding_keys},
            limit=len(normalized_binding_keys) * 2,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def get_by_role_selector(
        cls,
        *,
        market_data_set_uid: uuid.UUID | str,
        role_key: str,
        selector_type: str,
        selector_key: str,
        quote_side: str | None = None,
        status: str | None = "ACTIVE",
    ) -> PricingMarketDataSetCurveBinding | None:
        binding_key = curve_binding_key(
            role_key=role_key,
            selector_type=selector_type,
            selector_key=selector_key,
            quote_side=quote_side,
        )
        return cls.get_by_set_and_binding_key(
            market_data_set_uid=market_data_set_uid,
            binding_key=binding_key,
            status=status,
        )

    @classmethod
    def get_index_curve_selection(
        cls,
        *,
        market_data_set: PricingMarketDataSetSelector = None,
        market_data_set_uid: uuid.UUID | str | None = None,
        role_key: str,
        index_uid: uuid.UUID | str,
        quote_side: str | None = None,
        status: str | None = "ACTIVE",
    ) -> IndexCurveSelection | None:
        """Return one index-scoped curve selection for a market-data set and role."""

        resolved_market_data_set_uid = _resolve_market_data_set_uid(
            market_data_set=market_data_set,
            market_data_set_uid=market_data_set_uid,
        )
        binding = cls.get_by_role_selector(
            market_data_set_uid=resolved_market_data_set_uid,
            role_key=role_key,
            selector_type="index",
            selector_key=str(_coerce_uuid(index_uid)),
            quote_side=quote_side,
            status=status,
        )
        if binding is None:
            return None
        return IndexCurveSelection.from_curve_binding(binding)

    @classmethod
    def resolve_curve_uid(
        cls,
        *,
        market_data_set: PricingMarketDataSetSelector = None,
        role_key: str,
        selector_type: str,
        selector_key: str,
        quote_side: str | None = None,
    ) -> uuid.UUID:
        market_data_set_uid = PricingMarketDataSet.resolve_uid(market_data_set)
        binding = cls.get_by_role_selector(
            market_data_set_uid=market_data_set_uid,
            role_key=role_key,
            selector_type=selector_type,
            selector_key=selector_key,
            quote_side=quote_side,
            status="ACTIVE",
        )
        if binding is None:
            raise LookupError(
                "No pricing market-data curve binding found for "
                f"market_data_set_uid={market_data_set_uid}, role_key={role_key!r}, "
                f"selector_type={selector_type!r}, selector_key={selector_key!r}, "
                f"quote_side={quote_side!r}."
            )
        return binding.curve_uid

    @classmethod
    def resolve_index_curve_uid(
        cls,
        *,
        market_data_set: PricingMarketDataSetSelector = None,
        market_data_set_uid: uuid.UUID | str | None = None,
        role_key: str,
        index_uid: uuid.UUID | str,
        quote_side: str | None = None,
    ) -> uuid.UUID:
        """Resolve an index-scoped curve selection to the selected CurveTable.uid."""

        selection = cls.get_index_curve_selection(
            market_data_set=market_data_set,
            market_data_set_uid=market_data_set_uid,
            role_key=role_key,
            index_uid=index_uid,
            quote_side=quote_side,
            status="ACTIVE",
        )
        if selection is None:
            resolved_market_data_set_uid = _resolve_market_data_set_uid(
                market_data_set=market_data_set,
                market_data_set_uid=market_data_set_uid,
            )
            resolved_index_uid = _coerce_uuid(index_uid)
            raise LookupError(
                "No pricing market-data index curve selection found for "
                f"market_data_set_uid={resolved_market_data_set_uid}, "
                f"role_key={role_key!r}, index_uid={resolved_index_uid}, "
                f"quote_side={quote_side!r}."
            )
        return selection.curve_uid

    @classmethod
    def filter(cls, *, limit: int = 500, **filters: Any) -> list[PricingMarketDataSetCurveBinding]:
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={key: value for key, value in filters.items() if value is not None},
            limit=limit,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def filter_index_curve_selections(
        cls,
        *,
        limit: int = 500,
        market_data_set: PricingMarketDataSetSelector = None,
        market_data_set_uid: uuid.UUID | str | None = None,
        role_key: str | None = None,
        index_uid: uuid.UUID | str | None = None,
        quote_side: str | None = None,
        status: str | None = "ACTIVE",
    ) -> list[IndexCurveSelection]:
        """Filter index-scoped curve selections without exposing selector fields."""

        filters = _index_curve_selection_filters(
            market_data_set=market_data_set,
            market_data_set_uid=market_data_set_uid,
            role_key=role_key,
            index_uid=index_uid,
            quote_side=quote_side,
            status=status,
        )
        return [
            IndexCurveSelection.from_curve_binding(binding)
            for binding in cls.filter(limit=limit, **filters)
        ]

    @classmethod
    def filter_for_curve(
        cls,
        *,
        curve_uid: uuid.UUID | str,
        limit: int = 500,
        status: str | None = None,
    ) -> list[PricingMarketDataSetCurveBinding]:
        """Return curve-selection bindings that point at one CurveTable row."""

        filters: dict[str, Any] = {"curve_uid": _coerce_uuid(curve_uid)}
        if status is not None:
            filters["status"] = status
        return cls.filter(limit=limit, **filters)

    @classmethod
    def count_for_curve(
        cls,
        *,
        curve_uid: uuid.UUID | str,
        status: str | None = None,
    ) -> int:
        """Count curve-selection bindings that point at one CurveTable row."""

        filters: dict[str, Any] = {"curve_uid": _coerce_uuid(curve_uid)}
        if status is not None:
            filters["status"] = status
        result = count_model(cls._active_context(), model=cls.__table__, filters=filters)
        return _count_from_operation_result(result)

    @classmethod
    def count_index_selector_references(
        cls,
        *,
        index_uid: uuid.UUID | str,
        status: str | None = None,
    ) -> int:
        """Count curve-selection bindings that use an index as selector."""

        filters: dict[str, Any] = {
            "selector_type": "index",
            "selector_key": str(_coerce_uuid(index_uid)),
        }
        if status is not None:
            filters["status"] = status
        result = count_model(cls._active_context(), model=cls.__table__, filters=filters)
        return _count_from_operation_result(result)

    @classmethod
    def list(
        cls,
        *,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> dict[str, Any]:
        limit, offset = _validate_pagination(limit=limit, offset=offset)
        exact_filters = {key: value for key, value in filters.items() if value is not None}
        context = cls._active_context()
        count_result = count_model(context, model=cls.__table__, filters=exact_filters)
        result = search_model(
            context,
            model=cls.__table__,
            filters=exact_filters,
            limit=limit,
            offset=offset,
        )
        return {
            "count": _count_from_operation_result(count_result),
            "limit": limit,
            "offset": offset,
            "results": [cls.model_validate(row) for row in operation_result_rows(result)],
        }

    @classmethod
    def list_index_curve_selections(
        cls,
        *,
        limit: int = 50,
        offset: int = 0,
        market_data_set: PricingMarketDataSetSelector = None,
        market_data_set_uid: uuid.UUID | str | None = None,
        role_key: str | None = None,
        index_uid: uuid.UUID | str | None = None,
        quote_side: str | None = None,
        status: str | None = "ACTIVE",
    ) -> dict[str, Any]:
        """List index-scoped curve selections in the standard pagination envelope."""

        filters = _index_curve_selection_filters(
            market_data_set=market_data_set,
            market_data_set_uid=market_data_set_uid,
            role_key=role_key,
            index_uid=index_uid,
            quote_side=quote_side,
            status=status,
        )
        response = cls.list(limit=limit, offset=offset, **filters)
        return {
            **response,
            "results": [
                IndexCurveSelection.from_curve_binding(binding) for binding in response["results"]
            ],
        }

    @classmethod
    def _active_context(cls):
        runtime = resolve_pricing_runtime(
            models=cls.__required_tables__,
            row_model_name=cls.__name__,
        )
        return runtime.context

    @classmethod
    def _from_operation_result(
        cls,
        result: Mapping[str, Any],
        *,
        required: bool = True,
    ) -> PricingMarketDataSetCurveBinding | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError(
                "MetaTable operation result did not include a PricingMarketDataSetCurveBinding row."
            )
        return None


class PricingMarketDataSetCreate(BaseModel):
    """Payload for creating one pricing market-data set."""

    model_config = ConfigDict(extra="forbid")

    set_key: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: str = Field(default="ACTIVE", min_length=1, max_length=32)
    metadata_json: dict[str, Any] | None = None


class PricingMarketDataSetUpsert(PricingMarketDataSetCreate):
    """Payload for inserting or replacing a market-data set by set_key."""


class PricingMarketDataSetUpdate(BaseModel):
    """Payload for updating mutable market-data set fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, min_length=1, max_length=32)
    metadata_json: dict[str, Any] | None = None


class PricingMarketDataSetBindingCreate(BaseModel):
    """Payload for creating one pricing market-data set binding."""

    model_config = ConfigDict(extra="forbid")

    market_data_set_uid: uuid.UUID
    concept_key: str = Field(min_length=1, max_length=128)
    data_node_uid: uuid.UUID
    storage_table_identifier: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class PricingMarketDataSetBindingUpsert(PricingMarketDataSetBindingCreate):
    """Payload for inserting or replacing a binding by market-data set and concept."""


class PricingMarketDataSetBindingUpdate(BaseModel):
    """Payload for updating mutable market-data set binding fields."""

    model_config = ConfigDict(extra="forbid")

    data_node_uid: uuid.UUID | None = None
    storage_table_identifier: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class PricingMarketDataSetCurveBindingCreate(BaseModel):
    """Payload for creating one market-data-set curve binding."""

    model_config = ConfigDict(extra="forbid")

    market_data_set_uid: uuid.UUID
    binding_key: str | None = Field(default=None, min_length=1, max_length=255)
    role_key: str = Field(min_length=1, max_length=64)
    selector_type: str = Field(min_length=1, max_length=64)
    selector_key: str = Field(min_length=1, max_length=255)
    quote_side: str | None = Field(default=None, max_length=32)
    curve_uid: uuid.UUID
    source: str | None = Field(default=None, max_length=255)
    priority: int = 0
    status: str = Field(default="ACTIVE", min_length=1, max_length=32)
    metadata_json: dict[str, Any] | None = None


class PricingMarketDataSetCurveBindingUpsert(PricingMarketDataSetCurveBindingCreate):
    """Payload for inserting or replacing a curve binding by derived binding key."""


class PricingMarketDataSetCurveBindingUpdate(BaseModel):
    """Payload for updating mutable market-data-set curve binding fields."""

    model_config = ConfigDict(extra="forbid")

    quote_side: str | None = Field(default=None, max_length=32)
    curve_uid: uuid.UUID | None = None
    source: str | None = Field(default=None, max_length=255)
    priority: int | None = None
    status: str | None = Field(default=None, min_length=1, max_length=32)
    metadata_json: dict[str, Any] | None = None


class IndexCurveSelection(BaseModel):
    """User-facing view of an index-scoped market-data curve selection."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    uid: uuid.UUID
    market_data_set_uid: uuid.UUID
    role_key: str
    index_uid: uuid.UUID
    quote_side: str | None = None
    curve_uid: uuid.UUID
    source: str | None = None
    priority: int = 0
    status: str = "ACTIVE"
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def from_curve_binding(
        cls,
        binding: PricingMarketDataSetCurveBinding,
    ) -> IndexCurveSelection:
        selector_type = _normalize_curve_binding_part(
            binding.selector_type,
            field_name="selector_type",
        ).lower()
        if selector_type != "index":
            raise ValueError(
                "IndexCurveSelection can only be built from selector_type='index' "
                f"bindings, not selector_type={binding.selector_type!r}."
            )
        return cls(
            uid=binding.uid,
            market_data_set_uid=binding.market_data_set_uid,
            role_key=binding.role_key,
            index_uid=_coerce_uuid(binding.selector_key),
            quote_side=binding.quote_side,
            curve_uid=binding.curve_uid,
            source=binding.source,
            priority=binding.priority,
            status=binding.status,
            metadata_json=binding.metadata_json,
        )


class IndexCurveSelectionCreate(BaseModel):
    """Payload for selecting a curve by market-data set, role, index, and quote side."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    market_data_set: PricingMarketDataSetSelector = None
    market_data_set_uid: uuid.UUID | None = None
    role_key: str = Field(min_length=1, max_length=64)
    index_uid: uuid.UUID
    quote_side: str | None = Field(default=None, max_length=32)
    curve_uid: uuid.UUID
    source: str | None = Field(default=None, max_length=255)
    priority: int = 0
    status: str = Field(default="ACTIVE", min_length=1, max_length=32)
    metadata_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_market_data_set_selector(self) -> IndexCurveSelectionCreate:
        if self.market_data_set is not None and self.market_data_set_uid is not None:
            raise ValueError("Pass either market_data_set or market_data_set_uid, not both.")
        return self


class IndexCurveSelectionUpsert(IndexCurveSelectionCreate):
    """Payload for inserting or replacing an index curve selection."""


def _normalize_set_key(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("market-data set key cannot be empty.")
    return normalized


def _normalize_concept_key(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("concept_key cannot be empty.")
    return normalized


def curve_binding_key(
    *,
    role_key: str,
    selector_type: str,
    selector_key: str,
    quote_side: str | None = None,
) -> str:
    role = _normalize_curve_binding_part(role_key, field_name="role_key").lower()
    selector = _normalize_curve_binding_part(
        selector_type,
        field_name="selector_type",
    ).lower()
    key = _normalize_curve_binding_part(selector_key, field_name="selector_key")
    if selector == "currency":
        key = key.upper()
    side = "default" if quote_side in (None, "") else _normalize_quote_side(quote_side)
    return f"{role}:{selector}:{key}:{side}"


def _curve_binding_values(values: dict[str, Any]) -> dict[str, Any]:
    if not values.get("binding_key"):
        values["binding_key"] = curve_binding_key(
            role_key=values["role_key"],
            selector_type=values["selector_type"],
            selector_key=values["selector_key"],
            quote_side=values.get("quote_side"),
        )
    else:
        values["binding_key"] = _normalize_binding_key(values["binding_key"])
    values["role_key"] = _normalize_curve_binding_part(
        values["role_key"],
        field_name="role_key",
    ).lower()
    values["selector_type"] = _normalize_curve_binding_part(
        values["selector_type"],
        field_name="selector_type",
    ).lower()
    values["selector_key"] = _normalize_curve_binding_part(
        values["selector_key"],
        field_name="selector_key",
    )
    if values["selector_type"] == "currency":
        values["selector_key"] = values["selector_key"].upper()
    if values.get("quote_side") not in (None, ""):
        values["quote_side"] = _normalize_quote_side(values["quote_side"])
    else:
        values["quote_side"] = None
    return values


def _normalize_binding_key(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("binding_key cannot be empty.")
    return normalized


def _normalize_quote_side(value: str) -> str:
    return _normalize_curve_binding_part(value, field_name="quote_side").lower()


def _normalize_curve_binding_part(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty.")
    return normalized


def _resolve_market_data_set_uid(
    *,
    market_data_set: PricingMarketDataSetSelector = None,
    market_data_set_uid: uuid.UUID | str | None = None,
) -> uuid.UUID:
    if market_data_set is not None and market_data_set_uid is not None:
        raise ValueError("Pass either market_data_set or market_data_set_uid, not both.")
    if market_data_set_uid is not None:
        return _coerce_uuid(market_data_set_uid)
    return PricingMarketDataSet.resolve_uid(market_data_set)


def _optional_market_data_set_uid(
    *,
    market_data_set: PricingMarketDataSetSelector = None,
    market_data_set_uid: uuid.UUID | str | None = None,
) -> uuid.UUID | None:
    if market_data_set is not None and market_data_set_uid is not None:
        raise ValueError("Pass either market_data_set or market_data_set_uid, not both.")
    if market_data_set_uid is not None:
        return _coerce_uuid(market_data_set_uid)
    if market_data_set is not None:
        return PricingMarketDataSet.resolve_uid(market_data_set)
    return None


def _index_curve_selection_values(selection: BaseModel) -> dict[str, Any]:
    market_data_set_uid = _resolve_market_data_set_uid(
        market_data_set=getattr(selection, "market_data_set"),
        market_data_set_uid=getattr(selection, "market_data_set_uid"),
    )
    return {
        "market_data_set_uid": market_data_set_uid,
        "role_key": selection.role_key,
        "selector_type": "index",
        "selector_key": str(_coerce_uuid(selection.index_uid)),
        "quote_side": selection.quote_side,
        "curve_uid": selection.curve_uid,
        "source": selection.source,
        "priority": selection.priority,
        "status": selection.status,
        "metadata_json": selection.metadata_json,
    }


def _index_curve_selection_filters(
    *,
    market_data_set: PricingMarketDataSetSelector = None,
    market_data_set_uid: uuid.UUID | str | None = None,
    role_key: str | None = None,
    index_uid: uuid.UUID | str | None = None,
    quote_side: str | None = None,
    status: str | None = "ACTIVE",
) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "market_data_set_uid": _optional_market_data_set_uid(
            market_data_set=market_data_set,
            market_data_set_uid=market_data_set_uid,
        ),
        "selector_type": "index",
        "status": status,
    }
    if role_key is not None:
        filters["role_key"] = _normalize_curve_binding_part(
            role_key,
            field_name="role_key",
        ).lower()
    if index_uid is not None:
        filters["selector_key"] = str(_coerce_uuid(index_uid))
    if quote_side is not None:
        filters["quote_side"] = _normalize_quote_side(quote_side)
    return filters


def _validate_pagination(*, limit: int, offset: int) -> tuple[int, int]:
    if limit < 0:
        raise ValueError("limit must be greater than or equal to 0.")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0.")
    return limit, offset


def _count_from_operation_result(result: Mapping[str, Any] | list[Any] | None) -> int:
    rows = operation_result_rows(result)
    if not rows:
        return 0
    return int(rows[0].get("count") or 0)


def _coerce_uuid(value: uuid.UUID | str | Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if value in (None, ""):
        raise ValueError("UUID value cannot be empty.")
    return uuid.UUID(str(value))


__all__ = [
    "curve_binding_key",
    "IndexCurveSelection",
    "IndexCurveSelectionCreate",
    "IndexCurveSelectionUpsert",
    "PricingMarketDataSet",
    "PricingMarketDataSetBinding",
    "PricingMarketDataSetBindingCreate",
    "PricingMarketDataSetBindingUpdate",
    "PricingMarketDataSetBindingUpsert",
    "PricingMarketDataSetCurveBinding",
    "PricingMarketDataSetCurveBindingCreate",
    "PricingMarketDataSetCurveBindingUpdate",
    "PricingMarketDataSetCurveBindingUpsert",
    "PricingMarketDataSetCreate",
    "PricingMarketDataSetSelector",
    "PricingMarketDataSetUpdate",
    "PricingMarketDataSetUpsert",
]
