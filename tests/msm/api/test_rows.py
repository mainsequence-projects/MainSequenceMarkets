from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from msm.api.accounts import Account, AccountGroup, AccountTargetPositionAssignment
from msm.api.assets import (
    AssetCategory,
    AssetCategoryMembership,
    AssetType,
    OpenFigiDetails,
)
from msm.api.calendars import Calendar
from msm.api.execution import Order, OrderManager, OrderStatusEvent
from msm.api.market_metadata import (
    InstrumentsConfiguration,
    RebalanceStrategyMetadata,
    SignalMetadata,
)
from msm.api.portfolios import Fund, Portfolio, PortfolioAssetDetail, PortfolioMetadata
from msm.models.registration import markets_meta_table_fullname
from msm.models import (
    AccountGroupTable,
    AccountTable,
    AccountTargetPositionAssignmentTable,
    AssetCategoryMembershipTable,
    AssetCategoryTable,
    AssetTypeTable,
    AssetTable,
    CalendarTable,
    FundTable,
    InstrumentsConfigurationTable,
    OpenFigiDetailsTable,
    OrderManagerTable,
    OrderTable,
    PortfolioAssetDetailTable,
    PortfolioMetadataTable,
    PortfolioTable,
    RebalanceStrategyMetadataTable,
    SignalMetadataTable,
)


@pytest.mark.parametrize(
    ("row_model", "table_model", "upsert_keys"),
    [
        (AssetType, AssetTypeTable, ("asset_type",)),
        (AssetCategory, AssetCategoryTable, ("unique_identifier",)),
        (AssetCategoryMembership, AssetCategoryMembershipTable, ("category_uid", "asset_uid")),
        (OpenFigiDetails, OpenFigiDetailsTable, ("asset_uid",)),
        (Calendar, CalendarTable, ("name",)),
        (Account, AccountTable, ("unique_identifier",)),
        (
            AccountTargetPositionAssignment,
            AccountTargetPositionAssignmentTable,
            ("account_uid", "target_positions_time"),
        ),
        (Portfolio, PortfolioTable, ("unique_identifier",)),
        (PortfolioAssetDetail, PortfolioAssetDetailTable, ("portfolio_uid",)),
        (PortfolioMetadata, PortfolioMetadataTable, ("unique_identifier",)),
        (Fund, FundTable, ("unique_identifier",)),
        (SignalMetadata, SignalMetadataTable, ("signal_uid",)),
        (
            RebalanceStrategyMetadata,
            RebalanceStrategyMetadataTable,
            ("rebalance_strategy_uid",),
        ),
        (InstrumentsConfiguration, InstrumentsConfigurationTable, ("configuration_key",)),
        (OrderManager, OrderManagerTable, ("unique_identifier",)),
        (Order, OrderTable, ("order_time", "order_remote_id", "asset_unique_identifier")),
    ],
)
def test_api_rows_declare_table_and_upsert_contracts(
    row_model,
    table_model,
    upsert_keys,
) -> None:
    assert row_model.__table__ is table_model
    assert table_model in row_model.__required_tables__
    assert row_model.__upsert_keys__ == upsert_keys


def test_portfolio_create_schemas_includes_domain_required_tables(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_create_schemas(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr("msm.bootstrap.create_schemas", fake_create_schemas)

    assert Portfolio.create_schemas(namespace="mainsequence.examples") is runtime
    assert calls == [
        {
            "models": [AssetTable, PortfolioTable, PortfolioAssetDetailTable],
            "namespace": "mainsequence.examples",
        }
    ]


def test_missing_required_table_fails_before_operation(monkeypatch) -> None:
    runtime = SimpleNamespace(
        context=object(),
        target_meta_table_uid_by_fullname={
            markets_meta_table_fullname(PortfolioTable): str(uuid.uuid4()),
        },
    )

    def fake_attach_schemas(**kwargs):
        raise RuntimeError("offline unit test")

    monkeypatch.setattr("msm.bootstrap._RUNTIME", runtime)
    monkeypatch.setattr("msm.bootstrap.attach_schemas", fake_attach_schemas)

    with pytest.raises(RuntimeError, match="AssetTable"):
        Portfolio.filter(unique_identifier_contains="demo")


def test_append_only_status_event_does_not_define_generic_upsert() -> None:
    assert OrderStatusEvent.__upsert_keys__ == ()

    with pytest.raises(NotImplementedError):
        OrderStatusEvent.upsert(
            event_time=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            order_status="filled",
        )


def test_account_group_requires_model_portfolio_dependency() -> None:
    assert AccountGroupTable in AccountGroup.__required_tables__
