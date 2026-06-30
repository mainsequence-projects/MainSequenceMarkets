from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.schemas.pricing_curves import Curve


def _curve_row(
    *,
    uid: uuid.UUID | None = None,
    index_uid: uuid.UUID | None = None,
) -> Curve:
    return Curve(
        uid=uid or uuid.uuid4(),
        unique_identifier="USD-SOFR-DISCOUNT",
        display_name="USD SOFR Discount Curve",
        curve_type="discount",
        index_uid=index_uid or uuid.uuid4(),
        interpolation_method="log_linear_discount",
        compounding="compounded_annual",
        source="unit-test",
        metadata_json={"provider": "test"},
    )


def test_pricing_curve_list_uses_paginated_source_list(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    row = _curve_row(index_uid=index_uid)
    captured: dict[str, object] = {}

    def fake_list_curves(**kwargs):
        captured.update(kwargs)
        return {"count": 2, "limit": kwargs["limit"], "offset": kwargs["offset"], "results": [row]}

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.list_pricing_curves",
        fake_list_curves,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/pricing/curves/",
        params={
            "limit": 1,
            "offset": 0,
            "search": "SOFR",
            "curve_type": "discount",
            "index_uid": str(index_uid),
            "source": "unit-test",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 2,
        "next": (
            "http://testserver/api/v1/pricing/curves/?limit=1&offset=1&search=SOFR"
            f"&curve_type=discount&index_uid={index_uid}&source=unit-test"
        ),
        "previous": None,
        "results": [
            {
                "uid": str(row.uid),
                "unique_identifier": "USD-SOFR-DISCOUNT",
                "display_name": "USD SOFR Discount Curve",
                "curve_type": "discount",
                "index_uid": str(index_uid),
                "currency_code": None,
                "quote_side": None,
                "interpolation_method": "log_linear_discount",
                "compounding": "compounded_annual",
                "source": "unit-test",
                "status": "ACTIVE",
                "metadata_json": {"provider": "test"},
            }
        ],
    }
    assert captured == {
        "limit": 1,
        "offset": 0,
        "search": "SOFR",
        "curve_type": "discount",
        "index_uid": str(index_uid),
        "source": "unit-test",
    }


def test_pricing_curve_list_returns_400_for_source_value_error(monkeypatch) -> None:
    def fake_list_curves(**_kwargs):
        raise ValueError("bad curve filter")

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.list_pricing_curves",
        fake_list_curves,
    )

    client = TestClient(app)
    response = client.get("/api/v1/pricing/curves/")

    assert response.status_code == 400
    assert response.json() == {"detail": "bad curve filter"}


def test_get_pricing_curve_summary_returns_standard_summary(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.get_pricing_curve_summary",
        lambda uid: {
            "entity": {
                "id": str(curve_uid),
                "type": "pricing_curve",
                "title": "USD SOFR Discount Curve",
            },
            "badges": [
                {
                    "key": "curve_type",
                    "label": "discount",
                    "tone": "info",
                    "link_url": None,
                }
            ],
            "inline_fields": [
                {
                    "key": "uid",
                    "label": "UID",
                    "value": str(curve_uid),
                    "kind": "code",
                },
                {
                    "key": "index_uid",
                    "label": "Index UID",
                    "value": str(index_uid),
                    "kind": "code",
                },
            ],
            "highlight_fields": [
                {
                    "key": "display_name",
                    "label": "Display Name",
                    "value": "USD SOFR Discount Curve",
                    "kind": "text",
                    "icon": "database",
                }
            ],
            "stats": [],
            "label_management": None,
            "summary_warning": None,
            "extensions": {
                "curve": {
                    "uid": str(curve_uid),
                    "unique_identifier": "USD-SOFR-DISCOUNT",
                    "display_name": "USD SOFR Discount Curve",
                    "curve_type": "discount",
                    "index_uid": str(index_uid),
                }
            },
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/pricing/curves/{curve_uid}/summary/")

    assert response.status_code == 200
    assert response.json() == {
        "entity": {
            "id": str(curve_uid),
            "type": "pricing_curve",
            "title": "USD SOFR Discount Curve",
        },
        "badges": [
            {
                "key": "curve_type",
                "label": "discount",
                "tone": "info",
                "link_url": None,
            }
        ],
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                    "value": str(curve_uid),
                    "kind": "code",
                    "icon": None,
                    "link_url": None,
                },
                {
                    "key": "index_uid",
                    "label": "Index UID",
                    "value": str(index_uid),
                    "kind": "code",
                    "icon": None,
                    "link_url": None,
                },
            ],
        "highlight_fields": [
            {
                "key": "display_name",
                "label": "Display Name",
                "value": "USD SOFR Discount Curve",
                "kind": "text",
                "icon": "database",
                "link_url": None,
            }
        ],
        "stats": [],
        "label_management": None,
        "summary_warning": None,
        "extensions": {
            "curve": {
                "uid": str(curve_uid),
                "unique_identifier": "USD-SOFR-DISCOUNT",
                "display_name": "USD SOFR Discount Curve",
                "curve_type": "discount",
                "index_uid": str(index_uid),
            }
        },
    }


def test_get_pricing_curve_summary_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.get_pricing_curve_summary",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/pricing/curves/missing-curve/summary/")

    assert response.status_code == 404
    assert "missing-curve" in response.json()["detail"]


