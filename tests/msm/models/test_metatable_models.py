from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from mainsequence.client.exceptions import ConflictError
from mainsequence.tdag.meta_tables import (
    PlatformManagedMetaTable,
    metatable_configured_tablename,
)

import msm.meta_tables as meta_tables
import msm.models as models
from msm.base import MarketsMetaTableMixin
from msm.meta_tables import build_markets_registration_requests, markets_meta_table_fullname
from msm.models import (
    AssetTypeTable,
    AssetTable,
    BondDetailsTable,
    CurrencySpotTable,
    FutureDetailsTable,
    IndexTable,
    IssuerTable,
    OpenFigiDetailsTable,
    markets_sqlalchemy_models,
)


def test_markets_models_use_platform_managed_table_mixin() -> None:
    table_names: dict[str, type] = {}

    for model in markets_sqlalchemy_models():
        assert issubclass(model, PlatformManagedMetaTable)
        assert "__tablename__" not in model.__dict__
        assert model.__table__.name == metatable_configured_tablename(model)
        assert model.__table__.name not in table_names
        table_names[model.__table__.name] = model


def test_default_namespace_keeps_bare_metatable_identifier() -> None:
    assert AssetTable.__markets_base_identifier__ == "Asset"
    assert AssetTable.__metatable_identifier__ == "Asset"
    assert AssetTable.metatable_identifier() == "Asset"


def test_non_default_namespace_prefixes_metatable_identifier() -> None:
    class ExampleNamespacedTable(MarketsMetaTableMixin):
        __abstract__ = True
        __metatable_namespace__ = "mainsequence.examples"
        __metatable_identifier__ = "Asset"

    assert ExampleNamespacedTable.__markets_base_identifier__ == "Asset"
    assert ExampleNamespacedTable.__metatable_identifier__ == "mainsequence.examples.Asset"
    assert ExampleNamespacedTable.metatable_identifier() == "mainsequence.examples.Asset"


def test_asset_model_does_not_store_arbitrary_metadata_json() -> None:
    assert "metadata_json" not in AssetTable.__table__.c


def test_asset_type_model_is_registry_table() -> None:
    assert AssetTypeTable.__markets_base_identifier__ == "AssetType"
    assert AssetTypeTable.__metatable_identifier__ == "AssetType"
    assert "asset_type" in AssetTypeTable.__table__.c
    assert "display_name" in AssetTypeTable.__table__.c
    assert "description" in AssetTypeTable.__table__.c
    assert "metadata_json" in AssetTypeTable.__table__.c
    assert any(
        index.unique and [column.name for column in index.columns] == ["asset_type"]
        for index in AssetTypeTable.__table__.indexes
    )


def test_index_model_is_reference_table() -> None:
    table = IndexTable.__table__

    assert IndexTable.__markets_base_identifier__ == "Index"
    assert IndexTable.__metatable_identifier__ == "Index"
    assert "uid" in table.c
    assert "unique_identifier" in table.c
    assert "display_name" in table.c
    assert "description" in table.c
    assert "provider" in table.c
    assert "metadata_json" in table.c
    assert any(
        index.unique and [column.name for column in index.columns] == ["unique_identifier"]
        for index in table.indexes
    )


def test_issuer_model_is_reference_table() -> None:
    table = IssuerTable.__table__

    assert IssuerTable.__markets_base_identifier__ == "Issuer"
    assert IssuerTable.__metatable_identifier__ == "Issuer"
    assert "uid" in table.c
    assert "unique_identifier" in table.c
    assert "display_name" in table.c
    assert "metadata_json" in table.c
    assert any(
        index.unique and [column.name for column in index.columns] == ["unique_identifier"]
        for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["display_name"]
        for index in table.indexes
    )


