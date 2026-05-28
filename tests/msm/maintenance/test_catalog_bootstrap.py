from __future__ import annotations

from types import SimpleNamespace

import pytest
from mainsequence.client.exceptions import ConflictError

import msm.maintenance.catalog as catalog
from msm.maintenance.models import markets_meta_table_contract_hash
from msm.models import AssetTable, AssetTypeTable
from msm.models.registration import markets_meta_table_fullname


def _meta_table(
    uid: str,
    *,
    namespace: str = "ms-markets",
    identifier: str = "Asset",
    description: str | None = None,
    storage_hash: str = "asset-storage-hash",
):
    return SimpleNamespace(
        uid=uid,
        namespace=namespace,
        identifier=identifier,
        description=description,
        data_source_uid=None,
        storage_hash=storage_hash,
    )


def test_catalog_bootstrap_registers_missing_application_table(monkeypatch) -> None:
    asset_storage_hash = AssetTable.__table__.name
    registered_meta_table = _meta_table(
        "asset-meta-table-uid",
        description="Asset catalog rows.",
        storage_hash=asset_storage_hash,
    )
    search_in_filters: list[dict] = []
    upserted_rows: list[dict] = []
    register_calls: list[dict] = []

    monkeypatch.setattr(
        catalog,
        "bootstrap_catalog_table",
        lambda **_kwargs: _meta_table(
            "catalog-meta-table-uid",
            identifier="MarketsMetaTableCatalog",
            storage_hash="catalog-storage-hash",
        ),
    )
    def fake_search_model(_context, **kwargs):
        search_in_filters.append(dict(kwargs["in_filters"]))
        return {"rows": []}

    monkeypatch.setattr(catalog, "search_model", fake_search_model)
    monkeypatch.setattr(catalog, "_resolve_platform_meta_table", lambda *_args, **_kwargs: None)

    def fake_register(cls, **kwargs):
        register_calls.append(kwargs)
        return registered_meta_table

    def fake_upsert_model(_context, **kwargs):
        assert kwargs["conflict_columns"] == ["storage_hash"]
        upserted_rows.append(dict(kwargs["values"]))
        return {"rows": [kwargs["values"]]}

    monkeypatch.setattr(AssetTable, "register", classmethod(fake_register))
    monkeypatch.setattr(catalog, "upsert_model", fake_upsert_model)

    result = catalog.bootstrap_markets_meta_tables_from_catalog(
        models=[AssetTable],
        data_source_uid="data-source-uid",
    )

    assert result.registered_count == 1
    assert result.imported_count == 0
    assert result.attached_count == 0
    assert result.registration.target_meta_table_uid_by_fullname == {
        markets_meta_table_fullname(AssetTable): "asset-meta-table-uid"
    }
    assert search_in_filters == [{"storage_hash": [asset_storage_hash]}]
    assert register_calls[0]["data_source_uid"] == "data-source-uid"
    assert upserted_rows[0]["meta_table_uid"] == "asset-meta-table-uid"
    assert upserted_rows[0]["description"] == "Asset catalog rows."
    assert upserted_rows[0]["storage_hash"] == asset_storage_hash
    assert "management_mode" not in upserted_rows[0]
    assert "data_source_uid" not in upserted_rows[0]
    assert upserted_rows[0]["contract_hash"]


