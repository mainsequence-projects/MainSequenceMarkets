from __future__ import annotations

import logging
import runpy
from pathlib import Path

import metatables
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
JOB_PATH = PROJECT_ROOT / "jobs" / "migrate_markets.py"


@pytest.mark.parametrize("migrated", [False, True])
def test_job_always_calls_shared_upgrade_and_exposes_timings(
    monkeypatch, capsys, caplog, migrated: bool
) -> None:
    calls = []

    def upgrade(provider):
        calls.append(provider)
        logging.getLogger("metatables.migrations.runner").info(
            "Application migration msm:mainsequence.markets: catalog finalization took 0.001s"
        )
        return {"revision": "0018", "migrated": migrated, "data_source_uid": "test-source"}

    monkeypatch.setattr(metatables, "upgrade_application", upgrade)
    # Restore the logger's level after running the script in this process.
    runner_logger = logging.getLogger("metatables.migrations.runner")
    monkeypatch.setattr(runner_logger, "level", logging.WARNING)

    runpy.run_path(str(JOB_PATH), run_name="__main__")

    assert calls == ["msm_migrations:migration"]
    assert "catalog finalization took 0.001s" in caplog.text
    output = capsys.readouterr().out
    assert "Applying and reconciling msm_migrations:migration" in output
    state = "migrated" if migrated else "already current"
    assert f"0018 ({state}) on test-source" in output


def test_job_does_not_hide_migration_or_finalization_failure(monkeypatch, capsys) -> None:
    failure = RuntimeError("catalog finalization failed")

    def upgrade(provider):
        assert provider == "msm_migrations:migration"
        raise failure

    monkeypatch.setattr(metatables, "upgrade_application", upgrade)
    monkeypatch.setattr(logging.getLogger("metatables.migrations.runner"), "level", logging.WARNING)

    with pytest.raises(RuntimeError) as raised:
        runpy.run_path(str(JOB_PATH), run_name="__main__")

    assert raised.value is failure
    assert "already current" not in capsys.readouterr().out
