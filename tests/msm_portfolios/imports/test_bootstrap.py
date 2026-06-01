from __future__ import annotations

from types import SimpleNamespace

import msm_portfolios.bootstrap as bootstrap
from msm.models import IndexTable
from msm_portfolios.models import (
    FundTable,
    PortfolioTable,
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
                "Fund",
            ]
        )
        is runtime
    )
    assert calls[0]["models"] == [
        "Asset",
        "Account",
        IndexTable,
        PortfolioTable,
        FundTable,
    ]
