from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from mainsequence.client.exceptions import ConflictError
from mainsequence.meta_tables import (
    PlatformManagedMetaTable,
    metatable_configured_tablename,
)

import msm.models.registration as meta_tables
import msm.models as models
from msm.base import MarketsMetaTableMixin, markets_table_storage_name
from msm.data_nodes.storage import AccountHoldingsStorage
from msm.maintenance.models import MarketsMetaTableCatalogTable
from msm.models.registration import (
    build_markets_registration_requests,
    is_time_index_meta_table_model,
    markets_meta_table_identifier,
)
from msm.models import (
    AssetTypeTable,
    AssetTable,
    BondAssetDetailsTable,
    CurrencySpotAssetDetailsTable,
    FutureAssetDetailsTable,
    IndexTable,
    IndexTypeTable,
    IssuerTable,
    OpenFigiAssetDetailsTable,
    markets_sqlalchemy_models,
)


def _install_fake_session_data_source(monkeypatch) -> None:
    from mainsequence.client import models_metatables

    monkeypatch.setattr(
        models_metatables,
        "get_session_data_source",
        lambda: SimpleNamespace(
            uid=str(uuid.uuid4()),
            related_resource=SimpleNamespace(status="AVAILABLE"),
        ),
    )


def test_markets_models_use_platform_managed_table_mixin() -> None:
    table_names: dict[str, type] = {}

    for model in markets_sqlalchemy_models():
        assert issubclass(model, PlatformManagedMetaTable)
        assert "__tablename__" not in model.__dict__
        assert model.__table__.name == metatable_configured_tablename(model)
        assert model.__table__.name not in table_names
        table_names[model.__table__.name] = model


def test_markets_models_declare_metatable_descriptions() -> None:
    for model in [MarketsMetaTableCatalogTable, *markets_sqlalchemy_models()]:
        description = getattr(model, "__metatable_description__", None)

        assert isinstance(description, str), model.__name__
        assert description.strip() == description
        assert len(description.split()) >= 8, model.__name__
        if is_time_index_meta_table_model(model):
            assert "keyed by" in description.lower(), model.__name__


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


def test_markets_metatable_identifier_survives_sdk_physical_binding(monkeypatch) -> None:
    table = AssetTypeTable.__table__
    identifier = markets_meta_table_identifier(AssetTypeTable)
    storage_name = str(table.name)

    monkeypatch.setitem(table.info, "identifier", identifier)
    monkeypatch.setattr(AssetTypeTable, "__metatable_storage_hash__", storage_name)
    monkeypatch.setattr(table, "_mainsequence_storage_hash", storage_name, raising=False)
    monkeypatch.setitem(table.info, "mainsequence_storage_hash", storage_name)
    monkeypatch.setattr(table, "name", "backend_physical_asset_type")
    monkeypatch.setattr(table, "fullname", "public.backend_physical_asset_type", raising=False)

    assert str(table.fullname) != identifier
    assert markets_meta_table_identifier(AssetTypeTable) == identifier
    assert markets_table_storage_name(AssetTypeTable) == storage_name


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
    removed_constant_name_field = "legacy_" + "constant_name"

    assert IndexTable.__markets_base_identifier__ == "Index"
    assert IndexTable.__metatable_identifier__ == "Index"
    assert "uid" in table.c
    assert "unique_identifier" in table.c
    assert "index_type" in table.c
    assert table.c.index_type.nullable is False
    assert "display_name" in table.c
    assert "description" in table.c
    assert "provider" in table.c
    assert "metadata_json" in table.c
    assert removed_constant_name_field not in table.c
    assert not hasattr(IndexTable, removed_constant_name_field)
    assert any(
        index.unique and [column.name for column in index.columns] == ["unique_identifier"]
        for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["index_type"] for index in table.indexes
    )


def test_index_type_model_is_registry_table() -> None:
    table = IndexTypeTable.__table__

    assert IndexTypeTable.__markets_base_identifier__ == "IndexType"
    assert IndexTypeTable.__metatable_identifier__ == "IndexType"
    assert "uid" in table.c
    assert "index_type" in table.c
    assert "display_name" in table.c
    assert "description" in table.c
    assert "metadata_json" in table.c
    assert any(
        index.unique and [column.name for column in index.columns] == ["index_type"]
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
        [column.name for column in index.columns] == ["display_name"] for index in table.indexes
    )


