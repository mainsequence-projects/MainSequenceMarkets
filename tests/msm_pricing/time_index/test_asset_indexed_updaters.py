"""``msm_pricing``'s asset-indexed and timestamped updaters on the core storage-first surface.

Split from ``tests/msm/time_index/test_asset_indexed_updaters.py``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from msm.time_index.accounts import AccountHoldings
from msm.time_index.assets import AssetSnapshot
from msm.time_index.assets.asset_indexed import ASSET_IDENTIFIER_DIMENSION
from msm.time_index.execution import (
    OrderEvents,
    Orders,
    Trades,
)
from msm.time_index.accounts.storage import AccountHoldingsStorage
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm.time_index.execution.storage import (
    OrderEventsStorage,
    OrdersStorage,
    TradesStorage,
)
from msm.time_index.utils.storage_schema import storage_column_dtypes_map
from msm.models import AssetTable, markets_sqlalchemy_models
from msm.models.registration import markets_foreign_key_target_identifiers
from msm_pricing.time_index import AssetPricingDetail
from msm_pricing.time_index.pricing_details.storage import AssetPricingDetailsStorage
from msm_pricing.meta_tables import pricing_sqlalchemy_models


@pytest.mark.parametrize(
    "node_cls",
    [
        AssetSnapshot,
        AssetPricingDetail,
        AccountHoldings,
        Orders,
        OrderEvents,
        Trades,
    ],
)
def test_asset_indexed_nodes_expose_storage_first_surface(
    node_cls,
    monkeypatch,
) -> None:
    assert "__data_node_identifier__" not in node_cls.__dict__
    assert "_default_identifier" not in node_cls.__dict__
    assert "_default_description" not in node_cls.__dict__
    output_table = node_cls._required_output_table()
    registered_identifier = f"registered.{output_table.metatable_identifier()}"
    monkeypatch.setattr(
        output_table,
        "get_identifier",
        classmethod(lambda _cls: registered_identifier),
    )
    assert node_cls._default_identifier() == registered_identifier
    assert node_cls._default_description() == output_table.__metatable_description__

    # msm storage registers through markets; pricing storage through pricing.
    registered = set(markets_sqlalchemy_models()) | set(pricing_sqlalchemy_models())
    assert output_table in registered

    assert not hasattr(node_cls, "_required_column_dtypes_map")
    assert not hasattr(node_cls, "_required_index_names")
    assert not hasattr(node_cls, "_required_time_index_name")
    assert node_cls._column_dtypes_map_for_storage(output_table) == storage_column_dtypes_map(
        output_table
    )
    assert not hasattr(node_cls, "build_mock_frame")
    assert not hasattr(node_cls, "build_schema_bootstrap_frame")
    assert not hasattr(node_cls, "build_initialization_frame")


def test_timestamped_storage_identifiers_use_camel_case_ts_suffix() -> None:
    assert AssetSnapshotsStorage.metatable_identifier() == "AssetSnapshotsTS"
    assert AccountHoldingsStorage.metatable_identifier() == "AccountHoldingsTS"
    assert OrdersStorage.metatable_identifier() == "OrdersTS"
    assert OrderEventsStorage.metatable_identifier() == "OrderEventsTS"
    assert TradesStorage.metatable_identifier() == "TradesTS"
    assert AssetPricingDetailsStorage.metatable_identifier() == "AssetPricingDetailsTS"


@pytest.mark.parametrize(
    ("node_cls", "storage_cls"),
    [
        (AssetSnapshot, AssetSnapshotsStorage),
        (AssetPricingDetail, AssetPricingDetailsStorage),
    ],
)
def test_timestamped_asset_nodes_bind_their_storage_class(node_cls, storage_cls) -> None:
    assert node_cls._required_output_table() is storage_cls
    assert storage_cls.__index_names__ == ["time_index", ASSET_IDENTIFIER_DIMENSION]
    assert ASSET_IDENTIFIER_DIMENSION in {column.name for column in storage_cls.__table__.columns}


@pytest.mark.parametrize(
    ("node_cls", "storage_cls"),
    [
        (AssetSnapshot, AssetSnapshotsStorage),
        (AssetPricingDetail, AssetPricingDetailsStorage),
    ],
)
def test_timestamped_asset_nodes_validate_real_frames_as_datetime64_ns_utc(
    node_cls,
    storage_cls,
) -> None:
    frame = node_cls.validate_frame(
        pd.DataFrame(
            [
                {
                    "time_index": "2026-05-26T00:00:00Z",
                    ASSET_IDENTIFIER_DIMENSION: "asset-1",
                    **{
                        column.name: ""
                        for column in storage_cls.__table__.columns
                        if column.name
                        not in {
                            "time_index",
                            ASSET_IDENTIFIER_DIMENSION,
                            "instrument_dump",
                            "metadata",
                        }
                    },
                    **{
                        column.name: {}
                        for column in storage_cls.__table__.columns
                        if column.name in {"instrument_dump", "metadata"}
                    },
                }
            ]
        )
    )

    assert list(frame.index.names) == list(storage_cls.__index_names__)
    assert str(frame.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"


@pytest.mark.parametrize("storage_cls", [AssetSnapshotsStorage, AssetPricingDetailsStorage])
def test_timestamped_asset_storage_has_asset_foreign_key(storage_cls) -> None:
    asset_identifier = AssetTable.__table__.name
    fk_column = storage_cls.__table__.columns[ASSET_IDENTIFIER_DIMENSION]

    assert markets_foreign_key_target_identifiers(storage_cls) == [asset_identifier]
    assert any(
        foreign_key.column is AssetTable.__table__.c.unique_identifier
        and foreign_key.ondelete == "RESTRICT"
        for foreign_key in fk_column.foreign_keys
    )
