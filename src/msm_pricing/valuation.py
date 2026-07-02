from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import math
import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from msm_pricing.api.market_data_bindings import PricingMarketDataSetSelector
from msm_pricing.instruments.base_instrument import InstrumentModel


class ValuationLine(BaseModel):
    """One instrument and unit multiplier in a valuation basket."""

    instrument: InstrumentModel
    units: float
    asset_uid: uuid.UUID | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("units")
    @classmethod
    def _validate_units(cls, value: float) -> float:
        units = float(value)
        if not math.isfinite(units):
            raise ValueError("units must be finite.")
        return units


class ValuationPosition(BaseModel):
    """Transient basket of instruments valued under one valuation context."""

    valuation_date: dt.datetime
    lines: list[ValuationLine] = Field(default_factory=list)
    market_data_set: PricingMarketDataSetSelector = None

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("valuation_date")
    @classmethod
    def _validate_valuation_date(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value

    def price(self, *, context: PricingValuationContext | None = None) -> float:
        """Return the unit-scaled total market value of all lines."""

        context = self._context(context)
        return float(
            sum(
                line.units * self._call_instrument(line.instrument, "price", context=context)
                for line in self.lines
            )
        )

    def price_breakdown(self, *, context: PricingValuationContext | None = None) -> list[dict[str, Any]]:
        """Return per-line pricing details scaled by units."""

        context = self._context(context)
        rows: list[dict[str, Any]] = []
        for line_index, line in enumerate(self.lines):
            unit_price = float(self._call_instrument(line.instrument, "price", context=context))
            rows.append(
                {
                    "line_index": line_index,
                    "instrument_type": type(line.instrument).__name__,
                    "asset_uid": line.asset_uid,
                    "units": line.units,
                    "unit_price": unit_price,
                    "market_value": line.units * unit_price,
                    "metadata_json": dict(line.metadata_json),
                }
            )
        return rows

    def analytics(self, *, context: PricingValuationContext | None = None) -> dict[str, Any]:
        """Return raw per-line analytics and unit-scaled numeric totals."""

        context = self._context(context)
        totals: dict[str, float] = defaultdict(float)
        rows: list[dict[str, Any]] = []
        for line_index, line in enumerate(self.lines):
            analytics = self._call_instrument(line.instrument, "analytics", context=context)
            if not isinstance(analytics, Mapping):
                raise TypeError(
                    f"{type(line.instrument).__name__}.analytics() must return a mapping."
                )
            scaled = {
                key: line.units * float(value)
                for key, value in analytics.items()
                if isinstance(value, (int, float)) and math.isfinite(float(value))
            }
            for key, value in scaled.items():
                totals[key] += value
            rows.append(
                {
                    "line_index": line_index,
                    "instrument_type": type(line.instrument).__name__,
                    "asset_uid": line.asset_uid,
                    "units": line.units,
                    "analytics": dict(analytics),
                    "scaled_analytics": scaled,
                    "metadata_json": dict(line.metadata_json),
                }
            )
        return {"lines": rows, "totals": dict(totals)}

    def get_cashflows(
        self,
        *,
        context: PricingValuationContext | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return unit-scaled cashflows grouped by instrument leg name."""

        context = self._context(context)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for line_index, line in enumerate(self.lines):
            cashflows = self._call_instrument(
                line.instrument,
                "get_cashflows",
                context=context,
            )
            if not isinstance(cashflows, Mapping):
                raise TypeError(
                    f"{type(line.instrument).__name__}.get_cashflows() must return a mapping."
                )
            for leg, rows in cashflows.items():
                if not isinstance(rows, list):
                    raise TypeError(
                        f"{type(line.instrument).__name__}.get_cashflows()[{leg!r}] "
                        "must return a list of row mappings."
                    )
                for row in rows:
                    if not isinstance(row, Mapping):
                        raise TypeError("cashflow rows must be mappings.")
                    scaled = dict(row)
                    amount = scaled.get("amount")
                    if isinstance(amount, (int, float)):
                        scaled["amount"] = line.units * float(amount)
                    scaled["line_index"] = line_index
                    scaled["instrument_type"] = type(line.instrument).__name__
                    scaled["asset_uid"] = line.asset_uid
                    scaled["units"] = line.units
                    grouped[str(leg)].append(scaled)
        return dict(grouped)

    def get_net_cashflows(self, *, context: PricingValuationContext | None = None) -> pd.Series:
        """Return aggregate unit-scaled net cashflows by payment date."""

        context = self._context(context)
        totals: dict[Any, float] = defaultdict(float)
        for line in self.lines:
            prepared = context.prepare_instrument(line.instrument)
            get_net_cashflows = getattr(prepared.instrument, "get_net_cashflows", None)
            if callable(get_net_cashflows):
                series = prepared.get_net_cashflows()
                if not isinstance(series, pd.Series):
                    raise TypeError(
                        f"{prepared.instrument_type}.get_net_cashflows() must return a Series."
                    )
                for payment_date, amount in series.items():
                    totals[payment_date] += line.units * float(amount)
                continue

            cashflows = self._call_instrument(
                line.instrument,
                "get_cashflows",
                context=context,
            )
            if not isinstance(cashflows, Mapping):
                raise TypeError(
                    f"{prepared.instrument_type}.get_cashflows() must return a mapping."
                )
            for rows in cashflows.values():
                if not isinstance(rows, list):
                    raise TypeError("cashflow buckets must be lists.")
                for row in rows:
                    if not isinstance(row, Mapping):
                        raise TypeError("cashflow rows must be mappings.")
                    payment_date = (
                        row.get("payment_date")
                        or row.get("date")
                        or row.get("pay_date")
                        or row.get("fixing_date")
                    )
                    if payment_date is None:
                        raise ValueError("cashflow row is missing a payment date.")
                    totals[payment_date] += line.units * float(row.get("amount", 0.0))

        if not totals:
            return pd.Series(dtype=float, name="net_cashflow")
        return pd.Series(totals, name="net_cashflow").sort_index()

    def _context(self, context: PricingValuationContext | None) -> PricingValuationContext:
        if context is not None:
            context.validate_position_compatibility(self)
            return context
        return PricingValuationContext.prepare_for_position(self)

    def _call_instrument(
        self,
        instrument: InstrumentModel,
        method_name: str,
        *,
        context: PricingValuationContext,
    ) -> Any:
        prepared = context.prepare_instrument(instrument)
        method = getattr(prepared, method_name, None)
        if not callable(method):
            raise TypeError(f"{prepared.instrument_type} does not support {method_name}().")
        return method()


@dataclass(frozen=True)
class IndexCurveRequirement:
    """One index-scoped curve requirement implied by the instrument universe."""

    role_key: str
    index_uid: uuid.UUID
    quote_side: str | None
    binding_key: str


@dataclass(frozen=True)
class PricingValuationInstrumentKey:
    """Stable identity for one caller-submitted instrument in a prepared universe."""

    source_id: int
    instrument_type: str
    fingerprint: str


@dataclass(frozen=True)
class PricingValuationContextSpec:
    """Immutable input contract used to build one pricing valuation context."""

    valuation_date: dt.datetime
    market_data_set: PricingMarketDataSetSelector
    market_data_set_uid: uuid.UUID | None
    curve_quote_side: str | None
    requirements: tuple[IndexCurveRequirement, ...]
    instruments: tuple[PricingValuationInstrumentKey, ...]

    @property
    def instrument_source_ids(self) -> frozenset[int]:
        return frozenset(instrument.source_id for instrument in self.instruments)

    @property
    def instrument_source_id_sequence(self) -> tuple[int, ...]:
        return tuple(instrument.source_id for instrument in self.instruments)

    @property
    def instruments_by_source_id(self) -> dict[int, PricingValuationInstrumentKey]:
        return {instrument.source_id: instrument for instrument in self.instruments}

    @property
    def requested_roles(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(requirement.role_key for requirement in self.requirements))

    def validate_instrument_member(self, instrument: InstrumentModel) -> None:
        source_id = id(instrument)
        instrument_key = self.instruments_by_source_id.get(source_id)
        if instrument_key is None:
            raise ValueError(
                "Instrument was not part of the prepared PricingValuationContext "
                f"universe: source_id={source_id}, instrument_type={type(instrument).__name__}."
            )
        fingerprint = _instrument_fingerprint(instrument)
        if fingerprint != instrument_key.fingerprint:
            raise ValueError(
                "Instrument terms changed after PricingValuationContext preparation: "
                f"source_id={source_id}, instrument_type={instrument_key.instrument_type}."
            )


@dataclass(frozen=True)
class PricingValuationContext:
    """Prepared runtime context for valuation basket pricing.

    The context owns cloned/wrapped instrument state so pricing a basket does
    not mutate caller-owned instrument objects.
    """

    spec: PricingValuationContextSpec
    market_data_bindings: dict[str, Any] = field(default_factory=dict)
    indexes: dict[uuid.UUID, Any] = field(default_factory=dict)
    index_conventions: dict[uuid.UUID, Any] = field(default_factory=dict)
    curve_bindings: dict[str, Any] = field(default_factory=dict)
    curves: dict[uuid.UUID, Any] = field(default_factory=dict)
    curve_building_details: dict[uuid.UUID, Any] = field(default_factory=dict)
    curve_observations: dict[uuid.UUID, Any] = field(default_factory=dict)
    curve_observation_dates: dict[uuid.UUID, dt.datetime] = field(default_factory=dict)
    curve_handles: dict[uuid.UUID, Any] = field(default_factory=dict)
    index_fixing_identifiers: dict[uuid.UUID, str] = field(default_factory=dict)
    fixing_observations: dict[str, dict[dt.date, float]] = field(default_factory=dict)
    quantlib_indexes: dict[str, Any] = field(default_factory=dict)
    _prepared_by_source_id: dict[int, PreparedInstrument] = field(default_factory=dict, init=False)

    @classmethod
    def prepare(
        cls,
        *,
        valuation_date: dt.datetime,
        market_data_set: PricingMarketDataSetSelector = None,
        instruments: list[InstrumentModel] | tuple[InstrumentModel, ...] = (),
        curve_quote_side: str | None = None,
        resolve_market_data_set: bool = True,
    ) -> PricingValuationContext:
        """Prepare one valuation context for a known instrument universe."""

        normalized_quote_side = _normalize_quote_side(curve_quote_side)
        requirements = _instrument_index_curve_requirements(
            instruments,
            quote_side=normalized_quote_side,
        )
        spec = PricingValuationContextSpec(
            valuation_date=_normalize_valuation_date(valuation_date),
            market_data_set=market_data_set,
            market_data_set_uid=_resolve_market_data_set_uid(
                market_data_set,
                resolve_market_data_set=resolve_market_data_set,
            ),
            curve_quote_side=normalized_quote_side,
            requirements=requirements,
            instruments=_instrument_keys(instruments),
        )
        context = cls(spec=spec)
        context._prepare_resolution_caches()
        for instrument in instruments:
            context.prepare_instrument(instrument)
        return context

    @classmethod
    def prepare_for_position(
        cls,
        position: ValuationPosition,
        *,
        curve_quote_side: str | None = None,
        resolve_market_data_set: bool = True,
    ) -> PricingValuationContext:
        """Prepare one context for every instrument in a valuation position."""

        return cls.prepare(
            valuation_date=position.valuation_date,
            market_data_set=position.market_data_set,
            instruments=tuple(line.instrument for line in position.lines),
            curve_quote_side=curve_quote_side,
            resolve_market_data_set=resolve_market_data_set,
        )

    @property
    def valuation_date(self) -> dt.datetime:
        return self.spec.valuation_date

    @property
    def market_data_set(self) -> PricingMarketDataSetSelector:
        return self.spec.market_data_set

    @property
    def market_data_set_uid(self) -> uuid.UUID | None:
        return self.spec.market_data_set_uid

    @property
    def curve_quote_side(self) -> str | None:
        return self.spec.curve_quote_side

    def validate_position_compatibility(self, position: ValuationPosition) -> None:
        """Reject accidental use of a context prepared for a different basket context."""

        if _normalize_valuation_date(position.valuation_date) != self.valuation_date:
            raise ValueError(
                "PricingValuationContext valuation_date does not match the ValuationPosition."
            )
        if position.market_data_set != self.market_data_set:
            raise ValueError(
                "PricingValuationContext market_data_set does not match the ValuationPosition."
            )
        position_source_ids = tuple(id(line.instrument) for line in position.lines)
        if position_source_ids != self.spec.instrument_source_id_sequence:
            raise ValueError(
                "PricingValuationContext instrument universe does not match the "
                "ValuationPosition."
            )
        for line in position.lines:
            self.spec.validate_instrument_member(line.instrument)

    def prepare_instrument(
        self,
        instrument: InstrumentModel,
        *,
        curve_handles: Mapping[str, Any] | Any | None = None,
    ) -> PreparedInstrument:
        """Return a distinct prepared wrapper for the submitted instrument."""

        source_id = id(instrument)
        self.spec.validate_instrument_member(instrument)
        if curve_handles is None:
            prepared = self._prepared_by_source_id.get(source_id)
            if prepared is not None:
                return prepared

        instrument_copy = _clone_instrument_terms(instrument)
        self._apply_to_instrument(instrument_copy)
        _apply_curve_handle_overrides(instrument_copy, curve_handles)
        prepared = PreparedInstrument(
            source_instrument=instrument,
            instrument=instrument_copy,
            context=self,
        )
        if curve_handles is None:
            self._prepared_by_source_id[source_id] = prepared
        return prepared

    def market_data_set_for_instrument(self) -> PricingMarketDataSetSelector:
        return self.market_data_set_uid if self.market_data_set_uid is not None else self.market_data_set

    def get_market_data_binding(self, concept_key: str) -> Any:
        try:
            return self.market_data_bindings[concept_key]
        except KeyError as exc:
            raise LookupError(
                "PricingValuationContext has no market-data binding cached for "
                f"concept_key={concept_key!r}."
            ) from exc

    def get_index_convention(self, index_uid: uuid.UUID | str) -> Any:
        resolved_uid = _coerce_uuid(index_uid, field_name="index_uid")
        try:
            return self.index_conventions[resolved_uid]
        except KeyError as exc:
            raise LookupError(
                "PricingValuationContext has no index convention cached for "
                f"index_uid={resolved_uid}."
            ) from exc

    def get_index(self, index_uid: uuid.UUID | str) -> Any:
        resolved_uid = _coerce_uuid(index_uid, field_name="index_uid")
        try:
            return self.indexes[resolved_uid]
        except KeyError as exc:
            raise LookupError(
                "PricingValuationContext has no index row cached for "
                f"index_uid={resolved_uid}."
            ) from exc

    def get_index_curve_binding(
        self,
        *,
        role_key: str,
        index_uid: uuid.UUID | str,
        quote_side: str | None = None,
    ) -> Any:
        from msm_pricing.api.market_data_bindings import curve_binding_key

        binding_key = curve_binding_key(
            role_key=role_key,
            selector_type="index",
            selector_key=str(_coerce_uuid(index_uid, field_name="index_uid")),
            quote_side=self.curve_quote_side if quote_side is None else quote_side,
        )
        try:
            return self.curve_bindings[binding_key]
        except KeyError as exc:
            raise LookupError(
                "PricingValuationContext has no curve binding cached for "
                f"binding_key={binding_key!r}."
            ) from exc

    def get_curve(self, curve_uid: uuid.UUID | str) -> Any:
        resolved_uid = _coerce_uuid(curve_uid, field_name="curve_uid")
        try:
            return self.curves[resolved_uid]
        except KeyError as exc:
            raise LookupError(
                f"PricingValuationContext has no curve row cached for curve_uid={resolved_uid}."
            ) from exc

    def get_curve_building_details(self, curve_uid: uuid.UUID | str) -> Any:
        resolved_uid = _coerce_uuid(curve_uid, field_name="curve_uid")
        try:
            return self.curve_building_details[resolved_uid]
        except KeyError as exc:
            raise LookupError(
                "PricingValuationContext has no curve-building details cached for "
                f"curve_uid={resolved_uid}."
            ) from exc

    def get_curve_observation(self, curve_uid: uuid.UUID | str) -> Any:
        resolved_uid = _coerce_uuid(curve_uid, field_name="curve_uid")
        try:
            return self.curve_observations[resolved_uid]
        except KeyError as exc:
            raise LookupError(
                "PricingValuationContext has no curve observation cached for "
                f"curve_uid={resolved_uid}."
            ) from exc

    def get_curve_handle(self, curve_uid: uuid.UUID | str) -> Any:
        resolved_uid = _coerce_uuid(curve_uid, field_name="curve_uid")
        try:
            return self.curve_handles[resolved_uid]
        except KeyError as exc:
            raise LookupError(
                "PricingValuationContext has no QuantLib curve handle cached for "
                f"curve_uid={resolved_uid}."
            ) from exc

    def resolve_curve_for_index_binding(
        self,
        *,
        index_uid: uuid.UUID | str,
        role_key: str,
        quote_side: str | None = None,
        curve_uid: uuid.UUID | str | None = None,
        curve_unique_identifier: str | None = None,
        expected_curve_type: str | None = None,
    ) -> Any:
        """Return a cached QuantLib curve handle for an index-scoped binding."""

        if curve_uid is not None and curve_unique_identifier is not None:
            raise ValueError("Pass either curve_uid or curve_unique_identifier, not both.")
        if curve_unique_identifier is not None:
            matching_curve = next(
                (
                    curve
                    for curve in self.curves.values()
                    if curve.unique_identifier == curve_unique_identifier
                ),
                None,
            )
            if matching_curve is None:
                raise LookupError(
                    "PricingValuationContext has no cached curve row for "
                    f"curve_unique_identifier={curve_unique_identifier!r}."
                )
            curve_uid = matching_curve.uid
        if curve_uid is None:
            curve_uid = self.get_index_curve_binding(
                role_key=role_key,
                index_uid=index_uid,
                quote_side=quote_side,
            ).curve_uid
        curve = self.get_curve(curve_uid)
        if expected_curve_type is not None and curve.curve_type != expected_curve_type:
            raise ValueError(
                f"Curve {curve.unique_identifier!r} has curve_type={curve.curve_type!r}, "
                f"not {expected_curve_type!r}."
            )
        return self.get_curve_handle(curve_uid)

    def resolve_quantlib_index(
        self,
        index_uid: uuid.UUID | str,
        *,
        forwarding_curve: Any | None = None,
        hydrate_fixings: bool = True,
        role_key: str | None = None,
        quote_side: str | None = None,
        settlement_days: int | None = None,
    ) -> Any:
        """Build a QuantLib index from cached context rows and observations."""

        from msm_pricing.pricing_engine.resolvers import build_quantlib_index_from_rows

        resolved_uid = _coerce_uuid(index_uid, field_name="index_uid")
        index = self.get_index(resolved_uid)
        convention = self.get_index_convention(resolved_uid)
        curve = forwarding_curve
        if curve is None:
            binding = self.get_index_curve_binding(
                role_key=role_key or "projection",
                index_uid=resolved_uid,
                quote_side=quote_side,
            )
            curve = self.get_curve_handle(binding.curve_uid)

        fixing_identifier = self.index_fixing_identifiers.get(resolved_uid)
        fixings = self.fixing_observations.get(fixing_identifier or "", {})
        return build_quantlib_index_from_rows(
            index=index,
            convention=convention,
            valuation_date=self.valuation_date,
            forwarding_curve=curve,
            hydrate_fixings=hydrate_fixings,
            settlement_days=settlement_days,
            fixings=fixings,
        )

    def _apply_to_instrument(self, instrument: InstrumentModel) -> None:
        set_valuation_date = getattr(instrument, "set_valuation_date", None)
        if not callable(set_valuation_date):
            raise TypeError(
                f"{type(instrument).__name__} does not support set_valuation_date(...)."
            )
        set_valuation_date(self.valuation_date)

        market_data_set = self.market_data_set_for_instrument()
        if market_data_set is not None:
            apply_market_data_set = getattr(instrument, "_apply_market_data_set", None)
            if callable(apply_market_data_set):
                apply_market_data_set(market_data_set)

        if self.curve_quote_side is not None:
            apply_curve_quote_side = getattr(instrument, "_apply_curve_quote_side", None)
            if callable(apply_curve_quote_side):
                apply_curve_quote_side(self.curve_quote_side)

        apply_context = getattr(instrument, "_apply_pricing_valuation_context", None)
        if callable(apply_context):
            apply_context(self)

    def _prepare_resolution_caches(self) -> None:
        requirements = self.spec.requirements
        if not requirements or self.market_data_set_uid is None:
            return

        self._prepare_market_data_bindings()
        self._prepare_indexes(requirements)
        self._prepare_index_conventions(requirements)
        self._prepare_curve_bindings(requirements)
        curve_uids = {binding.curve_uid for binding in self.curve_bindings.values()}
        self._prepare_curves(curve_uids)
        self._prepare_curve_building_details(curve_uids)
        self._prepare_curve_observations(curve_uids)
        self._prepare_fixing_observations(requirements)
        self._prepare_curve_handles(curve_uids)
        self._prepare_quantlib_indexes(requirements)

    def _prepare_market_data_bindings(self) -> None:
        from msm_pricing.api.market_data_bindings import PricingMarketDataSetBinding
        from msm_pricing.settings import (
            PRICING_CONCEPT_DISCOUNT_CURVES,
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
        )

        required_concepts = (
            PRICING_CONCEPT_DISCOUNT_CURVES,
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
        )
        rows = PricingMarketDataSetBinding.filter_for_set_and_concepts(
            market_data_set_uid=self.market_data_set_uid,
            concept_keys=required_concepts,
        )
        self.market_data_bindings.update({row.concept_key: row for row in rows})
        _require_keys(
            self.market_data_bindings,
            required_concepts,
            missing_message=(
                "PricingValuationContext could not resolve market-data bindings for "
                f"market_data_set_uid={self.market_data_set_uid}"
            ),
        )

    def _prepare_indexes(self, requirements: tuple[IndexCurveRequirement, ...]) -> None:
        from msm.api.indices import Index

        index_uids = tuple(sorted({requirement.index_uid for requirement in requirements}, key=str))
        rows = Index.filter_by_uids(index_uids)
        self.indexes.update({row.uid: row for row in rows})
        _require_keys(
            self.indexes,
            index_uids,
            missing_message="PricingValuationContext could not resolve index rows",
        )

    def _prepare_index_conventions(self, requirements: tuple[IndexCurveRequirement, ...]) -> None:
        from msm_pricing.api.index_convention_details import IndexConventionDetails

        index_uids = tuple(sorted({requirement.index_uid for requirement in requirements}, key=str))
        rows = IndexConventionDetails.filter_by_index_uids(index_uids)
        self.index_conventions.update({row.index_uid: row for row in rows})
        _require_keys(
            self.index_conventions,
            index_uids,
            missing_message="PricingValuationContext could not resolve index conventions",
        )

    def _prepare_curve_bindings(self, requirements: tuple[IndexCurveRequirement, ...]) -> None:
        from msm_pricing.api.market_data_bindings import PricingMarketDataSetCurveBinding

        binding_keys = tuple(requirement.binding_key for requirement in requirements)
        rows = PricingMarketDataSetCurveBinding.filter_by_binding_keys(
            market_data_set_uid=self.market_data_set_uid,
            binding_keys=binding_keys,
            status="ACTIVE",
        )
        duplicate_keys = _duplicate_values(row.binding_key for row in rows)
        if duplicate_keys:
            raise ValueError(
                "PricingValuationContext found multiple active curve bindings for "
                f"binding_key values: {', '.join(sorted(duplicate_keys))}."
            )
        self.curve_bindings.update({row.binding_key: row for row in rows})
        _require_keys(
            self.curve_bindings,
            binding_keys,
            missing_message=(
                "PricingValuationContext could not resolve curve bindings for "
                f"market_data_set_uid={self.market_data_set_uid}"
            ),
        )

    def _prepare_curves(self, curve_uids: set[uuid.UUID]) -> None:
        from msm_pricing.api.curves import Curve

        ordered_curve_uids = tuple(sorted(curve_uids, key=str))
        rows = Curve.filter_by_uids(ordered_curve_uids)
        self.curves.update({row.uid: row for row in rows})
        _require_keys(
            self.curves,
            ordered_curve_uids,
            missing_message="PricingValuationContext could not resolve curve rows",
        )

    def _prepare_curve_building_details(self, curve_uids: set[uuid.UUID]) -> None:
        from msm_pricing.api.curve_building_details import CurveBuildingDetails

        ordered_curve_uids = tuple(sorted(curve_uids, key=str))
        rows = CurveBuildingDetails.filter_by_curve_uids(ordered_curve_uids)
        self.curve_building_details.update({row.curve_uid: row for row in rows})
        _require_keys(
            self.curve_building_details,
            ordered_curve_uids,
            missing_message="PricingValuationContext could not resolve curve-building details",
        )

    def _prepare_curve_observations(self, curve_uids: set[uuid.UUID]) -> None:
        curve_identifier_to_uid = {
            self.curves[curve_uid].unique_identifier: curve_uid for curve_uid in curve_uids
        }
        observations = self._data_interface().get_historical_discount_curve_observations(
            tuple(curve_identifier_to_uid),
            self.valuation_date,
        )
        for curve_identifier, (observation, effective_date) in observations.items():
            curve_uid = curve_identifier_to_uid[curve_identifier]
            self.curve_observations[curve_uid] = observation
            self.curve_observation_dates[curve_uid] = effective_date
        _require_keys(
            self.curve_observations,
            tuple(sorted(curve_uids, key=str)),
            missing_message="PricingValuationContext could not resolve curve observations",
        )

    def _prepare_fixing_observations(
        self,
        requirements: tuple[IndexCurveRequirement, ...],
    ) -> None:
        from msm_pricing.pricing_engine.resolvers import fixing_identifier_from_rows

        index_uids = tuple(sorted({requirement.index_uid for requirement in requirements}, key=str))
        for index_uid in index_uids:
            self.index_fixing_identifiers[index_uid] = fixing_identifier_from_rows(
                index=self.indexes[index_uid],
                convention=self.index_conventions[index_uid],
            )
        identifiers = tuple(dict.fromkeys(self.index_fixing_identifiers.values()))
        start_date = self.valuation_date - dt.timedelta(days=365)
        observations = self._data_interface().get_historical_fixings_for_identifiers(
            identifiers,
            start_date,
            self.valuation_date,
        )
        self.fixing_observations.update(observations)
        missing = [identifier for identifier in identifiers if not self.fixing_observations.get(identifier)]
        if missing:
            raise LookupError(
                "PricingValuationContext could not resolve fixing observations: "
                f"{', '.join(missing)}."
            )

    def _prepare_curve_handles(self, curve_uids: set[uuid.UUID]) -> None:
        from msm_pricing.pricing_engine.resolvers import build_curve_from_curve_observation

        for curve_uid in sorted(curve_uids, key=str):
            self.curve_handles[curve_uid] = build_curve_from_curve_observation(
                curve=self.curves[curve_uid],
                building_details=self.curve_building_details[curve_uid],
                observation=self.curve_observations[curve_uid],
                effective_curve_date=self.curve_observation_dates[curve_uid],
            )

    def _prepare_quantlib_indexes(
        self,
        requirements: tuple[IndexCurveRequirement, ...],
    ) -> None:
        for requirement in requirements:
            self.quantlib_indexes[requirement.binding_key] = self.resolve_quantlib_index(
                requirement.index_uid,
                role_key=requirement.role_key,
                quote_side=requirement.quote_side,
            )

    def _data_interface(self) -> Any:
        from msm_pricing.data_interface.data_interface import MSDataInterface
        from msm_pricing.settings import (
            PRICING_CONCEPT_DISCOUNT_CURVES,
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
        )

        return MSDataInterface(
            market_data_configuration={
                "data_node_uids": {
                    PRICING_CONCEPT_DISCOUNT_CURVES: self.market_data_bindings[
                        PRICING_CONCEPT_DISCOUNT_CURVES
                    ].data_node_uid,
                    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: self.market_data_bindings[
                        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS
                    ].data_node_uid,
                }
            }
        )


@dataclass(frozen=True)
class PreparedInstrument:
    """Prepared wrapper around a cloned instrument and one valuation context."""

    source_instrument: InstrumentModel
    instrument: InstrumentModel
    context: PricingValuationContext

    @property
    def instrument_type(self) -> str:
        return type(self.instrument).__name__

    def price(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("price", *args, **kwargs)

    def analytics(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("analytics", *args, **kwargs)

    def get_cashflows(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_cashflows", *args, **kwargs)

    def get_net_cashflows(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("get_net_cashflows", *args, **kwargs)

    def z_spread(self, target_dirty_ccy: float, *args: Any, **kwargs: Any) -> Any:
        return self._call("z_spread", target_dirty_ccy, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.instrument, name)

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        method = getattr(self.instrument, method_name, None)
        if not callable(method):
            raise TypeError(f"{self.instrument_type} does not support {method_name}().")

        if (
            "market_data_set" not in kwargs
            and self.context.market_data_set_for_instrument() is not None
            and _accepts_keyword(method, "market_data_set")
        ):
            kwargs["market_data_set"] = self.context.market_data_set_for_instrument()
        if (
            "curve_quote_side" not in kwargs
            and self.context.curve_quote_side is not None
            and _accepts_keyword(method, "curve_quote_side")
        ):
            kwargs["curve_quote_side"] = self.context.curve_quote_side
        return method(*args, **kwargs)


def price_scenario(
    *,
    position: ValuationPosition,
    context: PricingValuationContext | None = None,
    line_curve_handles: Mapping[int, Mapping[str, Any] | Any] | None = None,
    scenario_curve_handles: Mapping[int, Mapping[str, Any] | Any] | None = None,
) -> dict[str, Any]:
    """Price base and scenario line values with explicit line-scoped curve handles."""

    context = position._context(context)
    rows: list[dict[str, Any]] = []
    base_total = 0.0
    scenario_total = 0.0
    for line_index, line in enumerate(position.lines):
        base_prepared = context.prepare_instrument(
            line.instrument,
            curve_handles=_line_curve_handles(line_curve_handles, line_index),
        )
        scenario_prepared = context.prepare_instrument(
            line.instrument,
            curve_handles=_line_curve_handles(scenario_curve_handles, line_index),
        )
        base_unit_price = float(base_prepared.price())
        scenario_unit_price = float(scenario_prepared.price())
        base_market_value = line.units * base_unit_price
        scenario_market_value = line.units * scenario_unit_price
        base_total += base_market_value
        scenario_total += scenario_market_value
        rows.append(
            {
                "line_index": line_index,
                "instrument_type": type(line.instrument).__name__,
                "asset_uid": line.asset_uid,
                "units": line.units,
                "base_unit_price": base_unit_price,
                "scenario_unit_price": scenario_unit_price,
                "base_market_value": base_market_value,
                "scenario_market_value": scenario_market_value,
                "market_value_delta": scenario_market_value - base_market_value,
                "metadata_json": dict(line.metadata_json),
            }
        )
    return {
        "lines": rows,
        "base_market_value": base_total,
        "scenario_market_value": scenario_total,
        "market_value_delta": scenario_total - base_total,
    }


def _instrument_index_curve_requirements(
    instruments: list[InstrumentModel] | tuple[InstrumentModel, ...],
    *,
    quote_side: str | None,
) -> tuple[IndexCurveRequirement, ...]:
    from msm_pricing.api.market_data_bindings import curve_binding_key

    requirements: list[IndexCurveRequirement] = []
    seen: set[str] = set()
    role_attributes = (
        ("floating_rate_index_uid", "projection"),
        ("float_leg_index_uid", "projection"),
        ("benchmark_rate_index_uid", "z_spread_base"),
    )
    for instrument in instruments:
        for attribute_name, role_key in role_attributes:
            value = getattr(instrument, attribute_name, None)
            if value is None:
                continue
            index_uid = _coerce_uuid(value, field_name=attribute_name)
            binding_key = curve_binding_key(
                role_key=role_key,
                selector_type="index",
                selector_key=str(index_uid),
                quote_side=quote_side,
            )
            if binding_key in seen:
                continue
            seen.add(binding_key)
            requirements.append(
                IndexCurveRequirement(
                    role_key=role_key,
                    index_uid=index_uid,
                    quote_side=quote_side,
                    binding_key=binding_key,
                )
            )
    return tuple(requirements)


def _instrument_keys(
    instruments: list[InstrumentModel] | tuple[InstrumentModel, ...],
) -> tuple[PricingValuationInstrumentKey, ...]:
    return tuple(
        PricingValuationInstrumentKey(
            source_id=id(instrument),
            instrument_type=type(instrument).__name__,
            fingerprint=_instrument_fingerprint(instrument),
        )
        for instrument in instruments
    )


def _instrument_fingerprint(instrument: InstrumentModel) -> str:
    payload: str
    try:
        payload = instrument.serialize_for_backend()
    except Exception:
        try:
            payload = instrument.model_dump_json()
        except Exception:
            payload = repr(instrument)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _line_curve_handles(
    curve_handles_by_line: Mapping[int, Mapping[str, Any] | Any] | None,
    line_index: int,
) -> Mapping[str, Any] | Any | None:
    if curve_handles_by_line is None:
        return None
    return curve_handles_by_line.get(line_index)


def _apply_curve_handle_overrides(
    instrument: InstrumentModel,
    curve_handles: Mapping[str, Any] | Any | None,
) -> None:
    if curve_handles is None:
        return
    reset_curve = getattr(instrument, "reset_curve", None)
    if not callable(reset_curve):
        raise TypeError(
            f"{type(instrument).__name__} does not support scenario curve-handle overrides."
        )
    curve_handle = _first_curve_handle(curve_handles)
    reset_curve(curve_handle)


def _first_curve_handle(curve_handles: Mapping[str, Any] | Any) -> Any:
    if not isinstance(curve_handles, Mapping):
        return curve_handles
    for key in ("default", "discount", "projection", "forwarding"):
        value = curve_handles.get(key)
        if value is not None:
            return value
    for value in curve_handles.values():
        if value is not None:
            return value
    raise ValueError("curve_handles mapping must contain at least one non-null handle.")


def _normalize_quote_side(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    return normalized


def _coerce_uuid(value: Any, *, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a UUID value.") from exc


def _require_keys(
    cache: Mapping[Any, Any],
    required_keys: tuple[Any, ...] | list[Any],
    *,
    missing_message: str,
) -> None:
    missing = [key for key in required_keys if key not in cache]
    if missing:
        raise LookupError(
            f"{missing_message}: {', '.join(str(key) for key in missing)}."
        )


def _duplicate_values(values: Any) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        key = str(value)
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return duplicates


def _normalize_valuation_date(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def _resolve_market_data_set_uid(
    market_data_set: PricingMarketDataSetSelector,
    *,
    resolve_market_data_set: bool,
) -> uuid.UUID | None:
    if market_data_set is None:
        return None
    uid = getattr(market_data_set, "uid", None)
    if uid is not None:
        return _coerce_uuid(uid, field_name="market_data_set.uid")
    try:
        return _coerce_uuid(market_data_set, field_name="market_data_set")
    except ValueError:
        if not resolve_market_data_set:
            return None
    from msm_pricing.api.market_data_bindings import PricingMarketDataSet

    return PricingMarketDataSet.resolve_uid(market_data_set)


def _clone_instrument_terms(instrument: InstrumentModel) -> InstrumentModel:
    try:
        cloned = InstrumentModel.rebuild(instrument.serialize_for_backend())
    except Exception:
        cloned = instrument.model_copy(deep=True)
        set_valuation_date = getattr(cloned, "set_valuation_date", None)
        if callable(set_valuation_date):
            set_valuation_date(None)

    if hasattr(instrument, "_asset_uid") and hasattr(cloned, "_asset_uid"):
        cloned._asset_uid = instrument._asset_uid
    return cloned


def _accepts_keyword(method: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.name == keyword:
            return True
        if parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD and parameter.name == keyword:
            return True
    return False


__all__ = [
    "IndexCurveRequirement",
    "PreparedInstrument",
    "PricingValuationContext",
    "PricingValuationContextSpec",
    "PricingValuationInstrumentKey",
    "ValuationLine",
    "ValuationPosition",
    "price_scenario",
]
