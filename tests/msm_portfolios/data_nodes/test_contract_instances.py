from __future__ import annotations

import os

import pytest
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")

from metatables import PlatformTimeIndexMetaTable, sqlalchemy_naming_convention
from msm.base import MarketsBase
from msm.data_nodes.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_column_nullable_map,
    storage_index_names,
    storage_time_index_name,
)
from msm.models import AssetTable, PortfolioTable, SignalMetadataTable
from msm_portfolios.data_nodes.contract_instances import (
    PORTFOLIO_STORAGE_CONTRACTS,
    configured_contract_instance_storage,
    configured_portfolio_weights_storage,
    configured_portfolios_storage,
    configured_signal_weights_storage,
    contract_columns_satisfied,
    contract_instance_identifier,
    contract_instance_table_name,
)
from msm_portfolios.data_nodes.portfolios.storage import PortfolioWeightsStorage, PortfoliosStorage
from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage
from msm_portfolios.models import portfolio_sqlalchemy_models


@pytest.mark.parametrize(
    ("factory", "contract", "core"),
    [
        (configured_portfolios_storage, "PortfoliosTS", PortfoliosStorage),
        (configured_portfolio_weights_storage, "PortfolioWeightsTS", PortfolioWeightsStorage),
        (configured_signal_weights_storage, "SignalWeightsTS", SignalWeightsStorage),
    ],
)
def test_instances_share_the_contract_schema_under_a_provider_namespace(factory, contract, core):
    instance = factory(
        instance_key="main", namespace="my-provider", storage_app="my_provider"
    )

    assert issubclass(instance, PlatformTimeIndexMetaTable)
    assert instance is not core
    assert storage_column_dtypes_map(instance) == storage_column_dtypes_map(core)
    assert storage_column_nullable_map(instance) == storage_column_nullable_map(core)
    assert storage_time_index_name(instance) == storage_time_index_name(core)
    assert storage_index_names(instance) == storage_index_names(core)
    assert [column.name for column in instance.__table__.columns] == [
        column.name for column in core.__table__.columns
    ]
    assert instance.__table__.name == contract_instance_table_name(
        contract, "main", storage_app="my_provider"
    )
    assert instance.__table__.name.startswith("my_provider__")
    assert instance.__metatable_identifier__ == f"my-provider.{contract}.main"
    assert instance.metatable_identifier() == f"my-provider.{contract}.main"
    assert instance.__metatable_namespace__ == "my-provider"
    assert instance.__table__.info == {
        "namespace": "my-provider",
        "identifier": f"my-provider.{contract}.main",
        "markets_storage_app": "my_provider",
    }
    assert instance.__metatable_extra_hash_components__ == {
        "storage_contract": contract,
        "instance_key": "main",
    }
    unique = [index for index in instance.__table__.indexes if index.unique]
    assert [[column.name for column in index.columns] for index in unique] == [
        list(core.__index_names__)
    ]
    # The core table stays the Markets-owned instance and the migration registry is unchanged.
    assert core in portfolio_sqlalchemy_models()
    assert instance not in portfolio_sqlalchemy_models()


def test_instances_keep_the_contract_foreign_keys_to_core_registries() -> None:
    values = configured_portfolios_storage(instance_key="fk_check", namespace="ns-a")
    weights = configured_portfolio_weights_storage(instance_key="fk_check", namespace="ns-a")
    signals = configured_signal_weights_storage(instance_key="fk_check", namespace="ns-a")

    def targets(model, column):
        return sorted(fk.target_fullname for fk in model.__table__.c[column].foreign_keys)

    portfolio = f"{PortfolioTable.__table__.fullname}.unique_identifier"
    asset = f"{AssetTable.__table__.fullname}.unique_identifier"
    assert targets(values, "portfolio_identifier") == [portfolio]
    assert targets(weights, "portfolio_identifier") == [portfolio]
    assert targets(weights, "asset_identifier") == [asset]
    assert targets(signals, "signal_uid") == [f"{SignalMetadataTable.__table__.fullname}.signal_uid"]
    assert targets(signals, "asset_identifier") == [asset]


def test_identifier_is_stable_and_derived_from_contract_and_instance_key() -> None:
    first = configured_portfolios_storage(instance_key="Stable", namespace="ns-b")
    second = configured_portfolios_storage(instance_key="stable", namespace="ns-b")
    markets = configured_portfolios_storage(instance_key="second_engine")

    assert first is second
    assert contract_instance_identifier("PortfoliosTS", "Stable") == "PortfoliosTS.stable"
    # The default Markets namespace keeps the bare identifier, as every Markets table does.
    assert markets.__metatable_identifier__ == "PortfoliosTS.second_engine"
    assert markets.__table__.name == "ms_markets__portfoliosts__second_engine"
    assert markets.__table__.name != PortfoliosStorage.__table__.name
    with pytest.raises(ValueError, match="instance_key"):
        configured_portfolios_storage(instance_key="Bad Key!")
    with pytest.raises(ValueError, match="Unknown portfolio storage contract"):
        configured_contract_instance_storage("BarsTS", instance_key="x")


def test_provider_base_receives_copies_of_the_referenced_core_tables() -> None:
    class ProviderBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    instance = configured_signal_weights_storage(
        instance_key="own_base",
        namespace="provider-ns",
        storage_app="provider_app",
        base=ProviderBase,
    )

    assert issubclass(instance, ProviderBase)
    assert instance.__table__.metadata is ProviderBase.metadata
    assert set(ProviderBase.metadata.tables) == {
        "provider_app__signalweightsts__own_base",
        AssetTable.__table__.name,
        SignalMetadataTable.__table__.name,
    }
    assert "provider_app__signalweightsts__own_base" not in MarketsBase.metadata.tables
    assert ProviderBase.metadata.tables[AssetTable.__table__.name] is not AssetTable.__table__


def test_contract_columns_allow_provider_extras_but_not_missing_columns() -> None:
    required = PORTFOLIO_STORAGE_CONTRACTS["PortfoliosTS"].column_names

    assert contract_columns_satisfied("PortfoliosTS", [*required, "provider_only"])
    assert not contract_columns_satisfied("PortfoliosTS", required[:-1])