def test_asset_related_models_are_grouped_under_assets_package() -> None:
    from msm.models.assets import (
        AssetCategoryMembershipTable as PackageAssetCategoryMembershipTable,
        AssetCategoryTable as PackageAssetCategoryTable,
        AssetTable as PackageAssetTable,
        AssetTypeTable as PackageAssetTypeTable,
        BondDetailsTable as PackageBondDetailsTable,
        CurrencySpotTable as PackageCurrencySpotTable,
        OpenFigiDetailsTable as PackageOpenFigiDetailsTable,
    )
    from msm.models.assets.bonds import BondDetailsTable as BondsBondDetailsTable
    from msm.models.assets.categories import (
        AssetCategoryMembershipTable as CategoriesAssetCategoryMembershipTable,
        AssetCategoryTable as CategoriesAssetCategoryTable,
    )
    from msm.models.assets.core import AssetTable as CoreAssetTable
    from msm.models.assets.currency_spot import CurrencySpotTable as CurrencyAssetSpotTable
    from msm.models.assets.provider_details import (
        OpenFigiDetailsTable as ProviderOpenFigiDetailsTable,
    )
    from msm.models.assets.types import AssetTypeTable as TypesAssetTypeTable

    assert PackageAssetTable is AssetTable
    assert CoreAssetTable is AssetTable
    assert PackageAssetTypeTable is AssetTypeTable
    assert TypesAssetTypeTable is AssetTypeTable
    assert PackageCurrencySpotTable is CurrencySpotTable
    assert CurrencyAssetSpotTable is CurrencySpotTable
    assert PackageBondDetailsTable is BondDetailsTable
    assert BondsBondDetailsTable is BondDetailsTable
    assert PackageAssetCategoryTable is CategoriesAssetCategoryTable
    assert PackageAssetCategoryMembershipTable is CategoriesAssetCategoryMembershipTable
    assert PackageOpenFigiDetailsTable is OpenFigiDetailsTable
    assert ProviderOpenFigiDetailsTable is OpenFigiDetailsTable


def test_legacy_model_aliases_are_removed() -> None:
    assert not hasattr(models, "Asset")


def test_selected_metatable_models_resolve_in_dependency_order() -> None:
    models = meta_tables.resolve_markets_meta_table_models(
        ["AssetCategoryMembership", "Asset"],
    )

    assert models == [
        AssetTable,
        meta_tables.resolve_markets_meta_table_model("AssetCategoryMembership"),
    ]


def test_asset_type_resolves_before_asset_when_selected() -> None:
    models = meta_tables.resolve_markets_meta_table_models(["Asset", "AssetType"])

    assert models == [AssetTypeTable, AssetTable]


def test_currency_spot_resolves_after_asset_dependencies_when_selected() -> None:
    models = meta_tables.resolve_markets_meta_table_models(["CurrencySpot", "Asset", "AssetType"])

    assert models == [AssetTypeTable, AssetTable, CurrencySpotTable]


def test_future_details_resolves_after_asset_and_index_dependencies_when_selected() -> None:
    models = meta_tables.resolve_markets_meta_table_models(
        ["FutureDetails", "Index", "Asset", "AssetType"]
    )

    assert models == [AssetTypeTable, AssetTable, IndexTable, FutureDetailsTable]


def test_bond_details_resolves_after_asset_and_issuer_dependencies_when_selected() -> None:
    models = meta_tables.resolve_markets_meta_table_models(
        ["BondDetails", "Issuer", "Asset", "AssetType"]
    )

    assert models == [AssetTypeTable, AssetTable, IssuerTable, BondDetailsTable]


def test_openfigi_details_uses_asset_uid_as_one_to_one_primary_key() -> None:
    table = OpenFigiDetailsTable.__table__

    assert "uid" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["asset_uid"]
    assert table.c.asset_uid.foreign_keys
    foreign_key = next(iter(table.c.asset_uid.foreign_keys))
    assert foreign_key.column is AssetTable.__table__.c.uid


def test_currency_spot_uses_asset_uid_as_one_to_one_primary_key() -> None:
    table = CurrencySpotTable.__table__

    assert "uid" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["asset_uid"]
    assert any(
        index.unique
        and [column.name for column in index.columns] == [
            "base_currency_uid",
            "quote_currency_uid",
        ]
        for index in table.indexes
    )

    asset_uid_fk = next(iter(table.c.asset_uid.foreign_keys))
    base_currency_uid_fk = next(iter(table.c.base_currency_uid.foreign_keys))
    quote_currency_uid_fk = next(iter(table.c.quote_currency_uid.foreign_keys))

    assert asset_uid_fk.column is AssetTable.__table__.c.uid
    assert asset_uid_fk.ondelete == "CASCADE"
    assert base_currency_uid_fk.column is AssetTable.__table__.c.uid
    assert base_currency_uid_fk.ondelete == "RESTRICT"
    assert quote_currency_uid_fk.column is AssetTable.__table__.c.uid
    assert quote_currency_uid_fk.ondelete == "RESTRICT"


