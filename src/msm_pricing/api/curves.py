from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from msm.api.base import _warn_deprecated_create_schemas, operation_result_rows
from msm.repositories.crud import (
    count_model,
    create_model,
    delete_model,
    get_model_by_uid,
    get_model_by_unique_identifier,
    search_model,
    update_model,
    upsert_model,
)

from msm_pricing.bootstrap import attach_pricing_schemas, resolve_pricing_runtime
from msm_pricing.data_nodes.curves.storage import CURVE_IDENTIFIER_DIMENSION
from msm_pricing.models.curves import CurveTable
from msm_pricing.settings import PRICING_CONCEPT_DISCOUNT_CURVES


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


class Curve(BaseModel):
    """Pricing-owned curve identity row used by curve DataNodes and runtime resolution."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[CurveTable]] = CurveTable
    __required_tables__: ClassVar[list[type[Any]]] = [CurveTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    uid: uuid.UUID
    unique_identifier: str
    display_name: str
    curve_type: str
    currency_code: str | None = None
    quote_side: str | None = None
    interpolation_method: str | None = None
    compounding: str | None = None
    source: str | None = None
    status: str = "ACTIVE"
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )

    @classmethod
    def start_engine(cls, **kwargs: Any):
        """Attach the pricing runtime tables required by this row API."""

        requested_models = kwargs.pop("models", None)
        models = [*cls.__required_tables__, *(requested_models or [])]
        return attach_pricing_schemas(models=models, **kwargs)

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        """Deprecated compatibility alias for :meth:`start_engine`."""

        _warn_deprecated_create_schemas(cls.__name__)
        return cls.start_engine(**kwargs)

    @classmethod
    def create(
        cls,
        payload: CurveCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Curve:
        values = _validate_payload(CurveCreate, payload, kwargs).model_dump()
        result = create_model(cls._active_context(), model=cls.__table__, values=values)
        return cls._from_operation_result(result)

    @classmethod
    def upsert(
        cls,
        payload: CurveUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Curve:
        values = _validate_payload(CurveUpsert, payload, kwargs).model_dump()
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
        payload: CurveUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Curve:
        values = _validate_payload(CurveUpdate, payload, kwargs).model_dump(
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
    def get_delete_impact(
        cls,
        *,
        uid: uuid.UUID | str,
        delete_values: bool = False,
        delete_curve_selections: bool = False,
    ) -> dict[str, Any] | None:
        curve = cls.get_by_uid(uid)
        if curve is None:
            return None

        context = _active_curve_delete_context()
        relationships = _curve_delete_relationships(
            context=context,
            curve=curve,
            delete_values=delete_values,
            delete_curve_selections=delete_curve_selections,
        )
        blocking_count = sum(item["count"] for item in relationships if item["blocks_delete"])
        affected_count = sum(item["count"] for item in relationships)

        return {
            "resource_type": "pricing_curve",
            "uid": curve.uid,
            "identifier": curve.unique_identifier,
            "display_name": curve.display_name,
            "can_delete": blocking_count == 0,
            "blocking_count": blocking_count,
            "affected_count": affected_count,
            "delete_endpoint": f"/api/v1/pricing/curves/{curve.uid}/",
            "relationships": relationships,
            "warnings": _curve_delete_warnings(
                relationships=relationships,
                delete_values=delete_values,
                delete_curve_selections=delete_curve_selections,
            ),
        }

    @classmethod
    def delete(
        cls,
        uid: uuid.UUID | str,
        *,
        delete_values: bool = False,
        delete_curve_selections: bool = False,
    ) -> dict[str, Any] | None:
        curve = cls.get_by_uid(uid)
        if curve is None:
            return None

        impact = cls.get_delete_impact(
            uid=curve.uid,
            delete_values=delete_values,
            delete_curve_selections=delete_curve_selections,
        )
        if impact is None:
            return None
        if not impact["can_delete"]:
            raise CurveDeleteConflictError(_format_curve_delete_blockers(impact))

        context = _active_curve_delete_context()
        storage_cleanups = (
            _delete_discount_curve_values(
                context=context,
                curve_identifier=curve.unique_identifier,
            )
            if delete_values
            else []
        )
        deleted_curve_selections_count = (
            _delete_curve_selection_rows(curve_uid=curve.uid)
            if delete_curve_selections
            else 0
        )
        try:
            result = delete_model(context, model=cls.__table__, uid=curve.uid)
        except Exception as exc:
            if _is_delete_conflict(exc):
                raise CurveDeleteConflictError(
                    "Pricing curve deletion was blocked by a database foreign-key "
                    f"reference not covered by preflight checks. Backend error: {exc}"
                ) from exc
            raise

        deleted_count = _deleted_count(result)
        if deleted_count == 0:
            raise CurveDeleteConflictError(
                "Pricing curve deletion was blocked by a concurrent state change."
            )

        return {
            "detail": "Pricing curve deleted.",
            "uid": curve.uid,
            "curve_identifier": curve.unique_identifier,
            "deleted_count": deleted_count,
            "deleted_values_count": sum(item["deleted_count"] for item in storage_cleanups),
            "deleted_curve_selections_count": deleted_curve_selections_count,
            "deleted_curve_building_details_count": _relationship_count(
                impact,
                key="curve_building_details",
            ),
            "delete_values": delete_values,
            "delete_curve_selections": delete_curve_selections,
            "storage_cleanups": storage_cleanups,
        }

    @classmethod
    def get_by_uid(cls, uid: uuid.UUID | str) -> Curve | None:
        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=uid)
        return cls._from_operation_result(result, required=False)

    @classmethod
    def filter_by_uids(
        cls,
        uids: list[uuid.UUID | str] | tuple[uuid.UUID | str, ...] | set[uuid.UUID | str],
    ) -> list[Curve]:
        resolved_uids = [_coerce_uuid(value) for value in uids]
        if not resolved_uids:
            return []
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            in_filters={"uid": resolved_uids},
            limit=len(resolved_uids),
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def get_by_unique_identifier(cls, unique_identifier: str) -> Curve | None:
        result = get_model_by_unique_identifier(
            cls._active_context(),
            model=cls.__table__,
            unique_identifier=unique_identifier,
        )
        return cls._from_operation_result(result, required=False)

    @classmethod
    def get_frontend_detail_summary(cls, uid: uuid.UUID | str) -> dict[str, Any] | None:
        row = cls.get_by_uid(uid)
        if row is None:
            return None

        row_payload = row.model_dump(mode="json")
        row_uid = str(row.uid)
        title = row.display_name or row.unique_identifier or row_uid
        curve_selection_count = cls.count_curve_selections(row.uid)
        curve_selections_url = f"/api/v1/pricing/curves/{row_uid}/curve-selections/"

        badges: list[dict[str, Any]] = [
            {
                "key": "curve_type",
                "label": row.curve_type,
                "tone": "info",
            }
        ]
        if row.currency_code not in (None, ""):
            badges.append(
                {
                    "key": "currency_code",
                    "label": str(row.currency_code),
                    "tone": "neutral",
                }
            )
        if row.quote_side not in (None, ""):
            badges.append(
                {
                    "key": "quote_side",
                    "label": str(row.quote_side),
                    "tone": "neutral",
                }
            )
        if row.source not in (None, ""):
            badges.append(
                {
                    "key": "source",
                    "label": str(row.source),
                    "tone": "neutral",
                }
            )

        highlight_fields: list[dict[str, Any]] = [
            {
                "key": "display_name",
                "label": "Display Name",
                "value": row.display_name,
                "kind": "text",
                "icon": "database",
            },
            {
                "key": "curve_type",
                "label": "Curve Type",
                "value": row.curve_type,
                "kind": "code",
                "icon": "line-chart",
            },
        ]
        if row.currency_code not in (None, ""):
            highlight_fields.append(
                {
                    "key": "currency_code",
                    "label": "Currency",
                    "value": row.currency_code,
                    "kind": "code",
                    "icon": "circle-dollar-sign",
                }
            )
        if row.interpolation_method not in (None, ""):
            highlight_fields.append(
                {
                    "key": "interpolation_method",
                    "label": "Interpolation",
                    "value": row.interpolation_method,
                    "kind": "code",
                    "icon": "activity",
                }
            )
        if row.compounding not in (None, ""):
            highlight_fields.append(
                {
                    "key": "compounding",
                    "label": "Compounding",
                    "value": row.compounding,
                    "kind": "code",
                    "icon": "activity",
                }
            )

        summary = {
            "entity": {
                "id": row_uid,
                "type": "pricing_curve",
                "title": title,
            },
            "badges": badges,
            "inline_fields": [
                {
                    "key": "uid",
                    "label": "UID",
                    "value": row_uid,
                    "kind": "code",
                },
                {
                    "key": "unique_identifier",
                    "label": "Identifier",
                    "value": row.unique_identifier,
                    "kind": "code",
                },
                {
                    "key": "curve_selection_count",
                    "label": "Curve Selections",
                    "value": curve_selection_count,
                    "kind": "number",
                    "link_url": curve_selections_url,
                },
            ],
            "highlight_fields": highlight_fields,
            "stats": [],
            "label_management": None,
            "summary_warning": None,
            "extensions": {
                "curve": row_payload,
                "curve_selection_count": curve_selection_count,
                "curve_selections_url": curve_selections_url,
                "metadata_json": row.metadata_json,
            },
        }
        return summary

    @classmethod
    def count_curve_selections(cls, uid: uuid.UUID | str) -> int:
        from msm_pricing.api.market_data_bindings import PricingMarketDataSetCurveBinding

        return PricingMarketDataSetCurveBinding.count_for_curve(curve_uid=uid)

    @classmethod
    def list_curve_selections(cls, uid: uuid.UUID | str) -> dict[str, Any] | None:
        curve = cls.get_by_uid(uid)
        if curve is None:
            return None

        from msm_pricing.api.market_data_bindings import PricingMarketDataSetCurveBinding

        bindings = PricingMarketDataSetCurveBinding.filter_for_curve(
            curve_uid=curve.uid,
            limit=5000,
        )
        related_context = _curve_selection_related_context(bindings)
        results = [
            _curve_selection_payload(binding, context=related_context) for binding in bindings
        ]
        return {
            "curve": {
                "uid": curve.uid,
                "unique_identifier": curve.unique_identifier,
                "display_name": curve.display_name,
                "curve_type": curve.curve_type,
            },
            "count": len(results),
            "results": results,
        }

    @classmethod
    def get_discount_curve_nodes(
        cls,
        *,
        uid: uuid.UUID | str,
        market_data_set: Any,
        valuation_date: dt.datetime | None = None,
    ) -> dict[str, Any] | None:
        curve = cls.get_by_uid(uid)
        if curve is None:
            return None

        from msm_pricing.api.market_data_bindings import (
            PricingMarketDataSet,
            PricingMarketDataSetBinding,
        )
        from msm_pricing.data_interface import MSDataInterface

        market_data_set_uid = PricingMarketDataSet.resolve_uid(market_data_set)
        market_data_set_row = PricingMarketDataSet.get_by_uid(market_data_set_uid)
        if market_data_set_row is None:
            raise LookupError(f"No pricing market-data set found for uid={market_data_set_uid}.")

        binding = PricingMarketDataSetBinding.get_by_set_and_concept(
            market_data_set_uid=market_data_set_uid,
            concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
        )
        if binding is None:
            raise LookupError(
                "No pricing market-data binding found for "
                f"market_data_set_uid={market_data_set_uid}, "
                f"concept_key={PRICING_CONCEPT_DISCOUNT_CURVES!r}."
            )

        interface = MSDataInterface(
            market_data_configuration={
                "data_node_uids": {
                    PRICING_CONCEPT_DISCOUNT_CURVES: binding.data_node_uid,
                }
            }
        )
        try:
            observation, effective_date = _read_discount_curve_observation(
                interface=interface,
                curve_identifier=curve.unique_identifier,
                valuation_date=valuation_date,
            )
        except LookupError as exc:
            raise LookupError(
                _missing_discount_curve_observation_message(
                    curve_identifier=curve.unique_identifier,
                    market_data_set_row=market_data_set_row,
                    binding=binding,
                    valuation_date=valuation_date,
                )
            ) from exc

        return {
            "curve_uid": curve.uid,
            "curve_identifier": curve.unique_identifier,
            "curve": curve.model_dump(mode="json"),
            "market_data_set": {
                "uid": market_data_set_row.uid,
                "set_key": market_data_set_row.set_key,
                "display_name": market_data_set_row.display_name,
            },
            "binding": {
                "uid": binding.uid,
                "concept_key": binding.concept_key,
                "data_node_uid": binding.data_node_uid,
                "storage_table_identifier": binding.storage_table_identifier,
            },
            "valuation_date": valuation_date,
            "effective_date": effective_date,
            "request_mode": "historical" if valuation_date is not None else "latest",
            "nodes": _normalize_discount_curve_nodes(observation["nodes"]),
            "key_nodes": _normalize_discount_curve_key_nodes(observation.get("key_nodes")),
            "metadata_json": _normalize_discount_curve_metadata(
                observation.get("metadata_json")
            ),
        }

    @classmethod
    def filter(cls, *, limit: int = 500, **filters: Any) -> list[Curve]:
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
        search: str | None = None,
        **filters: Any,
    ) -> dict[str, Any]:
        limit, offset = _validate_pagination(limit=limit, offset=offset)
        exact_filters = {key: value for key, value in filters.items() if value is not None}
        contains_filters = (
            {"unique_identifier": search.strip()} if search is not None and search.strip() else {}
        )
        context = cls._active_context()
        count_result = count_model(
            context,
            model=cls.__table__,
            filters=exact_filters,
            contains_filters=contains_filters,
        )
        result = search_model(
            context,
            model=cls.__table__,
            filters=exact_filters,
            contains_filters=contains_filters,
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
    ) -> Curve | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError("MetaTable operation result did not include a Curve row.")
        return None


def _curve_selection_related_context(bindings: list[Any]) -> dict[str, dict[uuid.UUID, Any]]:
    market_data_set_uids = {binding.market_data_set_uid for binding in bindings}
    index_uids: set[uuid.UUID] = set()
    for binding in bindings:
        if str(binding.selector_type).lower() != "index":
            continue
        try:
            index_uids.add(uuid.UUID(str(binding.selector_key)))
        except ValueError:
            continue

    return {
        "market_data_sets": _market_data_sets_by_uid(market_data_set_uids),
        "indexes": _indexes_by_uid(index_uids),
    }


def _market_data_sets_by_uid(uids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
    if not uids:
        return {}

    from msm_pricing.api.market_data_bindings import PricingMarketDataSet

    result = search_model(
        PricingMarketDataSet._active_context(),
        model=PricingMarketDataSet.__table__,
        in_filters={"uid": list(uids)},
        limit=len(uids),
    )
    rows: dict[uuid.UUID, Any] = {}
    for row in operation_result_rows(result):
        market_data_set = PricingMarketDataSet.model_validate(row)
        rows[market_data_set.uid] = market_data_set
    return rows


def _indexes_by_uid(uids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
    if not uids:
        return {}

    from msm.api.indices import Index

    result = search_model(
        Index._active_context(),
        model=Index.__table__,
        in_filters={"uid": list(uids)},
        limit=len(uids),
    )
    rows: dict[uuid.UUID, Any] = {}
    for row in operation_result_rows(result):
        index = Index.model_validate(row)
        rows[index.uid] = index
    return rows


def _curve_selection_payload(
    binding: Any,
    *,
    context: dict[str, dict[uuid.UUID, Any]],
) -> dict[str, Any]:
    return {
        "binding_uid": binding.uid,
        "market_data_set": _curve_selection_market_data_set_payload(
            binding,
            context=context,
        ),
        "role_key": binding.role_key,
        "quote_side": binding.quote_side,
        "selector": _curve_selection_selector_payload(binding, context=context),
        "status": binding.status,
        "source": binding.source,
    }


def _curve_selection_market_data_set_payload(
    binding: Any,
    *,
    context: dict[str, dict[uuid.UUID, Any]],
) -> dict[str, Any]:
    market_data_set = context["market_data_sets"].get(binding.market_data_set_uid)
    if market_data_set is None:
        return {
            "uid": binding.market_data_set_uid,
            "set_key": None,
            "display_name": None,
        }
    return {
        "uid": market_data_set.uid,
        "set_key": market_data_set.set_key,
        "display_name": market_data_set.display_name,
    }


def _curve_selection_selector_payload(
    binding: Any,
    *,
    context: dict[str, dict[uuid.UUID, Any]],
) -> dict[str, Any]:
    selector_type = str(binding.selector_type)
    payload: dict[str, Any] = {
        "type": selector_type,
        "selector_key": binding.selector_key,
    }
    if selector_type.lower() != "index":
        return payload

    try:
        index_uid = uuid.UUID(str(binding.selector_key))
    except ValueError:
        return payload

    payload["index_uid"] = index_uid

    index = context["indexes"].get(index_uid)
    if index is not None:
        payload["index_identifier"] = index.unique_identifier
        payload["display_name"] = index.display_name
    return payload


def _validate_pagination(*, limit: int, offset: int) -> tuple[int, int]:
    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1.")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0.")
    return limit, offset


def _count_from_operation_result(result: Mapping[str, Any] | list[Any] | None) -> int:
    rows = operation_result_rows(result or {})
    if not rows:
        return 0
    return int(rows[0].get("count") or 0)


class CurveDeleteConflictError(ValueError):
    """Raised when a curve cannot be deleted with the requested cleanup flags."""


def _active_curve_delete_context():
    from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
    from msm_pricing.models.curve_building_details import CurveBuildingDetailsTable
    from msm_pricing.models.market_data_bindings import (
        PricingMarketDataSetBindingTable,
        PricingMarketDataSetCurveBindingTable,
        PricingMarketDataSetTable,
    )

    runtime = resolve_pricing_runtime(
        models=[
            CurveTable,
            CurveBuildingDetailsTable,
            PricingMarketDataSetTable,
            PricingMarketDataSetBindingTable,
            PricingMarketDataSetCurveBindingTable,
            DiscountCurvesStorage,
        ],
        row_model_name="Curve delete",
    )
    return runtime.context


def _curve_delete_relationships(
    *,
    context: Any,
    curve: Curve,
    delete_values: bool,
    delete_curve_selections: bool,
) -> list[dict[str, Any]]:
    from msm_pricing.models.curve_building_details import CurveBuildingDetailsTable
    from msm_pricing.models.market_data_bindings import PricingMarketDataSetCurveBindingTable

    curve_building_details_count = _count_model_rows(
        context,
        model=CurveBuildingDetailsTable,
        filters={"curve_uid": curve.uid},
    )
    curve_selection_count = _count_model_rows(
        context,
        model=PricingMarketDataSetCurveBindingTable,
        filters={"curve_uid": curve.uid},
    )
    observation_count, unsupported_storage_count, storage_scope_count = (
        _discount_curve_observation_impact_counts(
            context=context,
            curve_identifier=curve.unique_identifier,
        )
    )
    observation_relationship_count = observation_count + unsupported_storage_count

    return [
        {
            "key": "curve_building_details",
            "label": "Curve building details",
            "model": "CurveBuildingDetailsTable",
            "column": "curve_uid",
            "relationship_type": "direct",
            "on_delete": "CASCADE",
            "count": curve_building_details_count,
            "effect": "cascade_delete",
            "severity": "destructive",
            "blocks_delete": False,
            "description": (
                "Curve-owned build details are keyed by this curve and cascade "
                "when the curve row is deleted."
            ),
        },
        {
            "key": "pricing_curve_selections",
            "label": "Pricing curve selections",
            "model": "PricingMarketDataSetCurveBindingTable",
            "column": "curve_uid",
            "relationship_type": "direct",
            "on_delete": "RESTRICT",
            "count": curve_selection_count,
            "effect": "delete_cleanup" if delete_curve_selections else "blocks_delete",
            "severity": "destructive" if delete_curve_selections else "blocking",
            "blocks_delete": curve_selection_count > 0 and not delete_curve_selections,
            "description": (
                "Market-data-set curve-selection rows point at this curve. They "
                "must be removed or explicitly deleted before deleting the curve."
            ),
        },
        {
            "key": "discount_curve_observations",
            "label": "Discount curve observations",
            "model": "DiscountCurvesStorage",
            "column": CURVE_IDENTIFIER_DIMENSION,
            "relationship_type": "direct",
            "on_delete": "RESTRICT",
            "count": observation_relationship_count,
            "effect": "delete_cleanup"
            if delete_values and unsupported_storage_count == 0
            else "blocks_delete",
            "severity": "destructive"
            if delete_values and unsupported_storage_count == 0
            else "blocking",
            "blocks_delete": observation_relationship_count > 0
            and (not delete_values or unsupported_storage_count > 0),
            "description": (
                "Timestamped discount-curve rows reference this curve by "
                "curve_identifier. Cleanup uses TimeIndexMetaTable.delete_after_date "
                "with a scoped curve_identifier dimension filter."
            ),
        },
        {
            "key": "discount_curve_storage_sources",
            "label": "Discount curve storage sources",
            "model": "PricingMarketDataSetBindingTable",
            "column": "data_node_uid",
            "relationship_type": "indirect",
            "on_delete": "NO ACTION",
            "count": storage_scope_count,
            "effect": "informational",
            "severity": "info",
            "blocks_delete": False,
            "description": (
                "Unique discount_curves storage tables checked for curve observations. "
                "Market-data-set source bindings are not deleted with the curve."
            ),
        },
    ]


def _discount_curve_observation_impact_counts(
    *,
    context: Any,
    curve_identifier: str,
) -> tuple[int, int, int]:
    observation_count = 0
    unsupported_storage_count = 0
    storage_scopes = _discount_curve_storage_scopes(context=context)
    for scope in storage_scopes:
        if not _storage_scope_supports_curve_identifier(scope):
            unsupported_storage_count += 1
            continue
        observation_count += _count_discount_curve_storage_scope(
            scope,
            curve_identifier=curve_identifier,
            timeout=context.timeout,
        )
    return observation_count, unsupported_storage_count, len(storage_scopes)


def _count_model_rows(context: Any, *, model: type[Any], filters: dict[str, Any]) -> int:
    return _count_from_operation_result(
        count_model(
            context,
            model=model,
            filters=filters,
        )
    )


def _discount_curve_storage_scopes(*, context: Any) -> list[dict[str, Any]]:
    from mainsequence.client.metatables import TimeIndexMetaTable
    from msm_pricing.api.market_data_bindings import PricingMarketDataSetBinding
    from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage

    scopes: dict[str, dict[str, Any]] = {}
    canonical_storage = DiscountCurvesStorage.get_time_index_meta_table()
    if canonical_storage is not None:
        _add_discount_curve_storage_scope(
            scopes,
            time_index_meta_table=canonical_storage,
            data_node_uid=str(canonical_storage.uid),
            storage_table_identifier=_storage_identifier(canonical_storage),
            source="canonical",
        )

    bindings = PricingMarketDataSetBinding.filter(
        limit=5000,
        concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
    )
    for binding in bindings:
        data_node_uid = str(binding.data_node_uid)
        if data_node_uid in scopes:
            scopes[data_node_uid]["market_data_binding_count"] += 1
            continue
        try:
            storage = TimeIndexMetaTable.get_by_uid(
                data_node_uid,
                timeout=context.timeout,
            )
        except Exception as exc:
            scopes[data_node_uid] = {
                "data_node_uid": data_node_uid,
                "storage_table_identifier": binding.storage_table_identifier,
                "time_index_meta_table": None,
                "market_data_binding_count": 1,
                "source": "market_data_set_binding",
                "unsupported_reason": str(exc),
            }
            continue
        _add_discount_curve_storage_scope(
            scopes,
            time_index_meta_table=storage,
            data_node_uid=data_node_uid,
            storage_table_identifier=binding.storage_table_identifier
            or _storage_identifier(storage),
            source="market_data_set_binding",
        )
    return list(scopes.values())


def _add_discount_curve_storage_scope(
    scopes: dict[str, dict[str, Any]],
    *,
    time_index_meta_table: Any,
    data_node_uid: str,
    storage_table_identifier: str | None,
    source: str,
) -> None:
    scopes[data_node_uid] = {
        "data_node_uid": data_node_uid,
        "storage_table_identifier": storage_table_identifier,
        "time_index_meta_table": time_index_meta_table,
        "market_data_binding_count": 0 if source == "canonical" else 1,
        "source": source,
        "unsupported_reason": None,
    }


def _storage_scope_supports_curve_identifier(scope: Mapping[str, Any]) -> bool:
    table = scope.get("time_index_meta_table")
    if table is None:
        return False
    if CURVE_IDENTIFIER_DIMENSION not in _storage_column_names(table):
        scope["unsupported_reason"] = "Storage table has no curve_identifier column."
        return False
    table_index_names = set(getattr(table, "table_index_names", None) or [])
    if CURVE_IDENTIFIER_DIMENSION not in table_index_names:
        scope["unsupported_reason"] = (
            "Storage table does not declare curve_identifier as an index dimension."
        )
        return False
    return True


def _storage_column_names(table: Any) -> set[str]:
    names: set[str] = set()
    for column in getattr(table, "columns", None) or []:
        if isinstance(column, Mapping):
            name = column.get("name")
        else:
            name = getattr(column, "name", None)
        if name not in (None, ""):
            names.add(str(name))
    return names


def _count_discount_curve_storage_scope(
    scope: Mapping[str, Any],
    *,
    curve_identifier: str,
    timeout: int | None,
) -> int:
    table = scope["time_index_meta_table"]
    result = table.run_query(
        _curve_observation_count_sql(
            table=table,
            curve_identifier=curve_identifier,
        ),
        timeout=timeout,
    )
    return _count_from_operation_result(result)


def _curve_observation_count_sql(*, table: Any, curve_identifier: str) -> str:
    table_name = _qualified_table_name(
        schema=getattr(table, "physical_schema", None),
        table=getattr(table, "physical_table_name", None),
    )
    return (
        f"SELECT COUNT(*) AS count FROM {table_name} "
        f"WHERE {_quote_identifier(CURVE_IDENTIFIER_DIMENSION)} = "
        f"{_quote_literal(curve_identifier)}"
    )


def _qualified_table_name(*, schema: str | None, table: str | None) -> str:
    if table in (None, ""):
        raise RuntimeError("TimeIndexMetaTable is missing physical_table_name.")
    if schema in (None, ""):
        return _quote_identifier(str(table))
    return f"{_quote_identifier(str(schema))}.{_quote_identifier(str(table))}"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _storage_identifier(table: Any) -> str | None:
    identifier = getattr(table, "identifier", None)
    if identifier in (None, ""):
        return None
    return str(identifier)


def _curve_delete_warnings(
    *,
    relationships: list[dict[str, Any]],
    delete_values: bool,
    delete_curve_selections: bool,
) -> list[str]:
    warnings: list[str] = []
    relationship_by_key = {item["key"]: item for item in relationships}
    curve_selections = relationship_by_key["pricing_curve_selections"]
    observations = relationship_by_key["discount_curve_observations"]
    build_details = relationship_by_key["curve_building_details"]

    if curve_selections["count"] > 0 and not delete_curve_selections:
        warnings.append(
            "Delete is blocked while pricing curve-selection rows point at this curve."
        )
    elif curve_selections["count"] > 0:
        warnings.append("Pricing curve-selection rows will be deleted.")

    if observations["count"] > 0 and not delete_values:
        warnings.append(
            "Delete is blocked while discount-curve observations reference this curve."
        )
    elif observations["count"] > 0 and observations["blocks_delete"]:
        warnings.append(
            "Delete is blocked because at least one discount-curve storage table "
            "cannot be safely cleaned for this curve_identifier."
        )
    elif observations["count"] > 0:
        warnings.append("Discount-curve observations will be deleted.")

    if build_details["count"] > 0:
        warnings.append("Curve building details will be deleted by database cascade.")

    if not warnings:
        warnings.append("No dependent rows were found for this pricing curve.")
    return warnings


def _format_curve_delete_blockers(impact: Mapping[str, Any]) -> str:
    blockers = [
        relationship
        for relationship in impact.get("relationships", [])
        if relationship.get("blocks_delete")
    ]
    if not blockers:
        return "Pricing curve deletion is blocked."
    details = "; ".join(
        f"{item['label']} ({item['count']})" for item in blockers if item.get("count", 0) > 0
    )
    return f"Pricing curve deletion is blocked by dependent rows: {details}."


def _delete_discount_curve_values(
    *,
    context: Any,
    curve_identifier: str,
) -> list[dict[str, Any]]:
    cleanups: list[dict[str, Any]] = []
    for scope in _discount_curve_storage_scopes(context=context):
        if not _storage_scope_supports_curve_identifier(scope):
            reason = scope.get("unsupported_reason") or "storage scope is unsupported"
            raise CurveDeleteConflictError(
                "Cannot delete discount-curve observations from storage "
                f"{scope.get('data_node_uid')}: {reason}"
            )
        table = scope["time_index_meta_table"]
        result = table.delete_after_date(
            None,
            dimension_filters={CURVE_IDENTIFIER_DIMENSION: [curve_identifier]},
            timeout=context.timeout,
        )
        cleanups.append(
            {
                "data_node_uid": scope["data_node_uid"],
                "storage_table_identifier": scope.get("storage_table_identifier"),
                "deleted_count": _deleted_count(result),
                "table_empty": result.get("table_empty") if isinstance(result, Mapping) else None,
            }
        )
    return cleanups


def _delete_curve_selection_rows(*, curve_uid: uuid.UUID) -> int:
    from msm_pricing.api.market_data_bindings import PricingMarketDataSetCurveBinding

    count = PricingMarketDataSetCurveBinding.count_for_curve(curve_uid=curve_uid)
    if count <= 0:
        return 0
    deleted_count = 0
    for binding in PricingMarketDataSetCurveBinding.filter_for_curve(
        curve_uid=curve_uid,
        limit=count,
    ):
        deleted_count += _deleted_count(PricingMarketDataSetCurveBinding.delete(binding.uid))
    return deleted_count


def _relationship_count(impact: Mapping[str, Any], *, key: str) -> int:
    for relationship in impact.get("relationships", []):
        if relationship.get("key") == key:
            return int(relationship.get("count") or 0)
    return 0


def _deleted_count(result: Mapping[str, Any] | None) -> int:
    if not result:
        return 0
    return int(result.get("deleted_count") or 0)


def _is_delete_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "foreign key",
            "violates",
            "referenced",
            "restrict",
            "constraint",
        )
    )


def _read_discount_curve_observation(
    *,
    interface: Any,
    curve_identifier: str,
    valuation_date: dt.datetime | None,
) -> tuple[dict[str, Any], dt.datetime]:
    try:
        if valuation_date is None:
            if hasattr(interface, "get_latest_discount_curve_observation"):
                return interface.get_latest_discount_curve_observation(curve_identifier)
            nodes, effective_date = interface.get_latest_discount_curve(curve_identifier)
            return {"nodes": nodes, "key_nodes": None, "metadata_json": None}, effective_date
        if hasattr(interface, "get_historical_discount_curve_observation"):
            return interface.get_historical_discount_curve_observation(
                curve_identifier,
                valuation_date,
            )
        nodes, effective_date = interface.get_historical_discount_curve(
            curve_identifier,
            valuation_date,
        )
        return {"nodes": nodes, "key_nodes": None, "metadata_json": None}, effective_date
    except LookupError:
        raise
    except Exception as exc:
        message = str(exc)
        if " is empty" in message or "No latest discount curve observation" in message:
            raise LookupError(message) from exc
        raise


def _missing_discount_curve_observation_message(
    *,
    curve_identifier: str,
    market_data_set_row: Any,
    binding: Any,
    valuation_date: dt.datetime | None,
) -> str:
    market_data_set_label = market_data_set_row.set_key or str(market_data_set_row.uid)
    storage_label = binding.storage_table_identifier or "DiscountCurvesStorage"
    data_node_uid = str(binding.data_node_uid)

    if valuation_date is None:
        return (
            f"No discount-curve data has been published for curve {curve_identifier!r} "
            f"in pricing market-data set {market_data_set_label!r}. The curve registry "
            f"row and discount_curves binding exist, but bound DataNode {data_node_uid} "
            f"has no latest {storage_label} observation for this curve_identifier."
        )

    return (
        f"No discount-curve data was found for curve {curve_identifier!r} at "
        f"valuation_date {valuation_date.isoformat()} in pricing market-data set "
        f"{market_data_set_label!r}. The curve registry row and discount_curves "
        f"binding exist, but bound DataNode {data_node_uid} has no {storage_label} "
        "observation for this curve_identifier at that valuation date."
    )


def _normalize_discount_curve_nodes(nodes: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "days_to_maturity": int(node["days_to_maturity"]),
            "zero": float(node["zero"]),
        }
        for node in nodes
    ]


def _normalize_discount_curve_key_nodes(key_nodes: Any | None) -> Any | None:
    if key_nodes is None:
        return None
    if isinstance(key_nodes, Mapping):
        return dict(key_nodes)
    if isinstance(key_nodes, list):
        return key_nodes
    raise ValueError("Discount curve key_nodes must be a JSON object or list when present.")


def _normalize_discount_curve_metadata(
    metadata_json: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if metadata_json is None:
        return None
    return dict(metadata_json)


class CurveCreate(BaseModel):
    """Payload for creating a pricing curve identity row."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    curve_type: str = Field(min_length=1, max_length=64)
    currency_code: str | None = Field(default=None, max_length=16)
    quote_side: str | None = Field(default=None, max_length=32)
    interpolation_method: str | None = Field(default=None, max_length=64)
    compounding: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=255)
    status: str = Field(default="ACTIVE", min_length=1, max_length=32)
    metadata_json: dict[str, Any] | None = None


class CurveUpsert(CurveCreate):
    """Payload for inserting or replacing a curve by unique identifier."""


class CurveUpdate(BaseModel):
    """Payload for updating mutable curve fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    curve_type: str | None = Field(default=None, min_length=1, max_length=64)
    currency_code: str | None = Field(default=None, max_length=16)
    quote_side: str | None = Field(default=None, max_length=32)
    interpolation_method: str | None = Field(default=None, max_length=64)
    compounding: str | None = Field(default=None, max_length=64)
    source: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, min_length=1, max_length=32)
    metadata_json: dict[str, Any] | None = None


def _coerce_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return uuid.UUID(str(value))


__all__ = [
    "Curve",
    "CurveCreate",
    "CurveDeleteConflictError",
    "CurveUpdate",
    "CurveUpsert",
]
