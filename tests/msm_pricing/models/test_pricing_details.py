from __future__ import annotations

from mainsequence.meta_tables import PlatformManagedMetaTable

from msm.base import MARKETS_TABLE_APP, markets_table_name
from msm.models import AssetTable, IndexTable
from msm_pricing.models import (
    AssetCurrentPricingDetailsTable,
    CurveBuildingDetailsTable,
    CurveTable,
    IndexConventionDetailsTable,
    PricingMarketDataSetCurveBindingTable,
    PricingMarketDataSetTable,
)


def test_asset_current_pricing_details_is_platform_managed_table() -> None:
    assert issubclass(AssetCurrentPricingDetailsTable, PlatformManagedMetaTable)
    assert AssetCurrentPricingDetailsTable.__table__.name == markets_table_name(
        MARKETS_TABLE_APP,
        AssetCurrentPricingDetailsTable.__metatable_identifier__,
    )
    assert AssetCurrentPricingDetailsTable.__metatable_identifier__ == "AssetCurrentPricingDetails"


def test_asset_current_pricing_details_uses_asset_uid_as_one_to_one_primary_key() -> None:
    table = AssetCurrentPricingDetailsTable.__table__

    assert "uid" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["asset_uid"]

    asset_uid_fk = next(iter(table.c.asset_uid.foreign_keys))
    assert asset_uid_fk.column is AssetTable.__table__.c.uid
    assert asset_uid_fk.ondelete == "CASCADE"


def test_asset_current_pricing_details_columns_and_indexes() -> None:
    table = AssetCurrentPricingDetailsTable.__table__

    assert set(table.c.keys()) == {
        "asset_uid",
        "instrument_type",
        "instrument_dump",
        "pricing_details_date",
        "serialization_format",
        "pricing_package_version",
        "source",
        "metadata",
    }
    assert "metadata_json" not in table.c
    assert table.c.instrument_type.nullable is False
    assert table.c.instrument_dump.nullable is False
    assert table.c.pricing_details_date.nullable is False
    assert table.c.serialization_format.nullable is False
    assert table.c.pricing_package_version.nullable is True
    assert table.c.source.nullable is True
    assert table.c.metadata.nullable is True

    assert any(
        [column.name for column in index.columns] == ["instrument_type"] for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["pricing_details_date"]
        for index in table.indexes
    )


def test_index_convention_details_uses_index_uid_as_one_to_one_primary_key() -> None:
    assert issubclass(IndexConventionDetailsTable, PlatformManagedMetaTable)

    table = IndexConventionDetailsTable.__table__

    assert "uid" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["index_uid"]

    index_uid_fk = next(iter(table.c.index_uid.foreign_keys))
    assert index_uid_fk.column is IndexTable.__table__.c.uid
    assert index_uid_fk.ondelete == "CASCADE"

    assert set(table.c.keys()) == {
        "index_uid",
        "index_family",
        "convention_dump",
        "serialization_format",
        "source",
        "metadata",
    }


def test_curve_table_has_no_index_relationship() -> None:
    assert issubclass(CurveTable, PlatformManagedMetaTable)

    table = CurveTable.__table__

    assert [column.name for column in table.primary_key.columns] == ["uid"]
    assert set(table.c.keys()) == {
        "uid",
        "unique_identifier",
        "display_name",
        "curve_type",
        "currency_code",
        "quote_side",
        "interpolation_method",
        "compounding",
        "source",
        "status",
        "metadata",
    }
    assert "day_counter_code" not in table.c
    assert "index_uid" not in table.c

    expected_indexes = {
        ("unique_identifier",),
        ("curve_type",),
        ("currency_code",),
        ("quote_side",),
        ("source",),
        ("status",),
    }
    actual_indexes = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert expected_indexes.issubset(actual_indexes)


def test_curve_building_details_is_one_to_one_with_curve() -> None:
    assert issubclass(CurveBuildingDetailsTable, PlatformManagedMetaTable)

    table = CurveBuildingDetailsTable.__table__

    assert "uid" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["curve_uid"]
    curve_uid_fk = next(iter(table.c.curve_uid.foreign_keys))
    assert curve_uid_fk.column is CurveTable.__table__.c.uid
    assert curve_uid_fk.ondelete == "CASCADE"

    assert set(table.c.keys()) == {
        "curve_uid",
        "builder_type",
        "quote_convention",
        "rate_unit",
        "day_counter_code",
        "calendar_code",
        "interpolation_method",
        "compounding",
        "compounding_frequency",
        "extrapolation_policy",
        "bootstrap_method",
        "builder_payload",
        "source",
        "metadata",
    }


def test_market_data_set_curve_binding_selects_curve_identity() -> None:
    assert issubclass(PricingMarketDataSetCurveBindingTable, PlatformManagedMetaTable)

    table = PricingMarketDataSetCurveBindingTable.__table__

    assert [column.name for column in table.primary_key.columns] == ["uid"]
    assert set(table.c.keys()) == {
        "uid",
        "market_data_set_uid",
        "binding_key",
        "role_key",
        "selector_type",
        "selector_key",
        "quote_side",
        "curve_uid",
        "source",
        "priority",
        "status",
        "metadata",
    }

    set_uid_fk = next(iter(table.c.market_data_set_uid.foreign_keys))
    assert set_uid_fk.column is PricingMarketDataSetTable.__table__.c.uid
    assert set_uid_fk.ondelete == "CASCADE"

    curve_uid_fk = next(iter(table.c.curve_uid.foreign_keys))
    assert curve_uid_fk.column is CurveTable.__table__.c.uid
    assert curve_uid_fk.ondelete == "RESTRICT"

    expected_indexes = {
        ("market_data_set_uid", "binding_key"),
        ("role_key",),
        ("selector_type", "selector_key"),
        ("quote_side",),
        ("curve_uid",),
        ("status",),
    }
    actual_indexes = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert expected_indexes.issubset(actual_indexes)
