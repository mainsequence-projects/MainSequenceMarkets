from __future__ import annotations

import logging
import runpy
from contextlib import contextmanager
from pathlib import Path

import metatables
import metatables.endpoint
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
JOB_PATH = PROJECT_ROOT / "jobs" / "migrate_markets.py"


@pytest.fixture
def discovery_scope(monkeypatch):
    state = {"budgets": [], "active": False}
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

    monkeypatch.setattr(metatables.endpoint, "api_endpoint_scope", observe_scope)
    return state


@pytest.mark.parametrize("migrated", [False, True])
def test_job_always_calls_shared_upgrade_and_exposes_timings(
    monkeypatch, capsys, caplog, discovery_scope, migrated: bool
) -> None:
    calls = []

    def upgrade(provider):
        assert discovery_scope["active"]
        calls.append(provider)
        logging.getLogger("metatables.migrations.runner").info(
            "Application migration msm:mainsequence.markets: catalog finalization took 0.001s"
        )
        return {"revision": "0020", "migrated": migrated, "data_source_uid": "test-source"}

    monkeypatch.setattr(metatables, "upgrade_application", upgrade)
    # Restore the logger's level after running the script in this process.
    runner_logger = logging.getLogger("metatables.migrations.runner")
    monkeypatch.setattr(runner_logger, "level", logging.WARNING)

    runpy.run_path(str(JOB_PATH), run_name="__main__")

    assert calls == ["msm_migrations:migration"]
    assert discovery_scope == {"budgets": [300], "active": False}
    assert "catalog finalization took 0.001s" in caplog.text
    output = capsys.readouterr().out
    assert "Applying and reconciling msm_migrations:migration" in output
    state = "migrated" if migrated else "already current"
    assert f"0020 ({state}) on test-source" in output


def test_job_does_not_hide_migration_or_finalization_failure(
    monkeypatch, capsys, discovery_scope
) -> None:
    failure = RuntimeError("catalog finalization failed")

    def upgrade(provider):
        assert discovery_scope["active"]
        assert provider == "msm_migrations:migration"
        raise failure

    monkeypatch.setattr(metatables, "upgrade_application", upgrade)
    monkeypatch.setattr(logging.getLogger("metatables.migrations.runner"), "level", logging.WARNING)

    with pytest.raises(RuntimeError) as raised:
        runpy.run_path(str(JOB_PATH), run_name="__main__")

    assert raised.value is failure
    assert discovery_scope == {"budgets": [300], "active": False}
    assert "already current" not in capsys.readouterr().out
