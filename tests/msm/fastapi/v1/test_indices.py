from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.services import indices as index_service


def test_get_indexes_returns_core_index_rows(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.indices.list_indices",
        lambda **kwargs: [
            {
                "uid": str(index_uid),
                "unique_identifier": "SPX",
                "index_type": "equity",
                "display_name": "S&P 500 Index",
                "description": "Large-cap US equity index",
                "provider": "example",
                "metadata_json": {"currency": "USD"},
            }
        ],
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/index/",
        params={
            "response_format": "frontend_list",
            "search": "spx",
            "limit": 10,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "next": None,
        "previous": None,
        "results": [
            {
                "uid": str(index_uid),
                "unique_identifier": "SPX",
                "index_type": "equity",
                "display_name": "S&P 500 Index",
                "description": "Large-cap US equity index",
                "provider": "example",
                "metadata_json": {"currency": "USD"},
            }
        ],
    }


def test_get_indexes_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/index/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 400
    assert "frontend_list" in response.json()["detail"]


def test_get_index_returns_record(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.indices.get_index",
        lambda uid: {
            "uid": str(index_uid),
            "unique_identifier": "SPX",
            "index_type": "equity",
            "display_name": "S&P 500 Index",
            "description": "Large-cap US equity index",
            "provider": "example",
            "metadata_json": {"currency": "USD"},
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/index/{index_uid}/")

    assert response.status_code == 200
    assert response.json() == {
        "uid": str(index_uid),
        "unique_identifier": "SPX",
        "index_type": "equity",
        "display_name": "S&P 500 Index",
        "description": "Large-cap US equity index",
        "provider": "example",
        "metadata_json": {"currency": "USD"},
    }


def test_get_index_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.indices.get_index",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/index/missing-index/")

    assert response.status_code == 404
    assert "missing-index" in response.json()["detail"]


def test_get_index_delete_impact_returns_preflight_summary(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.indices.get_index_delete_impact",
        lambda uid: {
            "resource_type": "index",
            "uid": str(index_uid),
            "identifier": "MX-TIIE",
            "display_name": "TIIE",
            "can_delete": False,
            "blocking_count": 2,
            "affected_count": 5,
            "delete_endpoint": f"/api/v1/index/{index_uid}/",
            "relationships": [
                {
                    "key": "index_fixings",
                    "label": "Index fixings",
                    "model": "IndexFixingsStorage",
                    "column": "index_identifier",
                    "relationship_type": "direct",
                    "on_delete": "RESTRICT",
                    "count": 2,
                    "effect": "blocks_delete",
                    "severity": "blocking",
                    "blocks_delete": True,
                    "description": "Fixings reference this index.",
                },
                {
                    "key": "portfolio_published_index",
                    "label": "Published portfolio links",
                    "model": "PortfolioTable",
                    "column": "published_index_uid",
                    "relationship_type": "direct",
                    "on_delete": "SET NULL",
                    "count": 3,
                    "effect": "set_null",
                    "severity": "mutating",
                    "blocks_delete": False,
                    "description": "Portfolio links are nulled.",
                },
            ],
            "warnings": ["Delete is blocked while RESTRICT dependencies reference this index."],
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/index/{index_uid}/delete-impact/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resource_type"] == "index"
    assert payload["uid"] == str(index_uid)
    assert payload["identifier"] == "MX-TIIE"
    assert payload["can_delete"] is False
    assert payload["blocking_count"] == 2
    assert payload["affected_count"] == 5
    assert payload["relationships"][0]["key"] == "index_fixings"
    assert payload["relationships"][0]["severity"] == "blocking"
    assert payload["relationships"][0]["blocks_delete"] is True
    assert payload["relationships"][1]["effect"] == "set_null"
    assert payload["relationships"][1]["severity"] == "mutating"


def test_get_index_delete_impact_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.indices.get_index_delete_impact",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/index/missing-index/delete-impact/")

    assert response.status_code == 404
    assert "missing-index" in response.json()["detail"]


def test_index_delete_impact_service_counts_dependency_effects(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    calls: list[tuple[object, str, dict[str, object]]] = []

    monkeypatch.setattr(
        index_service,
        "_get_delete_impact_runtime",
        lambda: SimpleNamespace(context="core-context"),
    )
    monkeypatch.setattr(
        index_service,
        "_get_delete_impact_pricing_runtime",
        lambda: SimpleNamespace(context="pricing-context"),
    )
    monkeypatch.setattr(
        index_service,
        "_get_index_record",
        lambda context, uid: {
            "uid": str(index_uid),
            "unique_identifier": "MX-TIIE",
            "display_name": "TIIE",
        },
    )

    counts = {
        ("core-context", "FutureAssetDetailsTable"): 1,
        ("pricing-context", "IndexFixingsStorage"): 2,
        ("core-context", "PortfolioTable"): 3,
        ("pricing-context", "IndexConventionDetailsTable"): 1,
        ("pricing-context", "PricingMarketDataSetCurveBindingTable"): 4,
    }

    def fake_count_model(context, *, model, filters):
        calls.append((context, model.__name__, filters))
        return {"rows": [{"count": counts[(context, model.__name__)]}]}

    monkeypatch.setattr("msm.repositories.crud.count_model", fake_count_model)

    response = index_service.get_index_delete_impact(uid=str(index_uid))

    assert response is not None
    assert response.resource_type == "index"
    assert response.identifier == "MX-TIIE"
    assert response.can_delete is False
    assert response.blocking_count == 7
    assert response.affected_count == 11
    assert [relationship.key for relationship in response.relationships] == [
        "future_asset_details",
        "index_fixings",
        "portfolio_published_index",
        "index_convention_details",
        "pricing_curve_selections",
    ]
    assert [relationship.severity for relationship in response.relationships] == [
        "blocking",
        "blocking",
        "mutating",
        "destructive",
        "blocking",
    ]
    assert calls == [
        ("core-context", "FutureAssetDetailsTable", {"underlying_index_uid": str(index_uid)}),
        ("pricing-context", "IndexFixingsStorage", {"index_identifier": "MX-TIIE"}),
        ("core-context", "PortfolioTable", {"published_index_uid": str(index_uid)}),
        ("pricing-context", "IndexConventionDetailsTable", {"index_uid": str(index_uid)}),
        (
            "pricing-context",
            "PricingMarketDataSetCurveBindingTable",
            {
                "selector_type": "index",
                "selector_key": str(index_uid),
            },
        ),
    ]


def test_delete_index_returns_null(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.indices.delete_index",
        lambda uid: True,
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/index/{uuid.uuid4()}/")

    assert response.status_code == 200
    assert response.json() is None


def test_delete_index_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.indices.delete_index",
        lambda uid: False,
    )

    client = TestClient(app)
    response = client.delete("/api/v1/index/missing-index/")

    assert response.status_code == 404
    assert "missing-index" in response.json()["detail"]
