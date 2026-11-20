from __future__ import annotations

import asyncio
from contextlib import contextmanager

import metatables.endpoint
import pytest

import apps.v1.main as main


@pytest.mark.parametrize("failure_stage", [None, "markets", "pricing"])
def test_startup_wait_scope_covers_both_attachments_and_preserves_failures(monkeypatch, failure_stage):
    state = {"active": False, "budgets": [], "calls": []}
    failure = RuntimeError("runtime attachment failed")
    monkeypatch.setattr(main.time, "monotonic", lambda: 0)
    original = metatables.endpoint.api_endpoint_scope

    @contextmanager
    def observe_scope(*, discovery_timeout):
        state["budgets"].append(discovery_timeout)
        with original(discovery_timeout=discovery_timeout):
            state["active"] = True
            try:
                yield
            finally:
                state["active"] = False

    def attach(stage):
        assert state["active"]
        state["calls"].append(stage)
        if failure_stage == stage:
            raise failure

    monkeypatch.setattr(main, "api_endpoint_scope", observe_scope)
    monkeypatch.setattr(main, "ensure_apps_v1_runtime", lambda: attach("markets"))
    monkeypatch.setattr(main, "ensure_apps_v1_pricing_runtime", lambda: attach("pricing"))

    async def startup():
        async with main.lifespan(None):
            # Only startup gets the extended scope; normal serving does not.
            assert not state["active"]

    if failure_stage:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(startup())
        assert caught.value is failure
    else:
        asyncio.run(startup())
    assert state["budgets"] == [300]
    assert not state["active"]
    assert state["calls"] == (["markets"] if failure_stage == "markets" else ["markets", "pricing"])


@pytest.mark.parametrize("stage", ["markets", "pricing"])
@pytest.mark.parametrize("kind", ["auth", "wake"])
def test_startup_recovers_temporary_dependency_failure(monkeypatch, stage, kind):
    from types import SimpleNamespace
    from mainsequence.client.exceptions import ServerError
    from metatables.endpoint import ApiResolutionError

    clock = [0]
    calls = []
    failure = (
        ServerError("temporarily unavailable", response=SimpleNamespace(status_code=503),
                    payload={"code": "authentication_unavailable"})
        if kind == "auth" else ApiResolutionError(
            "MetaTables deployment is unavailable; check its deployment status.")
    )
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])

    async def sleep(delay):
        clock[0] += delay

    def attach(name):
        calls.append(name)
        if name == stage and calls.count(name) == 1:
            raise failure

    monkeypatch.setattr(main.asyncio, "sleep", sleep)
    monkeypatch.setattr(main, "ensure_apps_v1_runtime", lambda: attach("markets"))
    monkeypatch.setattr(main, "ensure_apps_v1_pricing_runtime", lambda: attach("pricing"))

    async def startup():
        async with main.lifespan(None):
            assert metatables.endpoint._operation.get() is None

    asyncio.run(startup())
    assert calls == (["markets", "markets", "pricing"] if stage == "markets" else
                     ["markets", "pricing", "markets", "pricing"])
    assert clock[0] == 5


@pytest.mark.parametrize("status,code", [(401, "authentication_unavailable"),
                                         (403, "authentication_unavailable"),
                                         (500, "authentication_unavailable"),
                                         (503, "schema_invalid")])
def test_startup_does_not_retry_other_failures(monkeypatch, status, code):
    from types import SimpleNamespace
    from mainsequence.client.exceptions import AuthenticationError, PermissionDeniedError, ServerError

    error_type = {401: AuthenticationError, 403: PermissionDeniedError}.get(status, ServerError)
    failure = error_type("failure", response=SimpleNamespace(status_code=status), payload={"code": code})
    calls = []

    def attach():
        calls.append("markets")
        raise failure

    monkeypatch.setattr(main, "ensure_apps_v1_runtime", attach)

    async def startup():
        async with main.lifespan(None):
            pytest.fail("Failed attachment must never serve")

    with pytest.raises(error_type) as caught:
        asyncio.run(startup())
    assert caught.value is failure
    assert calls == ["markets"]


def test_startup_temporary_failure_exhausts_one_budget(monkeypatch):
    from types import SimpleNamespace
    from mainsequence.client.exceptions import ServerError

    clock = [0]
    calls = []
    failure = ServerError("temporarily unavailable", response=SimpleNamespace(status_code=503),
                          payload={"code": "authentication_unavailable"})
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])

    async def sleep(delay):
        clock[0] += delay

    def attach():
        calls.append(clock[0])
        raise failure

    monkeypatch.setattr(main.asyncio, "sleep", sleep)
    monkeypatch.setattr(main, "ensure_apps_v1_runtime", attach)

    async def startup():
        async with main.lifespan(None):
            pytest.fail("Persistent failure must never serve")

    with pytest.raises(ServerError) as caught:
        asyncio.run(startup())
    assert caught.value is failure
    assert calls[0] == 0 and calls[-1] == 300
    assert len(calls) == 61
