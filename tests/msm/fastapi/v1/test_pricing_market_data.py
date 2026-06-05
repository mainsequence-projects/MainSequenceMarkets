from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.schemas.pricing_market_data import (
    PricingMarketDataSet,
    PricingMarketDataSetBinding,
)


def _market_data_set_row(uid: uuid.UUID | None = None) -> PricingMarketDataSet:
    return PricingMarketDataSet(
        uid=uid or uuid.uuid4(),
        set_key="default",
        display_name="Default pricing market data",
        description=None,
        status="ACTIVE",
        metadata_json=None,
    )


def _binding_row(
    *,
    uid: uuid.UUID | None = None,
    market_data_set_uid: uuid.UUID | None = None,
    data_node_uid: uuid.UUID | None = None,
) -> PricingMarketDataSetBinding:
    return PricingMarketDataSetBinding(
        uid=uid or uuid.uuid4(),
        market_data_set_uid=market_data_set_uid or uuid.uuid4(),
        concept_key="discount_curves",
        data_node_uid=data_node_uid or uuid.uuid4(),
        storage_table_identifier="DiscountCurvesStorage",
        source="unit-test",
        metadata_json=None,
    )


def test_pricing_market_data_card_returns_resource_links() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/pricing/market_data/")

    assert response.status_code == 200
    assert response.json() == {
        "resource": "pricing_market_data",
        "description": "Manage pricing market-data sets and concept bindings.",
        "resources": [
            {
                "key": "sets",
                "model": "PricingMarketDataSet",
                "list_url": "/api/v1/pricing/market_data/sets/",
                "create_url": "/api/v1/pricing/market_data/sets/",
                "upsert_url": "/api/v1/pricing/market_data/sets/upsert/",
            },
            {
                "key": "bindings",
                "model": "PricingMarketDataSetBinding",
                "list_url": "/api/v1/pricing/market_data/bindings/",
                "create_url": "/api/v1/pricing/market_data/bindings/",
                "upsert_url": "/api/v1/pricing/market_data/bindings/upsert/",
            },
        ],
    }


def test_pricing_market_data_set_list_uses_paginated_source_list(monkeypatch) -> None:
    row = _market_data_set_row()
    captured: dict[str, object] = {}

    def fake_list_sets(**kwargs):
        captured.update(kwargs)
        return {"count": 2, "limit": kwargs["limit"], "offset": kwargs["offset"], "results": [row]}

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.list_pricing_market_data_sets",
        fake_list_sets,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/pricing/market_data/sets/",
        params={"limit": 1, "offset": 0, "status": "ACTIVE", "set_key": "default"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 2,
        "next": "http://testserver/api/v1/pricing/market_data/sets/?limit=1&offset=1&status=ACTIVE&set_key=default",
        "previous": None,
        "results": [
            {
                "uid": str(row.uid),
                "set_key": "default",
                "display_name": "Default pricing market data",
                "description": None,
                "status": "ACTIVE",
                "metadata_json": None,
            }
        ],
    }
    assert captured == {
        "limit": 1,
        "offset": 0,
        "status": "ACTIVE",
        "set_key": "default",
    }


def test_pricing_market_data_set_detail_returns_row(monkeypatch) -> None:
    row = _market_data_set_row()

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.get_pricing_market_data_set",
        lambda uid: row,
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/pricing/market_data/sets/{row.uid}/")

    assert response.status_code == 200
    assert response.json()["uid"] == str(row.uid)
    assert response.json()["set_key"] == "default"


def test_pricing_market_data_set_detail_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.get_pricing_market_data_set",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/pricing/market_data/sets/missing-set/")

    assert response.status_code == 404
    assert "missing-set" in response.json()["detail"]


def test_pricing_market_data_set_by_key_wraps_source_lookup(monkeypatch) -> None:
    row = _market_data_set_row()
    captured: dict[str, object] = {}

    def fake_get_by_key(**kwargs):
        captured.update(kwargs)
        return row

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.get_pricing_market_data_set_by_key",
        fake_get_by_key,
    )

    client = TestClient(app)
    response = client.get("/api/v1/pricing/market_data/sets/by-key/default/")

    assert response.status_code == 200
    assert response.json()["uid"] == str(row.uid)
    assert captured == {"set_key": "default"}


