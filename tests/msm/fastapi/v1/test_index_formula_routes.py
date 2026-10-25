"""Formula save, activate, retire and preview over FormulaIndex (ADR 0047, step 1)."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.services import indices as index_service
from msm.analytics.indices import IndexFormulaDefinition, IndexFormulaInput, IndexFormulaResult
from msm.api.indices import FormulaIndex, Index
from msm.services.indices import IndexFormulaDetail

INDEX_UID = uuid.uuid4()
DEFINITION_UID = uuid.uuid4()
SOURCE_TABLE_UID = uuid.uuid4()
START = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
END = dt.datetime(2026, 1, 3, tzinfo=dt.UTC)


def _index() -> Index:
    return Index(
        uid=INDEX_UID,
        unique_identifier="SPX-TR",
        index_type="equity",
        display_name="S&P 500 total return",
        calculation_method="formula",
        value_format="decimal",
    )


def _definition(**overrides) -> IndexFormulaDefinition:
    payload = {
        "valid_from": START,
        "formula": 'asset["BBG000B9XRY4"].close * 2',
        "alignment_policy": "exact",
        "missing_data_policy": "drop",
    }
    payload.update(overrides)
    return IndexFormulaDefinition.model_validate(payload)


def _input() -> IndexFormulaInput:
    return IndexFormulaInput.model_validate(
        {
            "source_reference": {"type": "asset", "identifier": "BBG000B9XRY4"},
            "meta_table_uid": str(SOURCE_TABLE_UID),
            "observable": "close",
        }
    )


def _detail(status: str = "draft") -> IndexFormulaDetail:
    return IndexFormulaDetail(
        uid=DEFINITION_UID,
        index_uid=INDEX_UID,
        version=1,
        status=status,
        valid_from=START,
        formula='asset["BBG000B9XRY4"].close * 2',
        alignment_policy="exact",
        missing_data_policy="drop",
        definition_hash="a" * 64,
        input_count=1,
        inputs=(_input(),),
    )


def _save_body() -> dict:
    return {
        "definition": {
            "valid_from": START.isoformat(),
            "formula": 'asset["BBG000B9XRY4"].close * 2',
        },
        "inputs": [
            {
                "source_reference": {"type": "asset", "identifier": "BBG000B9XRY4"},
                "meta_table_uid": str(SOURCE_TABLE_UID),
                "observable": "close",
            }
        ],
    }


def test_save_formula_route_passes_typed_definition_and_inputs(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_save(*, uid, definition, inputs):
        captured.update(uid=uid, definition=definition, inputs=inputs)
        return _detail()

    monkeypatch.setattr("apps.v1.routers.indices.save_index_formula", fake_save)

    response = TestClient(app).post(f"/api/v1/index/{INDEX_UID}/formulas/", json=_save_body())

    assert response.status_code == 201
    assert response.json()["uid"] == str(DEFINITION_UID)
    assert response.json()["status"] == "draft"
    assert captured["uid"] == str(INDEX_UID)
    assert isinstance(captured["definition"], IndexFormulaDefinition)
    assert captured["definition"].status == "draft"
    assert [item.observable for item in captured["inputs"]] == ["close"]


def test_save_formula_route_maps_errors(monkeypatch) -> None:
    client = TestClient(app)
    body = _save_body()

    monkeypatch.setattr("apps.v1.routers.indices.save_index_formula", lambda **_kwargs: None)
    assert client.post(f"/api/v1/index/{INDEX_UID}/formulas/", json=body).status_code == 404

    def custom_index(**_kwargs):
        raise ValueError("uses calculation_method='custom' and cannot own formulas")

    monkeypatch.setattr("apps.v1.routers.indices.save_index_formula", custom_index)
    assert client.post(f"/api/v1/index/{INDEX_UID}/formulas/", json=body).status_code == 400

    def missing_source(**_kwargs):
        raise LookupError("formula Asset source 'X' was not found")

    monkeypatch.setattr("apps.v1.routers.indices.save_index_formula", missing_source)
    assert client.post(f"/api/v1/index/{INDEX_UID}/formulas/", json=body).status_code == 404

    body["definition"]["formula"] = "asset[close"
    assert client.post(f"/api/v1/index/{INDEX_UID}/formulas/", json=body).status_code == 422


def test_activate_and_retire_routes_return_the_stored_version(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "apps.v1.routers.indices.activate_index_formula",
        lambda *, uid, definition_uid: captured.update(activate=(uid, definition_uid)) or _detail("active"),
    )

    def fake_retire(*, uid, definition_uid, valid_to):
        captured["retire"] = (uid, definition_uid, valid_to)
        return _detail("retired")

    monkeypatch.setattr("apps.v1.routers.indices.retire_index_formula", fake_retire)
    client = TestClient(app)
    base = f"/api/v1/index/{INDEX_UID}/formulas/{DEFINITION_UID}"

    activated = client.post(f"{base}/activate/")
    retired_now = client.post(f"{base}/retire/")
    retired_at = client.post(f"{base}/retire/", json={"valid_to": END.isoformat()})
    assert retired_at.status_code == 200

    assert activated.status_code == 200 and activated.json()["status"] == "active"
    assert captured["activate"] == (str(INDEX_UID), str(DEFINITION_UID))
    assert retired_now.status_code == 200 and retired_now.json()["status"] == "retired"
    assert captured["retire"] == (str(INDEX_UID), str(DEFINITION_UID), END)

    monkeypatch.setattr("apps.v1.routers.indices.activate_index_formula", lambda **_kwargs: None)
    assert client.post(f"{base}/activate/").status_code == 404


def test_preview_routes_return_a_tabular_frame(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_preview(**kwargs):
        captured.append(kwargs)
        from msm.api.http import build_tabular_frame

        return build_tabular_frame(rows=[{"time_index": 1, "index_identifier": "SPX-TR", "value": 2.0}])

    monkeypatch.setattr("apps.v1.routers.indices.preview_index_formula", fake_preview)
    client = TestClient(app)

    draft = client.post(
        f"/api/v1/index/{INDEX_UID}/formulas/preview/",
        json={**_save_body(), "start": START.isoformat(), "end": END.isoformat()},
    )
    stored = client.post(
        f"/api/v1/index/{INDEX_UID}/formulas/{DEFINITION_UID}/preview/",
        json={"start": START.isoformat(), "end": END.isoformat()},
    )
    bad_window = client.post(
        f"/api/v1/index/{INDEX_UID}/formulas/{DEFINITION_UID}/preview/",
        json={"start": END.isoformat(), "end": START.isoformat()},
    )

    assert draft.status_code == 200 and draft.json()["rows"][0]["value"] == 2.0
    assert stored.status_code == 200
    assert bad_window.status_code == 422
    assert captured[0]["definition"].formula == 'asset["BBG000B9XRY4"].close * 2'
    assert captured[0]["start"] == START and captured[0]["end"] == END
    assert captured[1] == {
        "uid": str(INDEX_UID),
        "start": START,
        "end": END,
        "definition_uid": str(DEFINITION_UID),
    }
    for route in (
        "/api/v1/index/{uid}/formulas/preview/",
        "/api/v1/index/{uid}/formulas/{definition_uid}/preview/",
    ):
        assert app.openapi()["paths"][route]["post"]["x-ui-contract"] == "core.tabular_frame@v1"


def test_save_service_takes_identity_from_the_stored_index(monkeypatch) -> None:
    index = _index()
    captured: dict[str, object] = {}
    monkeypatch.setattr(index_service, "_get_runtime", lambda: SimpleNamespace(context=object()))
    monkeypatch.setattr(index_service, "get_index", lambda *, uid: index if uid == str(INDEX_UID) else None)

    def fake_upsert(cls, **kwargs):
        captured.update(kwargs)
        return FormulaIndex(index=index, definition=_definition(uid=DEFINITION_UID, index_uid=INDEX_UID, version=1), inputs=(_input(),))

    monkeypatch.setattr(FormulaIndex, "upsert", classmethod(fake_upsert))
    monkeypatch.setattr(
        index_service,
        "get_core_formula",
        lambda _context, *, index_uid, definition_uid: _detail() if definition_uid == DEFINITION_UID else None,
    )

    detail = index_service.save_index_formula(uid=str(INDEX_UID), definition=_definition(), inputs=[_input()])

    assert detail is not None and detail.uid == DEFINITION_UID
    assert captured["unique_identifier"] == "SPX-TR"
    assert captured["index_type"] == "equity"
    assert captured["display_name"] == "S&P 500 total return"
    assert captured["value_format"] == "decimal"
    assert captured["inputs"] == (_input(),)
    assert index_service.save_index_formula(uid=str(uuid.uuid4()), definition=_definition(), inputs=[_input()]) is None
    assert index_service.save_index_formula.__registry_write__ == ("index", "save:formula")


def test_activate_and_retire_services_reject_a_formula_of_another_index(monkeypatch) -> None:
    index = _index()
    other = index.model_copy(update={"uid": uuid.uuid4(), "unique_identifier": "OTHER"})
    stored = FormulaIndex(index=other, definition=_definition(uid=DEFINITION_UID, index_uid=other.uid, version=1), inputs=(_input(),))
    monkeypatch.setattr(index_service, "_get_runtime", lambda: SimpleNamespace(context=object()))
    monkeypatch.setattr(index_service, "get_index", lambda *, uid: index)
    monkeypatch.setattr(FormulaIndex, "get_by_definition_uid", classmethod(lambda cls, definition_uid: stored))

    assert index_service.activate_index_formula(uid=str(INDEX_UID), definition_uid=str(DEFINITION_UID)) is None
    assert index_service.retire_index_formula(uid=str(INDEX_UID), definition_uid=str(DEFINITION_UID)) is None
    with pytest.raises(LookupError):
        index_service.preview_index_formula(uid=str(INDEX_UID), start=START, end=END, definition_uid=str(DEFINITION_UID))


def test_preview_service_calculates_an_unsaved_formula_without_persisting(monkeypatch) -> None:
    index = _index()
    monkeypatch.setattr(index_service, "_get_runtime", lambda: SimpleNamespace(context=object()))
    monkeypatch.setattr(index_service, "get_index", lambda *, uid: index)
    captured: dict[str, object] = {}

    def fake_calculate(self, *, start, end, times=None):
        captured.update(definition=self.definition, inputs=self.inputs, start=start, end=end)
        return IndexFormulaResult(
            values=pd.DataFrame(
                {
                    "time_index": pd.to_datetime([START, START + dt.timedelta(days=1)], utc=True),
                    "index_identifier": index.unique_identifier,
                    "value": [2.0, float("nan")],
                    "definition_uid": None,
                    "observation_status": "ready",
                    "source_as_of": pd.to_datetime([START, None], utc=True),
                    "metadata_json": None,
                }
            )
        )

    monkeypatch.setattr(FormulaIndex, "calculate_from_sources", fake_calculate)
    monkeypatch.setattr(FormulaIndex, "upsert", classmethod(lambda cls, **_kwargs: pytest.fail("preview must not persist")))

    frame = index_service.preview_index_formula(
        uid=str(INDEX_UID), start=START, end=END, definition=_definition(), inputs=[_input()]
    )

    assert frame is not None
    assert captured["start"] == START and captured["end"] == END
    assert captured["inputs"] == (_input(),)
    rows = frame.model_dump(exclude_none=True)["rows"]
    assert rows[0]["time_index"] == int(START.timestamp() * 1000)
    assert rows[0]["value"] == 2.0
    assert rows[0]["source_as_of"] == int(START.timestamp() * 1000)
    assert rows[1]["value"] is None
    assert rows[1]["source_as_of"] is None
    assert frame.source.context["persisted"] is False
    with pytest.raises(ValueError, match="needs a definition"):
        index_service.preview_index_formula(uid=str(INDEX_UID), start=START, end=END)
