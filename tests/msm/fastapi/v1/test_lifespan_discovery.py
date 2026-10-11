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
