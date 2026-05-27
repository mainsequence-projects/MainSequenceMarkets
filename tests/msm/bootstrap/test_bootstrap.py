from __future__ import annotations

import os
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "

import msm.bootstrap as bootstrap
from msm.settings import DEFAULT_MARKETS_NAMESPACE


@pytest.fixture(autouse=True)
def reset_schema_runtime(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "_RUNTIME", None)
    monkeypatch.setattr(bootstrap, "_CREATE_SCHEMAS_CONFIG", None)
    monkeypatch.setattr(bootstrap, "_RUNTIME_BY_CONFIG", {})
    monkeypatch.delenv("MSM_AUTO_REGISTER_NAMESPACE", raising=False)


def install_fake_bootstrap_modules(monkeypatch):
    calls = []
    attach_calls = []
    registration = SimpleNamespace(
        target_meta_table_uid_by_fullname={"public.asset": "asset-meta-table-uid"},
        meta_tables=["asset-meta-table"],
        models=["Asset"],
        meta_table_by_fullname={"public.asset": "asset-meta-table"},
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

    def fake_resolve_registered_markets_meta_tables(**kwargs):
        attach_calls.append(kwargs)
        return registration

    monkeypatch.setitem(
        sys.modules,
        "msm.models.registration",
        SimpleNamespace(
            markets_meta_table_fullname=lambda model: "public.asset",
            markets_meta_table_models=lambda: ["Asset"],
            resolve_markets_meta_table_models=lambda models=None: list(models or ["Asset"]),
            register_markets_meta_tables=fake_register_markets_meta_tables,
            resolve_registered_markets_meta_tables=fake_resolve_registered_markets_meta_tables,
        ),
    )
    monkeypatch.setitem(sys.modules, "msm.repositories", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "msm.repositories.base",
        SimpleNamespace(MarketsRepositoryContext=FakeMarketsRepositoryContext),
    )
    return calls, attach_calls, registration


class SpyLogger:
    def __init__(self) -> None:
        self.events = []

    def info(self, event: str, **kwargs) -> None:
        self.events.append((event, kwargs))


def test_create_schemas_registers_metatables_and_returns_repository_context(
    monkeypatch,
) -> None:
    calls, _attach_calls, registration = install_fake_bootstrap_modules(monkeypatch)

    runtime = bootstrap.create_schemas(data_source_uid="data-source-uid")

    assert runtime.registration is registration
    assert runtime.meta_tables == ["asset-meta-table"]
    assert runtime.meta_table_models == ["Asset"]
    assert runtime.context.target_meta_table_uid_by_fullname == {
        "public.asset": "asset-meta-table-uid"
    }
    assert runtime.namespace == DEFAULT_MARKETS_NAMESPACE
    assert runtime.context.namespace == DEFAULT_MARKETS_NAMESPACE
    assert calls[0]["data_source_uid"] == "data-source-uid"
    assert calls[0]["models"] == ["Asset"]
    assert "labels" not in calls[0]


def test_create_schemas_can_register_selected_models(monkeypatch) -> None:
    calls, _attach_calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    runtime = bootstrap.create_schemas(
        namespace="mainsequence.examples",
        models=["Asset"],
    )

    assert runtime.meta_table_models == ["Asset"]
    assert calls[0]["models"] == ["Asset"]


def test_create_schemas_uses_auto_register_namespace_when_omitted(monkeypatch) -> None:
    calls, _attach_calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    configured_namespaces = []
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(
        bootstrap,
        "configure_metatable_namespace",
        lambda namespace: configured_namespaces.append(namespace),
    )

    runtime = bootstrap.create_schemas(models=["Asset"])

    assert runtime.namespace == "mainsequence.examples"
    assert runtime.context.namespace == "mainsequence.examples"
    assert configured_namespaces == ["mainsequence.examples"]
    assert calls[0]["models"] == ["Asset"]


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
        "Resolved markets MetaTable models",
        "Registered markets MetaTables",
        "Created markets repository context",
        "Created markets runtime",
        "Reusing cached markets runtime; no MetaTables registered",
    ]
    resolved_event = spy_logger.events[2][1]
    assert resolved_event["model_count"] == 1
    assert resolved_event["models"] == ["Asset"]
    registered_event = spy_logger.events[3][1]
    assert registered_event["meta_table_count"] == 1
    assert registered_event["target_meta_table_count"] == 1
    runtime_event = spy_logger.events[5][1]
    assert runtime_event["data_node_handles"] == list(bootstrap.DATA_NODE_HANDLE_NAMES)


