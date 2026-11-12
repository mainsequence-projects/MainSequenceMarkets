"""Create missing asset types and assets inside one transaction (ADR 0051).

Both statements insert with ``ON CONFLICT DO NOTHING``: an existing asset type or asset is
never changed, and the caller reads the rows that exist afterwards. The uids are chosen
by the caller, so a row whose uid it chose is a row its transaction created.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, bindparam, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from metatables import MetaTableCompiledSQLDialect
from metatables.compiled_sql.v1 import GuardedStatement
from msm.constants import ASSET_TYPE_CURRENCY_DEFINITION, AssetTypeDefinition
from msm.models import AssetTable, AssetTypeTable

from .base import (
    MarketsCompiledWrite,
    MarketsOperationContext,
    compile_markets_statements,
    execute_markets_write,
    resolve_markets_sql_target,
)

CURRENCY_ASSET_GUARD = "currency_asset_type"
"""Guard label of the currency read: the asset exists with the ``currency`` type."""


@dataclass(frozen=True)
class NewAssetType:
    """An asset type to create when it is missing."""

    uid: uuid.UUID
    asset_type: str
    display_name: str | None = None
    description: str | None = None

    @classmethod
    def from_definition(cls, definition: AssetTypeDefinition) -> NewAssetType:
        return cls(
            uid=uuid.uuid4(),
            asset_type=definition.asset_type,
            display_name=definition.display_name,
            description=definition.description,
        )


@dataclass(frozen=True)
class NewAsset:
    """An asset to create when it is missing."""

    uid: uuid.UUID
    unique_identifier: str
    asset_type: str


def dialect_insert(model: Any, dialect: MetaTableCompiledSQLDialect) -> Any:
    """The dialect's ``INSERT`` construct, which carries its ``ON CONFLICT`` clause."""

    if dialect == "postgresql":
        return postgresql_insert(model)
    if dialect == "sqlite":
        return sqlite_insert(model)
    raise ValueError(f"Unsupported SQL dialect {dialect!r} for an ON CONFLICT insert.")


def insert_missing_asset_types(
    asset_types: Sequence[NewAssetType],
    *,
    dialect: MetaTableCompiledSQLDialect,
) -> Any:
    """Insert the asset types that do not exist; an existing one is left as it is."""

    return (
        dialect_insert(AssetTypeTable, dialect)
        .values(
            [
                {
                    "uid": item.uid,
                    "asset_type": item.asset_type,
                    "display_name": item.display_name,
                    "description": item.description,
                }
                for item in asset_types
            ]
        )
        .on_conflict_do_nothing(index_elements=[AssetTypeTable.asset_type])
    )


def insert_missing_assets(
    assets: Sequence[NewAsset],
    *,
    dialect: MetaTableCompiledSQLDialect,
) -> Any:
    """Insert the assets that do not exist; an existing one keeps its uid and type."""

    return (
        dialect_insert(AssetTable, dialect)
        .values(
            [
                {
                    "uid": item.uid,
                    "unique_identifier": item.unique_identifier,
                    "asset_type": item.asset_type,
                }
                for item in assets
            ]
        )
        .on_conflict_do_nothing(index_elements=[AssetTable.unique_identifier])
    )


def currency_asset_statements(
    code: str,
    *,
    dialect: MetaTableCompiledSQLDialect,
) -> list[GuardedStatement | Any]:
    """Get or create the currency asset ``code``, creating the ``currency`` type first.

    The last statement reads the asset back and is guarded: it must find it with the
    ``currency`` type, or the transaction rolls back.
    """

    identifier = str(code or "").strip()
    if not identifier:
        raise ValueError("A currency asset requires a non-empty code.")
    asset_type = NewAssetType.from_definition(ASSET_TYPE_CURRENCY_DEFINITION)
    asset = NewAsset(
        uid=uuid.uuid4(),
        unique_identifier=identifier,
        asset_type=asset_type.asset_type,
    )
    return [
        insert_missing_asset_types([asset_type], dialect=dialect),
        insert_missing_assets([asset], dialect=dialect),
        GuardedStatement(
            select(AssetTable)
            .where(AssetTable.unique_identifier == bindparam("code", value=identifier, type_=String()))
            .where(AssetTable.asset_type == asset_type.asset_type),
            expect_rows=1,
            label=CURRENCY_ASSET_GUARD,
        ),
    ]


def build_get_or_create_currency_asset_operation(
    context: MarketsOperationContext,
    *,
    code: str,
    dialect: MetaTableCompiledSQLDialect | None = None,
) -> MarketsCompiledWrite:
    """Compile the currency get-or-create as one transaction (ADR 0051, decision 9)."""

    data_source_uid, dialect = resolve_markets_sql_target(context, dialect=dialect)
    return compile_markets_statements(
        currency_asset_statements(code, dialect=dialect),
        context=context,
        operation="upsert",
        data_source_uid=data_source_uid,
        dialect=dialect,
    )


def get_or_create_currency_asset(
    context: MarketsOperationContext,
    *,
    code: str,
) -> dict[str, Any]:
    """Run the currency get-or-create; no rows when the asset exists with another type."""

    return execute_markets_write(
        build_get_or_create_currency_asset_operation(context, code=code),
        context=context,
        refused_by=(CURRENCY_ASSET_GUARD,),
    )


__all__ = [
    "CURRENCY_ASSET_GUARD",
    "NewAsset",
    "NewAssetType",
    "build_get_or_create_currency_asset_operation",
    "currency_asset_statements",
    "dialect_insert",
    "get_or_create_currency_asset",
    "insert_missing_asset_types",
    "insert_missing_assets",
]
