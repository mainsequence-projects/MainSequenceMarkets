from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from mainsequence.server.caller_assertions import ASSERTION_HEADER
from mainsequence.server.fastapi import install_request_identity

from apps.v1.main import app, create_app
from msm.services.indices import IndexActor

USER_UID = "9b4d2f8e-1a3c-4e5b-8d7f-6c0a2e4b6d35"
TEAM_UID = "3c9e1f7a-5b2d-4e8c-a6f0-7d1b3e5a9c24"


def test_create_app_installs_request_identity_once() -> None:
    with pytest.raises(RuntimeError, match="already installed"):
        install_request_identity(create_app())


def test_request_with_an_invalid_caller_assertion_is_refused() -> None:
    response = TestClient(app).get("/health", headers={ASSERTION_HEADER: "not-an-assertion"})

    assert response.status_code == 401


def test_request_with_another_releases_assertion_is_refused(caller_assertions) -> None:
    assertion = caller_assertions.sign(aud="urn:mainsequence:fapi:another-release")

    response = TestClient(app).get("/health", headers={ASSERTION_HEADER: assertion})

    assert response.status_code == 401


def test_index_routes_act_for_the_verified_caller(monkeypatch, caller_assertions) -> None:
    received: list[IndexActor | None] = []

    def list_index_datasets(*, uid, actor, include_empty):
        received.append(actor)
        return []

    monkeypatch.setattr("apps.v1.routers.indices.list_index_datasets", list_index_datasets)
    assertion = caller_assertions.sign(USER_UID, team_uids=[TEAM_UID])

    response = TestClient(app).get(
        "/api/v1/index/any-index/datasets/",
        headers={ASSERTION_HEADER: assertion},
    )

    assert response.status_code == 200
    assert received == [IndexActor(user_uid=USER_UID, team_uids=(TEAM_UID,))]
