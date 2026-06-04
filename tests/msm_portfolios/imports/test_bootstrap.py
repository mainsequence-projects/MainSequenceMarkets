from __future__ import annotations

import inspect
from types import SimpleNamespace

import msm_portfolios.bootstrap as bootstrap
from msm.models import AccountTable, AssetTable, IndexTable
from msm_portfolios.models import (
    PortfolioTable,
    VirtualFundTable,
    portfolio_sqlalchemy_models,
)


def test_portfolio_bootstrap_defaults_to_portfolio_model_graph(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_start_engine(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr(bootstrap, "_start_engine", fake_start_engine)

    assert bootstrap.start_engine(namespace="mainsequence.examples") is runtime
    assert calls[0]["models"] == list(portfolio_sqlalchemy_models())


def test_portfolio_start_engine_signature_excludes_migration_setup_arguments() -> None:
    parameters = inspect.signature(bootstrap.start_engine).parameters

    assert "data_source_uid" not in parameters
    assert "open_for_everyone" not in parameters
    assert "protect_from_deletion" not in parameters
    assert "introspect" not in parameters


def test_portfolio_bootstrap_resolves_portfolio_names_and_passes_core_names(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_start_engine(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr(bootstrap, "_start_engine", fake_start_engine)

    assert (
        bootstrap.start_engine(
            models=[
                "Asset",
                "Account",
                "Index",
                "Portfolio",
                "VirtualFund",
            ]
        )
        is runtime
    )
    assert calls[0]["models"] == [
        AssetTable,
        AccountTable,
        IndexTable,
        PortfolioTable,
        VirtualFundTable,
    ]
