"""Clearing an account's target with an empty positions list (route, service, statement)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app

CLEARED_AT = dt.datetime(2026, 11, 9, 15, 0, tzinfo=dt.UTC)


def test_add_target_positions_route_accepts_an_empty_list(monkeypatch) -> None:
    account_uid = str(uuid.uuid4())
    position_set_uid = str(uuid.uuid4())
    captured: dict[str, object] = {}

    def fake_add_account_target_positions(*, account_uid, payload):
        captured["positions"] = payload.positions
        return {
            "related_account_uid": account_uid,
            "target_positions_date": payload.target_positions_date,
            "position_set_uid": position_set_uid,
            "positions": [],
        }

    monkeypatch.setattr(
        "apps.v1.routers.accounts.add_account_target_positions",
        fake_add_account_target_positions,
    )

    response = TestClient(app).post(
        f"/api/v1/account/{account_uid}/add-target-positions/",
        json={"target_positions_date": CLEARED_AT.isoformat(), "overwrite": False, "positions": []},
    )

    assert response.status_code == 200
    assert captured["positions"] == []
    assert response.json()["position_set_uid"] == position_set_uid
    assert response.json()["positions"] == []


def test_add_target_positions_still_requires_the_positions_field() -> None:
    response = TestClient(app).post(
        f"/api/v1/account/{uuid.uuid4()}/add-target-positions/",
        json={"target_positions_date": CLEARED_AT.isoformat(), "overwrite": False},
    )

    assert response.status_code == 422


def _patch_account(monkeypatch, services, account_uid: str) -> None:
    monkeypatch.setattr(
        services,
        "get_account_by_uid",
        lambda context, uid: {"row": {"uid": account_uid, "account_name": "Some account"}},
    )


def test_clearing_writes_an_empty_snapshot_and_answers_it(monkeypatch) -> None:
    from msm.services import target_positions as services

    account_uid = str(uuid.uuid4())
    position_set_uid = str(uuid.uuid4())
    captured: dict[str, object] = {}
    _patch_account(monkeypatch, services, account_uid)

    def fake_replace(context, **kwargs):
        captured.update(kwargs)
        return {"rows": [{"uid": position_set_uid}]}

    def unexpected_read(context, **kwargs):
        raise AssertionError("A cleared snapshot is answered from the write.")

    monkeypatch.setattr(
        "msm.repositories.accounts.replace_account_target_positions_snapshot", fake_replace
    )
    monkeypatch.setattr(services, "get_account_target_positions_snapshot_response", unexpected_read)

    snapshot = services.add_account_target_positions_snapshot_response(
        object(),
        account_uid=account_uid,
        target_positions_date=CLEARED_AT,
        positions=[],
    )

    assert captured["positions"] == []
    assert captured["overwrite"] is False
    assert snapshot == {
        "related_account_uid": account_uid,
        "target_positions_date": CLEARED_AT,
        "position_set_uid": position_set_uid,
        "positions": [],
    }


def test_a_refused_clear_reports_the_existing_snapshot(monkeypatch) -> None:
    from msm.services import target_positions as services

    account_uid = str(uuid.uuid4())
    _patch_account(monkeypatch, services, account_uid)
    monkeypatch.setattr(
        "msm.repositories.accounts.replace_account_target_positions_snapshot",
        lambda context, **kwargs: {"rows": []},
    )

    with pytest.raises(services.AccountTargetPositionsSnapshotExistsError):
        services.add_account_target_positions_snapshot_response(
            object(),
            account_uid=account_uid,
            target_positions_date=CLEARED_AT,
            positions=[],
        )


def _replacement(positions: list[dict[str, object]], *, overwrite: bool):
    from msm.repositories import accounts as account_repository

    class FakeContext:
        data_source_uid = None
        limits = None

    return account_repository.build_replace_account_target_positions_snapshot_operation(
        FakeContext(),
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        account_uid=uuid.uuid4(),
        account_name="Some account",
        target_positions_date=CLEARED_AT,
        positions=positions,
        overwrite=overwrite,
    )


def test_clear_statement_deactivates_the_target_and_writes_no_rows(
    offline_postgresql_runtime,
) -> None:
    operation = _replacement([], overwrite=True)
    sql = operation.statement.sql

    assert operation.operation == "upsert"
    assert operation.statement.parameters["is_active"] is False
    assert "cleared_rows AS" in sql
    assert "DELETE FROM ms_markets__targetpositionsts" in sql
    assert "INSERT INTO ms_markets__targetpositionsts" not in sql
    # The top-level statement is the PositionSet upsert, so the result is its uid.
    top_level = sql.split("RETURNING true AS")[-1]
    assert "INSERT INTO ms_markets__positionset" in top_level
    assert top_level.rstrip().endswith("RETURNING ms_markets__positionset.uid")


def test_target_activation_follows_the_snapshot_write(offline_postgresql_runtime) -> None:
    asset_uid = uuid.uuid4()
    operation = _replacement(
        [
            {
                "target_type": "asset",
                "target_uid": str(asset_uid),
                "asset_uid": str(asset_uid),
                "portfolio_uid": None,
                "weight_notional_exposure": 1.0,
                "constant_notional_exposure": None,
                "single_asset_quantity": None,
                "metadata_json": {},
            }
        ],
        overwrite=False,
    )
    sql = operation.statement.sql

    assert operation.statement.parameters["is_active"] is True
    assert (
        "is_active = CASE WHEN (%(overwrite)s OR NOT (EXISTS (SELECT existing_position_set.uid"
        in sql
    )
    assert "THEN excluded.is_active ELSE ms_markets__accounttargetallocation.is_active END" in sql
    assert "INSERT INTO ms_markets__targetpositionsts" in sql
