from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "

import msm.bootstrap as bootstrap


@pytest.fixture(autouse=True)
def reset_start_runtime(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "_RUNTIME", None)
    monkeypatch.setattr(bootstrap, "_START_CONFIG", None)


def install_fake_bootstrap_modules(monkeypatch):
    calls = []
    registration = SimpleNamespace(
        target_meta_table_uid_by_fullname={"public.asset": "asset-meta-table-uid"},
        meta_tables=[],
    )

    class FakeMarketsRepositoryContext:
        def __init__(self, target_meta_table_uid_by_fullname, timeout=None) -> None:
            self.target_meta_table_uid_by_fullname = target_meta_table_uid_by_fullname
            self.timeout = timeout

    def fake_register_markets_meta_tables(**kwargs):
        calls.append(kwargs)
        return registration

    monkeypatch.setitem(
        sys.modules,
        "msm.meta_tables",
        SimpleNamespace(register_markets_meta_tables=fake_register_markets_meta_tables),
    )
    monkeypatch.setitem(sys.modules, "msm.repositories", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "msm.repositories.base",
        SimpleNamespace(MarketsRepositoryContext=FakeMarketsRepositoryContext),
    )
    return calls, registration


def test_start_registers_metatables_and_returns_repository_context(monkeypatch) -> None:
    calls, registration = install_fake_bootstrap_modules(monkeypatch)

    runtime = bootstrap.start(data_source_uid="data-source-uid", labels=["unit-test"])

    assert runtime.registration is registration
    assert runtime.context.target_meta_table_uid_by_fullname == {
        "public.asset": "asset-meta-table-uid"
    }
    assert calls[0]["data_source_uid"] == "data-source-uid"
    assert calls[0]["labels"] == ["unit-test"]


def test_start_returns_existing_runtime_for_same_process_config(monkeypatch) -> None:
    calls, _registration = install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    first_runtime = bootstrap.start(namespace="mainsequence.examples", labels=["unit-test"])
    second_runtime = bootstrap.start(namespace="mainsequence.examples", labels=["unit-test"])

    assert second_runtime is first_runtime
    assert len(calls) == 1


def test_start_rejects_second_process_config_change(monkeypatch) -> None:
    install_fake_bootstrap_modules(monkeypatch)
    monkeypatch.setattr(bootstrap, "configure_metatable_namespace", lambda namespace: None)

    bootstrap.start(namespace="mainsequence.examples", labels=["unit-test"])

    with pytest.raises(RuntimeError, match="already initialized"):
        bootstrap.start(namespace="mainsequence.other", labels=["unit-test"])


def test_start_rejects_conflicting_namespace_aliases(monkeypatch) -> None:
    install_fake_bootstrap_modules(monkeypatch)

    with pytest.raises(ValueError, match="either namespace or metatable_namespace"):
        bootstrap.start(
            namespace="mainsequence.examples",
            metatable_namespace="mainsequence.other",
        )


def test_example_bootstrap_delegates_namespace(monkeypatch) -> None:
    from examples.platform import bootstrap as example_bootstrap

    calls = []
    runtime = object()

    def fake_start(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr(example_bootstrap.msm, "start", fake_start)

    assert (
        example_bootstrap.start_examples_runtime(
            namespace="mainsequence.examples",
            labels=["asset-crud-example"],
        )
        is runtime
    )
    assert calls == [
        {
            "namespace": "mainsequence.examples",
            "labels": ["asset-crud-example"],
        }
    ]


def test_configure_metatable_namespace_rejects_already_loaded_models(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "msm.models", object())

    with pytest.raises(RuntimeError, match="before importing msm.models"):
        bootstrap.configure_metatable_namespace("mainsequence.examples")
