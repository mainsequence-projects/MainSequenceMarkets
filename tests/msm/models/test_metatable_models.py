from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import ClassVar

import pytest
from mainsequence.meta_tables import (
    MetaTableForeignKey,
    PlatformManagedMetaTable,
    PlatformTimeIndexMetaData,
)
from pydantic import AliasChoices, Field
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

import msm.models.registration as meta_tables
import msm.models as models
from msm.api.base import MarketsMetaTableRow, MarketsRow
from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_storage_name
from msm.data_nodes.storage import AccountHoldingsStorage
from msm.maintenance.models import MarketsMetaTableCatalogTable
from msm.migrations.registry import migration_model_registry
from msm.models.registration import (
    build_markets_registration_requests,
    is_time_index_meta_table_model,
    markets_meta_table_identifier,
    resolve_markets_meta_table_model,
    resolve_markets_meta_table_models,
)
from msm.models import (
    AccountGroupTable,
    AccountModelPortfolioTable,
    AccountTable,
    AccountTargetPortfolioTable,
    AssetTypeTable,
    AssetTable,
    BondAssetDetailsTable,
    CurrencySpotAssetDetailsTable,
    FutureAssetDetailsTable,
    IndexTable,
    IndexTypeTable,
    IssuerTable,
    OpenFigiAssetDetailsTable,
    PositionSetTable,
    markets_sqlalchemy_models,
)
from msm_pricing.meta_tables import pricing_sqlalchemy_models


class ExtensionAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    __metatable_identifier__ = "test.ExtensionAssetDetails"
    __metatable_extra_hash_components__ = {"storage_name": "test_extension_asset_details"}
    __metatable_description__ = (
        "Project-local asset details keyed by AssetTable uid for extension "
        "registration tests and custom asset classification."
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(AssetTable, column="uid", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    internal_asset_class: Mapped[str] = mapped_column(String(64), nullable=False)


class ExtensionAssetDetails(MarketsMetaTableRow):
    __table__: ClassVar[type[ExtensionAssetDetailsTable]] = ExtensionAssetDetailsTable
    __required_tables__: ClassVar[list[type[ExtensionAssetDetailsTable]]] = [
        ExtensionAssetDetailsTable,
    ]

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
    internal_asset_class: str


def _install_fake_session_data_source(monkeypatch) -> None:
    from mainsequence.client import metatables

    monkeypatch.setattr(
        metatables,
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
        assert model.__table__.name == model.get_storage_hash()
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


def test_built_in_metatables_declare_column_descriptions() -> None:
    seen: set[type] = set()
    models = []
    for model in [
        MarketsMetaTableCatalogTable,
        *markets_sqlalchemy_models(),
        *pricing_sqlalchemy_models(),
    ]:
        if model in seen:
            continue
        seen.add(model)
        models.append(model)

    for model in models:
        for column in model.__table__.columns:
            description = column.info.get("description")

            assert isinstance(description, str), f"{model.__name__}.{column.name}"
            assert description.strip() == description, f"{model.__name__}.{column.name}"
            assert len(description.split()) >= 5, f"{model.__name__}.{column.name}"


def test_timestamped_execution_fact_tables_are_not_domain_metatables() -> None:
    assert not hasattr(models, "ExecutionErrorTable")
    assert not hasattr(models, "OrderTable")
    assert not hasattr(models, "OrderStatusEventTable")
    assert not hasattr(models, "TradeTable")
    identifiers = {
        getattr(model, "__metatable_identifier__", model.__name__)
        for model in markets_sqlalchemy_models()
    }
    assert "ExecutionError" not in identifiers
    assert "Order" not in identifiers
    assert "OrderStatusEvent" not in identifiers
    assert "Trade" not in identifiers


def test_markets_metatable_row_keeps_legacy_alias() -> None:
    assert MarketsRow is MarketsMetaTableRow


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


def test_resolve_models_accepts_project_local_model_with_fk_dependency() -> None:
    assert resolve_markets_meta_table_model(ExtensionAssetDetailsTable) is (
        ExtensionAssetDetailsTable
    )
    assert resolve_markets_meta_table_models([ExtensionAssetDetailsTable]) == [
        AssetTable,
        ExtensionAssetDetailsTable,
    ]


def test_resolve_models_accepts_project_local_row_wrapper() -> None:
    assert resolve_markets_meta_table_model(ExtensionAssetDetails) is ExtensionAssetDetailsTable
    assert resolve_markets_meta_table_models([ExtensionAssetDetails]) == [
        AssetTable,
        ExtensionAssetDetailsTable,
    ]


def test_project_local_asset_detail_row_aliases_uid_to_asset_uid() -> None:
    asset_uid = uuid.uuid4()

    row = ExtensionAssetDetails.model_validate(
        {
            "asset_uid": asset_uid,
            "internal_asset_class": "equity",
        }
    )

    assert row.uid == asset_uid
    assert row.asset_uid == asset_uid


def test_resolve_models_rejects_duplicate_project_local_identifiers() -> None:
    class DuplicateIdentifierATable(MarketsMetaTableMixin, MarketsBase):
        __metatable_identifier__ = "test.DuplicateIdentifier"
        __metatable_extra_hash_components__ = {"storage_name": "duplicate_identifier_a"}
        __metatable_description__ = (
            "First duplicate identifier table used to verify bootstrap validation."
        )

        uid: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)

    class DuplicateIdentifierBTable(MarketsMetaTableMixin, MarketsBase):
        __metatable_identifier__ = "test.DuplicateIdentifier"
        __metatable_extra_hash_components__ = {"storage_name": "duplicate_identifier_b"}
        __metatable_description__ = (
            "Second duplicate identifier table used to verify bootstrap validation."
        )

        uid: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)

    with pytest.raises(ValueError, match="Duplicate markets MetaTable identifier"):
        resolve_markets_meta_table_models([DuplicateIdentifierATable, DuplicateIdentifierBTable])


def test_resolve_models_rejects_dependency_cycles(monkeypatch) -> None:
    class CycleATable(MarketsMetaTableMixin, MarketsBase):
        __metatable_identifier__ = "test.CycleA"
        __metatable_extra_hash_components__ = {"storage_name": "cycle_a"}
        __metatable_description__ = "Cycle A table used to test dependency graph errors."

        uid: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)

    class CycleBTable(MarketsMetaTableMixin, MarketsBase):
        __metatable_identifier__ = "test.CycleB"
        __metatable_extra_hash_components__ = {"storage_name": "cycle_b"}
        __metatable_description__ = "Cycle B table used to test dependency graph errors."

        uid: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)

    def fake_target_models(model):
        return {
            CycleATable: [CycleBTable],
            CycleBTable: [CycleATable],
        }.get(model, [])

    monkeypatch.setattr(meta_tables, "_metatable_foreign_key_target_models", fake_target_models)

    with pytest.raises(ValueError, match="dependency cycle"):
        resolve_markets_meta_table_models([CycleATable])


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


def test_account_relationships_live_on_account_table() -> None:
    assert "account_group_uid" in AccountTable.__table__.c
    assert "account_model_portfolio_uid" not in AccountTable.__table__.c
    assert "account_model_portfolio_uid" not in AccountGroupTable.__table__.c

    group_column = AccountTable.__table__.c["account_group_uid"]

    assert any(
        foreign_key.info["mainsequence_metatable_foreign_key"]["target_model"] is AccountGroupTable
        and foreign_key.info["mainsequence_metatable_foreign_key"]["target_column"] == "uid"
        for foreign_key in group_column.foreign_keys
    )


def test_account_metatable_columns_are_described() -> None:
    for model in [
        AccountModelPortfolioTable,
        AccountGroupTable,
        AccountTable,
        AccountTargetPortfolioTable,
        PositionSetTable,
    ]:
        for column in model.__table__.columns:
            assert column.info.get("label"), f"{model.__name__}.{column.name}"
            assert column.info.get("description"), f"{model.__name__}.{column.name}"


