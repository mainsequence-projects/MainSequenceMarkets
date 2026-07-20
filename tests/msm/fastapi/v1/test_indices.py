from __future__ import annotations

import datetime as dt
import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.api.indices import Index
from msm.services.indices import (
    IndexDatasetAccess,
    IndexDatasetDescriptor,
    IndexDatasetState,
    IndexDeleteImpact,
    IndexDeleteImpactRelationship,
    IndexSummary,
    IndexValueRow,
    IndexValuesResult,
)


def test_get_indexes_returns_core_index_rows(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.indices.list_indices",
        lambda **kwargs: (
            1,
            [
                {
                    "uid": str(index_uid),
                    "unique_identifier": "SPX",
                    "index_type": "equity",
                    "display_name": "S&P 500 Index",
                    "calculation_method": "custom",
                    "value_format": "decimal",
                    "value_suffix": None,
                    "description": "Large-cap US equity index",
                    "metadata_json": {"currency": "USD"},
                }
            ],
        ),
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
                "calculation_method": "custom",
                "value_format": "decimal",
                "value_suffix": None,
                "description": "Large-cap US equity index",
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
            "calculation_method": "custom",
            "value_format": "decimal",
            "value_suffix": None,
            "description": "Large-cap US equity index",
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
        "calculation_method": "custom",
        "value_format": "decimal",
        "value_suffix": None,
        "description": "Large-cap US equity index",
        "metadata_json": {"currency": "USD"},
    }


def test_related_index_meta_tables_forwards_optional_filters(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    calls = []

    def fake_list_index_related_meta_tables(*, uid, numeric, timestamped):
        calls.append((uid, numeric, timestamped))
        return ()

    monkeypatch.setattr(
        "apps.v1.routers.indices.list_index_related_meta_tables",
        fake_list_index_related_meta_tables,
    )
    client = TestClient(app)

    default_response = client.get(f"/api/v1/index/{index_uid}/related-meta-tables/")
    unfiltered_response = client.get(
        f"/api/v1/index/{index_uid}/related-meta-tables/",
        params={"numeric": "false", "timestamped": "false"},
    )

    assert default_response.status_code == 200
    assert default_response.json() == []
    assert unfiltered_response.status_code == 200
    assert unfiltered_response.json() == []
    assert calls == [
        (str(index_uid), True, True),
        (str(index_uid), False, False),
    ]


def test_related_index_meta_tables_service_forwards_optional_filters(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    index = Index(
        uid=index_uid,
        unique_identifier="USD-SOFR-3M",
        index_type="interest_rate",
        display_name="USD SOFR 3M",
        calculation_method="custom",
        value_format="decimal",
    )
    context = object()
    calls = []

    monkeypatch.setattr("apps.v1.services.indices.get_index", lambda uid: index)
    monkeypatch.setattr(
        "apps.v1.services.indices._get_runtime",
        lambda: type("Runtime", (), {"context": context})(),
    )

    def fake_list_core_related_meta_tables(
        active_context,
        *,
        index,
        numeric,
        timestamped,
    ):
        calls.append((active_context, index.uid, numeric, timestamped))
        return ()

    monkeypatch.setattr(
        "apps.v1.services.indices.list_core_related_meta_tables",
        fake_list_core_related_meta_tables,
    )

    from apps.v1.services.indices import list_index_related_meta_tables

    result = list_index_related_meta_tables(
        uid=str(index_uid),
        numeric=False,
        timestamped=True,
    )

    assert result == ()
    assert calls == [(context, index_uid, False, True)]


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
            calculation_method="formula",
            value_format="percent",
        ),
    )
    monkeypatch.setattr(
        "apps.v1.services.indices._get_runtime",
        lambda: type("Runtime", (), {"context": "core-context"})(),
    )
    monkeypatch.setattr(
        "apps.v1.services.indices.get_core_index_delete_impact",
        lambda context, index: IndexDeleteImpact(
            uid=index_uid,
            identifier="MX-TIIE",
            display_name="TIIE",
            can_delete=False,
            blocking_count=2,
            affected_count=2,
            delete_endpoint=f"/api/v1/index/{index_uid}/",
            relationships=(
                IndexDeleteImpactRelationship(
                    key="component_index_dependencies",
                    label="Formulas using this component Index",
                    model="IndexFormulaInput",
                    column="component_index_uid",
                    relationship_type="direct",
                    on_delete="RESTRICT",
                    count=2,
                    count_accuracy="exact",
                    effect="blocks_delete",
                    severity="blocking",
                    blocks_delete=True,
                    description="Authoritative declared Index relationship.",
                ),
            ),
        ),
    )

    from apps.v1.services.indices import get_index_delete_impact

    response = get_index_delete_impact(uid=str(index_uid))

    assert response is not None
    assert response.resource_type == "index"
    assert response.identifier == "MX-TIIE"
    assert response.can_delete is False
    assert response.blocking_count == 2
    assert response.affected_count == 2
    assert response.delete_endpoint == f"/api/v1/index/{index_uid}/"
    assert [relationship.key for relationship in response.relationships] == [
        "component_index_dependencies"
    ]
    assert "pricing" not in response.model_dump_json().lower()


