from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app


def test_get_catalogues_returns_catalogue_list(monkeypatch) -> None:
    catalog_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.catalog.list_catalogs",
        lambda **kwargs: {
            "results": [
                {
                    "uid": str(catalog_uid),
                    "namespace": "mainsequence.examples",
                    "identifier": "Asset",
                    "description": None,
                    "model_name": "AssetTable",
                    "meta_table_uid": "asset-meta-table-uid",
                    "contract_hash": "contract-hash",
                    "sdk_version": "4.0.12",
                    "created_at": "2026-05-28T00:00:00+00:00",
                    "updated_at": "2026-05-28T00:00:00+00:00",
                    "supports_row_listing": True,
                    "supports_row_delete": True,
                    "rows_endpoint": f"/api/v1/catalog/{catalog_uid}/rows/",
                    "delete_endpoint_template": f"/api/v1/catalog/{catalog_uid}/rows/{{uid}}/",
                    "physical_schema": "ignored",
                    "physical_table_name": "ignored",
                }
            ],
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
        },
    )

    client = TestClient(app)
    response = client.get("/api/v1/catalog/", params={"limit": 25, "offset": 0})

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "results": [
            {
                "uid": str(catalog_uid),
                "namespace": "mainsequence.examples",
                "identifier": "Asset",
                "description": None,
                "model_name": "AssetTable",
                "meta_table_uid": "asset-meta-table-uid",
                "contract_hash": "contract-hash",
                "sdk_version": "4.0.12",
                "created_at": "2026-05-28T00:00:00+00:00",
                "updated_at": "2026-05-28T00:00:00+00:00",
                "supports_row_listing": True,
                "supports_row_delete": True,
                "rows_endpoint": f"/api/v1/catalog/{catalog_uid}/rows/",
                "delete_endpoint_template": f"/api/v1/catalog/{catalog_uid}/rows/{{uid}}/",
            }
        ],
        "limit": 25,
        "offset": 0,
    }
    assert "physical_schema" not in payload["results"][0]
    assert "physical_table_name" not in payload["results"][0]


def test_get_catalogue_rows_returns_generic_rows(monkeypatch) -> None:
    catalog_uid = uuid.uuid4()
    row_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.catalog.list_catalog_rows",
        lambda **kwargs: {
            "catalog": {
                "uid": str(catalog_uid),
                "identifier": "Asset",
                "model_name": "AssetTable",
                "meta_table_uid": "asset-meta-table-uid",
            },
            "columns": [
                {
                    "name": "uid",
                    "type": "UUID",
                    "nullable": False,
                    "primary_key": True,
                }
            ],
            "results": [
                {
                    "uid": str(row_uid),
                    "values": {
                        "uid": str(row_uid),
                        "unique_identifier": "ASSET__BTC",
                    },
                }
            ],
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
        },
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/catalog/{catalog_uid}/rows/",
        params={"limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    assert response.json() == {
        "catalog": {
            "uid": str(catalog_uid),
            "identifier": "Asset",
            "model_name": "AssetTable",
            "meta_table_uid": "asset-meta-table-uid",
        },
        "columns": [
            {
                "name": "uid",
                "type": "UUID",
                "nullable": False,
                "primary_key": True,
            }
        ],
        "results": [
            {
                "uid": str(row_uid),
                "values": {
                    "uid": str(row_uid),
                    "unique_identifier": "ASSET__BTC",
                },
            }
        ],
        "limit": 10,
        "offset": 0,
    }


def test_delete_catalogue_row_returns_delete_contract(monkeypatch) -> None:
    catalog_uid = uuid.uuid4()
    row_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.catalog.delete_catalog_row",
        lambda **kwargs: {
            "detail": "Deleted catalogue row.",
            "catalog_uid": str(catalog_uid),
            "meta_table_uid": "asset-meta-table-uid",
            "uid": str(row_uid),
            "deleted_count": 1,
            "cascade": True,
        },
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/catalog/{catalog_uid}/rows/{row_uid}/")

    assert response.status_code == 200
    assert response.json() == {
        "detail": "Deleted catalogue row.",
        "catalog_uid": str(catalog_uid),
        "meta_table_uid": "asset-meta-table-uid",
        "uid": str(row_uid),
        "deleted_count": 1,
        "cascade": True,
    }


def test_delete_catalogue_row_returns_404_when_missing(monkeypatch) -> None:
    catalog_uid = uuid.uuid4()
    row_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.catalog.delete_catalog_row",
        lambda **kwargs: {
            "detail": "Catalog row was not found.",
            "catalog_uid": str(catalog_uid),
            "meta_table_uid": "asset-meta-table-uid",
            "uid": str(row_uid),
            "deleted_count": 0,
            "cascade": True,
        },
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/catalog/{catalog_uid}/rows/{row_uid}/")

    assert response.status_code == 404
    assert str(row_uid) in response.json()["detail"]
