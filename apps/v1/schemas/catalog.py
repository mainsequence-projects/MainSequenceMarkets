from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CatalogListRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    namespace: str
    identifier: str
    description: str | None = None
    model_name: str
    meta_table_uid: str
    storage_hash: str
    contract_hash: str
    sdk_version: str | None = None
    created_at: str
    updated_at: str
    supports_row_listing: bool
    supports_row_delete: bool
    rows_endpoint: str | None = None
    delete_endpoint_template: str | None = None


class CatalogListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[CatalogListRow]
    limit: int
    offset: int


class CatalogReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    identifier: str
    model_name: str
    meta_table_uid: str
    storage_hash: str


class CatalogColumn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    type: str
    nullable: bool
    primary_key: bool


class CatalogTableRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str
    values: dict[str, Any]


class CatalogRowsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    catalog: CatalogReference
    columns: list[CatalogColumn]
    results: list[CatalogTableRow]
    limit: int
    offset: int


class CatalogDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    catalog_uid: UUID
    meta_table_uid: str
    uid: str
    deleted_count: int
    cascade: bool
