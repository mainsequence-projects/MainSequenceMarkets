from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any

from mainsequence.client.exceptions import ConflictError
from mainsequence.client.models_metatables import MetaTable
from mainsequence.logconf import logger as _mainsequence_logger
from mainsequence.tdag.meta_tables import register_external_sqlalchemy_model

from msm.base import MARKETS_SCHEMA, MarketsBase
from msm.models.registration import (
    MarketsManagementMode,
    MarketsMetaTableRegistrationResult,
    markets_meta_table_fullname,
)
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import search_model, upsert_model

from .models import (
    MarketsMetaTableCatalogRow,
    MarketsMetaTableCatalogTable,
    markets_meta_table_contract_hash,
)


logger = _mainsequence_logger.bind(sub_application="markets", component="maintenance")


class CatalogBootstrapError(RuntimeError):
    """Raised when catalog bootstrap cannot safely resolve MetaTable state."""


@dataclass(frozen=True)
class CatalogBootstrapResult:
    """Catalog bootstrap output for application MetaTable registration."""

    registration: MarketsMetaTableRegistrationResult
    catalog_meta_table: MetaTable
    attached_count: int = 0
    imported_count: int = 0
    registered_count: int = 0


@dataclass(frozen=True)
class _CatalogBootstrapModelPlan:
    model: type[MarketsBase]
    table_fullname: str
    storage_hash: str


