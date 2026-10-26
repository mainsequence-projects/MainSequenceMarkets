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


def test_instances_on_a_provider_base_share_copied_targets_and_attach() -> None:
    """Several Asset foreign keys on one base reuse one copied target (was a TypeError)."""

    from msm.api.remote import use_remote_backend, use_runtime_backend
    from msm.models import AssetTable
    from msm.models.registration import resolve_markets_meta_table_models
    from msm.time_index.execution.storage import TradesStorage

    class ProviderBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    trades = configured_time_index_instance(
        TradesStorage, instance_key="main", namespace="ns-base", storage_app="ns_base", base=ProviderBase
    )
    curves = configured_time_index_instance(
        DiscountCurvesStorage, instance_key="main", namespace="ns-base", storage_app="ns_base", base=ProviderBase
    )

    assert trades.__table__.metadata is ProviderBase.metadata
    assert AssetTable.__table__.fullname in ProviderBase.metadata.tables
    assert curves.__table__.name in ProviderBase.metadata.tables

    resolved = resolve_markets_meta_table_models([trades])
    assert resolved[-1] is trades and AssetTable in resolved

    class _Backend:
        def call(self, resource, operation, arguments):  # pragma: no cover - never called
            raise AssertionError("attachment must not call the API")

    use_remote_backend(_Backend())
    try:
        assert resolve_markets_meta_table_models([trades]) == [trades]
    finally:
        use_runtime_backend()


def test_a_provider_base_holds_only_reference_copies_of_markets_tables() -> None:
    """Copied targets keep only their key column, so the provider metadata sorts on its own."""

    from msm_portfolios.time_index.contract_instances import (
        configured_portfolio_event_ledger_storage,
        configured_portfolio_weights_storage,
    )

    class OwnBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    kwargs = {"instance_key": "main", "namespace": "ns-ref", "storage_app": "ns_ref", "base": OwnBase}
    configured_portfolio_weights_storage(**kwargs)
    configured_portfolio_event_ledger_storage(**kwargs)

    sorted_names = [table.name for table in OwnBase.metadata.sorted_tables]
    assert "ns_ref__portfolioweightsts__main" in sorted_names
    portfolio = OwnBase.metadata.tables["ms_markets__portfolio"]
    asset = OwnBase.metadata.tables["ms_markets__asset"]
    assert [column.name for column in portfolio.c] == ["unique_identifier"]
    assert [column.name for column in asset.c] == ["unique_identifier"]
    assert not portfolio.foreign_keys and not asset.foreign_keys
