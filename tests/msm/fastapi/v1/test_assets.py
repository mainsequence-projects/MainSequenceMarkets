from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.services import assets as asset_service
import msm.services.asset_master_lists as asset_master_service


def test_get_assets_returns_core_asset_rows(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())

    monkeypatch.setattr("apps.v1.services.assets._get_runtime", lambda: runtime)
    monkeypatch.setattr(
        "apps.v1.services.assets._list_asset_rows",
        lambda context, **kwargs: [
            {
                "uid": str(asset_uid),
                "unique_identifier": "BTC",
                "asset_type": "crypto",
            }
        ],
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/asset/",
        params={
            "response_format": "frontend_list",
            "search": "btc",
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
                "uid": str(asset_uid),
                "unique_identifier": "BTC",
                "asset_type": "crypto",
            }
        ],
    }


def test_get_assets_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/asset/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 400
    assert "frontend_list" in response.json()["detail"]


def test_get_assets_passes_category_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_list_assets(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr("apps.v1.routers.assets.list_assets", fake_list_assets)

    client = TestClient(app)
    response = client.get(
        "/api/v1/asset/",
        params={
            "response_format": "frontend_list",
            "categories__uid": "category-uid-1",
            "limit": 25,
            "offset": 5,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 5,
        "next": None,
        "previous": "http://testserver/api/v1/asset/?response_format=frontend_list&categories__uid=category-uid-1&limit=25&offset=0",
        "results": [],
    }
    assert captured == {
        "search": "",
        "limit": 26,
        "offset": 5,
        "category_uid": "category-uid-1",
    }


def test_get_asset_monitor_frame_returns_tabular_asset_frame(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr("apps.v1.services.assets._get_runtime", lambda: runtime)

    def fake_list_asset_rows(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return [
            {
                "uid": str(asset_uid),
                "unique_identifier": "MXN-BONO-2031",
                "asset_type": "fixed_income",
            }
        ]

    monkeypatch.setattr("apps.v1.services.assets._list_asset_rows", fake_list_asset_rows)

    client = TestClient(app)
    response = client.get(
        "/api/v1/asset/monitor/frame/",
        params={
            "search": "BONO",
            "limit": 25,
            "offset": 0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["columns"][:3] == ["uid", "unique_identifier", "asset_type"]
    assert payload["rows"][0]["uid"] == str(asset_uid)
    assert payload["rows"][0]["unique_identifier"] == "MXN-BONO-2031"
    assert "Symbol" not in payload["rows"][0]
    assert payload["meta"]["marketAsset"]["assetKeyField"] == "unique_identifier"
    assert captured == {
        "context": runtime.context,
        "search": "BONO",
        "limit": 25,
        "offset": 0,
        "category_uid": None,
    }


def test_list_asset_rows_pushes_search_to_unique_identifier_contains(monkeypatch) -> None:
    captured_calls: list[dict[str, object]] = []

    def fake_search_assets(context, **kwargs):
        captured_calls.append(dict(kwargs))
        if kwargs.get("unique_identifier_contains") == "BONO":
            return {
                "rows": [
                    {
                        "uid": str(uuid.uuid4()),
                        "unique_identifier": "MXN-BONO-2031",
                        "asset_type": "fixed_income",
                    }
                ]
            }
        return {"rows": []}

    monkeypatch.setattr(asset_master_service, "service_search_assets", fake_search_assets)
    monkeypatch.setattr(
        asset_master_service,
        "service_search_openfigi_details",
        lambda context, **kwargs: {"rows": []},
    )

    rows = asset_master_service.list_asset_rows(object(), search="BONO", limit=25, offset=0)

    assert len(rows) == 1
    assert rows[0]["unique_identifier"] == "MXN-BONO-2031"
    assert any(call.get("unique_identifier_contains") == "BONO" for call in captured_calls)


def test_list_asset_rows_searches_related_openfigi_ticker(monkeypatch) -> None:
    asset_uid = str(uuid.uuid4())
    captured_asset_calls: list[dict[str, object]] = []
    captured_detail_calls: list[dict[str, object]] = []

    def fake_search_assets(context, **kwargs):
        captured_asset_calls.append(dict(kwargs))
        if kwargs.get("uids") == (asset_uid,):
            return {
                "rows": [
                    {
                        "uid": asset_uid,
                        "unique_identifier": "MXN-GOVT-BILL-28D",
                        "asset_type": "fixed_income",
                    }
                ]
            }
        return {"rows": []}

    def fake_search_openfigi_details(context, **kwargs):
        captured_detail_calls.append(dict(kwargs))
        if kwargs.get("ticker_contains") == "CETE":
            return {
                "rows": [
                    {
                        "asset_uid": asset_uid,
                        "ticker": "CETE 28D",
                    }
                ]
            }
        return {"rows": []}

    monkeypatch.setattr(asset_master_service, "service_search_assets", fake_search_assets)
    monkeypatch.setattr(
        asset_master_service,
        "service_search_openfigi_details",
        fake_search_openfigi_details,
    )

    rows = asset_master_service.list_asset_rows(object(), search="CETE", limit=25, offset=0)

    assert len(rows) == 1
    assert rows[0]["uid"] == asset_uid
    assert rows[0]["unique_identifier"] == "MXN-GOVT-BILL-28D"
    assert captured_detail_calls[0]["ticker_contains"] == "CETE"
    assert any(call.get("uids") == (asset_uid,) for call in captured_asset_calls)


def test_list_asset_rows_fetches_category_members_by_uid(monkeypatch) -> None:
    asset_uid = str(uuid.uuid4())
    captured_asset_calls: list[dict[str, object]] = []

    def fake_search_assets(context, **kwargs):
        captured_asset_calls.append(dict(kwargs))
        if kwargs.get("uids") == (asset_uid,):
            return {
                "rows": [
                    {
                        "uid": asset_uid,
                        "unique_identifier": "BTC",
                        "asset_type": "crypto",
                    }
                ]
            }
        return {"rows": []}

    monkeypatch.setattr(asset_master_service, "service_search_assets", fake_search_assets)
    monkeypatch.setattr(
        asset_master_service,
        "service_list_asset_category_memberships",
        lambda context, **kwargs: {"rows": [{"asset_uid": asset_uid}]},
    )
    monkeypatch.setattr(
        asset_master_service,
        "service_search_openfigi_details",
        lambda context, **kwargs: {"rows": []},
    )

    rows = asset_master_service.list_asset_rows(
        object(),
        category_uid="category-uid-1",
        limit=25,
        offset=0,
    )

    assert rows == [
        {
            "uid": asset_uid,
            "unique_identifier": "BTC",
            "asset_type": "crypto",
        }
    ]
    assert captured_asset_calls == [{"uids": (asset_uid,), "limit": 100}]


def test_list_asset_catalog_rows_fetches_category_members_by_uid(monkeypatch) -> None:
    asset_uid = str(uuid.uuid4())
    captured_asset_calls: list[dict[str, object]] = []

    def fake_search_assets(context, **kwargs):
        captured_asset_calls.append(dict(kwargs))
        if kwargs.get("uids") == (asset_uid,):
            return {
                "rows": [
                    {
                        "uid": asset_uid,
                        "unique_identifier": "BTC",
                        "asset_type": "crypto",
                    }
                ]
            }
        return {"rows": []}

    monkeypatch.setattr(asset_master_service, "service_search_assets", fake_search_assets)
    monkeypatch.setattr(
        asset_master_service,
        "service_list_asset_category_memberships",
        lambda context, **kwargs: {"rows": [{"asset_uid": asset_uid}]},
    )
    monkeypatch.setattr(
        asset_master_service,
        "service_search_openfigi_details",
        lambda context, **kwargs: {"rows": []},
    )

    rows = asset_master_service.list_asset_catalog_rows(
        object(),
        category_uid="category-uid-1",
        limit=25,
        offset=0,
    )

    assert rows[0]["uid"] == asset_uid
    assert rows[0]["unique_identifier"] == "BTC"
    assert captured_asset_calls == [{"uids": (asset_uid,), "limit": 100}]


def test_get_asset_returns_detail_with_current_snapshot(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset",
        lambda uid: {
            "uid": str(asset_uid),
            "unique_identifier": "BTC",
            "asset_type": "crypto",
            "current_snapshot": {
                "time_index": "2026-06-04T15:45:57+00:00",
                "asset_identifier": "BTC",
                "name": "Bitcoin",
                "ticker": "BTC",
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "BTC",
            },
            "details": [],
            "trading_view": None,
            "order_form": None,
        },
    )

    client = TestClient(app)
    response = client.get(
        f"/api/v1/asset/{asset_uid}/",
        params={"response_format": "frontend_detail"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "uid": str(asset_uid),
        "unique_identifier": "BTC",
        "asset_type": "crypto",
        "current_snapshot": {
            "time_index": "2026-06-04T15:45:57Z",
            "asset_identifier": "BTC",
            "name": "Bitcoin",
            "ticker": "BTC",
            "exchange_code": "CRYPTO",
            "asset_ticker_group_id": "BTC",
        },
        "details": [],
        "trading_view": None,
        "order_form": None,
    }


def test_get_asset_rejects_unknown_response_format() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/asset/some-asset/",
        params={"response_format": "frontend_list"},
    )

    assert response.status_code == 400
    assert "frontend_detail" in response.json()["detail"]


def test_get_asset_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/asset/missing-asset/")

    assert response.status_code == 404
    assert "missing-asset" in response.json()["detail"]


def test_delete_asset_returns_null(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.assets.delete_asset",
        lambda uid: True,
    )

    client = TestClient(app)
    response = client.delete(f"/api/v1/asset/{uuid.uuid4()}/")

    assert response.status_code == 200
    assert response.json() is None


def test_delete_asset_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.assets.delete_asset",
        lambda uid: False,
    )

    client = TestClient(app)
    response = client.delete("/api/v1/asset/missing-asset/")

    assert response.status_code == 404
    assert "missing-asset" in response.json()["detail"]


def test_get_asset_service_uses_uid_lookup(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr(asset_service, "_get_runtime", lambda: runtime)

    def fake_get_asset_record(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return {
            "uid": str(asset_uid),
            "unique_identifier": "BTC",
            "asset_type": "crypto",
            "current_snapshot": {
                "time_index": None,
                "asset_identifier": "BTC",
                "name": None,
                "ticker": None,
                "exchange_code": None,
                "asset_ticker_group_id": None,
            },
            "details": [],
            "trading_view": None,
            "order_form": None,
        }

    monkeypatch.setattr(asset_service, "_get_asset_record", fake_get_asset_record)

    response = asset_service.get_asset(uid=str(asset_uid))

    assert captured == {
        "context": runtime.context,
        "uid": str(asset_uid),
    }
    assert response is not None
    assert str(response.uid) == str(asset_uid)
    assert response.unique_identifier == "BTC"
    assert response.asset_type == "crypto"
    assert response.current_snapshot.asset_identifier == "BTC"


def test_delete_asset_service_uses_uid_lookup(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    runtime = SimpleNamespace(context=object())
    captured: dict[str, object] = {}

    monkeypatch.setattr(asset_service, "_get_runtime", lambda: runtime)

    def fake_delete_asset_record(context, **kwargs):
        captured["context"] = context
        captured.update(kwargs)
        return True

    monkeypatch.setattr(asset_service, "_delete_asset_record", fake_delete_asset_record)

    assert asset_service.delete_asset(uid=str(asset_uid)) is True
    assert captured == {
        "context": runtime.context,
        "uid": str(asset_uid),
    }


def test_core_get_asset_record_includes_latest_asset_snapshot(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    context = object()

    monkeypatch.setattr(
        asset_master_service,
        "service_get_asset_by_uid",
        lambda context, uid: {
            "row": {
                "uid": str(asset_uid),
                "unique_identifier": "example-asset-btc",
                "asset_type": "crypto",
            }
        },
    )

    def fake_asset_reference_details(asset_identifiers, *, repository_context):
        assert asset_identifiers == "example-asset-btc"
        assert repository_context is context
        return [
            {
                "asset_uid": str(asset_uid),
                "time_index": "2026-06-04T15:45:57+00:00",
                "asset_identifier": "example-asset-btc",
                "name": "Bitcoin",
                "ticker": "BTC",
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "BTC",
            }
        ]

    monkeypatch.setattr(
        asset_master_service,
        "asset_reference_details",
        fake_asset_reference_details,
    )

    detail = asset_master_service.get_asset_record(context, uid=str(asset_uid))

    assert detail == {
        "uid": str(asset_uid),
        "unique_identifier": "example-asset-btc",
        "asset_type": "crypto",
        "current_snapshot": {
            "time_index": dt.datetime(2026, 6, 4, 15, 45, 57, tzinfo=dt.timezone.utc),
            "asset_identifier": "example-asset-btc",
            "name": "Bitcoin",
            "ticker": "BTC",
            "exchange_code": "CRYPTO",
            "asset_ticker_group_id": "BTC",
        },
        "details": [],
        "trading_view": None,
        "order_form": None,
    }


def test_core_delete_asset_record_deletes_existing_asset(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    context = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        asset_master_service,
        "service_get_asset_by_uid",
        lambda context, uid: {
            "row": {
                "uid": str(asset_uid),
                "unique_identifier": "example-asset-btc",
                "asset_type": "crypto",
            }
        },
    )

    def fake_delete_asset(context, uid):
        captured["context"] = context
        captured["uid"] = uid
        return {}

    monkeypatch.setattr(asset_master_service, "service_delete_asset", fake_delete_asset)

    assert asset_master_service.delete_asset_record(context, uid=str(asset_uid)) is True
    assert captured == {
        "context": context,
        "uid": str(asset_uid),
    }


def test_core_delete_asset_record_returns_false_when_missing(monkeypatch) -> None:
    context = object()

    monkeypatch.setattr(
        asset_master_service,
        "service_get_asset_by_uid",
        lambda context, uid: {"rows": []},
    )

    def fail_delete_asset(context, uid):
        raise AssertionError("delete should not be called for a missing asset")

    monkeypatch.setattr(asset_master_service, "service_delete_asset", fail_delete_asset)

    assert asset_master_service.delete_asset_record(context, uid="missing-asset") is False


def test_get_asset_summary_returns_frontend_detail_summary(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset_summary",
        lambda uid: {
            "entity": {
                "id": str(asset_uid),
                "type": "asset",
                "title": "NASDAQ 100",
            },
            "badges": [
                {
                    "key": "status",
                    "label": "Active",
                    "tone": "success",
                }
            ],
            "inline_fields": [
                {
                    "key": "uid",
                    "label": "UID",
                    "value": str(asset_uid),
                    "kind": "code",
                }
            ],
            "highlight_fields": [
                {
                    "key": "name",
                    "label": "Name",
                    "value": "NASDAQ 100",
                    "kind": "text",
                    "icon": "database",
                }
            ],
            "stats": [
                {
                    "key": "rows",
                    "label": "Rows",
                    "display": "25",
                    "value": 25,
                    "kind": "number",
                }
            ],
            "label_management": {
                "labels": ["important", "live"],
                "add_label_url": "/add-label/",
                "remove_label_url": "/remove-label/",
            },
            "summary_warning": None,
            "extensions": {"anything_page_specific": True},
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/asset/{asset_uid}/summary/")

    assert response.status_code == 200
    assert response.json() == {
        "entity": {
            "id": str(asset_uid),
            "type": "asset",
            "title": "NASDAQ 100",
        },
        "badges": [
            {
                "key": "status",
                "label": "Active",
                "tone": "success",
            }
        ],
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": str(asset_uid),
                "kind": "code",
                "icon": None,
            }
        ],
        "highlight_fields": [
            {
                "key": "name",
                "label": "Name",
                "value": "NASDAQ 100",
                "kind": "text",
                "icon": "database",
            }
        ],
        "stats": [
            {
                "key": "rows",
                "label": "Rows",
                "display": "25",
                "value": 25,
                "kind": "number",
            }
        ],
        "label_management": {
            "labels": ["important", "live"],
            "add_label_url": "/add-label/",
            "remove_label_url": "/remove-label/",
        },
        "summary_warning": None,
        "extensions": {"anything_page_specific": True},
    }


def test_get_asset_summary_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset_summary",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/asset/missing-asset/summary/")

    assert response.status_code == 404
    assert "missing-asset" in response.json()["detail"]


def test_get_asset_pricing_details_returns_pricing_contract(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset_pricing_details",
        lambda uid: {
            "asset_uid": str(asset_uid),
            "instrument_type": "FixedRateBond",
            "instrument_dump": {"currency": "USD"},
            "pricing_details_date": "2026-05-28T00:00:00+00:00",
            "serialization_format": "msm_pricing.instrument.v1",
            "pricing_package_version": "1.0.0",
            "source": "test",
            "metadata_json": {"provider": "example"},
        },
    )

    client = TestClient(app)
    response = client.get(f"/api/v1/asset/{asset_uid}/get_pricing_details/")

    assert response.status_code == 200
    assert response.json() == {
        "asset_uid": str(asset_uid),
        "instrument_type": "FixedRateBond",
        "instrument_dump": {"currency": "USD"},
        "pricing_details_date": "2026-05-28T00:00:00Z",
        "serialization_format": "msm_pricing.instrument.v1",
        "pricing_package_version": "1.0.0",
        "source": "test",
        "metadata_json": {"provider": "example"},
        "pricing_support": None,
    }


def test_get_asset_pricing_details_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.assets.get_asset_pricing_details",
        lambda uid: None,
    )

    client = TestClient(app)
    response = client.get("/api/v1/asset/missing-asset/get_pricing_details/")

    assert response.status_code == 404
    assert "missing-asset" in response.json()["detail"]


def test_asset_pricing_details_service_uses_pricing_api_lookup(monkeypatch) -> None:
    asset_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    monkeypatch.setattr(asset_service, "_ensure_pricing_runtime", lambda: None)

    def fake_get_asset_current_pricing_details(uid):
        captured["uid"] = uid
        return {
            "asset_uid": str(asset_uid),
            "instrument_type": "FixedRateBond",
            "instrument_dump": {"currency": "USD"},
            "pricing_details_date": "2026-05-28T00:00:00+00:00",
            "serialization_format": "msm_pricing.instrument.v1",
            "pricing_package_version": None,
            "source": None,
            "metadata_json": None,
        }

    monkeypatch.setattr(
        asset_service,
        "_get_asset_current_pricing_details",
        fake_get_asset_current_pricing_details,
    )

    response = asset_service.get_asset_pricing_details(uid=str(asset_uid))

    assert captured == {"uid": str(asset_uid)}
    assert response is not None
    assert str(response.asset_uid) == str(asset_uid)
    assert response.pricing_support is not None
    assert response.pricing_support.supported is True
    assert response.pricing_support.operations
    assert response.pricing_support.operations[0].requires_market_data_set is True
