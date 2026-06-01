from __future__ import annotations

from types import SimpleNamespace

import pytest
from mainsequence.client.exceptions import ConflictError

import msm.maintenance.catalog as catalog
from msm.api.accounts import Account
from msm.data_nodes.storage import AccountHoldingsStorage
from msm.maintenance.models import (
    MarketsMetaTableCatalogTable,
    markets_meta_table_contract_hash,
)
from msm.models import AccountTable, AssetTable, AssetTypeTable
from msm.models.registration import markets_meta_table_identifier


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
        physical_table_name=storage_hash,
        management_mode="platform_managed",
    )


def _catalog_row_identity(model) -> dict[str, str]:
    return {
        "namespace": model.__metatable_namespace__,
        "identifier": model.__metatable_identifier__,
    }


def _catalog_search_filter(*models) -> dict[str, list[str]]:
    return {
        "identifier": sorted({model.__metatable_identifier__ for model in models}),
    }


def _disable_physical_contract_validation(monkeypatch) -> None:
    monkeypatch.setattr(
        catalog,
        "validate_platform_meta_table_physical_contract",
        lambda *_args, **_kwargs: None,
    )


def test_catalog_bootstrap_registers_missing_application_table(monkeypatch) -> None:
    asset_storage_hash = AssetTable.__table__.name
    registered_meta_table = _meta_table(
        "asset-meta-table-uid",
        **_catalog_row_identity(AssetTable),
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
        assert kwargs["conflict_columns"] == ["identifier"]
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
    assert (
        result.registration.meta_table_by_identifier[markets_meta_table_identifier(AssetTable)].uid
        == "asset-meta-table-uid"
    )
    assert search_in_filters == [_catalog_search_filter(AssetTable)]
    assert register_calls[0] == {"timeout": None}
    assert upserted_rows[0]["meta_table_uid"] == "asset-meta-table-uid"
    assert upserted_rows[0]["description"] == "Asset catalog rows."
    assert "storage_hash" not in upserted_rows[0]
    assert "management_mode" not in upserted_rows[0]
    assert "data_source_uid" not in upserted_rows[0]
    assert upserted_rows[0]["contract_hash"]


def test_rotate_catalogue_replaces_catalog_row_from_registered_row_model(monkeypatch) -> None:
    _disable_physical_contract_validation(monkeypatch)
    registered_meta_table = _meta_table(
        "account-meta-table-uid",
        **_catalog_row_identity(AccountTable),
        description="Account rows.",
        storage_hash=AccountTable.__table__.name,
    )
    existing_row = {
        **_catalog_row_identity(AccountTable),
        "description": "Old description.",
        "model_name": "AccountTable",
        "meta_table_uid": "account-meta-table-uid",
        "contract_hash": "stale-contract-hash",
        "sdk_version": "old",
    }
    register_calls: list[dict] = []
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

    def fake_search_model(_context, **kwargs):
        assert kwargs["in_filters"] == _catalog_search_filter(AccountTable)
        return {"rows": [existing_row]}

    def fake_register(cls, **kwargs):
        register_calls.append(kwargs)
        return registered_meta_table

    def fake_upsert_model(_context, **kwargs):
        assert kwargs["conflict_columns"] == ["identifier"]
        upserted_rows.append(dict(kwargs["values"]))
        return {"rows": [kwargs["values"]]}

    monkeypatch.setattr(catalog, "search_model", fake_search_model)
    monkeypatch.setattr(AccountTable, "register", classmethod(fake_register))
    monkeypatch.setattr(catalog, "upsert_model", fake_upsert_model)

    result = catalog.rotate_catalogue(Account)

    assert register_calls == [{}]
    assert result.identifier == AccountTable.__metatable_identifier__
    assert result.meta_table_uid == "account-meta-table-uid"
    assert result.old_contract_hash == "stale-contract-hash"
    assert result.new_contract_hash == markets_meta_table_contract_hash(AccountTable)
    assert result.changed is True
    assert upserted_rows[0]["identifier"] == AccountTable.__metatable_identifier__
    assert upserted_rows[0]["meta_table_uid"] == "account-meta-table-uid"
    assert upserted_rows[0]["contract_hash"] == markets_meta_table_contract_hash(AccountTable)


def test_catalog_bootstrap_attaches_cataloged_application_table(monkeypatch) -> None:
    _disable_physical_contract_validation(monkeypatch)
    asset_storage_hash = AssetTable.__table__.name
    search_in_filters: list[dict] = []
    catalog_row = {
        **_catalog_row_identity(AssetTable),
        "description": "Asset catalog rows.",
        "meta_table_uid": "asset-meta-table-uid",
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
        staticmethod(
            lambda **_kwargs: _meta_table(
                "asset-meta-table-uid",
                **_catalog_row_identity(AssetTable),
                description="Asset catalog rows.",
                storage_hash=asset_storage_hash,
            )
        ),
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
    assert search_in_filters == [_catalog_search_filter(AssetTable)]
    resolved = result.registration.meta_table_by_identifier[
        markets_meta_table_identifier(AssetTable)
    ]
    assert resolved.uid == "asset-meta-table-uid"
    assert resolved.storage_hash == asset_storage_hash
    assert resolved.physical_table_name == asset_storage_hash
    assert resolved.description == "Asset catalog rows."


def test_catalog_bootstrap_routes_cataloged_storage_table_through_register(
    monkeypatch,
) -> None:
    storage_hash = AccountHoldingsStorage.__table__.name
    catalog_row = {
        **_catalog_row_identity(AccountHoldingsStorage),
        "description": "Account holdings storage.",
        "meta_table_uid": "account-holdings-storage-uid",
        "contract_hash": markets_meta_table_contract_hash(AccountHoldingsStorage),
    }
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
    monkeypatch.setattr(catalog, "search_model", lambda *_args, **_kwargs: {"rows": [catalog_row]})
    monkeypatch.setattr(
        catalog,
        "_resolve_platform_meta_table",
        lambda *_args, **_kwargs: pytest.fail("storage attach should not use MetaTable lookup"),
    )
    monkeypatch.setattr(
        catalog,
        "upsert_model",
        lambda *_args, **_kwargs: pytest.fail("catalog row should not be rewritten"),
    )

    def fake_register(cls, **kwargs):
        register_calls.append(kwargs)
        return _meta_table(
            "account-holdings-storage-uid",
            **_catalog_row_identity(AccountHoldingsStorage),
            storage_hash=storage_hash,
        )

    monkeypatch.setattr(AccountHoldingsStorage, "register", classmethod(fake_register))

    result = catalog.bootstrap_markets_meta_tables_from_catalog(
        models=[AccountHoldingsStorage],
        data_source_uid="data-source-uid",
    )

    assert result.attached_count == 1
    assert result.registered_count == 0
    assert register_calls[0] == {"timeout": None}
    assert (
        result.registration.meta_table_by_identifier[
            markets_meta_table_identifier(AccountHoldingsStorage)
        ].uid
        == "account-holdings-storage-uid"
    )


def test_catalog_bootstrap_bulk_attaches_cataloged_tables(monkeypatch) -> None:
    _disable_physical_contract_validation(monkeypatch)
    search_in_filters: list[dict] = []
    catalog_rows = [
        {
            **_catalog_row_identity(AssetTypeTable),
            "meta_table_uid": "asset-type-meta-table-uid",
            "contract_hash": markets_meta_table_contract_hash(AssetTypeTable),
        },
        {
            **_catalog_row_identity(AssetTable),
            "meta_table_uid": "asset-meta-table-uid",
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

    attached_meta_tables = {
        "asset-type-meta-table-uid": _meta_table(
            "asset-type-meta-table-uid",
            **_catalog_row_identity(AssetTypeTable),
            storage_hash=AssetTypeTable.__table__.name,
        ),
        "asset-meta-table-uid": _meta_table(
            "asset-meta-table-uid",
            **_catalog_row_identity(AssetTable),
            storage_hash=AssetTable.__table__.name,
        ),
    }

    monkeypatch.setattr(catalog, "search_model", fake_search_model)
    monkeypatch.setattr(
        catalog.MetaTable,
        "get_by_uid",
        staticmethod(lambda uid, **_kwargs: attached_meta_tables[uid]),
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

    result = catalog.bootstrap_markets_meta_tables_from_catalog(models=[AssetTypeTable, AssetTable])

    assert result.attached_count == 2
    assert result.registered_count == 0
    assert result.imported_count == 0
    assert search_in_filters == [_catalog_search_filter(AssetTypeTable, AssetTable)]
    assert {
        identifier: meta_table.uid
        for identifier, meta_table in result.registration.meta_table_by_identifier.items()
    } == {
        markets_meta_table_identifier(AssetTypeTable): "asset-type-meta-table-uid",
        markets_meta_table_identifier(AssetTable): "asset-meta-table-uid",
    }


def test_catalog_bootstrap_rejects_catalog_contract_drift(monkeypatch) -> None:
    catalog_row = {
        **_catalog_row_identity(AssetTable),
        "meta_table_uid": "asset-meta-table-uid",
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
    _disable_physical_contract_validation(monkeypatch)
    existing_meta_table = _meta_table(
        "asset-meta-table-uid",
        **_catalog_row_identity(AssetTable),
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
        assert kwargs["conflict_columns"] == ["identifier"]
        upserted_rows.append(dict(kwargs["values"]))
        return {"rows": [kwargs["values"]]}

    monkeypatch.setattr(catalog, "upsert_model", fake_upsert_model)

    result = catalog.bootstrap_markets_meta_tables_from_catalog(models=[AssetTable])

    assert result.imported_count == 1
    assert result.registered_count == 0
    assert result.attached_count == 0
    assert upserted_rows[0]["meta_table_uid"] == "asset-meta-table-uid"
    assert upserted_rows[0]["description"] == "Imported asset catalog rows."


def test_catalog_bootstrap_registers_uncataloged_storage_table_without_platform_lookup(
    monkeypatch,
) -> None:
    storage_hash = AccountHoldingsStorage.__table__.name
    register_calls: list[dict] = []
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
        lambda *_args, **_kwargs: pytest.fail("storage bootstrap should go through register"),
    )

    def fake_register(cls, **kwargs):
        register_calls.append(kwargs)
        return _meta_table(
            "account-holdings-storage-uid",
            **_catalog_row_identity(AccountHoldingsStorage),
            storage_hash=storage_hash,
        )

    def fake_upsert_model(_context, **kwargs):
        upserted_rows.append(dict(kwargs["values"]))
        return {"rows": [kwargs["values"]]}

    monkeypatch.setattr(AccountHoldingsStorage, "register", classmethod(fake_register))
    monkeypatch.setattr(catalog, "upsert_model", fake_upsert_model)

    result = catalog.bootstrap_markets_meta_tables_from_catalog(
        models=[AccountHoldingsStorage],
        data_source_uid="data-source-uid",
    )

    assert result.registered_count == 1
    assert result.attached_count == 0
    assert register_calls[0] == {"timeout": None}
    assert upserted_rows[0]["meta_table_uid"] == "account-holdings-storage-uid"
    assert "storage_hash" not in upserted_rows[0]


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
    _disable_physical_contract_validation(monkeypatch)
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


class _IntrospectableMetaTable:
    management_mode = "platform_managed"

    def __init__(self, snapshot: dict) -> None:
        self._snapshot = snapshot

    def introspect(self, *, timeout=None):
        return {"introspection_snapshot": self._snapshot}


class _TopLevelIntrospectableMetaTable:
    management_mode = "platform_managed"

    def __init__(self, snapshot: dict) -> None:
        self._snapshot = snapshot

    def introspect(self, *, timeout=None):
        return {
            "introspection_snapshot": {},
            "columns": self._snapshot["columns"],
            "indexes_meta": self._snapshot["indexes"],
        }


def _physical_snapshot_for_model(model, *, include_indexes: bool = True) -> dict:
    return {
        "columns": [{"name": str(column.name)} for column in model.__table__.columns],
        "indexes": [
            {
                "name": str(index.name),
                "columns": [str(column.name) for column in index.columns],
                "unique": bool(index.unique),
            }
            for index in getattr(model.__table__, "indexes", set())
        ]
        if include_indexes
        else [],
    }


def test_platform_meta_table_physical_validation_accepts_expected_columns_and_indexes() -> None:
    meta_table = _IntrospectableMetaTable(
        _physical_snapshot_for_model(MarketsMetaTableCatalogTable)
    )

    catalog.validate_platform_meta_table_physical_contract(
        meta_table,
        model=MarketsMetaTableCatalogTable,
        timeout=7,
    )


def test_platform_meta_table_physical_validation_accepts_top_level_indexes_meta() -> None:
    meta_table = _TopLevelIntrospectableMetaTable(_physical_snapshot_for_model(AssetTypeTable))

    catalog.validate_platform_meta_table_physical_contract(
        meta_table,
        model=AssetTypeTable,
        timeout=7,
    )


def test_platform_meta_table_physical_validation_accepts_name_only_index_introspection() -> None:
    snapshot = _physical_snapshot_for_model(MarketsMetaTableCatalogTable)
    snapshot["indexes"] = [
        {
            "name": index["name"],
            "columns": [],
            "unique": False,
        }
        for index in snapshot["indexes"]
    ]
    meta_table = _IntrospectableMetaTable(snapshot)

    catalog.validate_platform_meta_table_physical_contract(
        meta_table,
        model=MarketsMetaTableCatalogTable,
        timeout=7,
    )


def test_platform_meta_table_physical_validation_rejects_stale_missing_indexes() -> None:
    meta_table = _IntrospectableMetaTable(
        _physical_snapshot_for_model(
            MarketsMetaTableCatalogTable,
            include_indexes=False,
        )
    )

    with pytest.raises(catalog.CatalogBootstrapError, match="stale physical storage"):
        catalog.validate_platform_meta_table_physical_contract(
            meta_table,
            model=MarketsMetaTableCatalogTable,
            timeout=7,
        )


def test_platform_meta_table_physical_validation_rejects_stale_extra_columns() -> None:
    snapshot = _physical_snapshot_for_model(MarketsMetaTableCatalogTable)
    snapshot["columns"].append({"name": "resource_type"})
    meta_table = _IntrospectableMetaTable(snapshot)

    with pytest.raises(catalog.CatalogBootstrapError, match="extra columns"):
        catalog.validate_platform_meta_table_physical_contract(
            meta_table,
            model=MarketsMetaTableCatalogTable,
            timeout=7,
        )


def test_platform_meta_table_physical_validation_rejects_stale_index_uniqueness() -> None:
    snapshot = _physical_snapshot_for_model(AssetTypeTable)
    asset_type_index = next(
        index for index in snapshot["indexes"] if index["columns"] == ["asset_type"]
    )
    asset_type_index["unique"] = False
    meta_table = _IntrospectableMetaTable(snapshot)

    with pytest.raises(catalog.CatalogBootstrapError, match="mismatched indexes"):
        catalog.validate_platform_meta_table_physical_contract(
            meta_table,
            model=AssetTypeTable,
            timeout=7,
        )


def test_platform_meta_table_physical_validation_rejects_stale_index_columns() -> None:
    snapshot = _physical_snapshot_for_model(AssetTypeTable)
    asset_type_index = next(
        index for index in snapshot["indexes"] if index["columns"] == ["asset_type"]
    )
    asset_type_index["columns"] = ["display_name"]
    meta_table = _IntrospectableMetaTable(snapshot)

    with pytest.raises(catalog.CatalogBootstrapError, match="mismatched indexes"):
        catalog.validate_platform_meta_table_physical_contract(
            meta_table,
            model=AssetTypeTable,
            timeout=7,
        )


def test_platform_meta_table_physical_validation_rejects_missing_snapshot() -> None:
    class EmptyResponseMetaTable:
        management_mode = "platform_managed"

        def introspect(self, *, timeout=None):
            return {}

    with pytest.raises(catalog.CatalogBootstrapError, match="no physical snapshot"):
        catalog.validate_platform_meta_table_physical_contract(
            EmptyResponseMetaTable(),
            model=MarketsMetaTableCatalogTable,
            timeout=7,
        )
