from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.schemas.pricing_curves import Curve
from msm_pricing.api import CurveDeleteConflictError


def _curve_row(
    *,
    uid: uuid.UUID | None = None,
) -> Curve:
    return Curve(
        uid=uid or uuid.uuid4(),
        unique_identifier="USD-SOFR-DISCOUNT",
        display_name="USD SOFR Discount Curve",
        curve_type="discount",
        interpolation_method="log_linear_discount",
        compounding="compounded_annual",
        source="unit-test",
        metadata_json={"provider": "test"},
    )


def _delete_impact_payload(
    curve_uid: uuid.UUID,
    *,
    can_delete: bool = True,
) -> dict[str, object]:
    return {
        "resource_type": "pricing_curve",
        "uid": str(curve_uid),
        "identifier": "USD-SOFR-DISCOUNT",
        "display_name": "USD SOFR Discount Curve",
        "can_delete": can_delete,
        "blocking_count": 0 if can_delete else 2,
        "affected_count": 2,
        "delete_endpoint": f"/api/v1/pricing/curves/{curve_uid}/",
        "relationships": [
            {
                "key": "pricing_curve_selections",
                "label": "Pricing curve selections",
                "model": "PricingMarketDataSetCurveBindingTable",
                "column": "curve_uid",
                "relationship_type": "direct",
                "on_delete": "RESTRICT",
                "count": 2,
                "effect": "delete_cleanup" if can_delete else "blocks_delete",
                "severity": "destructive" if can_delete else "blocking",
                "blocks_delete": not can_delete,
                "description": "Curve-selection rows point at this curve.",
            }
        ],
        "warnings": ["Pricing curve-selection rows will be deleted."]
        if can_delete
        else ["Delete is blocked while pricing curve-selection rows point at this curve."],
    }


def test_pricing_curve_list_uses_paginated_source_list(monkeypatch) -> None:
    row = _curve_row()
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
            "source": "unit-test",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 2,
        "next": (
            "http://testserver/api/v1/pricing/curves/?limit=1&offset=1&search=SOFR"
            "&curve_type=discount&source=unit-test"
        ),
        "previous": None,
        "results": [
            {
                "uid": str(row.uid),
                "unique_identifier": "USD-SOFR-DISCOUNT",
                "display_name": "USD SOFR Discount Curve",
                "curve_type": "discount",
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
    curve_selections_url = f"/api/v1/pricing/curves/{curve_uid}/curve-selections/"

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
                    "key": "curve_selection_count",
                    "label": "Curve Selections",
                    "value": 2,
                    "kind": "number",
                    "link_url": curve_selections_url,
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
                },
                "curve_selection_count": 2,
                "curve_selections_url": curve_selections_url,
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
                "key": "curve_selection_count",
                "label": "Curve Selections",
                "value": 2,
                "kind": "number",
                "icon": None,
                "link_url": curve_selections_url,
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
            },
            "curve_selection_count": 2,
            "curve_selections_url": curve_selections_url,
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