def test_account_target_portfolio_owns_position_sets() -> None:
    assert "account_uid" in AccountTargetPortfolioTable.__table__.c
    assert "account_model_portfolio_uid" in AccountTargetPortfolioTable.__table__.c
    assert "account_target_portfolio_uid" in PositionSetTable.__table__.c
    assert "position_set_time" in PositionSetTable.__table__.c

    target_account_column = AccountTargetPortfolioTable.__table__.c["account_uid"]
    target_model_column = AccountTargetPortfolioTable.__table__.c["account_model_portfolio_uid"]
    position_set_parent_column = PositionSetTable.__table__.c["account_target_portfolio_uid"]

    assert any(
        foreign_key.info["mainsequence_metatable_foreign_key"]["target_model"] is AccountTable
        and foreign_key.info["mainsequence_metatable_foreign_key"]["target_column"] == "uid"
        for foreign_key in target_account_column.foreign_keys
    )
    assert any(
        foreign_key.info["mainsequence_metatable_foreign_key"]["target_model"]
        is AccountModelPortfolioTable
        and foreign_key.info["mainsequence_metatable_foreign_key"]["target_column"] == "uid"
        for foreign_key in target_model_column.foreign_keys
    )
    assert any(
        foreign_key.info["mainsequence_metatable_foreign_key"]["target_model"]
        is AccountTargetPortfolioTable
        and foreign_key.info["mainsequence_metatable_foreign_key"]["target_column"] == "uid"
        for foreign_key in position_set_parent_column.foreign_keys
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
        meta_tables.resolve_markets_meta_table_model("AssetCategory"),
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
        requests = build_markets_registration_requests(
            models=[model],
        )
        request = next(
            request for request in requests if request.identifier == model.__metatable_identifier__
        )
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


def test_migration_registry_models_use_sdk_base_metatable_classes() -> None:
    registry = migration_model_registry()
    assert registry
    assert AccountHoldingsStorage in registry
    assert all(issubclass(model, PlatformManagedMetaTable) for model in registry)
    assert issubclass(AccountHoldingsStorage, PlatformTimeIndexMetaData)


def test_markets_models_build_external_registration_requests_in_dependency_order(
    monkeypatch,
) -> None:
    _install_fake_session_data_source(monkeypatch)
    pairs = []

    for model in markets_sqlalchemy_models():
        requests = build_markets_registration_requests(
            data_source_uid=str(uuid.uuid4()),
            management_mode="external_registered",
            models=[model],
        )
        request = next(
            request for request in requests if request.identifier == model.__metatable_identifier__
        )
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


def test_markets_models_do_not_expose_direct_registration_helper() -> None:
    assert not hasattr(meta_tables, "register_markets_meta_tables")
    assert not hasattr(meta_tables, "register_external_sqlalchemy_model")


def test_resolve_registered_markets_meta_tables_filters_by_logical_identity(monkeypatch) -> None:
    calls = []
    meta_table = SimpleNamespace(
        uid="fake-meta-table-uid",
        namespace="mainsequence.markets",
        identifier="FakeModel",
    )

    class ResolveFakeModel(MarketsMetaTableMixin, MarketsBase):
        __metatable_namespace__ = "mainsequence.markets"
        __metatable_identifier__ = "FakeModel"
        __metatable_extra_hash_components__ = {"storage_name": "fake_model_resolve"}

        uid: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)

    def fake_filter(**kwargs):
        calls.append(kwargs)
        return [meta_table]

    monkeypatch.setattr(meta_tables.MetaTable, "filter", fake_filter)

    result = meta_tables.resolve_registered_markets_meta_tables(
        data_source_uid="data-source-uid",
        models=[ResolveFakeModel],
    )

    assert result.meta_table_by_identifier[markets_meta_table_identifier(ResolveFakeModel)] is (
        meta_table
    )
    assert calls == [
        {
            "timeout": None,
            "identifier": "FakeModel",
            "management_mode": "platform_managed",
        }
    ]


def test_resolve_registered_markets_meta_tables_rejects_missing_table(monkeypatch) -> None:
    class MissingFakeModel(MarketsMetaTableMixin, MarketsBase):
        __metatable_namespace__ = "mainsequence.markets"
        __metatable_identifier__ = "FakeModel"
        __metatable_extra_hash_components__ = {"storage_name": "fake_model_missing"}

        uid: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)

    monkeypatch.setattr(meta_tables.MetaTable, "filter", lambda **_kwargs: [])

    with pytest.raises(LookupError, match="Could not resolve registered"):
        meta_tables.resolve_registered_markets_meta_tables(models=[MissingFakeModel])