def test_pricing_market_data_set_create_wraps_source_create(monkeypatch) -> None:
    row = _market_data_set_row()
    captured: dict[str, object] = {}

    def fake_create(payload):
        captured["payload"] = payload.model_dump()
        return row

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.create_pricing_market_data_set",
        fake_create,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/pricing/market_data/sets/",
        json={"set_key": "default", "display_name": "Default pricing market data"},
    )

    assert response.status_code == 201
    assert response.json()["uid"] == str(row.uid)
    assert captured == {
        "payload": {
            "set_key": "default",
            "display_name": "Default pricing market data",
            "description": None,
            "status": "ACTIVE",
            "metadata_json": None,
        }
    }


def test_pricing_market_data_set_upsert_wraps_source_upsert(monkeypatch) -> None:
    row = _market_data_set_row()
    captured: dict[str, object] = {}

    def fake_upsert(payload):
        captured["payload"] = payload.model_dump()
        return row

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.upsert_pricing_market_data_set",
        fake_upsert,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/pricing/market_data/sets/upsert/",
        json={"set_key": "default", "display_name": "Default pricing market data"},
    )

    assert response.status_code == 200
    assert response.json()["uid"] == str(row.uid)
    assert captured["payload"]["set_key"] == "default"


def test_pricing_market_data_set_update_wraps_source_update(monkeypatch) -> None:
    row = _market_data_set_row()
    captured: dict[str, object] = {}

    def fake_update(**kwargs):
        captured["uid"] = kwargs["uid"]
        captured["payload"] = kwargs["payload"].model_dump(exclude_unset=True)
        return row

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.update_pricing_market_data_set",
        fake_update,
    )

    client = TestClient(app)
    response = client.patch(
        f"/api/v1/pricing/market_data/sets/{row.uid}/",
        json={"description": "Updated"},
    )

    assert response.status_code == 200
    assert captured == {"uid": str(row.uid), "payload": {"description": "Updated"}}


def test_pricing_market_data_set_delete_wraps_source_delete(monkeypatch) -> None:
    row_uid = uuid.uuid4()

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.delete_pricing_market_data_set",
        lambda uid: {
            "detail": "Deleted pricing market-data set.",
            "uid": uid,
            "deleted_count": 1,
        },
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/pricing/market_data/sets/{row_uid}/")

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Deleted pricing market-data set.",
        "uid": str(row_uid),
        "deleted_count": 1,
    }


def test_pricing_market_data_binding_global_list_uses_paginated_source_list(
    monkeypatch,
) -> None:
    market_data_set_uid = uuid.uuid4()
    row = _binding_row(market_data_set_uid=market_data_set_uid)
    captured: dict[str, object] = {}

    def fake_list_bindings(**kwargs):
        captured.update(kwargs)
        return {"count": 1, "limit": kwargs["limit"], "offset": kwargs["offset"], "results": [row]}

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.list_pricing_market_data_bindings",
        fake_list_bindings,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/pricing/market_data/bindings/",
        params={
            "limit": 25,
            "offset": 0,
            "market_data_set_uid": str(market_data_set_uid),
            "concept_key": "discount_curves",
        },
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["uid"] == str(row.uid)
    assert captured == {
        "limit": 25,
        "offset": 0,
        "market_data_set_uid": str(market_data_set_uid),
        "concept_key": "discount_curves",
    }


