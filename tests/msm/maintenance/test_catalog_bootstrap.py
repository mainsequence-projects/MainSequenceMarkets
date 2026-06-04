from __future__ import annotations

from types import SimpleNamespace

import pytest
from mainsequence.client.metatables import TimeIndexMetaTable

import msm.maintenance.catalog as catalog
from msm.data_nodes.storage import AccountHoldingsStorage
from msm.maintenance.models import MarketsMetaTableCatalogTable
from msm.models import AssetTable, AssetTypeTable


def _meta_table(
    uid: str,
    *,
    namespace: str = "ms-markets",
    identifier: str = "Asset",
    description: str | None = None,
    storage_hash: str = "asset-storage-hash",
    data_source_uid: str = "test-data-source-uid",
):
    return SimpleNamespace(
        uid=uid,
        namespace=namespace,
        identifier=identifier,
        description=description,
        data_source_uid=data_source_uid,
        storage_hash=storage_hash,
        physical_table_name=storage_hash,
        management_mode="platform_managed",
    )


def _time_index_meta_table(
    uid: str,
    *,
    namespace: str,
    identifier: str,
    storage_hash: str,
    description: str | None = None,
    data_source_uid: str = "test-data-source-uid",
) -> TimeIndexMetaTable:
    return TimeIndexMetaTable(
        uid=uid,
        namespace=namespace,
        identifier=identifier,
        description=description,
        data_source_uid=data_source_uid,
        storage_hash=storage_hash,
        physical_table_name=storage_hash,
        management_mode="platform_managed",
    )


def _catalog_row_identity(model) -> dict[str, str]:
    return {
        "namespace": model.__metatable_namespace__,
        "table_name": model.__table__.name,
    }


def _meta_table_identity(model) -> dict[str, str]:
    return {
        "namespace": model.__metatable_namespace__,
        "identifier": model.__table__.name,
    }


def _catalog_search_filter(*models) -> dict[str, list[str]]:
    return {
        "table_name": sorted({model.__table__.name for model in models}),
    }


def _catalog_row(model, *, meta_table_uid: str) -> dict[str, str]:
    return {
        **_catalog_row_identity(model),
        "description": getattr(model, "__metatable_description__", None) or "",
        "model_name": model.__name__,
        "meta_table_uid": meta_table_uid,
        "sdk_version": "test",
    }


