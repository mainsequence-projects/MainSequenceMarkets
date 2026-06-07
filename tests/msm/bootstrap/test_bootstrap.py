from __future__ import annotations

import inspect
import os
import sys
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "

import msm.bootstrap as bootstrap
from msm.base import MarketsBase, MarketsMetaTableMixin
from msm.models import AssetTable
from msm.settings import DEFAULT_MARKETS_NAMESPACE


class BootstrapExtensionAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    __metatable_identifier__ = "test.BootstrapExtensionAssetDetails"
    __metatable_description__ = (
        "Project-local asset details table used to verify bootstrap dependency "
        "closure for extension models."
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{AssetTable.__table__.fullname}.uid", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    internal_asset_class: Mapped[str] = mapped_column(String(64), nullable=False)


@pytest.fixture(autouse=True)
def reset_schema_runtime(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "_RUNTIME", None)
    monkeypatch.setattr(bootstrap, "_START_ENGINE_CONFIG", None)
    monkeypatch.setattr(bootstrap, "_RUNTIME_BY_CONFIG", {})
    monkeypatch.delenv("MSM_AUTO_REGISTER_NAMESPACE", raising=False)


def install_fake_bootstrap_modules(monkeypatch):
    resolve_calls = []
    registration = SimpleNamespace(
        meta_tables=["asset-meta-table"],
        models=["Asset"],
        meta_table_by_identifier={"Asset": "asset-meta-table"},
    )

    class FakeMarketsRepositoryContext:
        def __init__(
            self,
            timeout=None,
            namespace=None,
        ) -> None:
            self.timeout = timeout
            self.namespace = namespace

    def fake_resolve_registered_markets_meta_tables(**kwargs):
        resolve_calls.append(kwargs)
        return registration

    def fake_markets_meta_table_identifier(model):
        model_name = str(getattr(model, "__name__", model))
        return {
            "Asset": "Asset",
            "AssetTable": "Asset",
        }.get(model_name, model_name)

    monkeypatch.setitem(
        sys.modules,
        "msm.models.registration",
        SimpleNamespace(
            markets_meta_table_identifier=fake_markets_meta_table_identifier,
            markets_meta_table_models=lambda: ["Asset"],
            resolve_markets_meta_table_models=lambda models=None: list(models or ["Asset"]),
            resolve_registered_markets_meta_tables=fake_resolve_registered_markets_meta_tables,
        ),
    )
    monkeypatch.setitem(sys.modules, "msm.repositories", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "msm.repositories.base",
        SimpleNamespace(MarketsRepositoryContext=FakeMarketsRepositoryContext),
    )
    return resolve_calls, registration


class SpyLogger:
    def __init__(self) -> None:
        self.events = []

    def info(self, event: str, **kwargs) -> None:
        self.events.append((event, kwargs))


def test_start_engine_attaches_metatables_and_returns_repository_context(
    monkeypatch,
) -> None:
    calls, registration = install_fake_bootstrap_modules(monkeypatch)

    runtime = bootstrap.start_engine()

    assert runtime.registration is registration
    assert runtime.meta_tables == ["asset-meta-table"]
    assert runtime.meta_table_models == ["Asset"]
    assert runtime.namespace == DEFAULT_MARKETS_NAMESPACE
    assert runtime.context.namespace == DEFAULT_MARKETS_NAMESPACE
    assert calls[0]["models"] == ["Asset"]
    assert "data_source_uid" not in calls[0]


def test_start_engine_signature_excludes_migration_setup_arguments() -> None:
    parameters = inspect.signature(bootstrap.start_engine).parameters

    assert "data_source_uid" not in parameters
    assert "open_for_everyone" not in parameters
    assert "protect_from_deletion" not in parameters
    assert "introspect" not in parameters


def test_start_engine_can_attach_selected_models(monkeypatch) -> None:
    calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    runtime = bootstrap.start_engine(
        namespace="mainsequence.examples",
        models=["Asset"],
    )

    assert runtime.meta_table_models == ["Asset"]
    assert calls[0]["models"] == ["Asset"]


def test_start_engine_expands_project_local_model_dependencies(monkeypatch) -> None:
    import msm.models.registration as registration_module

    captured_models = []

    def fake_resolve_registered_markets_meta_tables(**kwargs):
        captured_models.append(kwargs["models"])
        return SimpleNamespace(
            meta_tables=[],
            models=kwargs["models"],
            meta_table_by_identifier={},
        )

    monkeypatch.setattr(
        registration_module,
        "resolve_registered_markets_meta_tables",
        fake_resolve_registered_markets_meta_tables,
    )
    runtime = bootstrap.start_engine(models=[BootstrapExtensionAssetDetailsTable])

    assert captured_models == [[AssetTable, BootstrapExtensionAssetDetailsTable]]
    assert runtime.meta_table_models == [AssetTable, BootstrapExtensionAssetDetailsTable]


def test_start_engine_uses_auto_register_namespace_when_omitted(monkeypatch) -> None:
    calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    configured_namespaces = []
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(
        bootstrap,
        "configure_metatable_namespace",
        lambda namespace: configured_namespaces.append(namespace),
    )

    runtime = bootstrap.start_engine(models=["Asset"])

    assert runtime.namespace == "mainsequence.examples"
    assert runtime.context.namespace == "mainsequence.examples"
    assert configured_namespaces == ["mainsequence.examples"]
    assert calls[0]["models"] == ["Asset"]


def test_start_engine_logs_bootstrap_resources(monkeypatch) -> None:
    install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)
    spy_logger = SpyLogger()
    monkeypatch.setattr(bootstrap, "logger", spy_logger)

    bootstrap.start_engine(namespace="mainsequence.examples")
    bootstrap.start_engine(namespace="mainsequence.examples")

    event_names = [event for event, _kwargs in spy_logger.events]
    assert event_names == [
        "Starting markets runtime attachment",
        "Configuring markets MetaTable namespace",
        "Resolved markets MetaTable models",
        "Resolved registered markets MetaTables",
        "Created markets repository context",
        "Created markets runtime",
        "Reusing cached markets runtime; no schema mutation needed",
    ]
    resolved_event = spy_logger.events[2][1]
    assert resolved_event["model_count"] == 1
    assert resolved_event["models"] == ["Asset"]
    attached_event = spy_logger.events[3][1]
    assert attached_event["meta_table_count"] == 1
    runtime_event = spy_logger.events[5][1]
    assert "data_node_handles" not in runtime_event


