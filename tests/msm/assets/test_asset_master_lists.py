from __future__ import annotations

import uuid

import pytest

from msm.models import AssetMasterListTable
from msm.repositories import MarketsRepositoryContext, build_create_asset_master_list_operation
from msm.services import (
    AssetMasterListValidationError,
    validate_asset_master_list_reference_meta_table,
)


def test_validate_asset_master_list_reference_accepts_unique_identifier_index() -> None:
    reference_meta_table = {
        "uid": str(uuid.uuid4()),
        "table_contract": {
            "columns": [
                {
                    "name": "unique_identifier",
                    "data_type": "str",
                    "nullable": False,
                },
            ],
            "indexes": [
                {
                    "name": "asset_unique_identifier_uidx",
                    "columns": ["unique_identifier"],
                    "unique": True,
                }
            ],
        },
    }

    result = validate_asset_master_list_reference_meta_table(reference_meta_table)

    assert result.table_uid == reference_meta_table["uid"]
    assert result.validation_version == "v1"
    assert result.column_names == ("unique_identifier",)


def test_validate_asset_master_list_reference_rejects_non_unique_identifier() -> None:
    reference_meta_table = {
        "uid": str(uuid.uuid4()),
        "table_contract": {
            "columns": [
                {
                    "name": "unique_identifier",
                    "data_type": "str",
                    "nullable": False,
                },
            ],
        },
    }

    with pytest.raises(AssetMasterListValidationError):
        validate_asset_master_list_reference_meta_table(reference_meta_table)


def test_build_create_asset_master_list_operation_compiles_to_write_scope() -> None:
    meta_table_uid = str(uuid.uuid4())
    context = MarketsRepositoryContext(
        target_meta_table_uid_by_fullname={
            str(AssetMasterListTable.__table__.fullname): meta_table_uid,
        }
    )

    operation = build_create_asset_master_list_operation(
        context,
        unique_identifier="canonical_assets",
        name="Canonical assets",
        reference_meta_table_uid=str(uuid.uuid4()),
    )

    assert operation.operation == "insert"
    assert operation.scope.tables[0].meta_table_uid == meta_table_uid
    assert operation.scope.tables[0].access == "write"
    assert AssetMasterListTable.__table__.name in operation.statement.sql
