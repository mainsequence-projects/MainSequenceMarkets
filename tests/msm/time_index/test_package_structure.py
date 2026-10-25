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
        "msm.time_index._time",
        "msm.time_index.contracts",
        "msm.time_index.namespaces",
        "msm.time_index.stamped",
        "msm.accounts",
        "msm.accounts.data_nodes",
        "msm.execution",
        "msm.execution.data_nodes",
        # ADR 0017 removed the DataNodeTableContract module entirely; its
        # holdings/position schemas now live on the storage classes.
        "msm.time_index.utils.contracts",
        # ms-markets 4.0 removed the pre-3.0 alias packages (ADR 0048).
        "msm.data_nodes",
        "msm_portfolios.data_nodes",
        "msm_pricing.data_nodes",
        "msm_portfolios.contrib.prices.data_nodes",
    ],
)
def test_legacy_data_node_module_paths_are_removed(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


@pytest.mark.parametrize(
    "module_name",
    [
        "msm.time_index.utils.time",
        "msm.time_index.utils.namespaces",
        "msm.time_index.utils.stamped",
        "msm.time_index.utils.storage_schema",
        "msm.time_index.accounts",
        "msm.time_index.accounts.storage",
        "msm.time_index.assets.storage",
        "msm.time_index.execution",
        "msm.time_index.execution.storage",
    ],
)
def test_time_index_package_structure_imports(module_name: str) -> None:
    assert importlib.import_module(module_name)
