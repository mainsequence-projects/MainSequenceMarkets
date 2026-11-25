"""A provider owns its Index-value table and the Index catalog finds it (ADR 0047, decision 4).

The provider declares the table with a class statement (ADR 0066); the catalog reads a
table it discovers through its registration and declares nothing (ADR 0066, decision 7).
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData
from sqlalchemy.dialects import sqlite
from sqlalchemy.orm import DeclarativeBase

from metatables import sqlalchemy_naming_convention
from msm.api.indices import Index
from msm.base import MarketsBase
from msm.models import IndexTable
from msm.services.indices import catalog as catalog_service
from msm.services.indices import discover_canonical_datasets, read_index_values
from msm.time_index.indices.storage import (
    IndexValues1d,
    IndexValuesInstance,
    require_cadenced_index_values_storage,
)

COLUMNS = (
    "time_index",
    "index_identifier",
    "value",
    "definition_uid",
    "observation_status",
    "source_as_of",
    "metadata_json",
)


class ProviderBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class ProviderDailyIndexValues(IndexValuesInstance, ProviderBase):
    __cadence__ = "1d"
    __metatable_namespace__ = "my_provider"
    __markets_storage_app__ = "my_provider"


def _meta_table(*, identifier: str, namespace: str, physical_table_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        uid=uuid.uuid4(),
        identifier=identifier,
        namespace=namespace,
        cadence="1d",
        physical_table_name=physical_table_name,
        physical_schema="public",
        table_index_names=["time_index", "index_identifier"],
        columns=[SimpleNamespace(name=name) for name in COLUMNS],
        description="Index values published by a provider.",
        registration=None,
    )


def test_markets_keeps_its_table_and_a_provider_declares_its_own() -> None:
    markets = IndexValues1d
    provider = ProviderDailyIndexValues

    assert markets.__table__.name == "ms_markets__index_values__t_1d"
    assert provider.__table__.name == "my_provider__index_values__t_1d"
    assert provider.__metatable_namespace__ == "my_provider"
    assert provider.__table__.info["identifier"] == "my_provider.IndexValuesTS.1d"
    assert provider.__metatable_identifier__ == "my_provider." + markets.__metatable_identifier__
    assert [c.name for c in provider.__table__.columns] == [c.name for c in markets.__table__.columns]
    assert provider.__index_names__ == markets.__index_names__
    assert provider.__table__.metadata is ProviderBase.metadata
    assert IndexTable.__table__.fullname not in ProviderBase.metadata.tables
    assert {fk.target_fullname for fk in provider.__table__.foreign_keys} == {
        fk.target_fullname for fk in markets.__table__.foreign_keys
    }
    assert require_cadenced_index_values_storage(provider) == "1d"


def test_a_provider_table_needs_its_own_storage_app_and_a_cadence() -> None:
    class Base(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    with pytest.raises(ValueError, match="must declare __markets_storage_app__"):

        class NoApp(IndexValuesInstance, Base):
            __cadence__ = "1d"
            __metatable_namespace__ = "my_provider"

    with pytest.raises(ValueError, match="its own storage_app"):

        class MarketsApp(IndexValuesInstance, Base):
            __cadence__ = "1d"
            __metatable_namespace__ = "my_provider"
            __markets_storage_app__ = "ms_markets"

    with pytest.raises(ValueError, match="must declare __cadence__"):

        class NoCadence(IndexValuesInstance, Base):
            __metatable_namespace__ = "my_provider"
            __markets_storage_app__ = "my_provider"

    with pytest.raises(ValueError, match="canonical interval"):

        class OddCadence(IndexValuesInstance, Base):
            __cadence__ = "daily"
            __metatable_namespace__ = "my_provider"
            __markets_storage_app__ = "my_provider"

    assert not Base.metadata.tables


def _registrations(monkeypatch) -> list[SimpleNamespace]:
    markets = IndexValues1d
    provider_table = _meta_table(
        identifier="my_provider.IndexValuesTS.1d",
        namespace="my_provider",
        physical_table_name="my_provider__index_values__t_1d",
    )
    markets_table = _meta_table(
        identifier=markets.__metatable_identifier__,
        namespace="mainsequence.markets",
        physical_table_name=markets.__table__.name,
    )
    rejected = [
        _meta_table(
            identifier="IndexValuesTS.1d",
            namespace="my_provider",
            physical_table_name="my_provider__index_values__t_1d",
        ),
        _meta_table(
            identifier="my_provider.IndexValuesTS.1d",
            namespace="my_provider",
            physical_table_name="my_provider__other_values__t_1d",
        ),
    ]
    tables = [markets_table, provider_table, *rejected]
    monkeypatch.setattr(
        catalog_service.TimeIndexMetaTable,
        "filter_by_body",
        lambda **kwargs: [
            table for table in tables if str(table.uid) in kwargs.get("uid__in", [str(table.uid)])
        ],
    )
    return tables


def test_the_catalog_discovers_a_provider_table(monkeypatch) -> None:
    _registrations(monkeypatch)

    datasets = discover_canonical_datasets()

    assert {(d.namespace, d.physical_table_name) for d in datasets} == {
        ("mainsequence.markets", "ms_markets__index_values__t_1d"),
        ("my_provider", "my_provider__index_values__t_1d"),
    }


def test_the_catalog_reads_a_provider_table_through_its_registration(monkeypatch) -> None:
    """The read names the registered table, with the contract's column types; nothing is
    declared on any base, so no class or table exists for it after the read."""

    _registrations(monkeypatch)
    (dataset,) = [d for d in discover_canonical_datasets() if d.namespace == "my_provider"]
    index = Index.model_construct(uid=uuid.uuid4(), unique_identifier="USD_SWAP_10Y")
    markets_tables = set(MarketsBase.metadata.tables)
    compiled = []

    def compile_statement(statement, **_kwargs):
        compiled.append(statement.compile(dialect=sqlite.dialect()))
        return statement

    monkeypatch.setattr(catalog_service, "compile_markets_statement", compile_statement)
    monkeypatch.setattr(
        catalog_service,
        "execute_markets_operation",
        lambda _operation, **_kwargs: {
            "rows": [
                {
                    "time_index": dt.datetime(2026, 7, 17, tzinfo=dt.UTC),
                    "index_identifier": "USD_SWAP_10Y",
                    "value": 0.042,
                    "definition_uid": None,
                    "observation_status": "final",
                    "source_as_of": None,
                    "metadata_json": None,
                }
            ]
        },
    )
    context = SimpleNamespace(limits=None, data_source_uid=None, timeout=None)

    result = read_index_values(
        context,
        index=index,
        dataset=dataset,
        start=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
        end=dt.datetime(2026, 7, 31, tzinfo=dt.UTC),
    )

    assert [row.value for row in result.rows] == [0.042]
    (statement,) = compiled
    assert 'FROM my_provider__index_values__t_1d' in str(statement)
    assert str(statement.params["time_index_1"]) == "2026-07-01 00:00:00+00:00"
    # The time bounds bind as timestamps, the contract's column type.
    bound = {name: bind.type.__class__.__name__ for name, bind in statement.binds.items()}
    assert bound["time_index_1"] == "DateTime"
    assert set(MarketsBase.metadata.tables) == markets_tables
    assert "my_provider__index_values__t_1d" not in markets_tables
    assert not any(
        mapper.local_table.name == "my_provider__index_values__t_1d"
        for mapper in MarketsBase.registry.mappers
    )
