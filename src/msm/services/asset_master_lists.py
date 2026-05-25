from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation

from msm.repositories import (
    MarketsRepositoryContext,
    build_create_asset_master_list_operation,
    build_get_default_asset_master_list_operation,
    create_asset_master_list,
    get_default_asset_master_list as repository_get_default_asset_master_list,
)


ASSET_MASTER_LIST_VALIDATION_VERSION = "v1"
REQUIRED_ASSET_REFERENCE_META_TABLE_COLUMNS = frozenset({"unique_identifier"})


@dataclass(frozen=True)
class AssetReferenceMetaTableValidationResult:
    """Result for validating the MetaTable selected as an asset master list."""

    table_uid: str
    validation_version: str
    column_names: tuple[str, ...]


class AssetMasterListValidationError(ValueError):
    pass


def build_create_validated_asset_master_list_operation(
    context: MarketsRepositoryContext,
    *,
    reference_meta_table: Any,
    unique_identifier: str,
    name: str,
    description: str = "",
    is_default: bool = False,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    validation = validate_asset_master_list_reference_meta_table(reference_meta_table)
    return build_create_asset_master_list_operation(
        context,
        unique_identifier=unique_identifier,
        name=name,
        description=description,
        reference_meta_table_uid=validation.table_uid,
        is_default=is_default,
        validation_version=validation.validation_version,
        metadata_json=metadata_json,
    )


def create_validated_asset_master_list(
    context: MarketsRepositoryContext,
    *,
    reference_meta_table: Any,
    unique_identifier: str,
    name: str,
    description: str = "",
    is_default: bool = False,
    metadata_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation = validate_asset_master_list_reference_meta_table(reference_meta_table)
    return create_asset_master_list(
        context,
        unique_identifier=unique_identifier,
        name=name,
        description=description,
        reference_meta_table_uid=validation.table_uid,
        is_default=is_default,
        validation_version=validation.validation_version,
        metadata_json=metadata_json,
    )


def build_resolve_asset_master_list_operation(
    context: MarketsRepositoryContext,
) -> MetaTableCompiledSQLOperation:
    return build_get_default_asset_master_list_operation(context)


def resolve_asset_master_list(context: MarketsRepositoryContext) -> dict[str, Any]:
    """Resolve the default AssetMasterList through the MetaTable execution API."""

    return repository_get_default_asset_master_list(context)


def validate_asset_master_list_reference_meta_table(
    reference_meta_table: Any,
) -> AssetReferenceMetaTableValidationResult:
    column_names = _reference_meta_table_column_names(reference_meta_table)
    missing_columns = sorted(REQUIRED_ASSET_REFERENCE_META_TABLE_COLUMNS - column_names)
    if missing_columns:
        raise AssetMasterListValidationError(
            "Selected reference MetaTable is missing required asset columns: "
            f"{missing_columns}."
        )

    if not _reference_meta_table_has_unique_identifier(reference_meta_table):
        raise AssetMasterListValidationError(
            "Selected reference MetaTable must expose a unique `unique_identifier` column."
        )

    return AssetReferenceMetaTableValidationResult(
        table_uid=_reference_meta_table_uid(reference_meta_table),
        validation_version=ASSET_MASTER_LIST_VALIDATION_VERSION,
        column_names=tuple(sorted(column_names)),
    )


def _reference_meta_table_uid(reference_meta_table: Any) -> str:
    uid = _value_for_key(reference_meta_table, "uid")
    if uid in (None, ""):
        raise AssetMasterListValidationError(
            "Selected reference MetaTable must expose a non-empty uid."
        )
    return str(uid)


def _reference_meta_table_column_names(reference_meta_table: Any) -> set[str]:
    column_names: set[str] = set()

    for column in _iter_column_payloads(reference_meta_table):
        name = _value_for_key(column, "name")
        logical_name = _value_for_key(column, "logical_name")
        if name:
            column_names.add(str(name))
        if logical_name:
            column_names.add(str(logical_name))

    table_contract = _table_contract_payload(reference_meta_table)
    for column in _as_list(table_contract.get("columns")):
        name = _value_for_key(column, "name")
        logical_name = _value_for_key(column, "logical_name")
        if name:
            column_names.add(str(name))
        if logical_name:
            column_names.add(str(logical_name))

    return column_names


def _reference_meta_table_has_unique_identifier(reference_meta_table: Any) -> bool:
    for column in _iter_column_payloads(reference_meta_table):
        column_names = {
            _value_for_key(column, "name"),
            _value_for_key(column, "logical_name"),
        }
        if "unique_identifier" in column_names and (
            bool(_value_for_key(column, "unique"))
            or bool(_value_for_key(column, "primary_key"))
        ):
            return True

    table_contract = _table_contract_payload(reference_meta_table)
    for column in _as_list(table_contract.get("columns")):
        column_names = {
            _value_for_key(column, "name"),
            _value_for_key(column, "logical_name"),
        }
        if "unique_identifier" in column_names and (
            bool(_value_for_key(column, "unique"))
            or bool(_value_for_key(column, "primary_key"))
        ):
            return True

    if _column_list_contains_unique_identifier(table_contract.get("unique_columns")):
        return True
    if _column_list_contains_unique_identifier(table_contract.get("unique")):
        return True

    if _unique_constraint_contains_identifier(table_contract.get("constraints")):
        return True
    if _unique_index_contains_identifier(table_contract.get("indexes")):
        return True
    if _unique_index_contains_identifier(_value_for_key(reference_meta_table, "indexes_meta")):
        return True

    return False


def _iter_column_payloads(reference_meta_table: Any) -> Iterable[Any]:
    columns = _value_for_key(reference_meta_table, "columns")
    if hasattr(columns, "all"):
        try:
            return list(columns.all())
        except TypeError:
            return []
    return _as_list(columns)


def _table_contract_payload(reference_meta_table: Any) -> dict[str, Any]:
    contract = _value_for_key(reference_meta_table, "table_contract") or {}
    if hasattr(contract, "model_dump"):
        return contract.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(contract, Mapping):
        return dict(contract)
    return {}


def _column_list_contains_unique_identifier(value: Any) -> bool:
    if value in (None, ""):
        return False
    if value == ["unique_identifier"]:
        return True
    if isinstance(value, Mapping):
        value = value.values()
    for item in _as_list(value):
        if item == "unique_identifier":
            return True
        if isinstance(item, Mapping):
            columns = _as_list(item.get("columns"))
            if columns == ["unique_identifier"]:
                return True
    return False


def _unique_constraint_contains_identifier(value: Any) -> bool:
    constraints = value
    if isinstance(constraints, Mapping):
        constraints = constraints.values()
    for constraint in _as_list(constraints):
        if not isinstance(constraint, Mapping):
            continue
        constraint_type = str(constraint.get("type") or constraint.get("constraint_type") or "")
        is_unique = bool(constraint.get("unique")) or constraint_type.lower() == "unique"
        columns = _as_list(constraint.get("columns"))
        if is_unique and columns == ["unique_identifier"]:
            return True
    return False


def _unique_index_contains_identifier(value: Any) -> bool:
    for index in _as_list(value):
        index_payload = _as_mapping(index)
        if bool(index_payload.get("unique")) and _as_list(index_payload.get("columns")) == [
            "unique_identifier"
        ]:
            return True
    return False


def _value_for_key(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json", by_alias=True, exclude_none=True)
        return payload.get(key)
    return getattr(value, key, None)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


__all__ = [
    "ASSET_MASTER_LIST_VALIDATION_VERSION",
    "REQUIRED_ASSET_REFERENCE_META_TABLE_COLUMNS",
    "AssetMasterListValidationError",
    "AssetReferenceMetaTableValidationResult",
    "build_create_validated_asset_master_list_operation",
    "build_resolve_asset_master_list_operation",
    "create_validated_asset_master_list",
    "resolve_asset_master_list",
    "validate_asset_master_list_reference_meta_table",
]
