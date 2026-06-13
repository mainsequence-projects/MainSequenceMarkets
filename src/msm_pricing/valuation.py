from __future__ import annotations

import datetime as dt
import inspect
import math
import uuid
from collections import defaultdict
from collections.abc import Mapping
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

    def price(self) -> float:
        """Return the unit-scaled total market value of all lines."""

        return float(
            sum(line.units * self._call_instrument(line.instrument, "price") for line in self.lines)
        )

    def price_breakdown(self) -> list[dict[str, Any]]:
        """Return per-line pricing details scaled by units."""

        rows: list[dict[str, Any]] = []
        for line_index, line in enumerate(self.lines):
            unit_price = float(self._call_instrument(line.instrument, "price"))
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

    def analytics(self) -> dict[str, Any]:
        """Return raw per-line analytics and unit-scaled numeric totals."""

        totals: dict[str, float] = defaultdict(float)
        rows: list[dict[str, Any]] = []
        for line_index, line in enumerate(self.lines):
            analytics = self._call_instrument(line.instrument, "analytics")
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

    def get_cashflows(self) -> dict[str, list[dict[str, Any]]]:
        """Return unit-scaled cashflows grouped by instrument leg name."""

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for line_index, line in enumerate(self.lines):
            cashflows = self._call_instrument(line.instrument, "get_cashflows")
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

    def get_net_cashflows(self) -> pd.Series:
        """Return aggregate unit-scaled net cashflows by payment date."""

        totals: dict[Any, float] = defaultdict(float)
        for line in self.lines:
            instrument = self._prepare_instrument(line.instrument)
            get_net_cashflows = getattr(instrument, "get_net_cashflows", None)
            if callable(get_net_cashflows):
                series = get_net_cashflows()
                if not isinstance(series, pd.Series):
                    raise TypeError(
                        f"{type(instrument).__name__}.get_net_cashflows() must return a Series."
                    )
                for payment_date, amount in series.items():
                    totals[payment_date] += line.units * float(amount)
                continue

            cashflows = self._call_instrument(instrument, "get_cashflows")
            if not isinstance(cashflows, Mapping):
                raise TypeError(
                    f"{type(instrument).__name__}.get_cashflows() must return a mapping."
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

    def _call_instrument(self, instrument: InstrumentModel, method_name: str) -> Any:
        prepared = self._prepare_instrument(instrument)
        method = getattr(prepared, method_name, None)
        if not callable(method):
            raise TypeError(f"{type(prepared).__name__} does not support {method_name}().")
        if self.market_data_set is not None and _accepts_keyword(method, "market_data_set"):
            return method(market_data_set=self.market_data_set)
        return method()

    def _prepare_instrument(self, instrument: InstrumentModel) -> InstrumentModel:
        set_valuation_date = getattr(instrument, "set_valuation_date", None)
        if not callable(set_valuation_date):
            raise TypeError(
                f"{type(instrument).__name__} does not support set_valuation_date(...)."
            )
        set_valuation_date(self.valuation_date)

        if self.market_data_set is not None:
            apply_market_data_set = getattr(instrument, "_apply_market_data_set", None)
            if callable(apply_market_data_set):
                apply_market_data_set(self.market_data_set)
        return instrument


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


__all__ = ["ValuationLine", "ValuationPosition"]