def test_index_summary_uses_reconciled_latest_observation_without_value_scan(
    monkeypatch,
) -> None:
    index_uid = uuid.uuid4()
    dataset_uid = str(uuid.uuid4())
    reconciled_at = dt.datetime(2026, 7, 19, 13, tzinfo=dt.UTC)
    latest_time = dt.datetime(2026, 7, 19, 12, tzinfo=dt.UTC)
    index = Index(
        uid=index_uid,
        unique_identifier="USD_SWAP_10Y",
        index_type="interest_rate",
        display_name="USD 10Y Swap Rate",
        calculation_method="custom",
        value_format="percent",
    )
    dataset = IndexDatasetDescriptor(
        meta_table_uid=dataset_uid,
        identifier="IndexValuesTS.1m",
        cadence="1m",
        physical_table_name="ms_markets__index_values__t_1m",
        time_index_name="time_index",
        index_names=("time_index", "index_identifier"),
        columns=("time_index", "index_identifier", "value"),
        foreign_keys=(),
        storage_kind="canonical_index_values",
        discovery_source="core_model",
        access=IndexDatasetAccess(can_view=True),
    )
    summary = IndexSummary(
        index=index,
        formula_count=0,
        input_count=0,
        dataset_count=1,
        cadences=("1m",),
        dataset_states=(
            IndexDatasetState(
                dataset=dataset,
                index_uid=index_uid,
                index_identifier=index.unique_identifier,
                population_state="populated",
                row_count=2,
                earliest_time_index=latest_time - dt.timedelta(minutes=1),
                latest_time_index=latest_time,
                reconciled_at=reconciled_at,
            ),
        ),
        authoritative_relationship_count=0,
        inferred_relationship_count=0,
    )
    monkeypatch.setattr("apps.v1.services.indices.get_index", lambda uid: index)
    monkeypatch.setattr(
        "apps.v1.services.indices._get_runtime",
        lambda: type("Runtime", (), {"context": object()})(),
    )
    monkeypatch.setattr(
        "apps.v1.services.indices.get_core_index_summary",
        lambda context, *, index, actor: summary,
    )

    from apps.v1.services.indices import get_index_summary

    response = get_index_summary(uid=str(index_uid), actor=None)

    assert response is not None
    latest = next(field for field in response.highlight_fields if field.key == "latest_observation")
    assert latest.value == latest_time.isoformat()
    assert latest.kind == "datetime"


def test_delete_index_returns_null_on_success(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    monkeypatch.setattr(
        "apps.v1.routers.indices.delete_index",
        lambda uid: True,
    )

    response = TestClient(app).delete(f"/api/v1/index/{index_uid}/")

    assert response.status_code == 200
    assert response.json() is None


def test_delete_index_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.v1.routers.indices.delete_index",
        lambda uid: False,
    )

    response = TestClient(app).delete("/api/v1/index/missing-index/")

    assert response.status_code == 404
    assert "missing-index" in response.json()["detail"]


def test_index_values_frame_uses_canonical_time_series_contract(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    dataset_uid = str(uuid.uuid4())
    timestamp = dt.datetime(2026, 7, 19, 12, tzinfo=dt.UTC)
    index = Index(
        uid=index_uid,
        unique_identifier="USD_SWAP_10Y",
        index_type="interest_rate",
        display_name="USD 10Y Swap Rate",
        calculation_method="custom",
        value_format="percent",
    )
    dataset = IndexDatasetDescriptor(
        meta_table_uid=dataset_uid,
        identifier="IndexValuesTS.1m",
        namespace="mainsequence.markets",
        cadence="1m",
        physical_table_name="ms_markets__index_values__t_1m",
        time_index_name="time_index",
        index_names=("time_index", "index_identifier"),
        columns=("time_index", "index_identifier", "value"),
        foreign_keys=(),
        storage_kind="canonical_index_values",
        discovery_source="core_model",
        access=IndexDatasetAccess(can_view=True),
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
