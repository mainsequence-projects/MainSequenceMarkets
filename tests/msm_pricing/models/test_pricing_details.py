from __future__ import annotations

from mainsequence.tdag.meta_tables import PlatformManagedMetaTable

from msm.models import AssetTable
from msm_pricing.models import AssetCurrentPricingDetailsTable


def test_asset_current_pricing_details_is_platform_managed_table() -> None:
    assert issubclass(AssetCurrentPricingDetailsTable, PlatformManagedMetaTable)
    assert "__tablename__" not in AssetCurrentPricingDetailsTable.__dict__
    assert (
        AssetCurrentPricingDetailsTable.__markets_base_identifier__
        == "AssetCurrentPricingDetails"
    )
    assert (
        AssetCurrentPricingDetailsTable.__metatable_identifier__
        == "AssetCurrentPricingDetails"
    )


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
        [column.name for column in index.columns] == ["instrument_type"]
        for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["pricing_details_date"]
        for index in table.indexes
    )
