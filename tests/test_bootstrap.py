from __future__ import annotations

import os
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "

import msm.bootstrap as bootstrap


@pytest.fixture(autouse=True)
def reset_schema_runtime(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "_RUNTIME", None)
    monkeypatch.setattr(bootstrap, "_CREATE_SCHEMAS_CONFIG", None)


def install_fake_bootstrap_modules(monkeypatch):
    calls = []
    registration = SimpleNamespace(
        target_meta_table_uid_by_fullname={"public.asset": "asset-meta-table-uid"},
        meta_tables=["asset-meta-table"],
    )

    class FakeMarketsRepositoryContext:
        def __init__(
            self,
            target_meta_table_uid_by_fullname,
            timeout=None,
            namespace=None,
        ) -> None:
            self.target_meta_table_uid_by_fullname = target_meta_table_uid_by_fullname
            self.timeout = timeout
            self.namespace = namespace

    def fake_register_markets_meta_tables(**kwargs):
        calls.append(kwargs)
        return registration

    monkeypatch.setitem(
        sys.modules,
        "msm.meta_tables",
        SimpleNamespace(
            markets_meta_table_models=lambda: ["Asset"],
            register_markets_meta_tables=fake_register_markets_meta_tables,
        ),
    )
    monkeypatch.setitem(sys.modules, "msm.repositories", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "msm.repositories.base",
        SimpleNamespace(MarketsRepositoryContext=FakeMarketsRepositoryContext),
    )
    return calls, registration


class SpyLogger:
    def __init__(self) -> None:
        self.events = []

    def info(self, event: str, **kwargs) -> None:
        self.events.append((event, kwargs))


def test_create_schemas_registers_metatables_and_returns_repository_context(
    monkeypatch,
) -> None:
    calls, registration = install_fake_bootstrap_modules(monkeypatch)

    runtime = bootstrap.create_schemas(data_source_uid="data-source-uid")

    assert runtime.registration is registration
    assert runtime.meta_tables == ["asset-meta-table"]
    assert runtime.meta_table_models == ["Asset"]
    assert runtime.context.target_meta_table_uid_by_fullname == {
        "public.asset": "asset-meta-table-uid"
    }
    assert runtime.namespace is None
    assert runtime.context.namespace is None
    assert calls[0]["data_source_uid"] == "data-source-uid"
    assert "labels" not in calls[0]


def test_create_schemas_logs_bootstrap_resources(monkeypatch) -> None:
    install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)
    spy_logger = SpyLogger()
    monkeypatch.setattr(bootstrap, "logger", spy_logger)

    bootstrap.create_schemas(namespace="mainsequence.examples")
    bootstrap.create_schemas(namespace="mainsequence.examples")

    event_names = [event for event, _kwargs in spy_logger.events]
    assert event_names == [
        "Starting markets bootstrap",
        "Configuring markets MetaTable namespace",
        "Registered markets MetaTables",
        "Created markets repository context",
        "Created markets runtime",
        "Reusing cached markets runtime; no MetaTables registered",
    ]
    registered_event = spy_logger.events[2][1]
    assert registered_event["meta_table_count"] == 1
    assert registered_event["target_meta_table_count"] == 1
    runtime_event = spy_logger.events[4][1]
    assert runtime_event["data_node_handles"] == list(bootstrap.DATA_NODE_HANDLE_NAMES)


def test_runtime_exposes_data_node_classes(monkeypatch) -> None:
    install_fake_bootstrap_modules(monkeypatch)
    account_data_nodes_module = ModuleType("msm.accounts.data_nodes")
    account_data_nodes_module.AccountHoldings = type("AccountHoldings", (), {})
    account_data_nodes_module.VirtualFundHoldings = type("VirtualFundHoldings", (), {})
    data_nodes_module = ModuleType("msm.data_nodes")
    data_nodes_module.AssetPricingDetail = type("AssetPricingDetail", (), {})
    data_nodes_module.AssetSnapshot = type("AssetSnapshot", (), {})
    portfolio_data_nodes_module = ModuleType("msm.portfolios.data_nodes")
    portfolio_data_nodes_module.PortfolioWeights = type("PortfolioWeights", (), {})
    portfolio_data_nodes_module.PortfoliosDataNode = type("PortfoliosDataNode", (), {})
    portfolio_data_nodes_module.SignalWeights = type("SignalWeights", (), {})
    monkeypatch.setitem(sys.modules, "msm.accounts.data_nodes", account_data_nodes_module)
    monkeypatch.setitem(sys.modules, "msm.data_nodes", data_nodes_module)
    monkeypatch.setitem(
        sys.modules,
        "msm.portfolios.data_nodes",
        portfolio_data_nodes_module,
    )

    runtime = bootstrap.create_schemas(data_source_uid="data-source-uid")

    assert runtime.data_nodes == {
        "AccountHoldings": account_data_nodes_module.AccountHoldings,
        "AssetPricingDetail": data_nodes_module.AssetPricingDetail,
        "AssetSnapshot": data_nodes_module.AssetSnapshot,
        "PortfolioWeights": portfolio_data_nodes_module.PortfolioWeights,
        "PortfoliosDataNode": portfolio_data_nodes_module.PortfoliosDataNode,
        "SignalWeights": portfolio_data_nodes_module.SignalWeights,
        "VirtualFundHoldings": account_data_nodes_module.VirtualFundHoldings,
    }


def test_create_schemas_returns_existing_runtime_for_same_process_config(
    monkeypatch,
) -> None:
    calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    first_runtime = bootstrap.create_schemas(namespace="mainsequence.examples")
    second_runtime = bootstrap.create_schemas(namespace="mainsequence.examples")

    assert second_runtime is first_runtime
    assert first_runtime.namespace == "mainsequence.examples"
    assert first_runtime.context.namespace == "mainsequence.examples"
    assert len(calls) == 1


def test_create_schemas_rejects_second_process_config_change(monkeypatch) -> None:
    install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    bootstrap.create_schemas(namespace="mainsequence.examples")

    with pytest.raises(RuntimeError, match="already initialized"):
        bootstrap.create_schemas(namespace="mainsequence.other")


def test_example_bootstrap_exposes_namespace_constant() -> None:
    from examples.platform import bootstrap as example_bootstrap

    assert example_bootstrap.EXAMPLE_METATABLE_NAMESPACE == "mainsequence.examples"


def test_configure_metatable_namespace_rejects_already_loaded_models(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "msm.models", object())

    with pytest.raises(RuntimeError, match="before importing msm.models"):
        bootstrap.configure_metatable_namespace("mainsequence.examples")
