"""The examples write only to MetaTables' local SQLite runtime (#109).

Markets' tables have the same names in every database, so an example that did not select
the local runtime would write to the real tables of the Environment it resolves.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]

# An operator tool for a real database, not an example in this sense.
OPERATOR_TOOLS = {"msm_portfolios/portfolio_midnight_timestamp_repair.py"}
WRITERS = (
    "msm/accounts/account_portfolio_full_workflow.py",
    "msm/accounts/account_virtual_fund_allocation_example.py",
    "msm/assets/asset_category_workflow.py",
    "msm/assets/asset_crud_workflow.py",
    "msm/assets/bond_workflow.py",
    "msm/assets/currency_spot_workflow.py",
    "msm/assets/derivatives/crypto_future_without_figi.py",
    "msm/assets/derivatives/index_future_from_openfigi.py",
    "msm/assets/us_treasury_bond_workflow.py",
    "msm/calendars/calendar_rules_and_exceptions_workflow.py",
    "msm/indices/index_values_frequency_migration.py",
    "msm/platform/custom_asset_details_extension.py",
    "msm/workflows/asset_category_workflow.py",
    "msm_portfolios/portfolio_equal_weights_dynamic_migration.py",
    "msm_portfolios/portfolio_equal_weights_example.py",
    "msm_portfolios/portfolio_equal_weights_prepare_schema.py",
    "msm_portfolios/portfolio_equal_weights_run.py",
    "msm_portfolios/portfolio_groups_example.py",
    "msm_pricing/bond_pricing_example/main.py",
    "msm_pricing/pricing_registry_rows.py",
)
RUN_EXAMPLE = """
import runpy, sys

sys.argv = sys.argv[1:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except RuntimeError as error:
    print("refused:", error)
print("client models imported:", bool({"msm.models", "metatables.models"} & set(sys.modules)))
"""
LOCAL_SQLITE = {"local_mode": True, "dialect": "sqlite"}
# Attaching is how an example starts to write; the others write with no attach of their own.
WRITE_CALLS = {
    "attach_pricing_schemas",
    "attach_schemas",
    "build_metatable_migration_provider",
    "reconcile_dataset_availability",
    "run_migration",
    "start_engine",
    "upgrade_application",
    "upsert",
    "upsert_many",
}


def test_every_example_that_writes_selects_the_local_runtime() -> None:
    root = REPOSITORY / "examples"
    unchecked = []
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root).as_posix()
        if name in OPERATOR_TOOLS:
            continue
        calls = {
            getattr(node.func, "attr", getattr(node.func, "id", None))
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Call)
        }
        if calls & WRITE_CALLS and "use_local_runtime" not in calls:
            unchecked.append(name)

    assert unchecked == []


@pytest.mark.parametrize("example", WRITERS)
def test_a_writing_example_selects_the_local_runtime_before_client_models(
    example, tmp_path
) -> None:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("METATABLES_", "MSM_", "MARKETS_"))
    }
    environment |= {
        "PYTHONPATH": os.pathsep.join(
            [str(REPOSITORY / "src"), str(REPOSITORY), os.environ.get("PYTHONPATH", "")]
        ),
        # No local API runs here, and a regression must not reach a hosted one.
        "METATABLES_LOCAL_STORAGE_DIR": str(tmp_path),
        "MAINSEQUENCE_ENDPOINT": "http://127.0.0.1:9",
    }

    run = subprocess.run(
        [sys.executable, "-c", RUN_EXAMPLE, str(REPOSITORY / "examples" / example)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert "refused: No running local MetaTables API" in run.stdout, run.stdout + run.stderr
    assert "client models imported: False" in run.stdout


@pytest.mark.parametrize(
    ("state", "backend", "refusal"),
    [
        (LOCAL_SQLITE, "", None),
        ({"local_mode": False, "dialect": "sqlite"}, "", "local SQLite runtime"),
        ({"local_mode": True, "dialect": "postgresql"}, "", "local SQLite runtime"),
        ({"local_mode": True, "dialect": None}, "", "local SQLite runtime"),
        (LOCAL_SQLITE, "remote", "Markets API"),
    ],
    ids=["local-sqlite", "hosted", "local-postgresql", "uninitialized", "markets-api"],
)
def test_use_local_runtime_selects_then_checks(monkeypatch, state, backend, refusal) -> None:
    import metatables

    from examples.msm.platform.bootstrap import use_local_runtime
    from msm.api import remote

    calls: list[str] = []
    monkeypatch.setattr(metatables, "configure_local_client", lambda: calls.append("select"))
    monkeypatch.setattr(metatables, "get_runtime_status", lambda: calls.append("check") or state)
    monkeypatch.setattr(remote, "_remote_backend", None)
    monkeypatch.setenv("MSM_API_BACKEND", backend)

    if refusal is None:
        use_local_runtime()
    else:
        with pytest.raises(RuntimeError, match=refusal):
            use_local_runtime()

    assert calls == ["select", "check"]