def bootstrap_markets_meta_tables_from_catalog(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    target_meta_table_uid_by_fullname: Mapping[str, Any] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_fullname: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> CatalogBootstrapResult:
    """Attach/register markets MetaTables through the maintenance catalog."""

    resolved_models = list(models or [])
    catalog_meta_table = bootstrap_catalog_table(
        data_source_uid=data_source_uid,
        timeout=timeout,
    )
    catalog_context = catalog_repository_context(
        catalog_meta_table=catalog_meta_table,
        timeout=timeout,
    )
    target_mapping = {
        str(key): _meta_table_uid(value)
        for key, value in (target_meta_table_uid_by_fullname or {}).items()
    }
    storage_hash_mapping = dict(storage_hash_by_fullname or {})
    model_plans = [
        _CatalogBootstrapModelPlan(
            model=model,
            table_fullname=markets_meta_table_fullname(model),
            storage_hash=_catalog_model_storage_hash(
                model,
                storage_hash=storage_hash_mapping.get(markets_meta_table_fullname(model)),
            ),
        )
        for model in resolved_models
    ]
    catalog_rows_by_storage_hash = find_catalog_rows_by_storage_hash(
        catalog_context,
        storage_hashes=[plan.storage_hash for plan in model_plans],
    )

    meta_tables: list[MetaTable] = []
    meta_table_by_fullname: dict[str, MetaTable] = {}
    attached_count = 0
    imported_count = 0
    registered_count = 0

    for position, plan in enumerate(model_plans, start=1):
        model = plan.model
        table_fullname = plan.table_fullname
        catalog_row = catalog_rows_by_storage_hash.get(plan.storage_hash)
        if catalog_row is not None:
            validate_catalog_contract(catalog_row, model=model)
            meta_table = meta_table_from_catalog_row(
                catalog_row,
                model=model,
                management_mode=management_mode,
            )
            attached_count += 1
            logger.debug(
                "Attached markets MetaTable from catalog",
                model=model.__name__,
                namespace=catalog_row.get("namespace"),
                identifier=catalog_row.get("identifier"),
                meta_table_uid=_meta_table_uid(meta_table),
                model_index=position,
                model_count=len(resolved_models),
            )
        else:
            meta_table = _resolve_platform_meta_table(
                model,
                data_source_uid=data_source_uid,
                management_mode=management_mode,
                timeout=timeout,
            )
            if meta_table is not None:
                imported_count += 1
                logger.info(
                    "Importing existing markets MetaTable into catalog",
                    model=model.__name__,
                    namespace=getattr(model, "__metatable_namespace__", None),
                    identifier=getattr(model, "__metatable_identifier__", None),
                    meta_table_uid=_meta_table_uid(meta_table),
                    model_index=position,
                    model_count=len(resolved_models),
                )
            else:
                meta_table = register_catalog_missing_meta_table(
                    model,
                    data_source_uid=data_source_uid,
                    management_mode=management_mode,
                    target_meta_table_uid_by_fullname=target_mapping,
                    open_for_everyone=open_for_everyone,
                    protect_from_deletion=protect_from_deletion,
                    introspect=introspect,
                    storage_hash=plan.storage_hash,
                    timeout=timeout,
                )
                registered_count += 1
                logger.info(
                    "Registered missing markets MetaTable from catalog bootstrap",
                    model=model.__name__,
                    namespace=getattr(model, "__metatable_namespace__", None),
                    identifier=getattr(model, "__metatable_identifier__", None),
                    meta_table_uid=_meta_table_uid(meta_table),
                    model_index=position,
                    model_count=len(resolved_models),
                )

            upsert_catalog_row(
                catalog_context,
                model=model,
                meta_table=meta_table,
            )

        meta_tables.append(meta_table)
        meta_table_by_fullname[table_fullname] = meta_table
        target_mapping[table_fullname] = _meta_table_uid(meta_table)

    return CatalogBootstrapResult(
        registration=MarketsMetaTableRegistrationResult(
            meta_tables=meta_tables,
            target_meta_table_uid_by_fullname=target_mapping,
            models=resolved_models,
            meta_table_by_fullname=meta_table_by_fullname,
        ),
        catalog_meta_table=catalog_meta_table,
        attached_count=attached_count,
        imported_count=imported_count,
        registered_count=registered_count,
    )


def bootstrap_catalog_table(
    *,
    data_source_uid: str | None = None,
    timeout: int | float | tuple[float, float] | None = None,
) -> MetaTable:
    """Attach or create the maintenance catalog MetaTable."""

    existing = _resolve_platform_meta_table(
        MarketsMetaTableCatalogTable,
        data_source_uid=data_source_uid,
        management_mode="platform_managed",
        timeout=timeout,
    )
    if existing is not None:
        logger.info(
            "Attached markets MetaTable catalog",
            namespace=getattr(existing, "namespace", None),
            identifier=getattr(existing, "identifier", None),
            meta_table_uid=_meta_table_uid(existing),
        )
        return existing

    logger.info(
        "Creating markets MetaTable catalog",
        namespace=getattr(MarketsMetaTableCatalogTable, "__metatable_namespace__", None),
        identifier=getattr(MarketsMetaTableCatalogTable, "__metatable_identifier__", None),
    )
    try:
        return MarketsMetaTableCatalogTable.register(
            data_source_uid=data_source_uid,
            introspect=False,
            timeout=timeout,
        )
    except ConflictError as exc:
        recovered = _meta_table_from_conflict(
            exc,
            model=MarketsMetaTableCatalogTable,
            management_mode="platform_managed",
            timeout=timeout,
        )
        if recovered is not None:
            logger.info(
                "Attached markets MetaTable catalog after duplicate registration",
                meta_table_uid=_meta_table_uid(recovered),
            )
            return recovered
        raise CatalogBootstrapError(
            "Could not create or attach the markets MetaTable catalog. "
            "Resolve the catalog MetaTable conflict before registering application tables."
        ) from exc


def catalog_repository_context(
    *,
    catalog_meta_table: MetaTable,
    timeout: int | float | tuple[float, float] | None = None,
) -> MarketsRepositoryContext:
    return MarketsRepositoryContext(
        target_meta_table_uid_by_fullname={
            markets_meta_table_fullname(MarketsMetaTableCatalogTable): _meta_table_uid(
                catalog_meta_table
            )
        },
        timeout=timeout,
        namespace=getattr(catalog_meta_table, "namespace", None),
    )


def find_catalog_row(
    context: MarketsRepositoryContext,
    *,
    model: type[MarketsBase],
    storage_hash: str | None = None,
) -> dict[str, Any] | None:
    rows_by_storage_hash = find_catalog_rows_by_storage_hash(
        context,
        storage_hashes=[
            _catalog_model_storage_hash(
                model,
                storage_hash=storage_hash,
            )
        ],
    )
    return rows_by_storage_hash.get(
        _catalog_model_storage_hash(
            model,
            storage_hash=storage_hash,
        )
    )


def find_catalog_rows_by_storage_hash(
    context: MarketsRepositoryContext,
    *,
    storage_hashes: Sequence[str],
) -> dict[str, dict[str, Any]]:
    requested_storage_hashes = list(dict.fromkeys(str(value) for value in storage_hashes if value))
    if not requested_storage_hashes:
        return {}

    result = search_model(
        context,
        model=MarketsMetaTableCatalogTable,
        in_filters={"storage_hash": requested_storage_hashes},
        limit=len(requested_storage_hashes) * 2,
    )
    rows_by_storage_hash: dict[str, dict[str, Any]] = {}
    for row in _operation_result_rows(result):
        row_storage_hash = str(row.get("storage_hash") or "")
        if not row_storage_hash:
            raise CatalogBootstrapError(
                "Markets MetaTable catalog returned a row without storage_hash."
            )
        if row_storage_hash in rows_by_storage_hash:
            raise CatalogBootstrapError(
                "Markets MetaTable catalog returned multiple rows for "
                f"storage_hash {row_storage_hash!r}. The catalog uniqueness invariant is broken."
            )
        rows_by_storage_hash[row_storage_hash] = row

    unknown_storage_hashes = sorted(
        set(rows_by_storage_hash).difference(requested_storage_hashes)
    )
    if unknown_storage_hashes:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog returned rows outside the requested storage hashes: "
            f"{unknown_storage_hashes!r}."
        )
    return rows_by_storage_hash