def test_list_pricing_curve_selections_returns_reverse_bindings(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    index_uid = uuid.uuid4()

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.list_pricing_curve_selections",
        lambda uid: {
            "curve": {
                "uid": str(curve_uid),
                "unique_identifier": "USD-SOFR-OFFER-BENCHMARK",
                "display_name": "USD SOFR offer benchmark",
                "curve_type": "discount",
            },
            "count": 1,
            "results": [
                {
                    "binding_uid": str(binding_uid),
                    "market_data_set": {
                        "uid": str(market_data_set_uid),
                        "set_key": "eod",
                        "display_name": "End of day",
                    },
                    "role_key": "z_spread_base",
                    "quote_side": "offer",
                    "selector": {
                        "type": "index",
                        "selector_key": str(index_uid),
                        "index_uid": str(index_uid),
                        "index_identifier": "USD-SOFR",
                        "display_name": "USD SOFR",
                    },
                    "status": "ACTIVE",
                    "source": "example",
                }
            ],
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/pricing/curves/{curve_uid}/curve-selections/")

    assert response.status_code == 200
    assert response.json() == {
        "curve": {
            "uid": str(curve_uid),
            "unique_identifier": "USD-SOFR-OFFER-BENCHMARK",
            "display_name": "USD SOFR offer benchmark",
            "curve_type": "discount",
        },
        "count": 1,
        "results": [
            {
                "binding_uid": str(binding_uid),
                "market_data_set": {
                    "uid": str(market_data_set_uid),
                    "set_key": "eod",
                    "display_name": "End of day",
                },
                "role_key": "z_spread_base",
                "quote_side": "offer",
                "selector": {
                    "type": "index",
                    "selector_key": str(index_uid),
                    "index_uid": str(index_uid),
                    "index_identifier": "USD-SOFR",
                    "display_name": "USD SOFR",
                },
                "status": "ACTIVE",
                "source": "example",
            }
        ],
    }


def test_list_pricing_curve_selections_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.list_pricing_curve_selections",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/pricing/curves/missing-curve/curve-selections/")

    assert response.status_code == 404
    assert "missing-curve" in response.json()["detail"]


def test_get_pricing_curve_delete_impact_returns_preflight(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_delete_impact(**kwargs):
        captured.update(kwargs)
        return _delete_impact_payload(curve_uid)

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.get_pricing_curve_delete_impact",
        fake_delete_impact,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/pricing/curves/{curve_uid}/delete-impact/",
        params={
            "delete_values": "true",
            "delete_curve_selections": "true",
        },
    )

    assert response.status_code == 200
    assert response.json()["uid"] == str(curve_uid)
    assert response.json()["can_delete"] is True
    assert response.json()["relationships"][0]["effect"] == "delete_cleanup"
    assert captured == {
        "uid": str(curve_uid),
        "delete_values": True,
        "delete_curve_selections": True,
    }


def test_get_pricing_curve_delete_impact_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.get_pricing_curve_delete_impact",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/pricing/curves/missing-curve/delete-impact/")

    assert response.status_code == 404
    assert "missing-curve" in response.json()["detail"]


def test_delete_pricing_curve_deletes_with_explicit_cleanup_flags(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_delete_curve(**kwargs):
        captured.update(kwargs)
        return {
            "detail": "Pricing curve deleted.",
            "uid": str(curve_uid),
            "curve_identifier": "USD-SOFR-DISCOUNT",
            "deleted_count": 1,
            "deleted_values_count": 4,
            "deleted_curve_selections_count": 2,
            "deleted_curve_building_details_count": 1,
            "delete_values": True,
            "delete_curve_selections": True,
            "storage_cleanups": [
                {
                    "data_node_uid": str(data_node_uid),
                    "storage_table_identifier": "DiscountCurvesStorage",
                    "deleted_count": 4,
                    "table_empty": False,
                }
            ],
        }

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.delete_pricing_curve",
        fake_delete_curve,
    )

    client = TestClient(app)
    response = client.delete(
        f"/api/v1/pricing/curves/{curve_uid}/",
        params={
            "delete_values": "true",
            "delete_curve_selections": "true",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Pricing curve deleted.",
        "uid": str(curve_uid),
        "curve_identifier": "USD-SOFR-DISCOUNT",
        "deleted_count": 1,
        "deleted_values_count": 4,
        "deleted_curve_selections_count": 2,
        "deleted_curve_building_details_count": 1,
        "delete_values": True,
        "delete_curve_selections": True,
        "storage_cleanups": [
            {
                "data_node_uid": str(data_node_uid),
                "storage_table_identifier": "DiscountCurvesStorage",
                "deleted_count": 4,
                "table_empty": False,
            }
        ],
    }
    assert captured == {
        "uid": str(curve_uid),
        "delete_values": True,
        "delete_curve_selections": True,
    }


def test_delete_pricing_curve_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.delete_pricing_curve",
        lambda **kwargs: None,
    )

    client = TestClient(app)
    response = client.delete("/api/v1/pricing/curves/missing-curve/")

    assert response.status_code == 404
    assert "missing-curve" in response.json()["detail"]


def test_delete_pricing_curve_returns_409_for_delete_conflict(monkeypatch) -> None:
    def fake_delete_curve(**kwargs):
        raise CurveDeleteConflictError("Pricing curve deletion is blocked.")

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.delete_pricing_curve",
        fake_delete_curve,
    )

    client = TestClient(app)
    response = client.delete("/api/v1/pricing/curves/blocked-curve/")

    assert response.status_code == 409
    assert response.json() == {"detail": "Pricing curve deletion is blocked."}


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
            "key_nodes": [{"maturity_date": "2026-06-30", "quote": 0.11}],
            "metadata_json": {"source_snapshot": "mock"},
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
        "key_nodes": [{"maturity_date": "2026-06-30", "quote": 0.11}],
        "metadata_json": {"source_snapshot": "mock"},
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
            "key_nodes": None,
            "metadata_json": None,
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
        raise LookupError(
            "No discount-curve data has been published for curve 'VALMER_TIIE_28' "
            "in pricing market-data set 'default'. The curve registry row and "
            "discount_curves binding exist, but bound DataNode data-node-uid has "
            "no latest ms_markets__discountcurvests observation for this curve_identifier."
        )

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
    detail = response.json()["detail"]
    assert "No discount-curve data has been published" in detail
    assert "VALMER_TIIE_28" in detail
    assert "bound DataNode data-node-uid" in detail


