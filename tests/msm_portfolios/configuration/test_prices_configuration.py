from __future__ import annotations

import pytest
from mainsequence.meta_tables import APIDataNode
from pydantic import ValidationError

from msm_portfolios.configuration import PricesConfiguration
from msm_portfolios.contrib.prices.data_nodes import (
    InterpolatedPrices,
    InterpolatedPricesConfig,
    _resolve_interpolated_source_prices,
    _source_time_indexed_profile_cadence,
)

SOURCE_TIME_INDEX_META_TABLE_UID = "00000000-0000-0000-0000-000000000001"


class _Profile:
    cadence = "1D"


class _StorageTable:
    uid = SOURCE_TIME_INDEX_META_TABLE_UID
    time_indexed_profile = _Profile()


def _api_price_source() -> APIDataNode:
    return APIDataNode(
        data_source_uid="source-data-source",
        storage_hash="source-prices",
        storage_table=_StorageTable(),
    )


def test_prices_configuration_uses_time_index_meta_table_uid() -> None:
    assert "source_time_index_meta_table_uid" in PricesConfiguration.model_fields
    assert "bar_frequency_id" not in PricesConfiguration.model_fields
    assert "markets_time_series" not in PricesConfiguration.model_fields
    assert "source_bars_data_node" not in PricesConfiguration.model_fields

    configuration = PricesConfiguration(
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
        source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
    )

    assert str(configuration.source_time_index_meta_table_uid) == (
        SOURCE_TIME_INDEX_META_TABLE_UID
    )


def test_prices_configuration_requires_source_time_index_meta_table_uid() -> None:
    with pytest.raises(ValidationError):
        PricesConfiguration(
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
        )


def test_prices_configuration_rejects_user_supplied_bar_frequency_id() -> None:
    with pytest.raises(ValidationError):
        PricesConfiguration(
            bar_frequency_id="1d",
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
            source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
        )


def test_interpolated_prices_config_accepts_source_storage_uid() -> None:
    assert "source_time_index_meta_table_uid" in InterpolatedPricesConfig.model_fields
    assert "source_price_instance" in InterpolatedPricesConfig.model_fields
    assert "bar_frequency_id" not in InterpolatedPricesConfig.model_fields
    assert "source_bars_data_node" not in InterpolatedPricesConfig.model_fields

    configuration = InterpolatedPricesConfig(
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
        source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
        asset_list=["example-asset-btc"],
    )

    assert str(configuration.source_time_index_meta_table_uid) == (
        SOURCE_TIME_INDEX_META_TABLE_UID
    )
    assert configuration.source_price_instance is None


def test_interpolated_prices_config_accepts_source_price_instance() -> None:
    source_price = _api_price_source()

    configuration = InterpolatedPricesConfig(
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
        source_price_instance=source_price,
        asset_list=["example-asset-btc"],
    )

    assert configuration.source_price_instance is source_price
    assert configuration.source_time_index_meta_table_uid is None


def test_interpolated_prices_config_rejects_missing_source() -> None:
    with pytest.raises(ValidationError, match="requires exactly one source"):
        InterpolatedPricesConfig(
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
            asset_list=["example-asset-btc"],
        )


def test_interpolated_prices_config_rejects_two_sources() -> None:
    with pytest.raises(ValidationError, match="requires exactly one source"):
        InterpolatedPricesConfig(
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
            source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
            source_price_instance=_api_price_source(),
            asset_list=["example-asset-btc"],
        )


def test_interpolated_prices_config_rejects_user_supplied_bar_frequency_id() -> None:
    with pytest.raises(ValidationError):
        InterpolatedPricesConfig(
            bar_frequency_id="1d",
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
            source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
            asset_list=["example-asset-btc"],
        )


def test_source_time_indexed_profile_cadence_is_canonicalized() -> None:
    assert (
        _source_time_indexed_profile_cadence(
            _api_price_source(),
            source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
        )
        == "1d"
    )


def test_interpolated_prices_resolves_source_instance_as_dependency() -> None:
    source_price = _api_price_source()
    configuration = InterpolatedPricesConfig(
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
        source_price_instance=source_price,
        asset_list=["example-asset-btc"],
    )

    resolved_source, source_uid = _resolve_interpolated_source_prices(configuration)
    node = object.__new__(InterpolatedPrices)
    node.bars_ts = resolved_source

    assert resolved_source is source_price
    assert source_uid == SOURCE_TIME_INDEX_META_TABLE_UID
    assert node.dependencies() == {"bars_ts": source_price}


def test_interpolated_prices_resolves_source_uid_as_api_dependency(monkeypatch) -> None:
    source_price = _api_price_source()

    def build_from_table_uid(uid: str) -> APIDataNode:
        assert uid == SOURCE_TIME_INDEX_META_TABLE_UID
        return source_price

    monkeypatch.setattr(APIDataNode, "build_from_table_uid", build_from_table_uid)

    configuration = InterpolatedPricesConfig(
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
        source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
        asset_list=["example-asset-btc"],
    )

    resolved_source, source_uid = _resolve_interpolated_source_prices(configuration)

    assert resolved_source is source_price
    assert source_uid == SOURCE_TIME_INDEX_META_TABLE_UID
