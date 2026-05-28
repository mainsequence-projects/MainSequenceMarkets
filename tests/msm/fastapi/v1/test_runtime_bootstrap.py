from __future__ import annotations

import apps.v1.runtime_bootstrap as runtime_bootstrap


def test_ensure_apps_v1_runtime_is_noop_without_namespace(monkeypatch) -> None:
    monkeypatch.delenv("MSM_AUTO_REGISTER_NAMESPACE", raising=False)
    monkeypatch.setattr(runtime_bootstrap, "_BOOTSTRAP_COMPLETE", False)

    assert runtime_bootstrap.ensure_apps_v1_runtime() is None
    assert runtime_bootstrap._BOOTSTRAP_COMPLETE is False


def test_ensure_apps_v1_runtime_calls_start_engine_for_v1_model_set(monkeypatch) -> None:
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(runtime_bootstrap, "_BOOTSTRAP_COMPLETE", False)

    start_engine_calls: list[dict[str, object]] = []
    runtime = object()

    import msm

    monkeypatch.setattr(
        msm,
        "start_engine",
        lambda **kwargs: start_engine_calls.append(kwargs) or runtime,
    )

    assert runtime_bootstrap.ensure_apps_v1_runtime() is runtime
    assert start_engine_calls == [
        {
            "namespace": "mainsequence.examples",
            "models": runtime_bootstrap.V1_RUNTIME_MODELS,
        }
    ]
    assert runtime_bootstrap._BOOTSTRAP_COMPLETE is True


def test_ensure_apps_v1_runtime_propagates_start_engine_failures(monkeypatch) -> None:
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(runtime_bootstrap, "_BOOTSTRAP_COMPLETE", False)

    import msm

    monkeypatch.setattr(
        msm,
        "start_engine",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    try:
        runtime_bootstrap.ensure_apps_v1_runtime()
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("ensure_apps_v1_runtime should propagate start_engine errors")
