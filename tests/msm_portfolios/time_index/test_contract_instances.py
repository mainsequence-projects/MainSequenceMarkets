from __future__ import annotations

import os

import pytest
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")

from metatables import (
    PlatformTimeIndexMetaTable,
    sqlalchemy_naming_convention,
    time_indexed_registration_request_from_sqlalchemy_model,
)
from metatables.api.backend.contracts.storage_layouts import normalize_storage_layout
from msm.base import MarketsBase
from msm.time_index.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_column_nullable_map,
    storage_index_names,
    storage_time_index_name,
)
from msm.models import AssetTable, CalendarTable, PortfolioTable
from msm.settings import DEFAULT_MARKETS_NAMESPACE
from msm_portfolios.time_index.contract_instances import (
    PORTFOLIO_CONTRACT_INSTANCES,
    PortfolioCalendarEventsInstance,
    PortfolioEventLedgerInstance,
    PortfolioRebalanceStateInstance,
)
from msm_portfolios.time_index.portfolios.storage import (
    PortfolioCalendarEventsStorage,
    PortfolioEventLedgerStorage,
    PortfolioRebalanceStateStorage,
)
from msm_portfolios.models import portfolio_sqlalchemy_models


class OwnerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class ProviderBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class Provider:
    __metatable_namespace__ = "my-provider"
    __markets_storage_app__ = "my_provider"


class ProviderRebalanceState(PortfolioRebalanceStateInstance, Provider, ProviderBase):
    __instance_key__ = "main"


class ProviderCalendarEvents(PortfolioCalendarEventsInstance, Provider, ProviderBase):
    __instance_key__ = "main"


class ProviderEventLedger(PortfolioEventLedgerInstance, Provider, ProviderBase):
    __instance_key__ = "main"


class MarketsNamespaceRebalanceState(PortfolioRebalanceStateInstance, OwnerBase):
    __instance_key__ = "second_engine"
    __metatable_namespace__ = DEFAULT_MARKETS_NAMESPACE
    __markets_storage_app__ = "second_app"


@pytest.mark.parametrize(
    ("instance", "contract", "core"),
    [
        (ProviderRebalanceState, "PortfolioRebalanceStateTS", PortfolioRebalanceStateStorage),
        (ProviderCalendarEvents, "PortfolioCalendarEventsTS", PortfolioCalendarEventsStorage),
        (ProviderEventLedger, "PortfolioEventLedgerTS", PortfolioEventLedgerStorage),
    ],
)
def test_instances_share_the_contract_schema_under_a_provider_namespace(instance, contract, core):
    assert issubclass(instance, PlatformTimeIndexMetaTable)
    assert instance is not core
    assert storage_column_dtypes_map(instance) == storage_column_dtypes_map(core)
    assert storage_column_nullable_map(instance) == storage_column_nullable_map(core)
    assert storage_time_index_name(instance) == storage_time_index_name(core)
    assert storage_index_names(instance) == storage_index_names(core)
    assert [column.name for column in instance.__table__.columns] == [
        column.name for column in core.__table__.columns
    ]
    assert instance.__table__.name == f"my_provider__{contract.lower()}__main"
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


@pytest.mark.parametrize("instance", [ProviderRebalanceState, ProviderCalendarEvents, ProviderEventLedger])
def test_instances_carry_the_core_storage_layout(instance) -> None:
    core_layout = getattr(instance.__core_storage__, "__storage_layout__", None)
    if core_layout is None:
        assert getattr(instance, "__storage_layout__", None) is None
    else:
        assert instance.__storage_layout__ == core_layout
        # A copy, so an instance can never change the core's layout.
        assert instance.__storage_layout__ is not core_layout


def test_event_ledger_instance_registers_with_the_core_secondary_index() -> None:
    # The default layout would name the lookup index after the four identity
    # dimensions (70 characters), which MetaTables refuses to register.
    request = time_indexed_registration_request_from_sqlalchemy_model(
        ProviderEventLedger, data_source_uid="00000000-0000-0000-0000-000000000000"
    ).model_dump(mode="json")
    contract = request["table_contract"]
    profile = contract["authoring"]["time_indexed"]
    layout = normalize_storage_layout(
        profile["storage_layout"],
        time_index_name=profile["time_index_name"],
        index_names=profile["index_names"],
        columns_by_name={column["name"]: column for column in contract["columns"]},
    )

    assert profile["storage_layout"] == PortfolioEventLedgerStorage.__storage_layout__
    assert [index["name"] for index in layout["secondary_indexes"]] == [
        "portfolio_event_ledger_identity"
    ]