def test_catalog_bootstrap_attaches_cataloged_application_table(monkeypatch) -> None:
    asset_storage_hash = AssetTable.__table__.name
    search_in_filters: list[dict] = []
    catalog_row = {
        "namespace": "ms-markets",
        "identifier": "Asset",
        "description": "Asset catalog rows.",
        "meta_table_uid": "asset-meta-table-uid",
        "storage_hash": asset_storage_hash,
        "contract_hash": markets_meta_table_contract_hash(AssetTable),
    }

    monkeypatch.setattr(
        catalog,
        "bootstrap_catalog_table",
        lambda **_kwargs: _meta_table(
            "catalog-meta-table-uid",
            identifier="MarketsMetaTableCatalog",
            storage_hash="catalog-storage-hash",
        ),
    )
    def fake_search_model(_context, **kwargs):
        search_in_filters.append(dict(kwargs["in_filters"]))
        return {"rows": [catalog_row]}

    monkeypatch.setattr(catalog, "search_model", fake_search_model)
    monkeypatch.setattr(
        catalog.MetaTable,
        "get_by_uid",
        staticmethod(lambda **_kwargs: pytest.fail("catalog attach should not fetch MetaTable")),
    )
    monkeypatch.setattr(
        AssetTable,
        "register",
        classmethod(lambda *_args, **_kwargs: pytest.fail("register should not run")),
    )
    monkeypatch.setattr(
        catalog,
        "upsert_model",
        lambda **_kwargs: pytest.fail("catalog row should not be rewritten"),
    )

    result = catalog.bootstrap_markets_meta_tables_from_catalog(models=[AssetTable])

    assert result.attached_count == 1
    assert result.registered_count == 0
    assert result.imported_count == 0
    assert search_in_filters == [{"storage_hash": [asset_storage_hash]}]
    resolved = result.registration.meta_table_by_fullname[
        markets_meta_table_fullname(AssetTable)
    ]
    assert resolved.uid == "asset-meta-table-uid"
    assert resolved.storage_hash == asset_storage_hash
    assert resolved.physical_table_name == asset_storage_hash
    assert resolved.description == "Asset catalog rows."


def test_catalog_bootstrap_bulk_attaches_cataloged_tables(monkeypatch) -> None:
    asset_type_storage_hash = AssetTypeTable.__table__.name
    asset_storage_hash = AssetTable.__table__.name
    search_in_filters: list[dict] = []
    catalog_rows = [
        {
            "namespace": "ms-markets",
            "identifier": "AssetType",
            "meta_table_uid": "asset-type-meta-table-uid",
            "storage_hash": asset_type_storage_hash,
            "contract_hash": markets_meta_table_contract_hash(AssetTypeTable),
        },
        {
            "namespace": "ms-markets",
            "identifier": "Asset",
            "meta_table_uid": "asset-meta-table-uid",
            "storage_hash": asset_storage_hash,
            "contract_hash": markets_meta_table_contract_hash(AssetTable),
        },
    ]

    monkeypatch.setattr(
        catalog,
        "bootstrap_catalog_table",
        lambda **_kwargs: _meta_table(
            "catalog-meta-table-uid",
            identifier="MarketsMetaTableCatalog",
            storage_hash="catalog-storage-hash",
        ),
    )

    def fake_search_model(_context, **kwargs):
        search_in_filters.append(dict(kwargs["in_filters"]))
        return {"rows": catalog_rows}

    monkeypatch.setattr(catalog, "search_model", fake_search_model)
    monkeypatch.setattr(
        catalog.MetaTable,
        "get_by_uid",
        staticmethod(lambda **_kwargs: pytest.fail("catalog attach should not fetch MetaTable")),
    )
    monkeypatch.setattr(
        catalog,
        "_resolve_platform_meta_table",
        lambda *_args, **_kwargs: pytest.fail("platform lookup should not run"),
    )
    monkeypatch.setattr(
        catalog,
        "upsert_model",
        lambda **_kwargs: pytest.fail("catalog row should not be rewritten"),
    )

    result = catalog.bootstrap_markets_meta_tables_from_catalog(
        models=[AssetTypeTable, AssetTable]
    )

    assert result.attached_count == 2
    assert result.registered_count == 0
    assert result.imported_count == 0
    assert search_in_filters == [
        {"storage_hash": [asset_type_storage_hash, asset_storage_hash]}
    ]
    assert result.registration.target_meta_table_uid_by_fullname == {
        markets_meta_table_fullname(AssetTypeTable): "asset-type-meta-table-uid",
        markets_meta_table_fullname(AssetTable): "asset-meta-table-uid",
    }


