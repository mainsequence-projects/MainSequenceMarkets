from __future__ import annotations

import uuid
from types import SimpleNamespace

from mainsequence.client import dtype_codec as dc

from msm.data_nodes.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_column_nullable_map,
)
from msm.models import AssetTable
from msm.models.registration import markets_foreign_key_target_identifiers
from msm_portfolios.data_nodes.storage import FundHoldingsStorage
from msm_portfolios.data_nodes.virtual_funds import VirtualFundHoldings
from msm_portfolios.models import FundTable, portfolio_sqlalchemy_models
from msm_portfolios.services.holdings import build_fund_holdings_frame


def test_fund_holdings_storage_is_registered_by_portfolio_graph() -> None:
    assert FundHoldingsStorage in set(portfolio_sqlalchemy_models())


def test_fund_holdings_storage_declares_fund_and_asset_foreign_keys() -> None:
    assert markets_foreign_key_target_identifiers(FundHoldingsStorage) == [
        AssetTable.__metatable_identifier__,
        FundTable.__metatable_identifier__,
    ]

    fund_asset_column = FundHoldingsStorage.__table__.columns["asset_identifier"]
    assert any(
        foreign_key.info["mainsequence_metatable_foreign_key"]["target_model"] is AssetTable
        and foreign_key.info["mainsequence_metatable_foreign_key"]["target_column"]
        == "unique_identifier"
        for foreign_key in fund_asset_column.foreign_keys
    )


def test_fund_holdings_node_uses_storage_first_contract() -> None:
    assert not hasattr(VirtualFundHoldings, "_required_column_dtypes_map")
    assert not hasattr(VirtualFundHoldings, "_required_index_names")
    assert not hasattr(VirtualFundHoldings, "_required_time_index_name")
    assert VirtualFundHoldings._column_dtypes_map_for_storage(
        FundHoldingsStorage
    ) == storage_column_dtypes_map(FundHoldingsStorage)
    assert VirtualFundHoldings._required_storage_table() is FundHoldingsStorage


def test_fund_holdings_nullability_is_sourced_from_storage_class() -> None:
    fund_nullable = storage_column_nullable_map(FundHoldingsStorage)

    assert fund_nullable["target_weight"] is True
    assert fund_nullable["fund_uid"] is False


def test_fund_holdings_dtype_tokens_match_storage_columns() -> None:
    dtype_map = VirtualFundHoldings._column_dtypes_map_for_storage(FundHoldingsStorage)

    assert dtype_map["target_weight"] == dc.FLOAT64
    assert dtype_map["quantity"] == dc.FLOAT64
    assert dtype_map["target_trade_time"] == dc.TIMESTAMP_TZ
    assert dtype_map["asset_identifier"] == dc.STRING
    assert dtype_map["fund_uid"] == dc.UUID_TOKEN


def test_fund_holdings_bound_dtype_map_uses_instance_storage_table() -> None:
    node = SimpleNamespace(storage_table=FundHoldingsStorage)

    assert VirtualFundHoldings._bound_column_dtypes_map(node) == storage_column_dtypes_map(
        FundHoldingsStorage
    )


def test_fund_holdings_node_does_not_expose_bootstrap_frame_api() -> None:
    assert not hasattr(VirtualFundHoldings, "build_schema_bootstrap_frame")
    assert not hasattr(VirtualFundHoldings, "build_schema_bootstrap_fund_frame")
    assert not hasattr(VirtualFundHoldings, "build_initialization_frame")
    assert not hasattr(VirtualFundHoldings, "build_mock_fund_frame")


def test_fund_holdings_frame_builder_keeps_target_weight_contract() -> None:
    fund_uid = uuid.uuid4()

    frame = build_fund_holdings_frame(
        holdings_date="2026-05-25T10:00:00+00:00",
        fund_uid=fund_uid,
        positions=[
            {
                "asset_identifier": "ETH",
                "quantity": "3",
                "target_weight": "0.15",
            }
        ],
    )

    assert list(frame.index.names) == list(FundHoldingsStorage.__index_names__)
    row = frame.reset_index().iloc[0]
    assert row["fund_uid"] == str(fund_uid)
    assert row["quantity"] == 3.0
    assert row["target_weight"] == 0.15
    assert str(frame.reset_index()["quantity"].dtype) == "float64"
    assert str(frame.reset_index()["target_weight"].dtype) == "float64"