def test_published_series_are_not_contracts() -> None:
    """ADR 0060: signal weights, portfolio weights and values are published, never instances."""

    assert sorted(contract.__core_storage__.__name__ for contract in PORTFOLIO_CONTRACT_INSTANCES) == [
        "PortfolioCalendarEventsStorage",
        "PortfolioEventLedgerStorage",
        "PortfolioRebalanceStateStorage",
    ]


def test_instances_keep_the_contract_foreign_keys_to_core_registries() -> None:
    def targets(model, column):
        return sorted(fk.target_fullname for fk in model.__table__.c[column].foreign_keys)

    assert targets(ProviderRebalanceState, "portfolio_identifier") == [
        f"{PortfolioTable.__table__.fullname}.unique_identifier"
    ]
    assert targets(ProviderRebalanceState, "asset_identifier") == [
        f"{AssetTable.__table__.fullname}.unique_identifier"
    ]
    assert targets(ProviderCalendarEvents, "calendar_identifier") == [
        f"{CalendarTable.__table__.fullname}.unique_identifier"
    ]


@pytest.mark.parametrize("instance", [ProviderRebalanceState, ProviderCalendarEvents, ProviderEventLedger])
def test_engine_output_instances_keep_every_core_foreign_key(instance) -> None:
    def foreign_keys(model):
        return sorted(
            (fk.parent.name, fk.target_fullname, fk.ondelete)
            for fk in model.__table__.foreign_keys
        )

    assert foreign_keys(instance) == foreign_keys(instance.__core_storage__)


def test_every_contract_declares_the_core_table_foreign_keys() -> None:
    for contract in PORTFOLIO_CONTRACT_INSTANCES:
        declared = sorted(
            (
                foreign_key.source_column,
                f"{foreign_key.target_table.__table__.fullname}.{foreign_key.target_column}",
            )
            for foreign_key in contract.__contract_foreign_keys__
        )
        core = sorted(
            (fk.parent.name, fk.target_fullname)
            for fk in contract.__core_storage__.__table__.foreign_keys
        )
        assert declared == core, contract.__name__


def test_identifier_is_stable_and_derived_from_contract_and_instance_key() -> None:
    class Stable(PortfolioRebalanceStateInstance, OwnerBase):
        __instance_key__ = "Stable"
        __metatable_namespace__ = "ns-b"
        __markets_storage_app__ = "app_b"

    assert Stable.__metatable_identifier__ == "ns-b.PortfolioRebalanceStateTS.stable"
    # The default Markets namespace keeps the bare identifier, as every Markets table does.
    markets = MarketsNamespaceRebalanceState
    assert markets.__metatable_identifier__ == "PortfolioRebalanceStateTS.second_engine"
    assert markets.__table__.name == "second_app__portfoliorebalancestatets__second_engine"
    assert markets.__table__.name != PortfolioRebalanceStateStorage.__table__.name


def test_provider_base_receives_only_the_instances_keyed_to_markets_columns() -> None:
    assert issubclass(ProviderRebalanceState, ProviderBase)
    assert ProviderRebalanceState.__table__.metadata is ProviderBase.metadata
    assert set(ProviderBase.metadata.tables) == {
        "my_provider__portfoliorebalancestatets__main",
        "my_provider__portfoliocalendareventsts__main",
        "my_provider__portfolioeventledgerts__main",
    }
    assert "my_provider__portfoliorebalancestatets__main" not in MarketsBase.metadata.tables
    targets = {key.parent.name: key.column for key in ProviderRebalanceState.__table__.foreign_keys}
    assert targets["asset_identifier"] is AssetTable.__table__.c.unique_identifier
    assert targets["portfolio_identifier"] is PortfolioTable.__table__.c.unique_identifier


def test_instances_carry_the_series_lookup_index_of_their_contract() -> None:
    lookup = [
        [column.name for column in index.columns]
        for index in ProviderRebalanceState.__table__.indexes
        if not index.unique
    ]

    assert lookup == [["portfolio_identifier", "time_index"]]
    assert all(len(index.name) <= 63 for index in ProviderRebalanceState.__table__.indexes)
