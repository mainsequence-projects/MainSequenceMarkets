from __future__ import annotations

from fastapi.testclient import TestClient

from apps.v1.main import app


def test_openapi_json_exposes_core_api_metadata() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    assert payload["openapi"].startswith("3.")
    assert payload["info"]["title"] == "MainSequence Markets Public API"
    assert payload["info"]["version"]
    assert payload["info"]["x-app-scope"] == "apps/v1"
    assert payload["servers"] == [{"url": "/", "description": "Current deployment"}]


def test_openapi_json_documents_asset_list_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    asset_list_operation = payload["paths"]["/api/v1/asset/"]["get"]
    assert asset_list_operation["summary"] == "List assets"
    assert asset_list_operation["operationId"] == "listAssets"
    assert asset_list_operation["tags"] == ["asset"]
    assert asset_list_operation["parameters"][0]["name"] == "response_format"
    assert asset_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "items": {"$ref": "#/components/schemas/AssetListRow"},
        "type": "array",
        "title": "Response Listassets",
    }
    assert asset_list_operation["responses"]["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_openapi_json_documents_asset_category_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    asset_category_list_operation = payload["paths"]["/api/v1/asset-category/"]["get"]
    assert asset_category_list_operation["summary"] == "List asset categories"
    assert asset_category_list_operation["operationId"] == "listAssetCategories"
    assert asset_category_list_operation["tags"] == ["asset-category"]
    assert asset_category_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AssetCategoryListResponse"
    }

    asset_category_detail_operation = payload["paths"]["/api/v1/asset-category/{uid}/"]["get"]
    assert asset_category_detail_operation["summary"] == "Get asset category detail"
    assert asset_category_detail_operation["operationId"] == "getAssetCategoryDetail"
    assert asset_category_detail_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AssetCategoryDetailResponse"
    }

    asset_category_bulk_delete_operation = payload["paths"]["/api/v1/asset-category/bulk-delete/"]["post"]
    assert asset_category_bulk_delete_operation["summary"] == "Bulk delete asset categories"
    assert asset_category_bulk_delete_operation["operationId"] == "bulkDeleteAssetCategories"
    assert asset_category_bulk_delete_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BulkDeleteAssetCategoriesResponse"
    }
