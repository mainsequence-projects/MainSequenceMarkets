"""An interpolation's source is an instance or a table reference (ADR 0066, decision 4)."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import ExitStack

import pytest
from metatables import TimeIndexMetaTable, TimeIndexTableRef
from pydantic import ValidationError

from msm.time_index.assets import AssetSnapshot
from msm.time_index.assets.snapshots import AssetSnapshotConfiguration
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm_portfolios.contrib.prices.updaters import (
    InterpolatedPrices,
    InterpolatedPricesConfig,
    _source_time_indexed_profile_cadence,
)
from tests.support.pinned_identities import (
    PRICES_TABLE_UID,
    SOURCE_TABLE_UID,
    PinnedInterpolatedPrices,
    _bound,
)

SOURCE_TIME_INDEX_META_TABLE_UID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def bound_tables(monkeypatch) -> Iterator[None]:
    """The source's and the prices' tables, bound to fake metadata; no request leaves."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("The test made a request.")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    with ExitStack() as stack:
        stack.enter_context(
            _bound(
                AssetSnapshotsStorage,
                SOURCE_TABLE_UID,
                cadence="1d",
                physical_table_name=AssetSnapshotsStorage.__table__.name,
            )
        )
        stack.enter_context(_bound(PinnedInterpolatedPrices, PRICES_TABLE_UID, cadence="1d"))
        yield


def _over_source(source) -> InterpolatedPrices:
    return InterpolatedPrices(
        _configuration(source_price_instance=source, asset_list=None),
        output_table=PinnedInterpolatedPrices,
    )


def _snapshots(*assets: str) -> AssetSnapshot:
    return AssetSnapshot(AssetSnapshotConfiguration(asset_list=list(assets) or None))


class _Profile:
    cadence = "1D"


def _api_price_source() -> TimeIndexTableRef:
    return TimeIndexTableRef(
        output_table=TimeIndexMetaTable.model_construct(
            uid=SOURCE_TIME_INDEX_META_TABLE_UID,
            data_source_uid="source-data-source",
            physical_table_name="my_provider__bars__t_1d",
            time_indexed_profile=_Profile(),
        )
    )


def _configuration(**changed) -> InterpolatedPricesConfig:
    return InterpolatedPricesConfig(
        **{
            "upsample_frequency_id": "1d",
            "intraday_bar_interpolation_rule": "ffill",
            "asset_list": ["example-asset-btc"],
            **changed,
        }
    )


def test_the_source_is_an_instance_or_a_table_reference() -> None:
    source_price = _api_price_source()

    configuration = _configuration(source_price_instance=source_price)

    assert configuration.source_price_instance is source_price
    assert "source_time_index_meta_table_uid" not in InterpolatedPricesConfig.model_fields
    assert "bar_frequency_id" not in InterpolatedPricesConfig.model_fields
    assert "source_bars_data_node" not in InterpolatedPricesConfig.model_fields


def test_a_configuration_without_a_source_is_refused() -> None:
    with pytest.raises(ValidationError, match="source_price_instance"):
        _configuration()


def test_a_source_table_uid_is_refused() -> None:
    with pytest.raises(ValidationError, match="source_time_index_meta_table_uid"):
        _configuration(
            source_price_instance=_api_price_source(),
            source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
        )


def test_interpolated_prices_config_rejects_user_supplied_bar_frequency_id() -> None:
    with pytest.raises(ValidationError):
        _configuration(source_price_instance=_api_price_source(), bar_frequency_id="1d")


def test_source_time_indexed_profile_cadence_is_canonicalized() -> None:
    assert _source_time_indexed_profile_cadence(_api_price_source().output_table) == "1d"


def test_interpolated_prices_reads_its_source_as_a_dependency() -> None:
    source_price = _api_price_source()
    node = object.__new__(InterpolatedPrices)
    node.bars_ts = _configuration(source_price_instance=source_price).source_price_instance

    assert node.dependencies() == {"bars_ts": source_price}


def test_with_no_assets_named_the_assets_are_the_source_updaters(bound_tables) -> None:
    prices = _over_source(_snapshots("ASSET_A", "ASSET_B"))

    assert prices.get_asset_list() == ["ASSET_A", "ASSET_B"]


def test_the_source_assets_are_part_of_the_identity(bound_tables) -> None:
    one = _over_source(_snapshots("ASSET_A", "ASSET_B"))
    other = _over_source(_snapshots("ASSET_A"))

    assert one.update_hash != other.update_hash


def test_a_source_updater_without_assets_is_refused_when_they_are_read(bound_tables) -> None:
    prices = _over_source(_snapshots())

    with pytest.raises(ValueError, match="AssetSnapshot has none"):
        prices.get_asset_list()


def test_a_table_reference_needs_the_assets_named() -> None:
    with pytest.raises(ValueError, match="TimeIndexTableRef is not an asset-indexed updater"):
        InterpolatedPrices(
            _configuration(source_price_instance=_api_price_source(), asset_list=None),
            output_table=PinnedInterpolatedPrices,
        )
