from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from mainsequence.client import dtype_codec as dc

from msm.data_nodes.accounts.storage import AccountHoldingsStorage
from msm.data_nodes.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_column_nullable_map,
)
from msm.models import AccountHoldingsSetTable, AssetTable, markets_sqlalchemy_models
from msm.models.registration import markets_foreign_key_target_identifiers
from msm.data_nodes.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
from msm.data_nodes.accounts.virtual_funds import VirtualFundHoldings
from msm.models import (
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)
from msm.services.accounts.virtual_fund_holdings import (
    build_virtual_fund_holdings_frame,
    validate_virtual_fund_allocation_bounds,
)


def test_virtual_fund_holdings_storage_is_registered_by_core_markets_graph() -> None:
    assert VirtualFundHoldingsStorage in set(markets_sqlalchemy_models())


def test_virtual_fund_holdings_storage_declares_allocation_foreign_keys() -> None:
    assert set(markets_foreign_key_target_identifiers(VirtualFundHoldingsStorage)) == {
        VirtualFundTable.__table__.name,
        AssetTable.__table__.name,
        VirtualFundHoldingsSetTable.__table__.name,
        AccountHoldingsSetTable.__table__.name,
    }

    asset_column = VirtualFundHoldingsStorage.__table__.columns["asset_identifier"]
    assert any(
        foreign_key.column is AssetTable.__table__.c.unique_identifier
        and foreign_key.ondelete == "RESTRICT"
        for foreign_key in asset_column.foreign_keys
    )


def test_virtual_fund_holdings_node_uses_storage_first_contract() -> None:
    assert not hasattr(VirtualFundHoldings, "_required_column_dtypes_map")
    assert not hasattr(VirtualFundHoldings, "_required_index_names")
    assert not hasattr(VirtualFundHoldings, "_required_time_index_name")
    assert VirtualFundHoldings._column_dtypes_map_for_storage(
        VirtualFundHoldingsStorage
    ) == storage_column_dtypes_map(VirtualFundHoldingsStorage)
    assert VirtualFundHoldings._required_storage_table() is VirtualFundHoldingsStorage


def test_virtual_fund_holdings_nullability_is_sourced_from_storage_class() -> None:
    nullable = storage_column_nullable_map(VirtualFundHoldingsStorage)

    assert nullable["allocated_quantity"] is False
    assert nullable["direction"] is False
    assert nullable["virtual_fund_uid"] is False
    assert nullable["virtual_fund_holdings_set_uid"] is False
    assert nullable["source_account_holdings_set_uid"] is False
    assert "target_weight" not in nullable


def test_virtual_fund_holdings_dtype_tokens_match_storage_columns() -> None:
    dtype_map = VirtualFundHoldings._column_dtypes_map_for_storage(VirtualFundHoldingsStorage)

    assert dtype_map["allocated_quantity"] == dc.FLOAT64
    assert dtype_map["direction"] == dc.INT16
    assert dtype_map["target_trade_time"] == dc.TIMESTAMP_TZ
    assert dtype_map["asset_identifier"] == dc.STRING
    assert dtype_map["virtual_fund_uid"] == dc.UUID_TOKEN
    assert dtype_map["virtual_fund_holdings_set_uid"] == dc.UUID_TOKEN
    assert dtype_map["source_account_holdings_set_uid"] == dc.UUID_TOKEN
    assert "quantity" not in dtype_map
    assert "target_weight" not in dtype_map


def test_virtual_fund_holdings_bound_dtype_map_uses_instance_storage_table() -> None:
    node = SimpleNamespace(storage_table=VirtualFundHoldingsStorage)

    assert VirtualFundHoldings._bound_column_dtypes_map(node) == storage_column_dtypes_map(
        VirtualFundHoldingsStorage
    )


def test_virtual_fund_holdings_node_does_not_expose_legacy_frame_api() -> None:
    assert not hasattr(VirtualFundHoldings, "build_schema_bootstrap_frame")
    assert not hasattr(VirtualFundHoldings, "build_schema_bootstrap_fund_frame")
    assert not hasattr(VirtualFundHoldings, "build_initialization_frame")
    assert not hasattr(VirtualFundHoldings, "build_mock_fund_frame")
    assert not hasattr(VirtualFundHoldings, "build_fund_holdings_frame")
    assert not hasattr(VirtualFundHoldings, "set_fund_holdings_frame")