def test_pricing_curve_summary_service_uses_pricing_api(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
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
                    "key": "curve_selection_count",
                    "label": "Curve Selections",
                    "value": 0,
                    "kind": "number",
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


def test_pricing_curve_selection_service_uses_pricing_api(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    binding_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "apps.v1.services.pricing_curves.ensure_apps_v1_pricing_runtime", lambda: None
    )

    def fake_selections(uid):
        captured["uid"] = uid
        return {
            "curve": {
                "uid": str(curve_uid),
                "unique_identifier": "USD-SOFR-DISCOUNT",
                "display_name": "USD SOFR Discount Curve",
                "curve_type": "discount",
            },
            "count": 1,
            "results": [
                {
                    "binding_uid": str(binding_uid),
                    "market_data_set": {
                        "uid": str(market_data_set_uid),
                        "set_key": "eod",
                        "display_name": "End of day",
                    },
                    "role_key": "projection",
                    "quote_side": "mid",
                    "selector": {
                        "type": "index",
                        "selector_key": str(index_uid),
                        "index_uid": str(index_uid),
                        "index_identifier": "USD-SOFR",
                        "display_name": "USD SOFR",
                    },
                    "status": "ACTIVE",
                    "source": "unit-test",
                }
            ],
        }

    monkeypatch.setattr(
        "apps.v1.services.pricing_curves._list_curve_selections",
        fake_selections,
    )

    from apps.v1.services.pricing_curves import list_pricing_curve_selections

    response = list_pricing_curve_selections(uid=str(curve_uid))

    assert captured == {"uid": str(curve_uid)}
    assert response is not None
    assert response.count == 1
    assert response.results[0].selector.index_identifier == "USD-SOFR"


def test_pricing_curve_delete_impact_service_uses_pricing_api(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "apps.v1.services.pricing_curves.ensure_apps_v1_pricing_runtime",
        lambda: None,
    )

    def fake_delete_impact(**kwargs):
        captured.update(kwargs)
        return _delete_impact_payload(curve_uid)

    monkeypatch.setattr(
        "apps.v1.services.pricing_curves._get_curve_delete_impact",
        fake_delete_impact,
    )

    from apps.v1.services.pricing_curves import get_pricing_curve_delete_impact

    response = get_pricing_curve_delete_impact(
        uid=str(curve_uid),
        delete_values=True,
        delete_curve_selections=True,
    )

    assert captured == {
        "uid": str(curve_uid),
        "delete_values": True,
        "delete_curve_selections": True,
    }
    assert response is not None
    assert response.can_delete is True


def test_pricing_curve_delete_service_uses_pricing_api(monkeypatch) -> None:
    curve_uid = uuid.uuid4()
    data_node_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "apps.v1.services.pricing_curves.ensure_apps_v1_pricing_runtime",
        lambda: None,
    )

    def fake_delete_curve(**kwargs):
        captured.update(kwargs)
        return {
            "detail": "Pricing curve deleted.",
            "uid": str(curve_uid),
            "curve_identifier": "USD-SOFR-DISCOUNT",
            "deleted_count": 1,
            "deleted_values_count": 4,
            "deleted_curve_selections_count": 2,
            "deleted_curve_building_details_count": 1,
            "delete_values": True,
            "delete_curve_selections": True,
            "storage_cleanups": [
                {
                    "data_node_uid": str(data_node_uid),
                    "storage_table_identifier": "DiscountCurvesStorage",
                    "deleted_count": 4,
                    "table_empty": False,
                }
            ],
        }

    monkeypatch.setattr(
        "apps.v1.services.pricing_curves._delete_curve",
        fake_delete_curve,
    )

    from apps.v1.services.pricing_curves import delete_pricing_curve

    response = delete_pricing_curve(
        uid=str(curve_uid),
        delete_values=True,
        delete_curve_selections=True,
    )

    assert captured == {
        "uid": str(curve_uid),
        "delete_values": True,
        "delete_curve_selections": True,
    }
    assert response is not None
    assert response.deleted_values_count == 4
