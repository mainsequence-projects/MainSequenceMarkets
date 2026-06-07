from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from msm.data_nodes.accounts import TargetPositions, TargetPositionsDataNodeConfiguration
from msm.data_nodes.accounts.constants import TARGET_TYPE_ASSET, TARGET_TYPE_PORTFOLIO
from msm.data_nodes.accounts.storage import TargetPositionsStorage
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.models import AssetTable, PortfolioTable, PositionSetTable, markets_sqlalchemy_models
from msm.models.registration import markets_foreign_key_target_identifiers
from msm.services.target_positions import (
    build_target_positions_frame,
    expand_portfolio_target_positions,
    validate_target_position_payload,
)
from msm_portfolios.models import portfolio_sqlalchemy_models


def test_target_positions_storage_belongs_to_core_account_model_graph() -> None:
    assert TargetPositionsStorage in set(markets_sqlalchemy_models())
    assert TargetPositionsStorage in set(portfolio_sqlalchemy_models())


def test_target_positions_storage_declares_target_foreign_keys() -> None:
    assert set(markets_foreign_key_target_identifiers(TargetPositionsStorage)) == {
        AssetTable.__table__.name,
        PortfolioTable.__table__.name,
        PositionSetTable.__table__.name,
    }

    position_set_column = TargetPositionsStorage.__table__.columns["position_set_uid"]
    asset_column = TargetPositionsStorage.__table__.columns["asset_uid"]
    portfolio_column = TargetPositionsStorage.__table__.columns["portfolio_uid"]
    assert any(
        foreign_key.column is PositionSetTable.__table__.c.uid and foreign_key.ondelete == "CASCADE"
        for foreign_key in position_set_column.foreign_keys
    )
    assert any(
        foreign_key.column is AssetTable.__table__.c.uid and foreign_key.ondelete == "RESTRICT"
        for foreign_key in asset_column.foreign_keys
    )
    assert any(
        foreign_key.column is PortfolioTable.__table__.c.uid and foreign_key.ondelete == "RESTRICT"
        for foreign_key in portfolio_column.foreign_keys
    )


def test_target_positions_storage_declares_target_index_names() -> None:
    assert TargetPositionsStorage.__index_names__ == [
        "time_index",
        "position_set_uid",
        "target_type",
        "target_uid",
    ]


def test_target_positions_storage_validates_target_type() -> None:
    storage = TargetPositionsStorage(target_type=TARGET_TYPE_ASSET)

    assert storage.target_type == TARGET_TYPE_ASSET
    with pytest.raises(ValueError, match="target_type must be one of: asset, portfolio"):
        storage.target_type = "fund"


def test_target_positions_node_uses_target_position_configuration() -> None:
    config = TargetPositions.default_config()

    assert isinstance(config, TargetPositionsDataNodeConfiguration)
    assert TargetPositions._required_storage_table() is TargetPositionsStorage
    assert TargetPositions._column_dtypes_map_for_storage(
        TargetPositionsStorage
    ) == storage_column_dtypes_map(TargetPositionsStorage)


def test_target_positions_bound_dtype_map_uses_instance_storage_table() -> None:
    node = SimpleNamespace(storage_table=TargetPositionsStorage)

    assert TargetPositions._bound_column_dtypes_map(node) == storage_column_dtypes_map(
        TargetPositionsStorage
    )


def test_target_positions_node_requires_real_frame() -> None:
    node = object.__new__(TargetPositions)

    with pytest.raises(ValueError, match="requires a real target-position frame"):
        node.get_target_positions_frame()


def test_target_positions_frame_accepts_asset_and_portfolio_targets() -> None:
    position_set_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()

    frame = build_target_positions_frame(
        target_positions_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
        position_set_uid=position_set_uid,
        positions=[
            {"asset_uid": asset_uid, "weight_notional_exposure": "0.6"},
            {"portfolio_uid": portfolio_uid, "weight_notional_exposure": "0.4"},
        ],
    )

    assert list(frame.index.names) == list(TargetPositionsStorage.__index_names__)
    flat = frame.reset_index()
    asset_row = flat[flat["target_type"] == TARGET_TYPE_ASSET].iloc[0]
    portfolio_row = flat[flat["target_type"] == TARGET_TYPE_PORTFOLIO].iloc[0]
    assert asset_row["position_set_uid"] == str(position_set_uid)
    assert asset_row["asset_uid"] == str(asset_uid)
    assert asset_row["target_uid"] == str(asset_uid)
    assert portfolio_row["portfolio_uid"] == str(portfolio_uid)
    assert portfolio_row["target_uid"] == str(portfolio_uid)
    assert str(flat["weight_notional_exposure"].dtype) == "float64"


def test_target_positions_reject_stale_asset_identifier() -> None:
    with pytest.raises(ValueError, match="not asset_identifier"):
        validate_target_position_payload(
            {
                "asset_identifier": "BTC",
                "weight_notional_exposure": "0.25",
            }
        )


def test_target_positions_require_exactly_one_target_reference() -> None:
    with pytest.raises(ValueError, match="exactly one of asset_uid or portfolio_uid"):
        validate_target_position_payload(
            {
                "asset_uid": uuid.uuid4(),
                "portfolio_uid": uuid.uuid4(),
                "weight_notional_exposure": "0.25",
            }
        )


def test_target_positions_require_exactly_one_exposure_shape() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        validate_target_position_payload(
            {
                "asset_uid": uuid.uuid4(),
                "weight_notional_exposure": "0.25",
                "single_asset_quantity": "1",
            }
        )


def test_portfolio_target_expansion_is_explicit() -> None:
    position_set_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    frame = build_target_positions_frame(
        target_positions_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
        position_set_uid=position_set_uid,
        positions=[{"portfolio_uid": portfolio_uid, "weight_notional_exposure": "0.5"}],
    )

    with pytest.raises(ValueError, match="portfolio_weight_resolver"):
        expand_portfolio_target_positions(frame)

    expanded = expand_portfolio_target_positions(
        frame,
        portfolio_weight_resolver=lambda _portfolio_uid: [{"asset_uid": asset_uid, "weight": 0.25}],
    )

    row = expanded.iloc[0]
    assert row["source_target_type"] == TARGET_TYPE_PORTFOLIO
    assert row["portfolio_uid"] == str(portfolio_uid)
    assert row["asset_uid"] == str(asset_uid)
    assert row["weight_notional_exposure"] == 0.125
