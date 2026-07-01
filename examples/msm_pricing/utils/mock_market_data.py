from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from msm_pricing.data_nodes import (
    CURVE_IDENTIFIER,
    CurveConfig,
    CurveKeyNode,
    DiscountCurvesNode,
    FixingRatesNode,
    IndexFixingConfiguration,
)
from msm.settings import INDEX_IDENTIFIER_DIMENSION
from msm_pricing.utils import to_py_date, to_ql_date

EXAMPLE_INDEX_UNIQUE_IDENTIFIER = "USD-SOFR-EXAMPLE"
EXAMPLE_CURVE_UNIQUE_IDENTIFIER = "USD-SOFR-EXAMPLE-DISCOUNT"
DEFAULT_CURVE_SAMPLING_DAYS = (1, 7, 30, 90, 180, 365, 730, 1095, 1460, 1825, 2555, 3650)
DEFAULT_FIXING_LOOKBACK_DAYS = 31


def build_flat_forward_zero_curve(
    *,
    valuation_date: dt.date | dt.datetime,
    zero_rate: float,
    sampling_days: tuple[int, ...] = DEFAULT_CURVE_SAMPLING_DAYS,
) -> dict[int, float]:
    """Build a sampled zero curve from a QuantLib flat-forward term structure."""

    import QuantLib as ql

    base_date = _as_datetime(valuation_date)
    ql_date = to_ql_date(base_date)
    day_counter = ql.Actual360()
    ql.Settings.instance().evaluationDate = ql_date
    curve = ql.FlatForward(
        ql_date,
        float(zero_rate),
        day_counter,
        ql.Compounded,
        ql.Annual,
    )
    handle = ql.YieldTermStructureHandle(curve)

    zeros: dict[int, float] = {}
    for days in sampling_days:
        maturity = ql_date + int(days)
        zeros[int(days)] = float(
            handle.zeroRate(maturity, day_counter, ql.Compounded, ql.Annual).rate()
        )
    return zeros


def build_flat_forward_key_nodes(
    *,
    valuation_date: dt.date | dt.datetime,
    zero_rate: float,
    sampling_days: tuple[int, ...] = DEFAULT_CURVE_SAMPLING_DAYS,
) -> list[dict[str, Any]]:
    """Build dated key-node inputs for the sampled flat-forward zero curve."""

    base_date = _as_datetime(valuation_date)
    ql_date = to_ql_date(base_date)
    return [
        CurveKeyNode(
            maturity_date=to_py_date(ql_date + int(days)).date(),
            instrument_type="direct_zero_rate",
            quote=float(zero_rate),
            quote_type="zero_rate",
            quote_unit="decimal",
            quote_side="mid",
            yield_value=float(zero_rate),
        ).model_dump(mode="json", by_alias=True, exclude_none=True)
        for days in sampling_days
    ]


def build_mock_fixings_frame(
    *,
    index_identifier: str,
    valuation_date: dt.date | dt.datetime,
    fixing_rate: float,
    lookback_days: int = DEFAULT_FIXING_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Create deterministic business-day fixings for an Index unique identifier."""

    import QuantLib as ql

    base_date = _as_datetime(valuation_date)
    calendar = ql.UnitedStates(ql.UnitedStates.Settlement)
    rows: list[dict[str, Any]] = []
    for offset in range(int(lookback_days), -1, -1):
        fixing_date = base_date - dt.timedelta(days=offset)
        ql_date = to_ql_date(fixing_date)
        if not calendar.isBusinessDay(ql_date):
            continue
        rows.append(
            {
                "time_index": _utc_timestamp(fixing_date),
                INDEX_IDENTIFIER_DIMENSION: index_identifier,
                "rate": float(fixing_rate),
            }
        )
    return pd.DataFrame(rows)


def example_index_convention_dump() -> dict[str, Any]:
    """Return the convention payload used by the floating-rate bond example."""

    return {
        "currency_code": "USD",
        "day_counter_code": "Actual360",
        "fixing_calendar_code": "US",
        "period": "3M",
        "settlement_days": 2,
        "business_day_convention": "ModifiedFollowing",
        "end_of_month": False,
        "fixings_unique_identifier": EXAMPLE_INDEX_UNIQUE_IDENTIFIER,
    }


class MockFlatForwardDiscountCurvesNode(DiscountCurvesNode):
    """Example discount-curve DataNode backed by a sampled QuantLib flat-forward curve."""

    def __init__(
        self,
        curve_config: CurveConfig,
        *,
        valuation_date: dt.date | dt.datetime,
        zero_rate: float = 0.05,
        **kwargs: Any,
    ) -> None:
        self.valuation_date = _as_datetime(valuation_date)
        self.zero_rate = float(zero_rate)
        super().__init__(curve_config, **kwargs)

    def build_curve_frame(
        self,
        *,
        update_statistics,
        curve_identifier: str,
        base_node_curve_points,
    ) -> pd.DataFrame:
        curve = build_flat_forward_zero_curve(
            valuation_date=self.valuation_date,
            zero_rate=self.zero_rate,
        )
        key_nodes = build_flat_forward_key_nodes(
            valuation_date=self.valuation_date,
            zero_rate=self.zero_rate,
        )
        return pd.DataFrame(
            [
                {
                    "time_index": _utc_timestamp(self.valuation_date),
                    CURVE_IDENTIFIER: curve_identifier,
                    "curve": curve,
                    "key_nodes": key_nodes,
                    "metadata_json": {
                        "source": "mock_flat_forward",
                        "sampling_days": list(DEFAULT_CURVE_SAMPLING_DAYS),
                    },
                }
            ]
        )


class MockIndexFixingsNode(FixingRatesNode):
    """Example index-fixings DataNode that emits deterministic mock rates."""

    def __init__(
        self,
        fixing_config: IndexFixingConfiguration,
        *,
        valuation_date: dt.date | dt.datetime,
        fixing_rate: float = 0.0525,
        lookback_days: int = DEFAULT_FIXING_LOOKBACK_DAYS,
        **kwargs: Any,
    ) -> None:
        self.valuation_date = _as_datetime(valuation_date)
        self.fixing_rate = float(fixing_rate)
        self.lookback_days = int(lookback_days)
        super().__init__(fixing_config, **kwargs)

    def build_fixing_frame(
        self,
        *,
        update_statistics,
        index_identifier: str,
    ) -> pd.DataFrame:
        return build_mock_fixings_frame(
            index_identifier=index_identifier,
            valuation_date=self.valuation_date,
            fixing_rate=self.fixing_rate,
            lookback_days=self.lookback_days,
        )


def _as_datetime(value: dt.date | dt.datetime) -> dt.datetime:
    if isinstance(value, dt.datetime):
        resolved = value
    else:
        resolved = dt.datetime.combine(value, dt.time())
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        return resolved.replace(tzinfo=dt.UTC)
    return resolved.astimezone(dt.UTC)


def _utc_timestamp(value: dt.date | dt.datetime) -> pd.Timestamp:
    return pd.Timestamp(_as_datetime(value)).tz_convert("UTC")
