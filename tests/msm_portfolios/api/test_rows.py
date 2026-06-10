from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm.api.base import MarketsMetaTableRow
from msm.api.portfolios import Portfolio, PortfolioCreate, PortfolioUpdate, PortfolioUpsert
from msm.models import CalendarTable, IndexTable, IndexTypeTable, PortfolioTable
from msm_portfolios.api.market_metadata import (
    RebalanceStrategyMetadata,
    SignalMetadata,
)
from msm_portfolios.api.portfolios import (
    PortfolioMetadata,
)
from msm_portfolios.models import (
    PortfolioMetadataTable,
    RebalanceStrategyMetadataTable,
    SignalMetadataTable,
)


@pytest.mark.parametrize(
    ("row_model", "table_model", "upsert_keys"),
    [
        (Portfolio, PortfolioTable, ("unique_identifier",)),
        (PortfolioMetadata, PortfolioMetadataTable, ("unique_identifier",)),
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

    assert Portfolio.start_engine(namespace="mainsequence.examples") is runtime
    assert calls == [
        {
            "models": [CalendarTable, IndexTypeTable, IndexTable, PortfolioTable],
            "namespace": "mainsequence.examples",
        }
    ]


def test_missing_required_table_fails_before_operation(monkeypatch) -> None:
    runtime = SimpleNamespace(
        context=object(),
        meta_table_models=[PortfolioTable],
    )

    def fake_attach_schemas(**kwargs):
        raise RuntimeError("offline unit test")

    monkeypatch.setattr("msm.bootstrap._RUNTIME", runtime)
    monkeypatch.setattr("msm.bootstrap.attach_schemas", fake_attach_schemas)

    with pytest.raises(RuntimeError, match="CalendarTable"):
        Portfolio.filter(unique_identifier_contains="demo")


def test_portfolio_create_payload_requires_calendar_uid() -> None:
    with pytest.raises(ValidationError):
        PortfolioCreate(unique_identifier="portfolio-without-calendar")

    with pytest.raises(ValidationError):
        PortfolioUpsert(unique_identifier="portfolio-without-calendar")


def test_portfolio_update_payload_rejects_null_calendar_uid() -> None:
    with pytest.raises(ValidationError, match="calendar_uid cannot be null"):
        PortfolioUpdate(calendar_uid=None)
