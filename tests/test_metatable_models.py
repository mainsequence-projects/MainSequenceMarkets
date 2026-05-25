from __future__ import annotations

import uuid

from msm.meta_tables import build_markets_registration_requests, markets_meta_table_fullname
from msm.models import AssetMasterList, markets_sqlalchemy_models


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