def test_start_engine_returns_existing_runtime_for_same_process_config(
    monkeypatch,
) -> None:
    calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    first_runtime = bootstrap.start_engine(namespace="mainsequence.examples")
    second_runtime = bootstrap.start_engine(namespace="mainsequence.examples")

    assert second_runtime is first_runtime
    assert first_runtime.namespace == "mainsequence.examples"
    assert first_runtime.context.namespace == "mainsequence.examples"
    assert len(calls) == 1


def test_start_engine_rejects_second_process_config_change(monkeypatch) -> None:
    install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    bootstrap.start_engine(namespace="mainsequence.examples")

    with pytest.raises(RuntimeError, match="already initialized"):
        bootstrap.start_engine(namespace="mainsequence.other")


def test_example_bootstrap_exposes_namespace_constant() -> None:
    from examples.msm.platform import bootstrap as example_bootstrap

    assert example_bootstrap.EXAMPLE_METATABLE_NAMESPACE == "mainsequence.examples"


def test_configure_metatable_namespace_rejects_already_loaded_models(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "msm.models", object())

    with pytest.raises(RuntimeError, match="already loaded with namespace"):
        bootstrap.configure_metatable_namespace("mainsequence.examples")


def test_configure_metatable_namespace_allows_loaded_models_with_same_namespace(
    monkeypatch,
) -> None:
    from msm.base import MarketsMetaTableMixin

    monkeypatch.setitem(sys.modules, "msm.models", object())
    monkeypatch.setattr(
        MarketsMetaTableMixin,
        "__metatable_namespace__",
        "mainsequence.examples",
    )

    bootstrap.configure_metatable_namespace("mainsequence.examples")


def test_attach_schemas_resolves_registered_metatables_without_registering(monkeypatch) -> None:
    resolve_calls, _registration = install_fake_bootstrap_modules(monkeypatch)

    bootstrap.attach_schemas(namespace="mainsequence.markets", models=["Asset"])

    assert resolve_calls == [
        {
            "management_mode": "platform_managed",
            "timeout": None,
            "models": ["Asset"],
        }
    ]


def test_attach_schemas_uses_auto_register_namespace_when_omitted(monkeypatch) -> None:
    resolve_calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")

    runtime = bootstrap.attach_schemas(models=["Asset"])

    assert runtime.namespace == "mainsequence.examples"
    assert runtime.context.namespace == "mainsequence.examples"
    assert resolve_calls == [
        {
            "management_mode": "platform_managed",
            "timeout": None,
            "models": ["Asset"],
        }
    ]


def test_resolve_runtime_requires_initialized_runtime_even_with_auto_namespace(
    monkeypatch,
) -> None:
    resolve_calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")

    with pytest.raises(RuntimeError, match="initialized markets runtime"):
        bootstrap.resolve_runtime(models=["Asset"], row_model_name="Asset")

    assert resolve_calls == []


def test_resolve_runtime_returns_active_runtime_for_required_tables(monkeypatch) -> None:
    resolve_calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    runtime = bootstrap.start_engine(namespace="mainsequence.examples", models=["Asset"])

    assert bootstrap.resolve_runtime(models=["Asset"], row_model_name="Asset") is runtime
    assert len(resolve_calls) == 1


def test_resolve_runtime_uses_identifier_after_physical_binding(monkeypatch) -> None:
    from msm.models import AssetTypeTable
    from msm.repositories.base import MarketsRepositoryContext

    identifier = "backend_physical_asset_type"
    registration = SimpleNamespace(
        meta_tables=["asset-type-meta-table"],
        models=[AssetTypeTable],
        meta_table_by_identifier={identifier: "asset-type-meta-table"},
    )
    runtime = bootstrap.MarketsRuntime(
        registration=registration,
        context=MarketsRepositoryContext(),
    )
    monkeypatch.setattr(bootstrap, "_RUNTIME", runtime)
    monkeypatch.setitem(AssetTypeTable.__table__.info, "identifier", identifier)
    monkeypatch.setattr(
        AssetTypeTable,
        "__metatable_uid__",
        "asset-type-meta-table-uid",
        raising=False,
    )
    monkeypatch.setattr(AssetTypeTable.__table__, "name", "backend_physical_asset_type")
    monkeypatch.setattr(
        AssetTypeTable.__table__,
        "fullname",
        "public.backend_physical_asset_type",
        raising=False,
    )

    assert bootstrap.resolve_runtime(models=[AssetTypeTable], row_model_name="AssetType") is runtime
    assert runtime.table(AssetTypeTable).meta_table == "asset-type-meta-table"


def test_resolve_runtime_missing_tables_error_names_table_declarations(
    monkeypatch,
) -> None:
    install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    bootstrap.start_engine(namespace="mainsequence.examples", models=["Asset"])

    with pytest.raises(RuntimeError, match="IndexTable") as exc_info:
        bootstrap.resolve_runtime(models=["IndexTable"], row_model_name="Index")

    message = str(exc_info.value)
    assert "Index" in message
    assert "Initialized tables: Asset" in message