def test_virtual_fund_holdings_frame_builder_uses_allocation_contract() -> None:
    virtual_fund_uid = uuid.uuid4()
    source_set_uid = uuid.uuid4()
    virtual_fund_set_uid = uuid.uuid4()

    frame = build_virtual_fund_holdings_frame(
        allocation_time="2026-05-25T10:00:00+00:00",
        virtual_fund_uid=virtual_fund_uid,
        source_account_holdings_set_uid=source_set_uid,
        virtual_fund_holdings_set_uid=virtual_fund_set_uid,
        allocations=[
            {
                "asset_identifier": "ETH",
                "allocated_quantity": "3",
                "direction": -1,
            }
        ],
    )

    assert list(frame.index.names) == list(VirtualFundHoldingsStorage.__index_names__)
    row = frame.reset_index().iloc[0]
    assert row["virtual_fund_uid"] == str(virtual_fund_uid)
    assert row["source_account_holdings_set_uid"] == str(source_set_uid)
    assert row["virtual_fund_holdings_set_uid"] == str(virtual_fund_set_uid)
    assert row["allocated_quantity"] == 3.0
    assert row["direction"] == -1
    assert str(frame.reset_index()["allocated_quantity"].dtype) == "float64"
    assert str(frame.reset_index()["direction"].dtype) == "int16"


def test_virtual_fund_allocation_bound_allows_remaining_source_quantity(monkeypatch) -> None:
    source_set_uid = str(uuid.uuid4())

    def fake_search_model(_context, *, model, **_kwargs):
        if model is AccountHoldingsStorage:
            return {
                "rows": [
                    {
                        "holdings_set_uid": source_set_uid,
                        "asset_identifier": "BTC",
                        "direction": 1,
                        "quantity": 10,
                    }
                ]
            }
        if model is VirtualFundHoldingsStorage:
            return {
                "rows": [
                    {
                        "source_account_holdings_set_uid": source_set_uid,
                        "virtual_fund_holdings_set_uid": str(uuid.uuid4()),
                        "asset_identifier": "BTC",
                        "direction": 1,
                        "allocated_quantity": 4,
                    }
                ]
            }
        raise AssertionError(model)

    monkeypatch.setattr(
        "msm.services.accounts.virtual_fund_holdings.search_model", fake_search_model
    )
    frame = build_virtual_fund_holdings_frame(
        allocation_time="2026-05-25T10:00:00+00:00",
        virtual_fund_uid=uuid.uuid4(),
        source_account_holdings_set_uid=source_set_uid,
        virtual_fund_holdings_set_uid=uuid.uuid4(),
        allocations=[{"asset_identifier": "BTC", "allocated_quantity": 6, "direction": 1}],
    )

    validate_virtual_fund_allocation_bounds(SimpleNamespace(), frame)


def test_virtual_fund_allocation_bound_rejects_overallocation(monkeypatch) -> None:
    source_set_uid = str(uuid.uuid4())

    def fake_search_model(_context, *, model, **_kwargs):
        if model is AccountHoldingsStorage:
            return {
                "rows": [
                    {
                        "holdings_set_uid": source_set_uid,
                        "asset_identifier": "BTC",
                        "direction": 1,
                        "quantity": 10,
                    }
                ]
            }
        if model is VirtualFundHoldingsStorage:
            return {
                "rows": [
                    {
                        "source_account_holdings_set_uid": source_set_uid,
                        "virtual_fund_holdings_set_uid": str(uuid.uuid4()),
                        "asset_identifier": "BTC",
                        "direction": 1,
                        "allocated_quantity": 4,
                    }
                ]
            }
        raise AssertionError(model)

    monkeypatch.setattr(
        "msm.services.accounts.virtual_fund_holdings.search_model", fake_search_model
    )
    frame = build_virtual_fund_holdings_frame(
        allocation_time="2026-05-25T10:00:00+00:00",
        virtual_fund_uid=uuid.uuid4(),
        source_account_holdings_set_uid=source_set_uid,
        virtual_fund_holdings_set_uid=uuid.uuid4(),
        allocations=[{"asset_identifier": "BTC", "allocated_quantity": 7, "direction": 1}],
    )

    with pytest.raises(ValueError, match="exceeds source account holdings"):
        validate_virtual_fund_allocation_bounds(SimpleNamespace(), frame)


def test_short_source_holdings_do_not_fund_long_allocations(monkeypatch) -> None:
    source_set_uid = str(uuid.uuid4())

    def fake_search_model(_context, *, model, **_kwargs):
        if model is AccountHoldingsStorage:
            return {
                "rows": [
                    {
                        "holdings_set_uid": source_set_uid,
                        "asset_identifier": "BTC",
                        "direction": -1,
                        "quantity": 10,
                    }
                ]
            }
        if model is VirtualFundHoldingsStorage:
            return {"rows": []}
        raise AssertionError(model)

    monkeypatch.setattr(
        "msm.services.accounts.virtual_fund_holdings.search_model", fake_search_model
    )
    frame = build_virtual_fund_holdings_frame(
        allocation_time="2026-05-25T10:00:00+00:00",
        virtual_fund_uid=uuid.uuid4(),
        source_account_holdings_set_uid=source_set_uid,
        virtual_fund_holdings_set_uid=uuid.uuid4(),
        allocations=[{"asset_identifier": "BTC", "allocated_quantity": 1, "direction": 1}],
    )

    with pytest.raises(ValueError, match="no matching source account holding"):
        validate_virtual_fund_allocation_bounds(SimpleNamespace(), frame)
