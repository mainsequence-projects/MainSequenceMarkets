from __future__ import annotations

import apps.v1.runtime_bootstrap as runtime_bootstrap


def test_ensure_apps_v1_runtime_uses_default_namespace_without_env(monkeypatch) -> None:
    monkeypatch.delenv("MSM_AUTO_REGISTER_NAMESPACE", raising=False)
    monkeypatch.setattr(runtime_bootstrap, "_BOOTSTRAP_COMPLETE", False)

    start_engine_calls: list[dict[str, object]] = []
    runtime = object()

    import msm_portfolios

    monkeypatch.setattr(
        msm_portfolios,
        "start_engine",
        lambda **kwargs: start_engine_calls.append(kwargs) or runtime,
    )

    assert runtime_bootstrap.ensure_apps_v1_runtime() is runtime
    assert start_engine_calls == [
        {
            "namespace": None,
            "models": runtime_bootstrap.V1_RUNTIME_MODELS,
        }
    ]
    assert runtime_bootstrap._BOOTSTRAP_COMPLETE is True


def test_ensure_apps_v1_runtime_calls_start_engine_for_v1_model_set(monkeypatch) -> None:
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(runtime_bootstrap, "_BOOTSTRAP_COMPLETE", False)

    start_engine_calls: list[dict[str, object]] = []
    runtime = object()

    import msm_portfolios

    monkeypatch.setattr(
        msm_portfolios,
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


def test_ensure_apps_v1_runtime_includes_target_position_models() -> None:
    assert "FutureAssetDetails" in runtime_bootstrap.V1_RUNTIME_MODELS
    assert "Portfolio" in runtime_bootstrap.V1_RUNTIME_MODELS
    assert "PortfolioMetadata" in runtime_bootstrap.V1_RUNTIME_MODELS
    assert "PortfolioWeightsStorage" in runtime_bootstrap.V1_RUNTIME_MODELS
    assert "TargetPositionsStorage" in runtime_bootstrap.V1_RUNTIME_MODELS
    assert "AccountTargetAllocation" in runtime_bootstrap.V1_RUNTIME_MODELS
    assert "PositionSet" in runtime_bootstrap.V1_RUNTIME_MODELS
    assert "VirtualFund" in runtime_bootstrap.V1_RUNTIME_MODELS
    assert "VirtualFundHoldingsSet" in runtime_bootstrap.V1_RUNTIME_MODELS
    assert "VirtualFundHoldingsStorage" in runtime_bootstrap.V1_RUNTIME_MODELS


def test_ensure_apps_v1_pricing_runtime_covers_current_pricing_detail_dependencies() -> None:
    from msm_pricing.api import (
        AssetCurrentPricingDetails,
        CurveBuildingDetails,
        PricingMarketDataSetCurveBinding,
    )
    from msm_pricing.meta_tables import resolve_pricing_meta_table_models

    runtime_models = set(
        resolve_pricing_meta_table_models(runtime_bootstrap.V1_PRICING_RUNTIME_MODELS)
    )

    assert set(AssetCurrentPricingDetails.__required_tables__).issubset(runtime_models)
    assert set(CurveBuildingDetails.__required_tables__).issubset(runtime_models)
    assert set(PricingMarketDataSetCurveBinding.__required_tables__).issubset(runtime_models)
    assert "IndexFixingsStorage" in runtime_bootstrap.V1_PRICING_RUNTIME_MODELS


def test_ensure_apps_v1_runtime_propagates_start_engine_failures(monkeypatch) -> None:
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(runtime_bootstrap, "_BOOTSTRAP_COMPLETE", False)

    import msm_portfolios

    monkeypatch.setattr(
        msm_portfolios,
        "start_engine",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    try:
        runtime_bootstrap.ensure_apps_v1_runtime()
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("ensure_apps_v1_runtime should propagate start_engine errors")


def test_ensure_apps_v1_portfolio_runtime_reuses_shared_runtime(monkeypatch) -> None:
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(runtime_bootstrap, "_BOOTSTRAP_COMPLETE", False)
    monkeypatch.setattr(runtime_bootstrap, "_PORTFOLIO_BOOTSTRAP_COMPLETE", False)

    start_engine_calls: list[dict[str, object]] = []
    runtime = object()

    import msm_portfolios

    monkeypatch.setattr(
        msm_portfolios,
        "start_engine",
        lambda **kwargs: start_engine_calls.append(kwargs) or runtime,
    )

    assert runtime_bootstrap.ensure_apps_v1_portfolio_runtime() is runtime
    assert start_engine_calls == [
        {
            "namespace": "mainsequence.examples",
            "models": runtime_bootstrap.V1_RUNTIME_MODELS,
        }
    ]
    assert runtime_bootstrap._BOOTSTRAP_COMPLETE is True
    assert runtime_bootstrap._PORTFOLIO_BOOTSTRAP_COMPLETE is True


def test_ensure_apps_v1_portfolio_runtime_does_not_restart_after_shared_start(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(runtime_bootstrap, "_BOOTSTRAP_COMPLETE", True)
    monkeypatch.setattr(runtime_bootstrap, "_PORTFOLIO_BOOTSTRAP_COMPLETE", False)

    import msm_portfolios

    monkeypatch.setattr(
        msm_portfolios,
        "start_engine",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("portfolio runtime must not start a second markets runtime")
        ),
    )

    assert runtime_bootstrap.ensure_apps_v1_portfolio_runtime() is None
    assert runtime_bootstrap._PORTFOLIO_BOOTSTRAP_COMPLETE is True


def test_ensure_apps_v1_pricing_runtime_attaches_pricing_models(monkeypatch) -> None:
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")
    monkeypatch.setattr(runtime_bootstrap, "_PRICING_BOOTSTRAP_COMPLETE", False)

    attach_calls: list[dict[str, object]] = []
    runtime = object()

    import msm_pricing.bootstrap as pricing_bootstrap

    monkeypatch.setattr(
        pricing_bootstrap,
        "attach_pricing_schemas",
        lambda **kwargs: attach_calls.append(kwargs) or runtime,
    )

    assert runtime_bootstrap.ensure_apps_v1_pricing_runtime() is runtime
    assert attach_calls == [
        {
            "namespace": "mainsequence.examples",
            "models": runtime_bootstrap.V1_PRICING_RUNTIME_MODELS,
            "seed_default_market_data_bindings": False,
            "replace_default_market_data_bindings": False,
        }
    ]
    assert runtime_bootstrap._PRICING_BOOTSTRAP_COMPLETE is True


def test_ensure_apps_v1_pricing_runtime_uses_default_namespace_without_env(monkeypatch) -> None:
    monkeypatch.delenv("MSM_AUTO_REGISTER_NAMESPACE", raising=False)
    monkeypatch.setattr(runtime_bootstrap, "_PRICING_BOOTSTRAP_COMPLETE", False)

    attach_calls: list[dict[str, object]] = []
    runtime = object()

    import msm_pricing.bootstrap as pricing_bootstrap

    monkeypatch.setattr(
        pricing_bootstrap,
        "attach_pricing_schemas",
        lambda **kwargs: attach_calls.append(kwargs) or runtime,
    )

    assert runtime_bootstrap.ensure_apps_v1_pricing_runtime() is runtime
    assert attach_calls == [
        {
            "namespace": None,
            "models": runtime_bootstrap.V1_PRICING_RUNTIME_MODELS,
            "seed_default_market_data_bindings": False,
            "replace_default_market_data_bindings": False,
        }
    ]
    assert runtime_bootstrap._PRICING_BOOTSTRAP_COMPLETE is True


def test_every_remote_row_resource_is_served_by_the_api_runtime() -> None:
    """`POST /rows/{resource}/{operation}/` runs on the runtime this API attaches.

    A row class the route offers whose tables are not attached raises a RuntimeError from
    `resolve_runtime` on every call, which the route answers with 500 (the order-manager
    batch lookup of a connector's execution ledger did exactly that).
    """

    from apps.v1.routers.rows import _load_row_classes
    from msm.models.registration import resolve_markets_meta_table_models
    from msm_portfolios.bootstrap import resolve_portfolio_models
    from msm_pricing.meta_tables import resolve_pricing_meta_table_models

    attached = set(
        resolve_markets_meta_table_models(
            resolve_portfolio_models(runtime_bootstrap.V1_RUNTIME_MODELS)
        )
    ) | set(resolve_pricing_meta_table_models(runtime_bootstrap.V1_PRICING_RUNTIME_MODELS))

    missing: dict[str, list[str]] = {}
    for resource, row_class in sorted(_load_row_classes().items()):
        required = list(getattr(row_class, "__required_tables__", None) or [])
        if row_class.__module__.startswith("msm_pricing."):
            needed = resolve_pricing_meta_table_models(required)
        else:
            needed = resolve_markets_meta_table_models(resolve_portfolio_models(required))
        absent = sorted(model.__name__ for model in needed if model not in attached)
        if absent:
            missing[resource] = absent

    assert missing == {}


def test_ensure_apps_v1_runtime_includes_execution_ledger_models() -> None:
    assert "OrderManager" in runtime_bootstrap.V1_RUNTIME_MODELS
