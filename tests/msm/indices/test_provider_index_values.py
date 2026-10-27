"""A provider owns its Index-value table and the Index catalog finds it (ADR 0047, decision 4)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import sqlalchemy_naming_convention
from msm.models import IndexTable
from msm.services.indices import catalog as catalog_service
from msm.services.indices import discover_canonical_datasets
from msm.time_index.indices.storage import (
    configured_index_values_storage,
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


def _meta_table(*, identifier: str, namespace: str, physical_table_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        uid=uuid.uuid4(),
        identifier=identifier,
        namespace=namespace,
        cadence="1d",
        physical_table_name=physical_table_name,
        table_index_names=["time_index", "index_identifier"],
        columns=[SimpleNamespace(name=name) for name in COLUMNS],
        description="Index values published by a provider.",
        registration=None,
    )


def test_markets_keeps_its_table_and_a_provider_gets_its_own() -> None:
    markets = configured_index_values_storage(cadence="1d")
    provider = configured_index_values_storage(
        cadence="1d", namespace="my_provider", storage_app="my_provider", base=ProviderBase
    )

    assert markets is configured_index_values_storage(cadence="1d")
    assert markets.__table__.name == "ms_markets__index_values__t_1d"
    assert provider.__table__.name == "my_provider__index_values__t_1d"
    assert provider.__metatable_namespace__ == "my_provider"
    assert provider.__table__.info["identifier"] == "my_provider.IndexValuesTS.1d"
    assert provider.__metatable_identifier__ == "my_provider." + markets.__metatable_identifier__
    assert [c.name for c in provider.__table__.columns] == [c.name for c in markets.__table__.columns]
    assert provider.__index_names__ == markets.__index_names__
    assert provider.__table__.metadata is ProviderBase.metadata
    assert IndexTable.__table__.fullname in ProviderBase.metadata.tables
    assert {fk.target_fullname for fk in provider.__table__.foreign_keys} == {
        fk.target_fullname for fk in markets.__table__.foreign_keys
    }
    assert require_cadenced_index_values_storage(provider) == "1d"


def test_a_provider_table_needs_its_own_storage_app() -> None:
    with pytest.raises(ValueError, match="its own storage_app"):
        configured_index_values_storage(cadence="1d", namespace="my_provider")
    with pytest.raises(ValueError, match="its own storage_app"):
        configured_index_values_storage(cadence="1d", namespace="my_provider", storage_app="ms_markets")


def test_the_catalog_discovers_and_reads_a_provider_table(monkeypatch) -> None:
    markets = configured_index_values_storage(cadence="1d")
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

    datasets = discover_canonical_datasets()

    assert {(d.namespace, d.physical_table_name) for d in datasets} == {
        ("mainsequence.markets", "ms_markets__index_values__t_1d"),
        ("my_provider", "my_provider__index_values__t_1d"),
    }
    provider_dataset = next(d for d in datasets if d.namespace == "my_provider")
    model, handle = catalog_service._dataset_model_and_handle(
        SimpleNamespace(limits=None, data_source_uid=None, timeout=None, namespace=None),
        provider_dataset,
    )
    assert model.__table__.name == "my_provider__index_values__t_1d"
    assert handle.meta_table is provider_table
