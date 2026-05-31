from __future__ import annotations

import pytest

from msm.services import catalog as catalog_service
from msm.services.catalog import CatalogTableUnsupportedError


def test_catalog_list_row_exposes_row_management_flags_without_resource_type() -> None:
    row = catalog_service._build_catalog_list_row(
        {
            "uid": "catalog-row-uid",
            "namespace": "ms-markets",
            "identifier": "Asset",
            "model_name": "AssetTable",
            "meta_table_uid": "asset-meta-table-uid",
            "contract_hash": "contract-hash",
            "created_at": "2026-05-28T00:00:00+00:00",
            "updated_at": "2026-05-28T00:00:00+00:00",
        }
    )

    assert "resource_type" not in row
    assert row["supports_row_listing"] is True


def test_catalog_unknown_model_rows_are_not_row_managed() -> None:
    with pytest.raises(CatalogTableUnsupportedError, match="cannot be resolved"):
        catalog_service._resolve_supported_catalog_model(
            {
                "model_name": "AssetSnapshot",
            }
        )
