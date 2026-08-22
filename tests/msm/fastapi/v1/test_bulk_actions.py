from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.services import asset_categories, portfolio_groups, portfolios


@pytest.mark.parametrize(
    ("path", "action_id", "endpoint", "preflight_endpoint"),
    [
        (
            "/api/v1/asset-category/discovery/",
            "bulk-delete-asset-categories",
            "/api/v1/asset-category/bulk-delete/",
            "/api/v1/asset-category/bulk-delete/preflight/",
        ),
        (
            "/api/v1/portfolio/discovery/",
            "bulk-delete-portfolios",
            "/api/v1/portfolio/bulk-delete/",
            "/api/v1/portfolio/bulk-delete/preflight/",
        ),
        (
            "/api/v1/portfolio-group/discovery/",
            "bulk-delete-portfolio-groups",
            "/api/v1/portfolio-group/bulk-delete/",
            "/api/v1/portfolio-group/bulk-delete/preflight/",
        ),
    ],
)
def test_bulk_action_discovery_uses_sdk_contract(
    path: str,
    action_id: str,
    endpoint: str,
    preflight_endpoint: str,
) -> None:
    response = TestClient(app).get(path)

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract"] == "command-center.resource_discovery@v1"
    assert len(payload["bulk_actions"]) == 1
    action = payload["bulk_actions"][0]
    assert action["id"] == action_id
    assert action["endpoint"] == endpoint
    assert action["preflight_endpoint"] == preflight_endpoint
    assert action["selection_modes"] == ["explicit"]