def test_asset_related_models_are_grouped_under_assets_package() -> None:
    from msm.models.assets import (
        AssetCategoryMembershipTable as PackageAssetCategoryMembershipTable,
        AssetCategoryTable as PackageAssetCategoryTable,
        AssetTable as PackageAssetTable,
        AssetTypeTable as PackageAssetTypeTable,
        BondAssetDetailsTable as PackageBondAssetDetailsTable,
        CurrencySpotAssetDetailsTable as PackageCurrencySpotAssetDetailsTable,
        OpenFigiAssetDetailsTable as PackageOpenFigiAssetDetailsTable,
    )
    from msm.models.assets.bonds import BondAssetDetailsTable as BondsBondAssetDetailsTable
    from msm.models.assets.categories import (
        AssetCategoryMembershipTable as CategoriesAssetCategoryMembershipTable,
        AssetCategoryTable as CategoriesAssetCategoryTable,
    )
    from msm.models.assets.core import AssetTable as CoreAssetTable
    from msm.models.assets.currency_spot import (
        CurrencySpotAssetDetailsTable as CurrencyAssetSpotTable,
    )
    from msm.models.assets.provider_details import (
        OpenFigiAssetDetailsTable as ProviderOpenFigiAssetDetailsTable,
    )
    from msm.models.assets.types import AssetTypeTable as TypesAssetTypeTable

    assert PackageAssetTable is AssetTable
    assert CoreAssetTable is AssetTable
    assert PackageAssetTypeTable is AssetTypeTable
    assert TypesAssetTypeTable is AssetTypeTable
    assert PackageCurrencySpotAssetDetailsTable is CurrencySpotAssetDetailsTable
    assert CurrencyAssetSpotTable is CurrencySpotAssetDetailsTable
    assert PackageBondAssetDetailsTable is BondAssetDetailsTable
    assert BondsBondAssetDetailsTable is BondAssetDetailsTable
    assert PackageAssetCategoryTable is CategoriesAssetCategoryTable
    assert PackageAssetCategoryMembershipTable is CategoriesAssetCategoryMembershipTable
    assert PackageOpenFigiAssetDetailsTable is OpenFigiAssetDetailsTable
    assert ProviderOpenFigiAssetDetailsTable is OpenFigiAssetDetailsTable


def test_legacy_model_aliases_are_removed() -> None:
    assert not hasattr(models, "Asset")


def test_legacy_root_metatable_registration_module_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        __import__("msm.meta_tables")


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


def test_index_type_resolves_before_index_when_selected() -> None:
    models = meta_tables.resolve_markets_meta_table_models(["Index", "IndexType"])

    assert models == [IndexTypeTable, IndexTable]


def test_currency_spot_resolves_after_asset_dependencies_when_selected() -> None:
    models = meta_tables.resolve_markets_meta_table_models(
        ["CurrencySpotAssetDetails", "Asset", "AssetType"]
    )

    assert models == [AssetTypeTable, AssetTable, CurrencySpotAssetDetailsTable]


def test_future_asset_details_resolves_after_asset_and_index_dependencies_when_selected() -> None:
    models = meta_tables.resolve_markets_meta_table_models(
        ["FutureAssetDetails", "Index", "IndexType", "Asset", "AssetType"]
    )

    assert models == [
        AssetTypeTable,
        AssetTable,
        IndexTypeTable,
        IndexTable,
        FutureAssetDetailsTable,
    ]


def test_bond_asset_details_resolves_after_asset_and_issuer_dependencies_when_selected() -> None:
    models = meta_tables.resolve_markets_meta_table_models(
        ["BondAssetDetails", "Issuer", "Asset", "AssetType"]
    )

    assert models == [AssetTypeTable, AssetTable, IssuerTable, BondAssetDetailsTable]


def test_openfigi_asset_details_uses_asset_uid_as_one_to_one_primary_key() -> None:
    table = OpenFigiAssetDetailsTable.__table__

    assert "uid" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["asset_uid"]
    assert table.c.asset_uid.foreign_keys
    foreign_key = next(iter(table.c.asset_uid.foreign_keys))
    assert foreign_key.column is AssetTable.__table__.c.uid