def test_future_details_uses_asset_uid_as_one_to_one_primary_key() -> None:
    table = FutureDetailsTable.__table__

    assert "uid" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["asset_uid"]
    assert set(table.c.keys()) == {
        "asset_uid",
        "kind",
        "underlying_index_uid",
        "quote_unit",
        "settlement_asset",
        "margin_asset",
        "settlement_model",
        "settlement_method",
        "contract_size",
        "contract_unit",
        "expires_at",
        "settles_at",
        "metadata",
    }

    asset_uid_fk = next(iter(table.c.asset_uid.foreign_keys))
    underlying_index_uid_fk = next(iter(table.c.underlying_index_uid.foreign_keys))
    settlement_asset_fk = next(iter(table.c.settlement_asset.foreign_keys))
    margin_asset_fk = next(iter(table.c.margin_asset.foreign_keys))

    assert asset_uid_fk.column is AssetTable.__table__.c.uid
    assert asset_uid_fk.ondelete == "CASCADE"
    assert underlying_index_uid_fk.column is IndexTable.__table__.c.uid
    assert underlying_index_uid_fk.ondelete == "RESTRICT"
    assert settlement_asset_fk.column is AssetTable.__table__.c.uid
    assert settlement_asset_fk.ondelete == "RESTRICT"
    assert margin_asset_fk.column is AssetTable.__table__.c.uid
    assert margin_asset_fk.ondelete == "RESTRICT"
    assert "metadata_payload" not in table.c
    assert any(
        [column.name for column in index.columns] == ["underlying_index_uid"]
        for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["settlement_asset"]
        for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["margin_asset"]
        for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["expires_at"]
        for index in table.indexes
    )


def test_bond_details_uses_asset_uid_as_one_to_one_primary_key() -> None:
    table = BondDetailsTable.__table__

    assert "uid" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["asset_uid"]
    assert set(table.c.keys()) == {
        "asset_uid",
        "issuer_uid",
        "currency_asset_uid",
        "issue_date",
        "maturity_date",
        "status",
    }

    asset_uid_fk = next(iter(table.c.asset_uid.foreign_keys))
    issuer_uid_fk = next(iter(table.c.issuer_uid.foreign_keys))
    currency_asset_uid_fk = next(iter(table.c.currency_asset_uid.foreign_keys))

    assert asset_uid_fk.column is AssetTable.__table__.c.uid
    assert asset_uid_fk.ondelete == "CASCADE"
    assert issuer_uid_fk.column is IssuerTable.__table__.c.uid
    assert issuer_uid_fk.ondelete == "RESTRICT"
    assert currency_asset_uid_fk.column is AssetTable.__table__.c.uid
    assert currency_asset_uid_fk.ondelete == "RESTRICT"
    assert any(
        [column.name for column in index.columns] == ["issuer_uid"]
        for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["currency_asset_uid"]
        for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["status"]
        for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["maturity_date"]
        for index in table.indexes
    )


def test_markets_models_build_platform_registration_requests_in_dependency_order() -> None:
    target_meta_table_uid_by_fullname: dict[str, str] = {}
    requests = []

    for model in markets_sqlalchemy_models():
        request = build_markets_registration_requests(
            data_source_uid=str(uuid.uuid4()),
            models=[model],
            target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
        )[0]
        requests.append(request)
        target_meta_table_uid_by_fullname[markets_meta_table_fullname(model)] = str(uuid.uuid4())

    assert AssetTypeTable in markets_sqlalchemy_models()
    assert requests
    assert all(request.management_mode == "platform_managed" for request in requests)
    assert all(
        request.storage_hash == request.table_contract.physical.table_name for request in requests
    )


def test_markets_models_build_external_registration_requests_in_dependency_order() -> None:
    target_meta_table_uid_by_fullname: dict[str, str] = {}
    requests = []

    for model in markets_sqlalchemy_models():
        request = build_markets_registration_requests(
            data_source_uid=str(uuid.uuid4()),
            management_mode="external_registered",
            models=[model],
            target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
        )[0]
        requests.append(request)
        target_meta_table_uid_by_fullname[markets_meta_table_fullname(model)] = str(uuid.uuid4())

    assert requests
    assert all(request.management_mode == "external_registered" for request in requests)


