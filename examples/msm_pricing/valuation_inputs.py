from __future__ import annotations

import datetime as dt
import json
import sys
import uuid
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from msm_pricing.instruments import Instrument  # noqa: E402
from msm_pricing.valuation import (  # noqa: E402
    PricingValuationContext,
    build_valuation_position,
)


class FlatPriceInstrument(Instrument):
    """Minimal offline instrument for demonstrating valuation input rows."""

    unit_price: float

    def price(self, *, market_data_set=None) -> float:
        if self.valuation_date is None:
            raise RuntimeError("valuation_date was not prepared")
        if market_data_set != "eod":
            raise RuntimeError("market_data_set was not injected from the position")
        return self.unit_price


def build_normalized_valuation_input_example() -> dict[str, Any]:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    first_asset_uid = uuid.UUID("00000000-0000-4000-8000-000000000101")
    second_asset_uid = uuid.UUID("00000000-0000-4000-8000-000000000102")
    first_instrument = FlatPriceInstrument(unit_price=101.25)
    second_instrument = FlatPriceInstrument(unit_price=98.75)
    normalized_rows = [
        {
            "instrument": first_instrument,
            "units": 2.0,
            "asset_uid": first_asset_uid,
            "metadata_json": {"source": "example-row-1"},
        },
        {
            "instrument": second_instrument,
            "units": -1.5,
            "asset_uid": second_asset_uid,
            "metadata_json": {"source": "example-row-2"},
        },
    ]
    position = build_valuation_position(
        normalized_rows,
        valuation_date=valuation_date,
        market_data_set="eod",
    )
    context = PricingValuationContext.prepare_for_position(
        position,
        resolve_market_data_set=False,
    )
    breakdown = position.price_breakdown(context=context)
    serializable_breakdown = [
        {
            **row,
            "asset_uid": str(row["asset_uid"]) if row["asset_uid"] is not None else None,
        }
        for row in breakdown
    ]
    return {
        "valuation_date": position.valuation_date.isoformat(),
        "market_data_set": position.market_data_set,
        "line_count": len(position.lines),
        "market_value": position.price(context=context),
        "breakdown": serializable_breakdown,
        "first_original_valuation_date": first_instrument.valuation_date,
        "second_original_valuation_date": second_instrument.valuation_date,
    }


if __name__ == "__main__":
    print(json.dumps(build_normalized_valuation_input_example(), default=str, indent=2))