def test_resolve_catalog_table_attaches_existing_catalog(monkeypatch) -> None:
    existing_catalog = _meta_table(
        "catalog-meta-table-uid",
        identifier=MarketsMetaTableCatalogTable.__table__.name,
        storage_hash=MarketsMetaTableCatalogTable.__table__.name,
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

    assert catalog.resolve_catalog_table() is existing_catalog


def test_resolve_catalog_table_rejects_missing_catalog(monkeypatch) -> None:
    monkeypatch.setattr(catalog, "_resolve_platform_meta_table", lambda *_args, **_kwargs: None)

    with pytest.raises(catalog.CatalogBootstrapError, match="not initialized"):
        catalog.resolve_catalog_table()


def test_catalog_attach_attaches_cataloged_application_table(monkeypatch) -> None:
    asset_storage_hash = AssetTable.__table__.name
    search_in_filters: list[dict] = []
    filter_calls: list[dict] = []
    catalog_meta_table = _meta_table(
        "catalog-meta-table-uid",
        identifier=MarketsMetaTableCatalogTable.__table__.name,
        storage_hash=MarketsMetaTableCatalogTable.__table__.name,
    )
    catalog_row = _catalog_row(AssetTable, meta_table_uid="asset-meta-table-uid")
    asset_meta_table = _meta_table(
        "asset-meta-table-uid",
        **_meta_table_identity(AssetTable),
        description="Asset catalog rows.",
        storage_hash=asset_storage_hash,
    )

    monkeypatch.setattr(catalog, "resolve_catalog_table", lambda **_kwargs: catalog_meta_table)

    def fake_search_model(_context, **kwargs):
        search_in_filters.append(dict(kwargs["in_filters"]))
        return {"rows": [catalog_row]}

    monkeypatch.setattr(catalog, "search_model", fake_search_model)

    def fake_filter(**kwargs):
        filter_calls.append(dict(kwargs))
        return [asset_meta_table]

    monkeypatch.setattr(
        catalog.MetaTable,
        "filter",
        staticmethod(fake_filter),
    )
    monkeypatch.setattr(
        catalog.MetaTable,
        "get_by_uid",
        staticmethod(lambda **_kwargs: pytest.fail("get_by_uid should not run")),
    )
    monkeypatch.setattr(
        AssetTable,
        "register",
        classmethod(lambda *_args, **_kwargs: pytest.fail("register should not run")),
    )
    monkeypatch.setattr(
        catalog,
        "upsert_model",
        lambda *_args, **_kwargs: pytest.fail("catalog row should not be rewritten"),
    )

    result = catalog.attach_markets_meta_tables_from_catalog(models=[AssetTable])

    assert result.attached_count == 1
    assert result.registered_count == 0
    assert result.imported_count == 0
    assert search_in_filters == [_catalog_search_filter(AssetTable)]
    assert filter_calls == [
        {
            "timeout": None,
            "uid__in": ["asset-meta-table-uid"],
            "management_mode": "platform_managed",
        }
    ]
    resolved = result.registration.meta_table_by_identifier[AssetTable.__table__.name]
    assert resolved.uid == "asset-meta-table-uid"
    assert resolved.storage_hash == asset_storage_hash
    assert resolved.physical_table_name == asset_storage_hash


def test_catalog_attach_bulk_attaches_cataloged_tables(monkeypatch) -> None:
    search_in_filters: list[dict] = []
    filter_calls: list[dict] = []
    catalog_meta_table = _meta_table(
        "catalog-meta-table-uid",
        identifier=MarketsMetaTableCatalogTable.__table__.name,
        storage_hash=MarketsMetaTableCatalogTable.__table__.name,
    )
    catalog_rows = [
        _catalog_row(AssetTypeTable, meta_table_uid="asset-type-meta-table-uid"),
        _catalog_row(AssetTable, meta_table_uid="asset-meta-table-uid"),
    ]
    attached_meta_tables = {
        "asset-type-meta-table-uid": _meta_table(
            "asset-type-meta-table-uid",
            **_meta_table_identity(AssetTypeTable),
            storage_hash=AssetTypeTable.__table__.name,
        ),
        "asset-meta-table-uid": _meta_table(
            "asset-meta-table-uid",
            **_meta_table_identity(AssetTable),
            storage_hash=AssetTable.__table__.name,
        ),
    }

    monkeypatch.setattr(catalog, "resolve_catalog_table", lambda **_kwargs: catalog_meta_table)

    def fake_search_model(_context, **kwargs):
        search_in_filters.append(dict(kwargs["in_filters"]))
        return {"rows": catalog_rows}

    monkeypatch.setattr(catalog, "search_model", fake_search_model)

    def fake_filter(**kwargs):
        filter_calls.append(dict(kwargs))
        return [attached_meta_tables[uid] for uid in kwargs["uid__in"]]

    monkeypatch.setattr(
        catalog.MetaTable,
        "filter",
        staticmethod(fake_filter),
    )
    monkeypatch.setattr(
        catalog.MetaTable,
        "get_by_uid",
        staticmethod(lambda **_kwargs: pytest.fail("get_by_uid should not run")),
    )
    monkeypatch.setattr(
        catalog,
        "upsert_model",
        lambda *_args, **_kwargs: pytest.fail("catalog row should not be rewritten"),
    )

    result = catalog.attach_markets_meta_tables_from_catalog(models=[AssetTypeTable, AssetTable])

    assert result.attached_count == 2
    assert result.registered_count == 0
    assert result.imported_count == 0
    assert search_in_filters == [_catalog_search_filter(AssetTypeTable, AssetTable)]
    assert filter_calls == [
        {
            "timeout": None,
            "uid__in": [
                "asset-type-meta-table-uid",
                "asset-meta-table-uid",
            ],
            "management_mode": "platform_managed",
        }
    ]
    assert {
        identifier: meta_table.uid
        for identifier, meta_table in result.registration.meta_table_by_identifier.items()
    } == {
        AssetTypeTable.__table__.name: "asset-type-meta-table-uid",
        AssetTable.__table__.name: "asset-meta-table-uid",
    }


def test_catalog_attach_resolves_time_index_storage_with_time_index_metadata(
    monkeypatch,
) -> None:
    search_in_filters: list[dict] = []
    meta_table_filter_calls: list[dict] = []
    time_index_filter_calls: list[dict] = []
    catalog_meta_table = _meta_table(
        "catalog-meta-table-uid",
        identifier=MarketsMetaTableCatalogTable.__table__.name,
        storage_hash=MarketsMetaTableCatalogTable.__table__.name,
    )
    catalog_rows = [
        _catalog_row(AssetTable, meta_table_uid="asset-meta-table-uid"),
        _catalog_row(
            AccountHoldingsStorage,
            meta_table_uid="account-holdings-storage-meta-table-uid",
        ),
    ]
    asset_meta_table = _meta_table(
        "asset-meta-table-uid",
        **_meta_table_identity(AssetTable),
        storage_hash=AssetTable.__table__.name,
    )
    account_holdings_meta_table = _time_index_meta_table(
        "account-holdings-storage-meta-table-uid",
        **_meta_table_identity(AccountHoldingsStorage),
        storage_hash=AccountHoldingsStorage.__table__.name,
    )

    monkeypatch.setattr(catalog, "resolve_catalog_table", lambda **_kwargs: catalog_meta_table)

    def fake_search_model(_context, **kwargs):
        search_in_filters.append(dict(kwargs["in_filters"]))
        return {"rows": catalog_rows}

    monkeypatch.setattr(catalog, "search_model", fake_search_model)

    def fake_meta_table_filter(**kwargs):
        meta_table_filter_calls.append(dict(kwargs))
        return [asset_meta_table]

    def fake_time_index_filter(**kwargs):
        time_index_filter_calls.append(dict(kwargs))
        return [account_holdings_meta_table]

    monkeypatch.setattr(catalog.MetaTable, "filter", staticmethod(fake_meta_table_filter))
    monkeypatch.setattr(
        catalog.TimeIndexMetaTable,
        "filter",
        staticmethod(fake_time_index_filter),
    )

    result = catalog.attach_markets_meta_tables_from_catalog(
        models=[AssetTable, AccountHoldingsStorage]
    )

    assert result.attached_count == 2
    assert search_in_filters == [_catalog_search_filter(AssetTable, AccountHoldingsStorage)]
    assert meta_table_filter_calls == [
        {
            "timeout": None,
            "uid__in": ["asset-meta-table-uid"],
            "management_mode": "platform_managed",
        }
    ]
    assert time_index_filter_calls == [
        {
            "timeout": None,
            "uid__in": ["account-holdings-storage-meta-table-uid"],
        }
    ]
    assert (
        result.registration.meta_table_by_identifier[AccountHoldingsStorage.__table__.name]
        is account_holdings_meta_table
    )
    assert AccountHoldingsStorage.get_time_index_metadata() is account_holdings_meta_table


def test_catalog_attach_rejects_missing_catalog_row(monkeypatch) -> None:
    catalog_meta_table = _meta_table(
        "catalog-meta-table-uid",
        identifier=MarketsMetaTableCatalogTable.__table__.name,
        storage_hash=MarketsMetaTableCatalogTable.__table__.name,
    )

    monkeypatch.setattr(catalog, "resolve_catalog_table", lambda **_kwargs: catalog_meta_table)
    monkeypatch.setattr(catalog, "search_model", lambda *_args, **_kwargs: {"rows": []})
    monkeypatch.setattr(
        AssetTable,
        "register",
        classmethod(lambda *_args, **_kwargs: pytest.fail("register should not run")),
    )

    with pytest.raises(catalog.CatalogBootstrapError, match="missing finalized rows"):
        catalog.attach_markets_meta_tables_from_catalog(models=[AssetTable])


def test_catalog_attach_uses_pointer_catalog_only(monkeypatch) -> None:
    catalog_meta_table = _meta_table(
        "catalog-meta-table-uid",
        identifier=MarketsMetaTableCatalogTable.__table__.name,
        storage_hash=MarketsMetaTableCatalogTable.__table__.name,
    )
    catalog_row = _catalog_row(AssetTable, meta_table_uid="asset-meta-table-uid")
    asset_meta_table = _meta_table(
        "asset-meta-table-uid",
        **_meta_table_identity(AssetTable),
        storage_hash=AssetTable.__table__.name,
    )

    monkeypatch.setattr(catalog, "resolve_catalog_table", lambda **_kwargs: catalog_meta_table)
    monkeypatch.setattr(catalog, "search_model", lambda *_args, **_kwargs: {"rows": [catalog_row]})
    monkeypatch.setattr(
        catalog.MetaTable,
        "filter",
        staticmethod(lambda **_kwargs: [asset_meta_table]),
    )

    result = catalog.attach_markets_meta_tables_from_catalog(models=[AssetTable])

    assert result.attached_count == 1
    assert (
        result.registration.meta_table_by_identifier[AssetTable.__table__.name] is asset_meta_table
    )


def test_resolve_catalog_meta_tables_rejects_stale_catalog_uid(monkeypatch) -> None:
    catalog_row = _catalog_row(AssetTable, meta_table_uid="dead-asset-meta-table-uid")
    plan = catalog._CatalogBootstrapModelPlan(
        model=AssetTable,
        namespace=AssetTable.__metatable_namespace__,
        table_name=AssetTable.__table__.name,
    )
    monkeypatch.setattr(
        catalog.MetaTable,
        "filter",
        staticmethod(lambda **_kwargs: []),
    )
    monkeypatch.setattr(
        catalog.MetaTable,
        "get_by_uid",
        staticmethod(lambda **_kwargs: pytest.fail("get_by_uid should not run")),
    )

    with pytest.raises(catalog.CatalogStaleMetaTableUidError, match="missing backend MetaTables"):
        catalog.resolve_catalog_meta_tables(
            {AssetTable.__table__.name: catalog_row},
            model_plans=[plan],
            management_mode="platform_managed",
        )
