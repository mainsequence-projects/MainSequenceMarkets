"""Provider-owned instances of Markets time-index storages (ADR 0047)."""

from __future__ import annotations

from functools import partial

import pytest
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import (
    PlatformTimeIndexMetaTable,
    sqlalchemy_naming_convention,
    time_indexed_registration_request_from_sqlalchemy_model,
)
from msm.storage_instances import configured_time_index_instance
from msm.time_index.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_column_nullable_map,
    storage_index_names,
    storage_time_index_name,
)
from msm_portfolios.time_index.contract_instances import (
    configured_contract_instance_storage,
    configured_portfolio_calendar_events_storage,
    configured_portfolio_event_ledger_storage,
    configured_portfolio_rebalance_state_storage,
)
from msm_portfolios.time_index.prices.storage import (
    ExternalPricesStorage,
    InterpolatedPricesStorage,
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
    # The keys are Markets' own columns; no Markets table is copied into the provider's metadata.
    core_targets = {fk.parent.name: fk.column for fk in core.__table__.foreign_keys}
    for fk in instance.__table__.foreign_keys:
        assert fk.column is core_targets[fk.parent.name]
        assert fk.column.table.key not in ProviderBase.metadata.tables


def test_instances_are_cached_and_validate_their_key() -> None:
    owner = {"namespace": "ns-c", "storage_app": "ns_c", "base": ProviderBase}
    first = configured_time_index_instance(DiscountCurvesStorage, instance_key="Cache", **owner)
    assert first is configured_time_index_instance(
        DiscountCurvesStorage, instance_key="cache", **owner
    )
    with pytest.raises(ValueError, match="instance_key"):
        configured_time_index_instance(DiscountCurvesStorage, instance_key="bad key", **owner)


def test_instances_on_a_provider_base_key_to_markets_tables_and_attach() -> None:
    """Several Asset foreign keys on one base resolve to Markets' table and attach it."""

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
    assert AssetTable.__table__.fullname not in ProviderBase.metadata.tables
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


def test_a_provider_base_holds_only_the_providers_tables() -> None:
    """The keys to Markets copy no table, and the provider metadata still sorts on its own."""

    from msm_portfolios.time_index.contract_instances import (
        configured_portfolio_event_ledger_storage,
        configured_portfolio_rebalance_state_storage,
    )

    class OwnBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    kwargs = {"instance_key": "main", "namespace": "ns-ref", "storage_app": "ns_ref", "base": OwnBase}
    rebalance = configured_portfolio_rebalance_state_storage(**kwargs)
    ledger = configured_portfolio_event_ledger_storage(**kwargs)

    assert sorted(table.name for table in OwnBase.metadata.sorted_tables) == sorted(
        [rebalance.__table__.name, ledger.__table__.name]
    )


INSTANCE_FACTORIES = {
    "time_index_instance": partial(configured_time_index_instance, DiscountCurvesStorage),
    "contract_instance": partial(configured_contract_instance_storage, "PortfolioRebalanceStateTS"),
    "rebalance_state": configured_portfolio_rebalance_state_storage,
    "calendar_events": configured_portfolio_calendar_events_storage,
    "event_ledger": configured_portfolio_event_ledger_storage,
}


@pytest.mark.parametrize("factory", INSTANCE_FACTORIES)
@pytest.mark.parametrize(
    ("argument", "empty"),
    [
        ("namespace", None),
        ("namespace", ""),
        ("namespace", "  "),
        ("storage_app", None),
        ("storage_app", ""),
        ("storage_app", "  "),
        ("base", None),
        ("base", ""),
    ],
)
def test_every_instance_factory_requires_the_owners_namespace_app_and_base(
    factory, argument, empty
) -> None:
    class OwnerBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    owner = {"namespace": "owner", "storage_app": "owner", "base": OwnerBase}
    build = INSTANCE_FACTORIES[factory]

    with pytest.raises(ValueError, match=f"{argument} is required"):
        build(instance_key="owned", **{**owner, argument: empty})
    del owner[argument]
    with pytest.raises(TypeError, match=argument):
        build(instance_key="owned", **owner)
    assert not OwnerBase.metadata.tables


def test_an_instance_takes_a_cadence_where_its_core_declares_none() -> None:
    """Interpolated prices: each instance's cadence is its upsample frequency (#95)."""

    class OwnerBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    owner = {"namespace": "ns-cadence", "storage_app": "ns_cadence", "base": OwnerBase}
    instance = configured_time_index_instance(
        InterpolatedPricesStorage, instance_key="daily", cadence=" 1D ", **owner
    )

    assert instance.__cadence__ == "1d"
    assert instance is configured_time_index_instance(
        InterpolatedPricesStorage, instance_key="daily", cadence="1d", **owner
    )
    request = time_indexed_registration_request_from_sqlalchemy_model(
        instance, data_source_uid="00000000-0000-0000-0000-000000000000"
    ).model_dump(mode="json")
    assert request["table_contract"]["authoring"]["time_indexed"]["cadence"] == "1d"

    # A cadence the core declares is the contract's, which its instances keep.
    kept = configured_time_index_instance(ExternalPricesStorage, instance_key="kept", **owner)
    assert kept.__cadence__ == "1d"
    with pytest.raises(ValueError, match="declares cadence"):
        configured_time_index_instance(
            ExternalPricesStorage, instance_key="other", cadence="5m", **owner
        )
    with pytest.raises(ValueError, match="cadence"):
        configured_time_index_instance(
            InterpolatedPricesStorage, instance_key="empty", cadence=" ", **owner
        )


@pytest.mark.parametrize("change", [{"cadence": "5m"}, {"namespace": "another"}])
def test_one_instance_table_has_one_cadence_and_one_namespace(change) -> None:
    class OwnerBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    declared = {
        "instance_key": "main",
        "cadence": "1d",
        "namespace": "ns-once",
        "storage_app": "ns_once",
        "base": OwnerBase,
    }
    configured_time_index_instance(InterpolatedPricesStorage, **declared)

    with pytest.raises(ValueError, match="already declared"):
        configured_time_index_instance(InterpolatedPricesStorage, **{**declared, **change})