def test_register_markets_meta_tables_logs_each_table(monkeypatch) -> None:
    class SpyLogger:
        def __init__(self) -> None:
            self.events = []

        def info(self, event: str, **kwargs) -> None:
            self.events.append((event, kwargs))

    class FakeModel:
        __metatable_namespace__ = "mainsequence.test"
        __metatable_identifier__ = "FakeModel"
        __table__ = SimpleNamespace(fullname="public.fake_asset", name="fake_asset")

        @classmethod
        def register(cls, **_kwargs):
            return SimpleNamespace(uid="fake-meta-table-uid")

    spy_logger = SpyLogger()
    monkeypatch.setattr(meta_tables, "logger", spy_logger)

    result = meta_tables.register_markets_meta_tables(
        data_source_uid="data-source-uid",
        models=[FakeModel],
    )

    assert result.target_meta_table_uid_by_fullname == {"public.fake_asset": "fake-meta-table-uid"}
    assert result.models == [FakeModel]
    assert result.meta_table_by_fullname["public.fake_asset"].uid == "fake-meta-table-uid"
    assert [event for event, _kwargs in spy_logger.events] == [
        "Registering markets MetaTable schema",
        "Registered markets MetaTable schema",
    ]
    registering_event = spy_logger.events[0][1]
    assert registering_event["model"] == "FakeModel"
    assert registering_event["namespace"] == "mainsequence.test"
    assert registering_event["identifier"] == "FakeModel"
    assert registering_event["model_index"] == 1
    assert registering_event["model_count"] == 1
    assert registering_event["table_fullname"] == "public.fake_asset"
    registered_event = spy_logger.events[1][1]
    assert registered_event["meta_table_uid"] == "fake-meta-table-uid"


def test_register_markets_meta_tables_reuses_duplicate_physical_table_conflict(
    monkeypatch,
) -> None:
    class FakeModel:
        __metatable_namespace__ = "mainsequence.examples"
        __metatable_identifier__ = "FakeModel"
        __table__ = SimpleNamespace(
            fullname="public.fake_asset",
            name="fake_asset",
        )

        @classmethod
        def register(cls, **_kwargs):
            raise ConflictError(
                "duplicate",
                payload={
                    "code": "duplicate_meta_table",
                    "existing_meta_table_uid": "existing-meta-table-uid",
                    "storage_hash": "fake_asset",
                    "physical_table_name": "fake_asset",
                    "data_source_uid": "data-source-uid",
                },
            )

    monkeypatch.setattr(
        meta_tables.MetaTable,
        "get_by_uid",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("not visible")),
    )

    result = meta_tables.register_markets_meta_tables(
        data_source_uid="data-source-uid",
        models=[FakeModel],
    )

    meta_table = result.meta_table_by_fullname["public.fake_asset"]
    assert result.target_meta_table_uid_by_fullname == {
        "public.fake_asset": "existing-meta-table-uid"
    }
    assert meta_table.uid == "existing-meta-table-uid"
    assert meta_table.physical_table_name == "fake_asset"
    assert meta_table.storage_hash == "fake_asset"


def test_resolve_registered_markets_meta_tables_filters_by_logical_identity(monkeypatch) -> None:
    calls = []
    meta_table = SimpleNamespace(
        uid="fake-meta-table-uid",
        namespace="mainsequence.markets",
        identifier="FakeModel",
    )

    class FakeModel:
        __metatable_namespace__ = "mainsequence.markets"
        __metatable_identifier__ = "FakeModel"
        __table__ = SimpleNamespace(
            fullname="public.fake_asset",
            name="fake_storage_hash",
        )

    def fake_filter(**kwargs):
        calls.append(kwargs)
        return [meta_table]

    monkeypatch.setattr(meta_tables.MetaTable, "filter", fake_filter)

    result = meta_tables.resolve_registered_markets_meta_tables(
        data_source_uid="data-source-uid",
        models=[FakeModel],
    )

    assert result.target_meta_table_uid_by_fullname == {"public.fake_asset": "fake-meta-table-uid"}
    assert result.meta_table_by_fullname["public.fake_asset"] is meta_table
    assert calls == [
        {
            "timeout": None,
            "physical_table_name": "fake_storage_hash",
            "identifier": "FakeModel",
            "namespace": "mainsequence.markets",
            "management_mode": "platform_managed",
            "data_source__uid": "data-source-uid",
        }
    ]


def test_resolve_registered_markets_meta_tables_rejects_missing_table(monkeypatch) -> None:
    class FakeModel:
        __metatable_namespace__ = "mainsequence.markets"
        __metatable_identifier__ = "FakeModel"
        __table__ = SimpleNamespace(
            fullname="public.fake_asset",
            name="fake_storage_hash",
        )

    monkeypatch.setattr(meta_tables.MetaTable, "filter", lambda **_kwargs: [])

    with pytest.raises(LookupError, match="Could not resolve registered"):
        meta_tables.resolve_registered_markets_meta_tables(models=[FakeModel])
