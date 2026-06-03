from __future__ import annotations

from types import SimpleNamespace

import pytest

from msm.api.base import MarketsMetaTableRow
from msm.models import AssetTable, IndexTable
from msm_portfolios.api.market_metadata import (
    RebalanceStrategyMetadata,
    SignalMetadata,
)
from msm_portfolios.api.portfolios import (
    Portfolio,
    PortfolioMetadata,
)
from msm_portfolios.api.virtual_funds import VirtualFund, VirtualFundHoldingsSet
from msm_portfolios.models import (
    PortfolioMetadataTable,
    PortfolioTable,
    RebalanceStrategyMetadataTable,
    SignalMetadataTable,
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)


@pytest.mark.parametrize(
    ("row_model", "table_model", "upsert_keys"),
    [
        (Portfolio, PortfolioTable, ("unique_identifier",)),
        (PortfolioMetadata, PortfolioMetadataTable, ("unique_identifier",)),
        (VirtualFund, VirtualFundTable, ("unique_identifier",)),
        (
            VirtualFundHoldingsSet,
            VirtualFundHoldingsSetTable,
            ("virtual_fund_uid", "source_account_holdings_set_uid"),
        ),
        (SignalMetadata, SignalMetadataTable, ("signal_uid",)),
        (
            RebalanceStrategyMetadata,
            RebalanceStrategyMetadataTable,
            ("rebalance_strategy_uid",),
        ),
    ],
)
def test_portfolio_api_rows_declare_table_and_upsert_contracts(
    row_model,
    table_model,
    upsert_keys,
) -> None:
    assert row_model.__table__ is table_model
    assert table_model in row_model.__required_tables__
    assert row_model.__upsert_keys__ == upsert_keys
    assert issubclass(row_model, MarketsMetaTableRow)


def test_portfolio_create_schemas_includes_domain_required_tables(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_start_engine(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr("msm.bootstrap.start_engine", fake_start_engine)

    assert Portfolio.create_schemas(namespace="mainsequence.examples") is runtime
    assert calls == [
        {
            "models": [IndexTable, PortfolioTable],
            "namespace": "mainsequence.examples",
        }
    ]


def test_virtual_fund_api_does_not_require_asset_proxy_table() -> None:
    assert AssetTable not in VirtualFund.__required_tables__


def test_missing_required_table_fails_before_operation(monkeypatch) -> None:
    runtime = SimpleNamespace(
        context=object(),
        meta_table_models=[PortfolioTable],
    )

    def fake_attach_schemas(**kwargs):
        raise RuntimeError("offline unit test")

    monkeypatch.setattr("msm.bootstrap._RUNTIME", runtime)
    monkeypatch.setattr("msm.bootstrap.attach_schemas", fake_attach_schemas)

    with pytest.raises(RuntimeError, match="IndexTable"):
        Portfolio.filter(unique_identifier_contains="demo")