def test_get_pricing_discount_curve_returns_latest_nodes(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()
    effective_date = dt.datetime(2026, 6, 2, tzinfo=dt.UTC)
    captured: dict[str, object] = {}

    def fake_discount_curve(**kwargs):
        captured.update(kwargs)
        return {
            "curve_uid": str(curve_uid),
            "curve_identifier": "USD-SOFR-DISCOUNT",
            "curve": {
                "uid": str(curve_uid),
                "unique_identifier": "USD-SOFR-DISCOUNT",
            },
            "market_data_set": {
                "uid": str(market_data_set_uid),
                "set_key": "eod",
                "display_name": "End of day",
            },
            "binding": {
                "uid": str(binding_uid),
                "concept_key": "discount_curves",
                "data_node_uid": str(data_node_uid),
                "storage_table_identifier": "DiscountCurvesStorage",
            },
            "valuation_date": None,
            "effective_date": effective_date.isoformat(),
            "request_mode": "latest",
            "nodes": [{"days_to_maturity": 28, "zero": 0.11}],
        }

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.get_pricing_curve_discount_curve",
        fake_discount_curve,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/pricing/curves/{curve_uid}/discount-curve/",
        params={"market_data_set": "eod"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "curve_uid": str(curve_uid),
        "curve_identifier": "USD-SOFR-DISCOUNT",
        "curve": {
            "uid": str(curve_uid),
            "unique_identifier": "USD-SOFR-DISCOUNT",
        },
        "market_data_set": {
            "uid": str(market_data_set_uid),
            "set_key": "eod",
            "display_name": "End of day",
        },
        "binding": {
            "uid": str(binding_uid),
            "concept_key": "discount_curves",
            "data_node_uid": str(data_node_uid),
            "storage_table_identifier": "DiscountCurvesStorage",
        },
        "valuation_date": None,
        "effective_date": "2026-06-02T00:00:00Z",
        "request_mode": "latest",
        "nodes": [{"days_to_maturity": 28, "zero": 0.11}],
    }
    assert captured == {
        "uid": str(curve_uid),
        "market_data_set": "eod",
        "valuation_date": None,
    }


def test_get_pricing_discount_curve_passes_historical_date(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()
    valuation_date = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)
    captured: dict[str, object] = {}

    def fake_discount_curve(**kwargs):
        captured.update(kwargs)
        return {
            "curve_uid": str(curve_uid),
            "curve_identifier": "USD-SOFR-DISCOUNT",
            "curve": {"uid": str(curve_uid)},
            "market_data_set": {
                "uid": str(market_data_set_uid),
                "set_key": "eod",
                "display_name": "End of day",
            },
            "binding": {
                "uid": str(binding_uid),
                "concept_key": "discount_curves",
                "data_node_uid": str(data_node_uid),
                "storage_table_identifier": None,
            },
            "valuation_date": valuation_date.isoformat(),
            "effective_date": valuation_date.isoformat(),
            "request_mode": "historical",
            "nodes": [{"days_to_maturity": 91, "zero": 0.105}],
        }

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.get_pricing_curve_discount_curve",
        fake_discount_curve,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/pricing/curves/{curve_uid}/discount-curve/",
        params={
            "market_data_set": str(market_data_set_uid),
            "valuation_date": "2026-06-01T00:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["request_mode"] == "historical"
    assert response.json()["valuation_date"] == "2026-06-01T00:00:00Z"
    assert captured == {
        "uid": str(curve_uid),
        "market_data_set": str(market_data_set_uid),
        "valuation_date": valuation_date,
    }


def test_get_pricing_discount_curve_returns_404_for_missing_curve(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.get_pricing_curve_discount_curve",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/pricing/curves/missing-curve/discount-curve/",
        params={"market_data_set": "eod"},
    )

    assert response.status_code == 404
    assert "missing-curve" in response.json()["detail"]


def test_get_pricing_discount_curve_returns_404_for_missing_observation(monkeypatch) -> None:
    def fake_discount_curve(**kwargs):
        raise LookupError("No latest discount curve observation found")

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.get_pricing_curve_discount_curve",
        fake_discount_curve,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/pricing/curves/curve-uid/discount-curve/",
        params={"market_data_set": "eod"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "No latest discount curve observation found"}


def test_pricing_curve_summary_service_uses_pricing_api(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "apps.v1.services.pricing_curves.ensure_apps_v1_pricing_runtime", lambda: None
    )

    def fake_summary(uid):
        captured["uid"] = uid
        return {
            "entity": {
                "id": str(curve_uid),
                "type": "pricing_curve",
                "title": "USD SOFR Discount Curve",
            },
            "badges": [],
            "inline_fields": [
                {
                    "key": "index_uid",
                    "label": "Index UID",
                    "value": str(index_uid),
                    "kind": "code",
                }
            ],
            "highlight_fields": [],
            "stats": [],
            "label_management": None,
            "summary_warning": None,
            "extensions": {},
        }

    monkeypatch.setattr(
        "apps.v1.services.pricing_curves._get_curve_frontend_detail_summary", fake_summary
    )

    from apps.v1.services.pricing_curves import get_pricing_curve_summary

    response = get_pricing_curve_summary(uid=str(curve_uid))

    assert captured == {"uid": str(curve_uid)}
    assert response is not None
    assert response.entity.id == str(curve_uid)
