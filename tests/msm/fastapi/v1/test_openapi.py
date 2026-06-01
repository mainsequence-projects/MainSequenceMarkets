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

    asset_summary_operation = payload["paths"]["/api/v1/asset/{uid}/summary/"]["get"]
    assert asset_summary_operation["summary"] == "Get asset summary"
    assert asset_summary_operation["operationId"] == "getAssetSummary"
    assert asset_summary_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FrontEndDetailSummary"
    }

    asset_pricing_details_operation = payload["paths"]["/api/v1/asset/{uid}/get_pricing_details/"][
        "get"
    ]
    assert asset_pricing_details_operation["summary"] == "Get asset pricing details"
    assert asset_pricing_details_operation["operationId"] == "getAssetPricingDetails"
    assert asset_pricing_details_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AssetCurrentPricingDetailsResponse"}


def test_openapi_json_documents_account_list_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    account_list_operation = payload["paths"]["/api/v1/account/"]["get"]
    assert account_list_operation["summary"] == "List accounts"
    assert account_list_operation["operationId"] == "listAccounts"
    assert account_list_operation["tags"] == ["account"]
    assert account_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccountListResponse"
    }

    account_summary_operation = payload["paths"]["/api/v1/account/{uid}/summary/"]["get"]
    assert account_summary_operation["summary"] == "Get account summary"
    assert account_summary_operation["operationId"] == "getAccountSummary"
    assert account_summary_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/FrontEndDetailSummary"}


def test_openapi_json_documents_asset_category_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    asset_category_list_operation = payload["paths"]["/api/v1/asset-category/"]["get"]
    assert asset_category_list_operation["summary"] == "List asset categories"
    assert asset_category_list_operation["operationId"] == "listAssetCategories"
    assert asset_category_list_operation["tags"] == ["asset-category"]
    assert asset_category_list_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AssetCategoryListResponse"}

    asset_category_detail_operation = payload["paths"]["/api/v1/asset-category/{uid}/"]["get"]
    assert asset_category_detail_operation["summary"] == "Get asset category detail"
    assert asset_category_detail_operation["operationId"] == "getAssetCategoryDetail"
    assert asset_category_detail_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AssetCategoryDetailResponse"}

    asset_category_bulk_delete_operation = payload["paths"]["/api/v1/asset-category/bulk-delete/"][
        "post"
    ]
    assert asset_category_bulk_delete_operation["summary"] == "Bulk delete asset categories"
    assert asset_category_bulk_delete_operation["operationId"] == "bulkDeleteAssetCategories"
    assert asset_category_bulk_delete_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/BulkDeleteAssetCategoriesResponse"}


def test_openapi_json_documents_index_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    index_list_operation = payload["paths"]["/api/v1/index/"]["get"]
    assert index_list_operation["summary"] == "List indexes"
    assert index_list_operation["operationId"] == "listIndexes"
    assert index_list_operation["tags"] == ["index"]
    assert index_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "items": {"$ref": "#/components/schemas/IndexListRow"},
        "type": "array",
        "title": "Response Listindexes",
    }

    index_detail_operation = payload["paths"]["/api/v1/index/{uid}/"]["get"]
    assert index_detail_operation["summary"] == "Get index"
    assert index_detail_operation["operationId"] == "getIndex"
    assert index_detail_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/IndexRecord"
    }

    index_delete_operation = payload["paths"]["/api/v1/index/{uid}/"]["delete"]
    assert index_delete_operation["summary"] == "Delete index"
    assert index_delete_operation["operationId"] == "deleteIndex"
    assert index_delete_operation["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_openapi_json_documents_catalogue_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    catalog_list_operation = payload["paths"]["/api/v1/catalog/"]["get"]
    assert catalog_list_operation["summary"] == "List catalogues"
    assert catalog_list_operation["operationId"] == "listCatalogues"
    assert catalog_list_operation["tags"] == ["catalog"]
    assert catalog_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CatalogListResponse"
    }

    catalog_rows_operation = payload["paths"]["/api/v1/catalog/{catalog_uid}/rows/"]["get"]
    assert catalog_rows_operation["summary"] == "List catalogue rows"
    assert catalog_rows_operation["operationId"] == "listCatalogueRows"
    assert catalog_rows_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CatalogRowsResponse"
    }

    catalog_delete_operation = payload["paths"]["/api/v1/catalog/{catalog_uid}/rows/{uid}/"][
        "delete"
    ]
    assert catalog_delete_operation["summary"] == "Delete catalogue row"
    assert catalog_delete_operation["operationId"] == "deleteCatalogueRow"
    assert catalog_delete_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/CatalogDeleteResponse"}
