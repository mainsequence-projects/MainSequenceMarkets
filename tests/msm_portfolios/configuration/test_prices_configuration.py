"""An interpolation's source is an instance or a table reference (ADR 0066, decision 4)."""

from __future__ import annotations

import pytest
from metatables import TimeIndexMetaTable, TimeIndexTableRef
from pydantic import ValidationError

from msm_portfolios.contrib.prices.updaters import (
    InterpolatedPrices,
    InterpolatedPricesConfig,
    _source_time_indexed_profile_cadence,
)

SOURCE_TIME_INDEX_META_TABLE_UID = "00000000-0000-0000-0000-000000000001"


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
