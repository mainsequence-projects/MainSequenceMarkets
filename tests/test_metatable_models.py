from __future__ import annotations

import uuid

from mainsequence.tdag.meta_tables import (
    PlatformManagedMetaTable,
    metatable_configured_tablename,
)

from msm.meta_tables import build_markets_registration_requests, markets_meta_table_fullname
from msm.models import Asset, AssetMasterList, markets_sqlalchemy_models


def test_markets_models_use_platform_managed_table_mixin() -> None:
    table_names: dict[str, type] = {}

    for model in markets_sqlalchemy_models():
        assert issubclass(model, PlatformManagedMetaTable)
        assert "__tablename__" not in model.__dict__
        assert model.__table__.name == metatable_configured_tablename(model)
        assert model.__table__.name not in table_names
        table_names[model.__table__.name] = model


def test_asset_model_does_not_store_arbitrary_metadata_json() -> None:
    assert "metadata_json" not in Asset.__table__.c


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
        target_meta_table_uid_by_fullname[markets_meta_table_fullname(model)] = str(
            uuid.uuid4()
        )

    assert AssetMasterList in markets_sqlalchemy_models()
    assert requests
    assert all(request.management_mode == "platform_managed" for request in requests)
    assert all(request.storage_hash == request.table_contract.physical.table_name for request in requests)


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
        target_meta_table_uid_by_fullname[markets_meta_table_fullname(model)] = str(
            uuid.uuid4()
        )

    assert requests
    assert all(request.management_mode == "external_registered" for request in requests)


def test_asset_master_list_is_control_plane_reference_without_database_fk() -> None:
    assert "reference_meta_table_uid" in AssetMasterList.__table__.c
    assert not AssetMasterList.__table__.foreign_keys
