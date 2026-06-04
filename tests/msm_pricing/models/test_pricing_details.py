from __future__ import annotations

from mainsequence.meta_tables import PlatformManagedMetaTable

from msm.base import MARKETS_TABLE_APP, markets_table_name
from msm.models import AssetTable, IndexTable
from msm_pricing.models import (
    AssetCurrentPricingDetailsTable,
    CurveTable,
    IndexConventionDetailsTable,
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


def test_curve_table_references_index_convention_details() -> None:
    assert issubclass(CurveTable, PlatformManagedMetaTable)

    table = CurveTable.__table__

    assert [column.name for column in table.primary_key.columns] == ["uid"]
    assert set(table.c.keys()) == {
        "uid",
        "unique_identifier",
        "display_name",
        "curve_type",
        "index_uid",
        "interpolation_method",
        "compounding",
        "source",
        "metadata",
    }
    assert "day_counter_code" not in table.c
    assert "currency_code" not in table.c

    index_uid_fk = next(iter(table.c.index_uid.foreign_keys))
    assert index_uid_fk.column is IndexConventionDetailsTable.__table__.c.index_uid
    assert index_uid_fk.ondelete == "RESTRICT"

    expected_indexes = {
        ("unique_identifier",),
        ("index_uid",),
        ("curve_type",),
        ("source",),
    }
    actual_indexes = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert expected_indexes.issubset(actual_indexes)
