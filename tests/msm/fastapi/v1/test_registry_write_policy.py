"""ADR 0047, decision 3: who may trigger a registry write.

Applications (workload identities) write registry rows only when the
``MARKETS_REGISTRY_WRITERS`` constant lists them for the resource; people,
requester-bound calls, Organization admins and calls without a request keep
working as before.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mainsequence.server.caller_assertions import ASSERTION_HEADER

from apps.v1 import policy
from apps.v1.identity import ActingIdentity, registry_write
from apps.v1.main import app

# Captured at import, before the autouse fixture in tests/conftest.py stubs them.
REAL_LOAD_POLICY = policy.load_registry_writer_policy
REAL_RESOLVE_IDENTITY_TYPE = policy.resolve_identity_type

APPLICATION_UID = "7d0c8e1a-2b3c-4d5e-8f9a-0b1c2d3e4f5a"
OTHER_APPLICATION_UID = "8e1d9f2b-3c4d-4e5f-9a0b-1c2d3e4f5a6b"


def _use(monkeypatch, *, writers: dict, identity_types: dict | None = None) -> None:
    monkeypatch.setattr(
        policy,
        "load_registry_writer_policy",
        lambda: policy.RegistryWriterPolicy.from_value(writers),
    )
    types = identity_types or {}
    monkeypatch.setattr(policy, "resolve_identity_type", lambda uid: types.get(uid, "human"))


def _caller(uid: str, **kwargs) -> ActingIdentity:
    return ActingIdentity(uid=uid, kind="caller", **kwargs)


def test_an_application_needs_an_allow_list_entry(monkeypatch) -> None:
    _use(
        monkeypatch,
        writers={"asset": [APPLICATION_UID]},
        identity_types={APPLICATION_UID: "workload", OTHER_APPLICATION_UID: "workload"},
    )

    policy.authorize_registry_write("asset", "create", _caller(APPLICATION_UID))
    with pytest.raises(policy.RegistryWriteForbidden, match="MARKETS_REGISTRY_WRITERS"):
        policy.authorize_registry_write("portfolio", "create", _caller(APPLICATION_UID))
    with pytest.raises(policy.RegistryWriteForbidden):
        policy.authorize_registry_write("asset", "create", _caller(OTHER_APPLICATION_UID))


def test_the_wildcard_entry_covers_every_resource(monkeypatch) -> None:
    _use(
        monkeypatch,
        writers={"*": [APPLICATION_UID]},
        identity_types={APPLICATION_UID: "workload"},
    )

    policy.authorize_registry_write("portfolio", "update", _caller(APPLICATION_UID))
    policy.authorize_registry_write("index", "create", _caller(APPLICATION_UID))


def test_people_requesters_admins_and_direct_calls_are_not_restricted(monkeypatch) -> None:
    _use(monkeypatch, writers={}, identity_types={APPLICATION_UID: "workload"})

    policy.authorize_registry_write("asset", "create", None)
    policy.authorize_registry_write("asset", "create", _caller("a-person"))
    policy.authorize_registry_write(
        "asset", "create", ActingIdentity(uid="a-person", kind="requester")
    )
    policy.authorize_registry_write(
        "asset", "create", _caller(APPLICATION_UID, is_organization_admin=True)
    )


def test_an_allow_listed_caller_needs_no_user_lookup(monkeypatch) -> None:
    monkeypatch.setattr(
        policy,
        "load_registry_writer_policy",
        lambda: policy.RegistryWriterPolicy.from_value({"asset": [APPLICATION_UID]}),
    )

    def lookup(_uid):
        raise AssertionError("an allow-listed caller must not need a User lookup")

    monkeypatch.setattr(policy, "resolve_identity_type", lookup)

    policy.authorize_registry_write("asset", "create", _caller(APPLICATION_UID))


@pytest.mark.parametrize(
    "value",
    ['{"asset": "not-a-list"}', "[1, 2]", "{not json", '{"asset": 7}'],
)
def test_a_malformed_allow_list_fails_closed(value) -> None:
    with pytest.raises(policy.RegistryWritePolicyError):
        policy.RegistryWriterPolicy.from_value(value)


def test_missing_constant_allows_no_application(monkeypatch) -> None:
    from mainsequence.client import Constant
    from mainsequence.client.utils import DoesNotExist

    def missing(_name):
        raise DoesNotExist("no constant")

    monkeypatch.setattr(Constant, "get_value", classmethod(lambda cls, name: missing(name)))

    assert REAL_LOAD_POLICY().writers == {}


def test_an_unreachable_constant_fails_closed(monkeypatch) -> None:
    from mainsequence.client import Constant

    def unreachable(cls, name):
        raise ConnectionError("platform unreachable")

    monkeypatch.setattr(Constant, "get_value", classmethod(unreachable))

    with pytest.raises(policy.RegistryWritePolicyError, match="ConnectionError"):
        REAL_LOAD_POLICY()


def test_identity_type_is_read_once_and_cached(monkeypatch) -> None:
    from mainsequence.client.models_user import User

    calls: list[str] = []

    def get_by_uid(uid):
        calls.append(uid)
        return SimpleNamespace(identity_type="workload")

    monkeypatch.setattr(User, "get_by_uid", classmethod(lambda cls, uid: get_by_uid(uid)))
    policy.clear_identity_type_cache()

    assert REAL_RESOLVE_IDENTITY_TYPE(APPLICATION_UID) == "workload"
    assert REAL_RESOLVE_IDENTITY_TYPE(APPLICATION_UID) == "workload"
    assert calls == [APPLICATION_UID]
    policy.clear_identity_type_cache()


def test_registry_write_refuses_before_the_service_runs(monkeypatch) -> None:
    _use(monkeypatch, writers={}, identity_types={APPLICATION_UID: "workload"})
    monkeypatch.setattr(
        "apps.v1.identity.acting_identity", lambda: _caller(APPLICATION_UID)
    )
    ran: list[bool] = []

    @registry_write("asset", "create")
    def create_asset():
        ran.append(True)

    with pytest.raises(policy.RegistryWriteForbidden):
        create_asset()
    assert ran == []


def test_a_refused_write_returns_403(monkeypatch, caller_assertions) -> None:
    _use(monkeypatch, writers={}, identity_types={APPLICATION_UID: "workload"})
    monkeypatch.setattr(
        "apps.v1.services.portfolios._get_runtime",
        lambda: pytest.fail("a refused write must not reach the runtime"),
    )

    response = TestClient(app).delete(
        f"/api/v1/portfolio/{uuid.uuid4()}/",
        headers={ASSERTION_HEADER: caller_assertions.sign(APPLICATION_UID)},
    )

    assert response.status_code == 403
    assert "MARKETS_REGISTRY_WRITERS" in response.json()["detail"]


def test_an_unreadable_policy_returns_503(monkeypatch, caller_assertions) -> None:
    def broken():
        raise policy.RegistryWritePolicyError("constant service unavailable")

    monkeypatch.setattr(policy, "load_registry_writer_policy", broken)

    response = TestClient(app).delete(
        f"/api/v1/portfolio/{uuid.uuid4()}/",
        headers={ASSERTION_HEADER: caller_assertions.sign(APPLICATION_UID)},
    )

    assert response.status_code == 503