def meta_table_from_catalog_row(
    catalog_row: Mapping[str, Any],
    *,
    model: type[MarketsBase],
    management_mode: MarketsManagementMode,
) -> MetaTable:
    storage_hash = str(catalog_row["storage_hash"])
    return MetaTable(
        uid=str(catalog_row["meta_table_uid"]),
        namespace=str(catalog_row.get("namespace") or ""),
        identifier=str(
            catalog_row.get("identifier")
            or getattr(model, "__metatable_identifier__", model.__name__)
        ),
        description=catalog_row.get("description"),
        storage_hash=storage_hash,
        physical_table_name=storage_hash,
        management_mode=management_mode,
    )


def resolve_catalog_meta_table(
    catalog_row: Mapping[str, Any],
    *,
    model: type[MarketsBase],
    timeout: int | float | tuple[float, float] | None = None,
) -> MetaTable:
    try:
        return MetaTable.get_by_uid(
            uid=str(catalog_row["meta_table_uid"]),
            timeout=timeout,
        )
    except Exception as exc:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog row is stale for "
            f"{model.__name__}: platform MetaTable {catalog_row.get('meta_table_uid')!r} "
            "could not be resolved. Repair or rebuild the catalog before startup."
        ) from exc


def validate_catalog_contract(
    catalog_row: Mapping[str, Any],
    *,
    model: type[MarketsBase],
) -> None:
    expected_contract_hash = markets_meta_table_contract_hash(model)
    actual_contract_hash = str(catalog_row.get("contract_hash") or "")
    if actual_contract_hash != expected_contract_hash:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog contract drift detected for "
            f"{model.__name__}. Catalog hash {actual_contract_hash!r} does not match "
            f"local hash {expected_contract_hash!r}. Add an explicit migration or repair "
            "the catalog before startup."
        )


def register_catalog_missing_meta_table(
    model: type[MarketsBase],
    *,
    data_source_uid: str | None,
    management_mode: MarketsManagementMode,
    target_meta_table_uid_by_fullname: Mapping[str, Any],
    open_for_everyone: bool,
    protect_from_deletion: bool,
    introspect: bool | None,
    storage_hash: str | None,
    timeout: int | float | tuple[float, float] | None,
) -> MetaTable:
    platform_kwargs = {
        "data_source_uid": data_source_uid,
        "open_for_everyone": open_for_everyone,
        "protect_from_deletion": protect_from_deletion,
        "target_meta_table_uid_by_fullname": target_meta_table_uid_by_fullname,
        "timeout": timeout,
    }
    try:
        if management_mode == "platform_managed":
            return model.register(
                introspect=False if introspect is None else introspect,
                **platform_kwargs,
            )
        if management_mode == "external_registered":
            return register_external_sqlalchemy_model(
                model,
                introspect=True if introspect is None else introspect,
                storage_hash=storage_hash,
                schema=MARKETS_SCHEMA,
                **platform_kwargs,
            )
    except ConflictError as exc:
        raise CatalogBootstrapError(
            "Markets MetaTable catalog drift detected while registering "
            f"{model.__name__}. The platform reports that the physical table already "
            "exists, but the catalog has no matching row. Run the catalog import/repair "
            "flow before normal schema bootstrap."
        ) from exc
    raise ValueError("management_mode must be 'platform_managed' or 'external_registered'.")


def upsert_catalog_row(
    context: MarketsRepositoryContext,
    *,
    model: type[MarketsBase],
    meta_table: MetaTable,
) -> dict[str, Any]:
    row = MarketsMetaTableCatalogRow.from_meta_table(
        model=model,
        meta_table=meta_table,
        sdk_version=_sdk_version(),
    )
    return upsert_model(
        context,
        model=MarketsMetaTableCatalogTable,
        values=row.to_payload(),
        conflict_columns=[
            "storage_hash",
        ],
    )