@pytest.mark.parametrize(
    ("path", "monkeypatch_target"),
    [
        (
            "/api/v1/asset-category/bulk-delete/preflight/",
            "apps.v1.routers.asset_categories.preflight_bulk_delete_asset_categories",
        ),
        (
            "/api/v1/portfolio/bulk-delete/preflight/",
            "apps.v1.routers.portfolios.preflight_bulk_delete_portfolios",
        ),
        (
            "/api/v1/portfolio-group/bulk-delete/preflight/",
            "apps.v1.routers.portfolio_groups.preflight_bulk_delete_portfolio_groups",
        ),
    ],
)
def test_bulk_action_preflight_preserves_blockers(
    monkeypatch,
    path: str,
    monkeypatch_target: str,
) -> None:
    resource_uid = uuid.uuid4()
    monkeypatch.setattr(
        monkeypatch_target,
        lambda **kwargs: {
            "allowed": False,
            "detail": "Selection is blocked.",
            "matched_count": len(kwargs["uids"]),
            "blockers": ["Protected reference exists."],
            "warnings": [],
            "domain_context": {"resource_uid": str(resource_uid)},
        },
    )

    response = TestClient(app).post(
        path,
        json={
            "selection": {"mode": "explicit", "uids": [str(resource_uid)]},
            "options": {},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "allowed": False,
        "detail": "Selection is blocked.",
        "matched_count": 1,
        "blockers": ["Protected reference exists."],
        "warnings": [],
        "domain_context": {"resource_uid": str(resource_uid)},
    }


def test_bulk_action_execution_reauthorizes_before_delete(monkeypatch) -> None:
    resource_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.preflight_bulk_delete_asset_categories",
        lambda **kwargs: {
            "allowed": False,
            "matched_count": 1,
            "blockers": ["Protected reference exists."],
            "warnings": [],
        },
    )

    def unexpected_delete(*args, **kwargs):
        raise AssertionError("Deletion must not run after a blocked preflight.")

    monkeypatch.setattr(
        "apps.v1.routers.asset_categories.bulk_delete_asset_categories",
        unexpected_delete,
    )

    response = TestClient(app).post(
        "/api/v1/asset-category/bulk-delete/",
        json={
            "selection": {"mode": "explicit", "uids": [str(resource_uid)]},
            "options": {},
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Protected reference exists."}


def test_bulk_action_execution_rejects_unadvertised_selection_mode() -> None:
    response = TestClient(app).post(
        "/api/v1/portfolio/bulk-delete/preflight/",
        json={
            "selection": {
                "mode": "all_matching",
                "query": {"search": "rates", "filters": {}},
            },
            "options": {},
        },
    )

    assert response.status_code == 400
    assert "explicit UID selection" in response.json()["detail"]


def test_bulk_action_execution_rejects_undeclared_options() -> None:
    response = TestClient(app).post(
        "/api/v1/portfolio-group/bulk-delete/preflight/",
        json={
            "selection": {"mode": "explicit", "uids": [str(uuid.uuid4())]},
            "options": {"cascade": True},
        },
    )

    assert response.status_code == 400
    assert "does not support options" in response.json()["detail"]


def test_legacy_bulk_delete_payload_is_rejected() -> None:
    response = TestClient(app).post(
        "/api/v1/asset-category/bulk-delete/",
        json={"uids": [str(uuid.uuid4())], "select_all": False},
    )

    assert response.status_code == 422


def test_bulk_action_operations_are_exposed_by_command_center_adapter() -> None:
    response = TestClient(app).get("/.well-known/command-center/connection-contract")
    assert response.status_code == 200
    operations = {
        operation["operationId"]: operation
        for operation in response.json()["availableOperations"]
    }

    for operation_id in (
        "discoverAssetCategories",
        "preflightBulkDeleteAssetCategories",
        "discoverPortfolios",
        "preflightBulkDeletePortfolios",
        "discoverPortfolioGroups",
        "preflightBulkDeletePortfolioGroups",
    ):
        assert operations[operation_id]["kind"] == "resource"

    for operation_id in (
        "bulkDeleteAssetCategories",
        "bulkDeletePortfolios",
        "bulkDeletePortfolioGroups",
    ):
        assert operations[operation_id]["kind"] == "mutation"


def test_asset_category_preflight_is_owned_by_apps_v1(monkeypatch) -> None:
    existing_uid = str(uuid.uuid4())
    missing_uid = str(uuid.uuid4())
    monkeypatch.setattr(
        asset_categories,
        "_get_runtime",
        lambda: SimpleNamespace(context=object()),
    )
    monkeypatch.setattr(
        asset_categories,
        "_get_asset_category_frontend_detail",
        lambda context, uid: {"uid": uid} if uid == existing_uid else None,
    )

    result = asset_categories.preflight_bulk_delete_asset_categories(
        uids=[existing_uid, missing_uid, existing_uid]
    )

    assert result.model_dump() == {
        "allowed": False,
        "detail": "The asset-category selection cannot be deleted as submitted.",
        "matched_count": 1,
        "blockers": [f"Asset category {missing_uid} was not found."],
        "warnings": [],
    }


def test_portfolio_group_preflight_is_owned_by_apps_v1(monkeypatch) -> None:
    first_uid = str(uuid.uuid4())
    second_uid = str(uuid.uuid4())
    monkeypatch.setattr(
        portfolio_groups,
        "_get_runtime",
        lambda: SimpleNamespace(context=object()),
    )
    monkeypatch.setattr(
        portfolio_groups,
        "_get_portfolio_group_by_uid",
        lambda context, uid: {"results": [{"uid": uid}]},
    )

    result = portfolio_groups.preflight_bulk_delete_portfolio_groups(
        uids=[first_uid, second_uid]
    )

    assert result.model_dump() == {
        "allowed": True,
        "detail": "2 portfolio groups are ready for deletion.",
        "matched_count": 2,
        "blockers": [],
        "warnings": [],
    }


def test_portfolio_preflight_is_owned_by_apps_v1(monkeypatch) -> None:
    portfolio_uid = str(uuid.uuid4())
    monkeypatch.setattr(
        portfolios,
        "_get_runtime",
        lambda: SimpleNamespace(context=object()),
    )
    monkeypatch.setattr(
        portfolios,
        "_portfolio_delete_preflight_item",
        lambda context, uid: (True, ["VirtualFundTable references this portfolio."]),
    )

    result = portfolios.preflight_bulk_delete_portfolios(uids=[portfolio_uid])

    assert result.model_dump() == {
        "allowed": False,
        "detail": "The portfolio selection cannot be deleted as submitted.",
        "matched_count": 1,
        "blockers": [
            f"Portfolio {portfolio_uid}: VirtualFundTable references this portfolio."
        ],
        "warnings": [],
    }