def test_runtime_exposes_data_node_classes(monkeypatch) -> None:
    install_fake_bootstrap_modules(monkeypatch)
    account_data_nodes_module = ModuleType("msm.data_nodes.accounts")
    account_data_nodes_module.AccountHoldings = type("AccountHoldings", (), {})
    account_data_nodes_module.VirtualFundHoldings = type("VirtualFundHoldings", (), {})
    asset_data_nodes_module = ModuleType("msm.data_nodes.assets")
    asset_data_nodes_module.AssetSnapshot = type("AssetSnapshot", (), {})
    pricing_data_nodes_module = ModuleType("msm_pricing.data_nodes")
    pricing_data_nodes_module.AssetPricingDetail = type("AssetPricingDetail", (), {})
    portfolio_data_nodes_module = ModuleType("msm.portfolios.data_nodes")
    portfolio_data_nodes_module.PortfolioWeights = type("PortfolioWeights", (), {})
    portfolio_data_nodes_module.PortfoliosDataNode = type("PortfoliosDataNode", (), {})
    portfolio_data_nodes_module.SignalWeights = type("SignalWeights", (), {})
    monkeypatch.setitem(sys.modules, "msm.data_nodes.accounts", account_data_nodes_module)
    monkeypatch.setitem(sys.modules, "msm.data_nodes.assets", asset_data_nodes_module)
    monkeypatch.setitem(sys.modules, "msm_pricing.data_nodes", pricing_data_nodes_module)
    monkeypatch.setitem(
        sys.modules,
        "msm.portfolios.data_nodes",
        portfolio_data_nodes_module,
    )

    runtime = bootstrap.create_schemas(data_source_uid="data-source-uid")

    assert runtime.data_nodes == {
        "AccountHoldings": account_data_nodes_module.AccountHoldings,
        "AssetPricingDetail": pricing_data_nodes_module.AssetPricingDetail,
        "AssetSnapshot": asset_data_nodes_module.AssetSnapshot,
        "PortfolioWeights": portfolio_data_nodes_module.PortfolioWeights,
        "PortfoliosDataNode": portfolio_data_nodes_module.PortfoliosDataNode,
        "SignalWeights": portfolio_data_nodes_module.SignalWeights,
        "VirtualFundHoldings": account_data_nodes_module.VirtualFundHoldings,
    }


def test_create_schemas_returns_existing_runtime_for_same_process_config(
    monkeypatch,
) -> None:
    calls, _attach_calls, _registration = install_fake_bootstrap_modules(monkeypatch)
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


def test_attach_schemas_resolves_registered_metatables_without_registering(monkeypatch) -> None:
    register_calls, attach_calls, _registration = install_fake_bootstrap_modules(monkeypatch)

    runtime = bootstrap.attach_schemas(namespace="mainsequence.markets", models=["Asset"])

    assert runtime.context.target_meta_table_uid_by_fullname == {
        "public.asset": "asset-meta-table-uid"
    }
    assert register_calls == []
    assert attach_calls == [
        {
            "data_source_uid": None,
            "management_mode": "platform_managed",
            "namespace": "mainsequence.markets",
            "timeout": None,
            "models": ["Asset"],
        }
    ]


def test_attach_schemas_uses_auto_register_namespace_when_omitted(monkeypatch) -> None:
    register_calls, attach_calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")

    runtime = bootstrap.attach_schemas(models=["Asset"])

    assert runtime.namespace == "mainsequence.examples"
    assert runtime.context.namespace == "mainsequence.examples"
    assert register_calls == []
    assert attach_calls == [
        {
            "data_source_uid": None,
            "management_mode": "platform_managed",
            "namespace": "mainsequence.examples",
            "timeout": None,
            "models": ["Asset"],
        }
    ]


def test_resolve_runtime_attaches_before_registering(monkeypatch) -> None:
    register_calls, attach_calls, _registration = install_fake_bootstrap_modules(monkeypatch)

    runtime = bootstrap.resolve_runtime(models=["Asset"], row_model_name="Asset")

    assert runtime.context.target_meta_table_uid_by_fullname["public.asset"]
    assert register_calls == []
    assert attach_calls[0]["models"] == ["Asset"]


def test_resolve_runtime_auto_registers_when_enabled(monkeypatch) -> None:
    runtime = SimpleNamespace(context=object())
    calls = []

    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setitem(
        sys.modules,
        "msm.models.registration",
        SimpleNamespace(resolve_markets_meta_table_models=lambda models=None: list(models or [])),
    )
    monkeypatch.setattr(
        bootstrap,
        "attach_schemas",
        lambda **kwargs: (_ for _ in ()).throw(LookupError("missing")),
    )

    def fake_auto_register_schemas(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr(bootstrap, "auto_register_schemas", fake_auto_register_schemas)

    assert bootstrap.resolve_runtime(models=["Asset"], row_model_name="Asset") is runtime
    assert calls == [
        {
            "namespace": "mainsequence.examples",
            "models": ["Asset"],
            "timeout": None,
        }
    ]


def test_resolve_runtime_missing_tables_error_names_registration_options(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "msm.models.registration",
        SimpleNamespace(resolve_markets_meta_table_models=lambda models=None: list(models or [])),
    )
    monkeypatch.setattr(
        bootstrap,
        "attach_schemas",
        lambda **kwargs: (_ for _ in ()).throw(LookupError("missing")),
    )

    with pytest.raises(RuntimeError, match="MSM_AUTO_REGISTER_NAMESPACE"):
        bootstrap.resolve_runtime(models=["AssetTable"], row_model_name="Asset")


def test_auto_register_schemas_registers_without_setting_explicit_config(monkeypatch) -> None:
    calls, _attach_calls, registration = install_fake_bootstrap_modules(monkeypatch)

    runtime = bootstrap.auto_register_schemas(
        namespace="mainsequence.markets",
        models=["Asset"],
    )

    assert runtime.registration is registration
    assert bootstrap._CREATE_SCHEMAS_CONFIG is None
    assert calls == [
        {
            "data_source_uid": None,
            "management_mode": "platform_managed",
            "timeout": None,
            "models": ["Asset"],
        }
    ]