def _resolve_platform_meta_table(
    model: type[MarketsBase],
    *,
    data_source_uid: str | None,
    management_mode: MarketsManagementMode,
    timeout: int | float | tuple[float, float] | None,
) -> MetaTable | None:
    matches: list[MetaTable] = []
    matched_filters: dict[str, Any] | None = None
    for filters in _registered_meta_table_filter_candidates(
        model,
        data_source_uid=data_source_uid,
        management_mode=management_mode,
    ):
        matches = MetaTable.filter(timeout=timeout, **filters)
        if matches:
            matched_filters = filters
            break
    if not matches:
        return None
    if len(matches) > 1:
        raise CatalogBootstrapError(
            "Multiple registered markets MetaTables matched "
            f"{model.__name__} with filters {matched_filters!r}. Pass data_source_uid "
            "or repair duplicate platform registrations before startup."
        )
    return matches[0]


def _registered_meta_table_filter_candidates(
    model: type[MarketsBase],
    *,
    data_source_uid: str | None,
    management_mode: MarketsManagementMode,
) -> list[dict[str, Any]]:
    base_filters: dict[str, Any] = {
        "identifier": getattr(model, "__metatable_identifier__", model.__name__),
        "namespace": getattr(model, "__metatable_namespace__", None),
        "management_mode": management_mode,
    }
    if data_source_uid:
        base_filters["data_source__uid"] = data_source_uid

    table_name = model.__table__.name
    return [
        _clean_filters({**base_filters, "physical_table_name": table_name}),
        _clean_filters({**base_filters, "storage_hash": table_name}),
    ]


def _clean_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if value not in (None, "")}


def _catalog_model_storage_hash(
    model: type[MarketsBase],
    *,
    storage_hash: str | None = None,
) -> str:
    if storage_hash not in (None, ""):
        return str(storage_hash)
    return str(model.__table__.name)


def _meta_table_from_conflict(
    exc: ConflictError,
    *,
    model: type[MarketsBase],
    management_mode: MarketsManagementMode,
    timeout: int | float | tuple[float, float] | None,
) -> MetaTable | None:
    payload = _conflict_payload(exc)
    existing_uid = payload.get("existing_meta_table_uid")
    if not existing_uid:
        return None

    try:
        return MetaTable.get_by_uid(uid=str(existing_uid), timeout=timeout)
    except Exception:
        table_name = str(payload.get("physical_table_name") or model.__table__.name)
        storage_hash = str(payload.get("storage_hash") or table_name)
        return MetaTable(
            uid=str(existing_uid),
            data_source_uid=payload.get("data_source_uid"),
            storage_hash=storage_hash,
            identifier=getattr(model, "__metatable_identifier__", model.__name__),
            namespace=getattr(model, "__metatable_namespace__", None),
            management_mode=management_mode,
            physical_table_name=table_name,
        )


def _conflict_payload(exc: ConflictError) -> dict[str, Any]:
    payload = getattr(exc, "payload", None)
    if isinstance(payload, Mapping):
        return dict(payload)

    response = getattr(exc, "response", None)
    if response is None:
        return {}
    try:
        response_payload = response.json()
    except Exception:
        return {}
    if isinstance(response_payload, Mapping):
        return dict(response_payload)
    return {}


def _meta_table_uid(value: Any) -> str:
    uid = getattr(value, "uid", value)
    if uid in (None, ""):
        raise ValueError("Registered MetaTable objects must expose a non-empty uid.")
    return str(uid)


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [dict(row) for row in result if isinstance(row, Mapping)]
    if not isinstance(result, Mapping):
        return []

    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]

    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            nested_rows = _operation_result_rows(value)
            if nested_rows:
                return nested_rows
            if key == "row" or "uid" in value:
                return [dict(value)]
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]

    if "uid" in result:
        return [dict(result)]
    return []


def _sdk_version() -> str | None:
    try:
        return package_version("ms-markets")
    except PackageNotFoundError:
        return None


__all__ = [
    "CatalogBootstrapError",
    "CatalogBootstrapResult",
    "bootstrap_catalog_table",
    "bootstrap_markets_meta_tables_from_catalog",
    "catalog_repository_context",
    "find_catalog_row",
    "find_catalog_rows_by_storage_hash",
    "meta_table_from_catalog_row",
    "register_catalog_missing_meta_table",
    "resolve_catalog_meta_table",
    "upsert_catalog_row",
    "validate_catalog_contract",
]