def test_pricing_market_data_binding_nested_list_filters_by_set(monkeypatch) -> None:
    market_data_set_uid = uuid.uuid4()
    row = _binding_row(market_data_set_uid=market_data_set_uid)
    captured: dict[str, object] = {}

    def fake_list_set_bindings(**kwargs):
        captured.update(kwargs)
        return {"count": 1, "limit": kwargs["limit"], "offset": kwargs["offset"], "results": [row]}

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.list_pricing_market_data_set_bindings",
        fake_list_set_bindings,
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/pricing/market_data/sets/{market_data_set_uid}/bindings/",
        params={"limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["market_data_set_uid"] == str(market_data_set_uid)
    assert captured == {
        "market_data_set_uid": str(market_data_set_uid),
        "limit": 10,
        "offset": 0,
    }


def test_pricing_market_data_binding_detail_returns_row(monkeypatch) -> None:
    row = _binding_row()

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.get_pricing_market_data_binding",
        lambda uid: row,
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/pricing/market_data/bindings/{row.uid}/")

    assert response.status_code == 200
    assert response.json()["uid"] == str(row.uid)
    assert response.json()["concept_key"] == "discount_curves"


def test_pricing_market_data_binding_detail_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.get_pricing_market_data_binding",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/pricing/market_data/bindings/missing-binding/")

    assert response.status_code == 404
    assert "missing-binding" in response.json()["detail"]


def test_pricing_market_data_binding_resolve_wraps_source_resolution(monkeypatch) -> None:
    data_node_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_resolve(**kwargs):
        captured.update(kwargs)
        return {
            "market_data_set": kwargs["market_data_set"],
            "concept_key": kwargs["concept_key"],
            "data_node_uid": data_node_uid,
        }

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.resolve_pricing_market_data_binding",
        fake_resolve,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/pricing/market_data/bindings/resolve/",
        params={"market_data_set": "default", "concept_key": "discount_curves"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "market_data_set": "default",
        "concept_key": "discount_curves",
        "data_node_uid": str(data_node_uid),
    }
    assert captured == {"market_data_set": "default", "concept_key": "discount_curves"}


def test_pricing_market_data_binding_create_wraps_source_create(monkeypatch) -> None:
    row = _binding_row()
    captured: dict[str, object] = {}

    def fake_create(payload):
        captured["payload"] = payload.model_dump()
        return row

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.create_pricing_market_data_binding",
        fake_create,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/pricing/market_data/bindings/",
        json={
            "market_data_set_uid": str(row.market_data_set_uid),
            "concept_key": "discount_curves",
            "data_node_uid": str(row.data_node_uid),
        },
    )

    assert response.status_code == 201
    assert response.json()["uid"] == str(row.uid)
    assert captured["payload"]["market_data_set_uid"] == row.market_data_set_uid


def test_pricing_market_data_binding_upsert_wraps_source_upsert(monkeypatch) -> None:
    row = _binding_row()
    captured: dict[str, object] = {}

    def fake_upsert(payload):
        captured["payload"] = payload.model_dump()
        return row

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.upsert_pricing_market_data_binding",
        fake_upsert,
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/pricing/market_data/bindings/upsert/",
        json={
            "market_data_set_uid": str(row.market_data_set_uid),
            "concept_key": "discount_curves",
            "data_node_uid": str(row.data_node_uid),
        },
    )

    assert response.status_code == 200
    assert response.json()["uid"] == str(row.uid)
    assert captured["payload"]["concept_key"] == "discount_curves"


def test_pricing_market_data_binding_update_wraps_source_update(monkeypatch) -> None:
    row = _binding_row()
    captured: dict[str, object] = {}

    def fake_update(**kwargs):
        captured["uid"] = kwargs["uid"]
        captured["payload"] = kwargs["payload"].model_dump(exclude_unset=True)
        return row

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.update_pricing_market_data_binding",
        fake_update,
    )

    client = TestClient(app)
    response = client.patch(
        f"/api/v1/pricing/market_data/bindings/{row.uid}/",
        json={"source": "updated-source"},
    )

    assert response.status_code == 200
    assert captured == {
        "uid": str(row.uid),
        "payload": {"source": "updated-source"},
    }


def test_pricing_market_data_binding_delete_wraps_source_delete(monkeypatch) -> None:
    row_uid = uuid.uuid4()

    monkeypatch.setattr(
        "apps.v1.routers.pricing_market_data.delete_pricing_market_data_binding",
        lambda uid: {
            "detail": "Deleted pricing market-data binding.",
            "uid": uid,
            "deleted_count": 1,
        },
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/pricing/market_data/bindings/{row_uid}/")

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Deleted pricing market-data binding.",
        "uid": str(row_uid),
        "deleted_count": 1,
    }
