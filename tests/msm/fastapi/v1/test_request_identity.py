from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from mainsequence.server.caller_assertions import ASSERTION_HEADER
from mainsequence.server.fastapi import install_request_identity

from apps.v1.main import app, create_app
from msm.services.indices import IndexActor

USER_UID = "9b4d2f8e-1a3c-4e5b-8d7f-6c0a2e4b6d35"
REQUESTER_UID = "6e2a8c4f-0b7d-4f1a-9e3c-5d8b2a7f4c61"
TEAM_UID = "3c9e1f7a-5b2d-4e8c-a6f0-7d1b3e5a9c24"
DATASETS_ROUTE = "/api/v1/index/any-index/datasets/"


def _record_index_actors(monkeypatch) -> list[IndexActor | None]:
    received: list[IndexActor | None] = []

    def list_index_datasets(*, uid, actor, include_empty):
        received.append(actor)
        return []

    monkeypatch.setattr("apps.v1.routers.indices.list_index_datasets", list_index_datasets)
    return received


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
    received = _record_index_actors(monkeypatch)
    assertion = caller_assertions.sign(USER_UID)

    response = TestClient(app).get(DATASETS_ROUTE, headers={ASSERTION_HEADER: assertion})

    assert response.status_code == 200
    # Caller assertions name no Teams, so the actor has none.
    assert received == [IndexActor(user_uid=USER_UID)]


@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"team_uids": [TEAM_UID]}, id="caller"),
        pytest.param(
            {
                "requester": {
                    "sub": REQUESTER_UID,
                    "is_organization_admin": False,
                    "team_uids": [TEAM_UID],
                }
            },
            id="requester",
        ),
    ],
)
def test_an_assertion_that_lists_teams_is_refused(monkeypatch, caller_assertions, claims) -> None:
    # The platform signs only `sub` and `is_organization_admin`, for the caller and for the
    # requester; an assertion that also lists `team_uids` is refused before any handler runs.
    received = _record_index_actors(monkeypatch)
    assertion = caller_assertions.sign(USER_UID, **claims)

    response = TestClient(app).get(DATASETS_ROUTE, headers={ASSERTION_HEADER: assertion})

    assert response.status_code == 401
    assert received == []


def test_a_requester_bound_assertion_without_teams_is_accepted(
    monkeypatch, caller_assertions
) -> None:
    received = _record_index_actors(monkeypatch)
    assertion = caller_assertions.sign(
        USER_UID, requester={"sub": REQUESTER_UID, "is_organization_admin": False}
    )

    response = TestClient(app).get(DATASETS_ROUTE, headers={ASSERTION_HEADER: assertion})

    assert response.status_code == 200
    assert len(received) == 1
