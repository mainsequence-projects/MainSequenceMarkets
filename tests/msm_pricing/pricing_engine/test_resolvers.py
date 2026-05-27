from __future__ import annotations

# ruff: noqa: E402

import datetime as dt
import uuid

import pytest

ql = pytest.importorskip("QuantLib")

from msm.api.indices import Index
from msm_pricing.api import Curve, IndexConventionDetails
from msm_pricing.pricing_engine import resolvers


def _convention(index_uid: uuid.UUID) -> IndexConventionDetails:
    return IndexConventionDetails(
        index_uid=index_uid,
        index_family="overnight",
        convention_dump={
            "currency_code": "USD",
            "day_counter_code": "Actual360",
            "fixing_calendar_code": "TARGET",
            "period": "1D",
            "settlement_days": 0,
            "business_day_convention": "Following",
        },
    )


def test_select_curve_requires_source_when_curve_match_is_ambiguous(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    first = Curve(
        uid=uuid.uuid4(),
        unique_identifier="USD-SOFR-DISCOUNT-A",
        display_name="USD SOFR Discount A",
        curve_type="discount",
        index_uid=index_uid,
    )
    second = Curve(
        uid=uuid.uuid4(),
        unique_identifier="USD-SOFR-DISCOUNT-B",
        display_name="USD SOFR Discount B",
        curve_type="discount",
        index_uid=index_uid,
    )

    monkeypatch.setattr(Curve, "filter", staticmethod(lambda **_kwargs: [first, second]))

    try:
        resolvers.select_curve(index_uid=index_uid, curve_type="discount")
    except ValueError as exc:
        assert "Multiple curve rows match" in str(exc)
    else:
        raise AssertionError("Expected ambiguous curve selection to fail.")


def test_resolve_quantlib_index_uses_backend_index_uid_and_curve_identity(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    curve = Curve(
        uid=uuid.uuid4(),
        unique_identifier="USD-SOFR-DISCOUNT",
        display_name="USD SOFR Discount",
        curve_type="discount",
        index_uid=index_uid,
    )
    calls = []

    monkeypatch.setattr(
        Index,
        "get_by_uid",
        staticmethod(lambda uid: calls.append(("index", uid)) or Index(
            uid=uid,
            unique_identifier="USD-SOFR",
            display_name="USD SOFR",
        )),
    )
    monkeypatch.setattr(
        IndexConventionDetails,
        "get_by_index_uid",
        staticmethod(lambda uid: calls.append(("convention", uid)) or _convention(uid)),
    )
    monkeypatch.setattr(
        Curve,
        "filter",
        staticmethod(lambda **kwargs: calls.append(("curve_filter", kwargs)) or [curve]),
    )
    monkeypatch.setattr(
        resolvers.data_interface,
        "get_historical_discount_curve",
        lambda curve_unique_identifier, target_date: (
            calls.append(("curve_data", curve_unique_identifier, target_date))
            or ([{"days_to_maturity": 1, "zero": 0.05}], target_date)
        ),
    )
    monkeypatch.setattr(
        resolvers,
        "add_historical_fixings",
        lambda target_date, ibor_index, *, reference_rate_uid: calls.append(
            ("fixings", target_date, reference_rate_uid)
        ),
    )

    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    index = resolvers.resolve_quantlib_index(
        index_uid,
        valuation_date=valuation_date,
        hydrate_fixings=True,
    )

    assert isinstance(index, ql.IborIndex)
    assert calls == [
        ("index", index_uid),
        ("convention", index_uid),
        ("convention", index_uid),
        (
            "curve_filter",
            {
                "limit": 2,
                "index_uid": index_uid,
                "curve_type": "discount",
            },
        ),
        ("curve_data", "USD-SOFR-DISCOUNT", valuation_date),
        ("fixings", ql.Date(27, 5, 2026), "USD-SOFR"),
    ]