def test_catalog_bootstrap_rejects_catalog_contract_drift(monkeypatch) -> None:
    catalog_row = {
        "namespace": "ms-markets",
        "identifier": "Asset",
        "meta_table_uid": "asset-meta-table-uid",
        "storage_hash": AssetTable.__table__.name,
        "contract_hash": "stale-contract-hash",
    }

    monkeypatch.setattr(
        catalog,
        "bootstrap_catalog_table",
        lambda **_kwargs: _meta_table(
            "catalog-meta-table-uid",
            identifier="MarketsMetaTableCatalog",
            storage_hash="catalog-storage-hash",
        ),
    )
    monkeypatch.setattr(
        catalog,
        "search_model",
        lambda *_args, **_kwargs: {"rows": [catalog_row]},
    )

    with pytest.raises(catalog.CatalogBootstrapError, match="contract drift"):
        catalog.bootstrap_markets_meta_tables_from_catalog(models=[AssetTable])


def test_catalog_bootstrap_imports_pre_catalog_platform_table(monkeypatch) -> None:
    existing_meta_table = _meta_table(
        "asset-meta-table-uid",
        description="Imported asset catalog rows.",
    )
    upserted_rows: list[dict] = []

    monkeypatch.setattr(
        catalog,
        "bootstrap_catalog_table",
        lambda **_kwargs: _meta_table(
            "catalog-meta-table-uid",
            identifier="MarketsMetaTableCatalog",
            storage_hash="catalog-storage-hash",
        ),
    )
    monkeypatch.setattr(catalog, "search_model", lambda *_args, **_kwargs: {"rows": []})
    monkeypatch.setattr(
        catalog,
        "_resolve_platform_meta_table",
        lambda *_args, **_kwargs: existing_meta_table,
    )
    monkeypatch.setattr(
        AssetTable,
        "register",
        classmethod(lambda *_args, **_kwargs: pytest.fail("register should not run")),
    )

    def fake_upsert_model(_context, **kwargs):
        assert kwargs["conflict_columns"] == ["storage_hash"]
        upserted_rows.append(dict(kwargs["values"]))
        return {"rows": [kwargs["values"]]}

    monkeypatch.setattr(catalog, "upsert_model", fake_upsert_model)

    result = catalog.bootstrap_markets_meta_tables_from_catalog(models=[AssetTable])

    assert result.imported_count == 1
    assert result.registered_count == 0
    assert result.attached_count == 0
    assert upserted_rows[0]["meta_table_uid"] == "asset-meta-table-uid"
    assert upserted_rows[0]["description"] == "Imported asset catalog rows."


def test_catalog_bootstrap_converts_duplicate_registration_to_drift_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        catalog,
        "bootstrap_catalog_table",
        lambda **_kwargs: _meta_table(
            "catalog-meta-table-uid",
            identifier="MarketsMetaTableCatalog",
            storage_hash="catalog-storage-hash",
        ),
    )
    monkeypatch.setattr(catalog, "search_model", lambda *_args, **_kwargs: {"rows": []})
    monkeypatch.setattr(catalog, "_resolve_platform_meta_table", lambda *_args, **_kwargs: None)

    def fake_register(cls, **_kwargs):
        raise ConflictError(
            "duplicate",
            payload={
                "code": "duplicate_meta_table",
                "existing_meta_table_uid": "existing-meta-table-uid",
            },
        )

    monkeypatch.setattr(AssetTable, "register", classmethod(fake_register))

    with pytest.raises(catalog.CatalogBootstrapError, match="catalog drift"):
        catalog.bootstrap_markets_meta_tables_from_catalog(models=[AssetTable])


def test_bootstrap_catalog_table_attaches_existing_catalog(monkeypatch) -> None:
    existing_catalog = _meta_table(
        "catalog-meta-table-uid",
        identifier="MarketsMetaTableCatalog",
        storage_hash="catalog-storage-hash",
    )

    monkeypatch.setattr(
        catalog,
        "_resolve_platform_meta_table",
        lambda *_args, **_kwargs: existing_catalog,
    )
    monkeypatch.setattr(
        catalog.MarketsMetaTableCatalogTable,
        "register",
        classmethod(lambda *_args, **_kwargs: pytest.fail("catalog register should not run")),
    )

    assert catalog.bootstrap_catalog_table() is existing_catalog
