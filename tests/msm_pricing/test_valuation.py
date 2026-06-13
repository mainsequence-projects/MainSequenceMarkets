from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pandas as pd
import pytest
from pydantic import PrivateAttr

import msm_pricing
from msm_pricing.instruments import Instrument
from msm_pricing.valuation import ValuationLine, ValuationPosition


class FakePricedInstrument(Instrument):
    price_value: float = 10.0
    analytics_value: dict[str, float] | None = None

    _market_data_sets: list[Any] = PrivateAttr(default_factory=list)
    _price_calls: int = PrivateAttr(default=0)

    def _apply_market_data_set(self, market_data_set=None) -> None:
        self._market_data_sets.append(market_data_set)

    def price(self, *, market_data_set=None) -> float:
        self._price_calls += 1
        if self.valuation_date is None:
            raise ValueError("valuation date was not set")
        self._market_data_sets.append(market_data_set)
        return self.price_value

    def analytics(self, *, market_data_set=None) -> dict[str, float]:
        if self.valuation_date is None:
            raise ValueError("valuation date was not set")
        self._market_data_sets.append(market_data_set)
        return self.analytics_value or {"clean_price": self.price_value, "accrued_amount": 1.5}

    def get_cashflows(self, *, market_data_set=None) -> dict[str, list[dict[str, Any]]]:
        if self.valuation_date is None:
            raise ValueError("valuation date was not set")
        self._market_data_sets.append(market_data_set)
        return {
            "fixed": [
                {"payment_date": dt.date(2026, 7, 1), "amount": 2.0},
                {"payment_date": dt.date(2026, 8, 1), "amount": 3.0},
            ]
        }

    def get_net_cashflows(self) -> pd.Series:
        if self.valuation_date is None:
            raise ValueError("valuation date was not set")
        return pd.Series(
            {
                dt.date(2026, 7, 1): 2.0,
                dt.date(2026, 8, 1): 3.0,
            },
            name="net_cashflow",
        )


class NoAnalyticsInstrument(Instrument):
    def price(self) -> float:
        return 1.0


def test_valuation_position_prices_lines_with_context_and_units() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    first = FakePricedInstrument(price_value=10.0)
    second = FakePricedInstrument(price_value=4.0)

    position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set="eod",
        lines=[
            ValuationLine(instrument=first, units=3.0, asset_uid=uuid.uuid4()),
            ValuationLine(instrument=second, units=-2.0),
        ],
    )

    assert position.price() == 22.0
    assert first.valuation_date == valuation_date
    assert second.valuation_date == valuation_date
    assert "eod" in first._market_data_sets
    assert "eod" in second._market_data_sets


def test_price_breakdown_preserves_input_order_and_asset_uid() -> None:
    asset_uid = uuid.uuid4()
    instrument = FakePricedInstrument(price_value=7.0)
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set="default",
        lines=[
            ValuationLine(
                instrument=instrument,
                units=5.0,
                asset_uid=asset_uid,
                metadata_json={"source": "unit-test"},
            )
        ],
    )

    assert position.price_breakdown() == [
        {
            "line_index": 0,
            "instrument_type": "FakePricedInstrument",
            "asset_uid": asset_uid,
            "units": 5.0,
            "unit_price": 7.0,
            "market_value": 35.0,
            "metadata_json": {"source": "unit-test"},
        }
    ]


def test_valuation_position_scales_analytics_and_cashflows() -> None:
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set="risk_manager",
        lines=[
            ValuationLine(
                instrument=FakePricedInstrument(
                    price_value=11.0,
                    analytics_value={"clean_price": 100.0, "accrued_amount": 2.0},
                ),
                units=2.0,
            )
        ],
    )

    assert position.analytics()["totals"] == {
        "clean_price": 200.0,
        "accrued_amount": 4.0,
    }
    assert position.get_cashflows()["fixed"] == [
        {
            "payment_date": dt.date(2026, 7, 1),
            "amount": 4.0,
            "line_index": 0,
            "instrument_type": "FakePricedInstrument",
            "asset_uid": None,
            "units": 2.0,
        },
        {
            "payment_date": dt.date(2026, 8, 1),
            "amount": 6.0,
            "line_index": 0,
            "instrument_type": "FakePricedInstrument",
            "asset_uid": None,
            "units": 2.0,
        },
    ]
    net_cashflows = position.get_net_cashflows()
    assert net_cashflows.to_dict() == {
        dt.date(2026, 7, 1): 4.0,
        dt.date(2026, 8, 1): 6.0,
    }


def test_valuation_position_rejects_non_finite_units() -> None:
    with pytest.raises(ValueError, match="units must be finite"):
        ValuationLine(instrument=FakePricedInstrument(), units=float("nan"))


def test_valuation_position_fails_for_unsupported_requested_output() -> None:
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        lines=[ValuationLine(instrument=NoAnalyticsInstrument(), units=1.0)],
    )

    with pytest.raises(TypeError, match="does not support analytics"):
        position.analytics()


def test_legacy_position_export_is_removed() -> None:
    assert not hasattr(msm_pricing, "Position")
    assert not hasattr(msm_pricing, "PositionLine")
