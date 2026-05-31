from __future__ import annotations

from types import SimpleNamespace

import msm.models as domain_models
from msm.maintenance.models import (
    MarketsMetaTableCatalogRow,
    MarketsMetaTableCatalogTable,
    markets_meta_table_contract_hash,
)
from msm.models import AssetTable, AssetTypeTable, markets_sqlalchemy_models


def test_catalog_table_stores_registered_metatable_identity() -> None:
    table = MarketsMetaTableCatalogTable.__table__

    assert MarketsMetaTableCatalogTable.__markets_base_identifier__ == ("MarketsMetaTableCatalog")
    assert MarketsMetaTableCatalogTable.__metatable_identifier__ == ("MarketsMetaTableCatalog")
    assert "uid" in table.c
    assert [column.name for column in table.primary_key.columns] == ["uid"]
    assert set(table.c.keys()) == {
        "uid",
        "namespace",
        "identifier",
        "description",
        "model_name",
        "meta_table_uid",
        "contract_hash",
        "sdk_version",
        "created_at",
        "updated_at",
    }


def test_catalog_table_is_not_part_of_application_model_registration_order() -> None:
    assert MarketsMetaTableCatalogTable not in markets_sqlalchemy_models()
    assert not hasattr(domain_models, "MarketsMetaTableCatalogTable")


def test_catalog_table_enforces_logical_identity_uniqueness_as_an_index() -> None:
    table = MarketsMetaTableCatalogTable.__table__
    indexes_by_columns = {
        tuple(column.name for column in index.columns): index for index in table.indexes
    }

    assert indexes_by_columns[("namespace", "identifier")].unique is True
    assert indexes_by_columns[("meta_table_uid",)].unique is True


def test_catalog_table_indexes_logical_identity_only() -> None:
    table = MarketsMetaTableCatalogTable.__table__
    index_column_sets = {tuple(column.name for column in index.columns) for index in table.indexes}

    assert ("namespace", "identifier") in index_column_sets
    assert ("storage_hash",) not in index_column_sets
    assert ("physical_table_name",) not in index_column_sets


def test_catalog_row_uses_platform_metatable_values() -> None:
    meta_table = SimpleNamespace(
        uid="meta-table-uid",
        namespace="mainsequence.examples",
        identifier="mainsequence.examples.Asset",
        description="Asset catalog rows for examples.",
        storage_hash="mt_mainsequence_examples_asset_hash",
    )

    row = MarketsMetaTableCatalogRow.from_meta_table(
        model=AssetTable,
        meta_table=meta_table,
        sdk_version="0.0.test",
    )

    assert row.namespace == "mainsequence.examples"
    assert row.identifier == "mainsequence.examples.Asset"
    assert row.description == "Asset catalog rows for examples."
    assert row.model_name == "AssetTable"
    assert row.meta_table_uid == "meta-table-uid"
    assert row.contract_hash == markets_meta_table_contract_hash(AssetTable)
    assert row.sdk_version == "0.0.test"
    assert row.identity_key == ("mainsequence.examples", "mainsequence.examples.Asset")


def test_catalog_row_payload_is_keyed_by_logical_identity() -> None:
    meta_table = SimpleNamespace(
        uid="meta-table-uid",
        namespace="ms-markets",
        identifier="Asset",
        storage_hash="asset-storage-hash",
    )

    row = MarketsMetaTableCatalogRow.from_meta_table(
        model=AssetTable,
        meta_table=meta_table,
    )

    payload = row.to_payload()
    assert row.identity_key == ("ms-markets", "Asset")
    assert payload["description"] is None
    assert "storage_hash" not in payload
    assert "management_mode" not in payload
    assert "data_source_uid" not in payload


def test_metatable_contract_hash_is_deterministic_and_model_specific() -> None:
    first = markets_meta_table_contract_hash(AssetTable)
    second = markets_meta_table_contract_hash(AssetTable)
    asset_type = markets_meta_table_contract_hash(AssetTypeTable)

    assert len(first) == 64
    assert first == second
    assert first != asset_type
