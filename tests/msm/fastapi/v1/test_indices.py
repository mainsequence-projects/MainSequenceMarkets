from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.api.indices import Index
from msm.services.indices import (
    IndexDatasetAccess,
    IndexDatasetDescriptor,
    IndexRelatedMetaTable,
    IndexValueRow,
    IndexValuesResult,
)


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


def test_index_delete_impact_service_uses_domain_neutral_relationships(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.services.indices.get_index",
        lambda uid: Index(
            uid=index_uid,
            unique_identifier="MX-TIIE",
            index_type="interest_rate",
            display_name="TIIE",
        ),
    )
    monkeypatch.setattr(
        "apps.v1.services.indices._get_runtime",
        lambda: type("Runtime", (), {"context": "core-context"})(),
    )
    monkeypatch.setattr(
        "apps.v1.services.indices.list_core_related_meta_tables",
        lambda context, index: [
            IndexRelatedMetaTable.model_validate(
                {
                    "key": "component_index_dependencies",
                    "label": "Methodologies using this component Index",
                    "owning_package": "msm",
                    "storage_kind": "related_reference_table",
                    "meta_table_uid": None,
                    "identifier": "IndexCalculationLeg",
                    "relationship_type": "direct",
                    "join_kind": "uid",
                    "join_column": "component_index_uid",
                    "on_delete": "RESTRICT",
                    "authoritative": True,
                    "discovery_source": "core_model",
                    "exploration_capability": "count",
                    "delete_capability": "none",
                    "count": 2,
                    "blocks_delete": True,
                    "confidence_reason": None,
                }
            )
        ],
    )

    from apps.v1.services.indices import get_index_delete_impact

    response = get_index_delete_impact(uid=str(index_uid))

    assert response is not None
    assert response.resource_type == "index"
    assert response.identifier == "MX-TIIE"
    assert response.can_delete is False
    assert response.blocking_count == 2
    assert response.affected_count == 2
    assert [relationship.key for relationship in response.relationships] == [
        "component_index_dependencies"
    ]
    assert "pricing" not in response.model_dump_json().lower()


def test_delete_index_requires_request_bound_actor() -> None:
    client = TestClient(app)
    response = client.delete(f"/api/v1/index/{uuid.uuid4()}/")

    assert response.status_code == 401


def test_delete_index_requires_preview_confirmation() -> None:
    client = TestClient(app)
    response = client.delete(
        f"/api/v1/index/{uuid.uuid4()}/",
        headers={"X-User-UID": str(uuid.uuid4())},
    )

    assert response.status_code == 428
    assert "preview" in response.json()["detail"].lower()


def test_bulk_preview_uses_request_bound_actor(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    user_uid = uuid.uuid4()
    captured = {}
    monkeypatch.setattr(
        "apps.v1.routers.indices.preview_index_bulk_delete",
        lambda payload, actor: (
            captured.update(payload=payload, actor=actor)
            or {
                "plan_id": str(uuid.uuid4()),
                "requested_mode": "values_only",
                "normalized_request": payload.model_dump(mode="json"),
                "created_at": "2026-07-19T12:00:00Z",
                "expires_at": "2026-07-19T12:05:00Z",
                "created_by_user_uid": actor.user_uid,
                "scope_hash": "a" * 64,
                "confirmation_token": "payload.signature",
                "executable": True,
                "indexes": [],
                "datasets": [],
                "relationships": [],
                "warnings": [],
                "required_acknowledgement_codes": [],
                "confirmation_phrase": "DELETE ALL SELECTED INDEX VALUES FOR 1 INDEX",
            }
        ),
    )

    response = TestClient(app).post(
        "/api/v1/index/bulk-delete/preview/",
        headers={"X-User-UID": str(user_uid)},
        json={"index_uids": [str(index_uid)], "mode": "values_only"},
    )

    assert response.status_code == 200
    assert captured["actor"].user_uid == str(user_uid)
    assert captured["actor"].team_uids == ()


def test_index_values_frame_uses_canonical_time_series_contract(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    dataset_uid = str(uuid.uuid4())
    timestamp = dt.datetime(2026, 7, 19, 12, tzinfo=dt.UTC)
    index = Index(
        uid=index_uid,
        unique_identifier="USD_SWAP_10Y",
        index_type="interest_rate",
        display_name="USD 10Y Swap Rate",
    )
    dataset = IndexDatasetDescriptor(
        meta_table_uid=dataset_uid,
        identifier="IndexValuesTS.1m",
        namespace="mainsequence.markets",
        cadence="1m",
        physical_table_name="ms_markets__index_values__t_1m",
        time_index_name="time_index",
        index_names=("time_index", "index_identifier"),
        columns=("time_index", "index_identifier", "value", "unit"),
        foreign_keys=(),
        storage_kind="canonical_index_values",
        discovery_source="core_model",
        access=IndexDatasetAccess(can_view=True),
        scoped_delete_supported=True,
    )
    values = IndexValuesResult(
        dataset=dataset,
        index_uid=index_uid,
        index_identifier=index.unique_identifier,
        start=timestamp,
        end=timestamp,
        order="asc",
        limit=10,
        rows=(
            IndexValueRow(
                time_index=timestamp,
                index_identifier=index.unique_identifier,
                value=0.04192,
                unit="decimal",
            ),
        ),
    )
    monkeypatch.setattr("apps.v1.services.indices.get_index", lambda uid: index)
    monkeypatch.setattr(
        "apps.v1.services.indices.get_canonical_dataset",
        lambda meta_table_uid, actor: dataset,
    )
    monkeypatch.setattr(
        "apps.v1.services.indices.read_index_values",
        lambda *args, **kwargs: values,
    )
    monkeypatch.setattr(
        "apps.v1.services.indices._get_runtime",
        lambda: type("Runtime", (), {"context": object()})(),
    )

    from apps.v1.services.indices import get_index_values_frame

    frame = get_index_values_frame(
        uid=str(index_uid),
        meta_table_uid=dataset_uid,
        start=timestamp,
        end=timestamp,
        order="asc",
        limit=10,
        actor=None,
    )

    assert frame is not None
    assert frame.source is not None
    assert frame.source.kind == "api"
    assert frame.source.id == "getIndexDatasetValuesFrame"
    assert frame.meta is not None
    assert frame.meta.timeSeries is not None
    assert frame.meta.timeSeries.timeField == "time_index"
    assert frame.meta.timeSeries.frequency == "1m"
    assert frame.rows[0]["time_index"] == int(timestamp.timestamp() * 1000)
