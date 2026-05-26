from __future__ import annotations

import uuid
from types import SimpleNamespace

from mainsequence.tdag.meta_tables import (
    PlatformManagedMetaTable,
    metatable_configured_tablename,
)

import msm.meta_tables as meta_tables
from msm.meta_tables import build_markets_registration_requests, markets_meta_table_fullname
from msm.models import (
    Asset,
    AssetMasterList,
    AssetMasterListTable,
    AssetTable,
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


def test_asset_model_does_not_store_arbitrary_metadata_json() -> None:
    assert "metadata_json" not in AssetTable.__table__.c


def test_legacy_model_aliases_point_to_table_declarations() -> None:
    assert Asset is AssetTable
    assert AssetMasterList is AssetMasterListTable


def test_selected_metatable_models_resolve_in_dependency_order() -> None:
    models = meta_tables.resolve_markets_meta_table_models(
        ["AssetCategoryMembership", "Asset"],
    )

    assert models == [
        AssetTable,
        meta_tables.resolve_markets_meta_table_model("AssetCategoryMembership"),
    ]


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

    assert AssetMasterListTable in markets_sqlalchemy_models()
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


def test_asset_master_list_is_control_plane_reference_without_database_fk() -> None:
    assert "reference_meta_table_uid" in AssetMasterList.__table__.c
    assert not AssetMasterList.__table__.foreign_keys


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
