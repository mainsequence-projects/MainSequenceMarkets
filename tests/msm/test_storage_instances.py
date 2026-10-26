"""Provider-owned instances of Markets time-index storages (ADR 0047)."""

from __future__ import annotations

import pytest
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import PlatformTimeIndexMetaTable, sqlalchemy_naming_convention
from msm.storage_instances import configured_time_index_instance
from msm.time_index.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_column_nullable_map,
    storage_index_names,
    storage_time_index_name,
)
from msm_pricing.time_index.curves.storage import DiscountCurvesStorage
from msm_pricing.time_index.index_fixings.storage import IndexFixingsStorage
from msm_pricing.time_index.pricing_details.storage import AssetPricingDetailsStorage


class ProviderBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


@pytest.mark.parametrize(
    "core", [DiscountCurvesStorage, IndexFixingsStorage, AssetPricingDetailsStorage]
)
def test_instances_keep_the_core_schema_in_the_provider_namespace(core) -> None:
    instance = configured_time_index_instance(
        core, instance_key="main", namespace="my-provider", storage_app="my_provider", base=ProviderBase
    )

    assert issubclass(instance, PlatformTimeIndexMetaTable)
    assert storage_column_dtypes_map(instance) == storage_column_dtypes_map(core)
    assert storage_column_nullable_map(instance) == storage_column_nullable_map(core)
    assert storage_time_index_name(instance) == storage_time_index_name(core)
    assert storage_index_names(instance) == storage_index_names(core)
    assert instance.__table__.name.startswith("my_provider__") and instance.__table__.name.endswith("__main")
    assert instance.__table__.info["namespace"] == "my-provider"
    core_identifier = core.__markets_authored_identifier__
    assert instance.__metatable_identifier__ == f"my-provider.{core_identifier}.main"
    assert instance.metatable_identifier() == f"my-provider.{core_identifier}.main"
    assert getattr(instance, "__cadence__", None) == getattr(core, "__cadence__", None)
    foreign_keys = sorted((fk.parent.name, fk.target_fullname) for fk in instance.__table__.foreign_keys)
    assert foreign_keys == sorted((fk.parent.name, fk.target_fullname) for fk in core.__table__.foreign_keys)
    # The referenced Markets tables are copies in the provider's metadata, not Markets classes.
    for fk in instance.__table__.foreign_keys:
        assert fk.column.table.metadata is ProviderBase.metadata


def test_instances_are_cached_and_validate_their_key() -> None:
    first = configured_time_index_instance(DiscountCurvesStorage, instance_key="Cache", namespace="ns-c")
    assert first is configured_time_index_instance(DiscountCurvesStorage, instance_key="cache", namespace="ns-c")
    with pytest.raises(ValueError, match="instance_key"):
        configured_time_index_instance(DiscountCurvesStorage, instance_key="bad key")
