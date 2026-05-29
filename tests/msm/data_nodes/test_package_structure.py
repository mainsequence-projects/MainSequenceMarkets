from __future__ import annotations

import importlib
import os

import pytest

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")


@pytest.mark.parametrize(
    "module_name",
    [
        "msm.data_nodes._time",
        "msm.data_nodes.contracts",
        "msm.data_nodes.namespaces",
        "msm.data_nodes.stamped",
        "msm.accounts",
        "msm.accounts.data_nodes",
        "msm.execution",
        "msm.execution.data_nodes",
    ],
)
def test_legacy_data_node_module_paths_are_removed(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


@pytest.mark.parametrize(
    "module_name",
    [
        "msm.data_nodes.utils.time",
        "msm.data_nodes.utils.contracts",
        "msm.data_nodes.utils.namespaces",
        "msm.data_nodes.utils.stamped",
        "msm.data_nodes.accounts",
        "msm.data_nodes.execution",
    ],
)
def test_data_node_package_structure_imports(module_name: str) -> None:
    assert importlib.import_module(module_name)