def test_currency_spot_asset_details_uses_asset_uid_as_one_to_one_primary_key() -> None:
    table = CurrencySpotAssetDetailsTable.__table__

    assert "uid" not in table.c
    assert [column.name for column in table.primary_key.columns] == ["asset_uid"]
    assert any(
        index.unique
        and [column.name for column in index.columns]
        == [
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


def test_future_asset_details_uses_asset_uid_as_one_to_one_primary_key() -> None:
    table = FutureAssetDetailsTable.__table__

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
        [column.name for column in index.columns] == ["settlement_asset"] for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["margin_asset"] for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["expires_at"] for index in table.indexes
    )


def test_bond_asset_details_uses_asset_uid_as_one_to_one_primary_key() -> None:
    table = BondAssetDetailsTable.__table__

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
        [column.name for column in index.columns] == ["issuer_uid"] for index in table.indexes
    )
    assert any(
        [column.name for column in index.columns] == ["currency_asset_uid"]
        for index in table.indexes
    )
    assert any([column.name for column in index.columns] == ["status"] for index in table.indexes)
    assert any(
        [column.name for column in index.columns] == ["maturity_date"] for index in table.indexes
    )


def test_markets_models_build_platform_registration_requests_in_dependency_order(
    monkeypatch,
) -> None:
    _install_fake_session_data_source(monkeypatch)
    pairs = []

    for model in markets_sqlalchemy_models():
        request = build_markets_registration_requests(
            models=[model],
        )[0]
        assert request.description == model.__metatable_description__
        pairs.append((model, request))
        monkeypatch.setattr(
            model,
            "__metatable_uid__",
            str(uuid.uuid4()),
            raising=False,
        )

    assert AssetTypeTable in markets_sqlalchemy_models()
    assert pairs

    # ADR 0017: domain MetaTables and DataNode storage (PlatformTimeIndexMetaData)
    # build different registration-request types.
    domain_requests = [req for model, req in pairs if not is_time_index_meta_table_model(model)]
    storage_requests = [req for model, req in pairs if is_time_index_meta_table_model(model)]
    assert domain_requests
    assert storage_requests
    assert all(request.management_mode == "platform_managed" for request in domain_requests)
    assert all(
        request.storage_hash
        and (
            request.table_contract.physical.table_name in (None, "")
            or request.storage_hash == request.table_contract.physical.table_name
        )
        for request in domain_requests
    )
    assert all(request.storage_hash for request in storage_requests)


def test_markets_models_build_external_registration_requests_in_dependency_order(
    monkeypatch,
) -> None:
    _install_fake_session_data_source(monkeypatch)
    pairs = []

    for model in markets_sqlalchemy_models():
        request = build_markets_registration_requests(
            data_source_uid=str(uuid.uuid4()),
            management_mode="external_registered",
            models=[model],
        )[0]
        assert request.description == model.__metatable_description__
        pairs.append((model, request))
        monkeypatch.setattr(
            model,
            "__metatable_uid__",
            str(uuid.uuid4()),
            raising=False,
        )

    assert pairs
    domain_requests = [req for model, req in pairs if not is_time_index_meta_table_model(model)]
    storage_requests = [req for model, req in pairs if is_time_index_meta_table_model(model)]
    assert domain_requests
    assert storage_requests
    assert all(request.management_mode == "external_registered" for request in domain_requests)
    assert all(
        getattr(request, "management_mode", "platform_managed") != "external_registered"
        for request in storage_requests
    )


def test_external_registration_mode_routes_storage_classes_through_sdk_register(
    monkeypatch,
) -> None:
    register_calls: list[dict] = []

    def fail_external_register(*_args, **_kwargs):
        raise AssertionError("storage classes must not use generic external registration")

    def fake_register(cls, **kwargs):
        register_calls.append(kwargs)
        return SimpleNamespace(uid="account-holdings-storage-uid")

    monkeypatch.setattr(
        meta_tables,
        "register_external_sqlalchemy_model",
        fail_external_register,
    )
    monkeypatch.setattr(AccountHoldingsStorage, "register", classmethod(fake_register))

    result = meta_tables.register_markets_meta_tables(
        data_source_uid="data-source-uid",
        management_mode="external_registered",
        models=[AccountHoldingsStorage],
    )

    assert register_calls
    assert register_calls[0] == {"timeout": None}
    assert (
        result.meta_table_by_identifier[markets_meta_table_identifier(AccountHoldingsStorage)].uid
        == "account-holdings-storage-uid"
    )


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

    assert result.models == [FakeModel]
    assert result.meta_table_by_identifier["FakeModel"].uid == "fake-meta-table-uid"
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
    assert "table_fullname" not in registering_event
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

    meta_table = result.meta_table_by_identifier["FakeModel"]
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

    assert result.meta_table_by_identifier["FakeModel"] is meta_table
    assert calls == [
        {
            "timeout": None,
            "identifier": "FakeModel",
            "management_mode": "platform_managed",
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
