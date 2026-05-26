from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from mainsequence.client.models_metatables import MetaTable, MetaTableRegistrationRequest
from mainsequence.logconf import logger as _mainsequence_logger
from mainsequence.tdag.meta_tables import (
    external_registered_registration_request_from_sqlalchemy_model,
    register_external_sqlalchemy_model,
)

from .base import MARKETS_SCHEMA, MarketsBase
from .models import markets_sqlalchemy_models


MarketsManagementMode = Literal["platform_managed", "external_registered"]
logger = _mainsequence_logger.bind(sub_application="markets", component="meta_tables")


@dataclass(frozen=True)
class MarketsMetaTableRegistrationResult:
    meta_tables: list[MetaTable]
    target_meta_table_uid_by_fullname: dict[str, str]


def markets_meta_table_models() -> list[type[MarketsBase]]:
    return list(markets_sqlalchemy_models())


def markets_meta_table_fullname(model: type[MarketsBase]) -> str:
    return str(model.__table__.fullname)


def markets_foreign_key_target_fullnames(model: type[MarketsBase]) -> list[str]:
    targets: set[str] = set()
    for foreign_key_constraint in model.__table__.foreign_key_constraints:
        for element in foreign_key_constraint.elements:
            targets.add(str(element.column.table.fullname))
    return sorted(targets)


def build_markets_registration_requests(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    target_meta_table_uid_by_fullname: Mapping[str, Any] | None = None,
    labels: Sequence[str] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_fullname: Mapping[str, str] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> list[MetaTableRegistrationRequest]:
    """Build MetaTable registration requests for all markets SQLAlchemy models.

    FK-bearing model contracts require registered target MetaTable UIDs. Callers
    that only want request construction must pass those UIDs by SQLAlchemy table
    fullname. `register_markets_meta_tables(...)` handles that mapping while it
    registers models in dependency order.
    """

    resolved_models = list(models or markets_meta_table_models())
    if management_mode == "external_registered" and not data_source_uid:
        raise ValueError("external_registered MetaTables require data_source_uid.")
    target_mapping = dict(target_meta_table_uid_by_fullname or {})
    storage_hash_mapping = dict(storage_hash_by_fullname or {})
    requests: list[MetaTableRegistrationRequest] = []

    for model in resolved_models:
        platform_kwargs = {
            "data_source_uid": data_source_uid,
            "labels": labels,
            "open_for_everyone": open_for_everyone,
            "protect_from_deletion": protect_from_deletion,
            "target_meta_table_uid_by_fullname": target_mapping,
        }
        external_kwargs = {**platform_kwargs, "schema": MARKETS_SCHEMA}
        if management_mode == "platform_managed":
            requests.append(
                model.build_registration_request(
                    introspect=False if introspect is None else introspect,
                    **platform_kwargs,
                )
            )
            continue
        if management_mode == "external_registered":
            requests.append(
                external_registered_registration_request_from_sqlalchemy_model(
                    model,
                    introspect=True if introspect is None else introspect,
                    storage_hash=storage_hash_mapping.get(markets_meta_table_fullname(model)),
                    **external_kwargs,
                )
            )
            continue
        raise ValueError(
            "management_mode must be 'platform_managed' or 'external_registered'."
        )

    return requests


def register_markets_meta_tables(
    *,
    data_source_uid: str | None = None,
    management_mode: MarketsManagementMode = "platform_managed",
    target_meta_table_uid_by_fullname: Mapping[str, Any] | None = None,
    labels: Sequence[str] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_fullname: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[type[MarketsBase]] | None = None,
) -> MarketsMetaTableRegistrationResult:
    """Register markets SQLAlchemy models as MetaTables in FK dependency order."""

    if management_mode == "external_registered" and not data_source_uid:
        raise ValueError("external_registered MetaTables require data_source_uid.")

    target_mapping = {
        str(key): _meta_table_uid(value)
        for key, value in (target_meta_table_uid_by_fullname or {}).items()
    }
    registered_meta_tables: list[MetaTable] = []
    storage_hash_mapping = dict(storage_hash_by_fullname or {})

    resolved_models = list(models or markets_meta_table_models())
    for position, model in enumerate(resolved_models, start=1):
        platform_kwargs = {
            "data_source_uid": data_source_uid,
            "labels": labels,
            "open_for_everyone": open_for_everyone,
            "protect_from_deletion": protect_from_deletion,
            "target_meta_table_uid_by_fullname": target_mapping,
            "timeout": timeout,
        }
        external_kwargs = {**platform_kwargs, "schema": MARKETS_SCHEMA}
        storage_hash = storage_hash_mapping.get(markets_meta_table_fullname(model))
        logger.info(
            "Registering markets MetaTable schema",
            management_mode=management_mode,
            model=model.__name__,
            namespace=getattr(model, "__metatable_namespace__", None),
            identifier=getattr(model, "__metatable_identifier__", None),
            model_index=position,
            model_count=len(resolved_models),
            table_fullname=markets_meta_table_fullname(model),
            table_name=model.__table__.name,
            storage_hash=storage_hash,
            target_meta_table_count=len(target_mapping),
        )
        if management_mode == "platform_managed":
            meta_table = model.register(
                introspect=False if introspect is None else introspect,
                **platform_kwargs,
            )
        elif management_mode == "external_registered":
            meta_table = register_external_sqlalchemy_model(
                model,
                introspect=True if introspect is None else introspect,
                storage_hash=storage_hash,
                **external_kwargs,
            )
        else:
            raise ValueError(
                "management_mode must be 'platform_managed' or 'external_registered'."
            )

        registered_meta_tables.append(meta_table)
        meta_table_uid = _meta_table_uid(meta_table)
        target_mapping[markets_meta_table_fullname(model)] = meta_table_uid
        logger.info(
            "Registered markets MetaTable schema",
            management_mode=management_mode,
            model=model.__name__,
            namespace=getattr(model, "__metatable_namespace__", None),
            identifier=getattr(model, "__metatable_identifier__", None),
            model_index=position,
            model_count=len(resolved_models),
            table_fullname=markets_meta_table_fullname(model),
            table_name=model.__table__.name,
            meta_table_uid=meta_table_uid,
        )

    return MarketsMetaTableRegistrationResult(
        meta_tables=registered_meta_tables,
        target_meta_table_uid_by_fullname=target_mapping,
    )


def _meta_table_uid(value: Any) -> str:
    uid = getattr(value, "uid", value)
    if uid in (None, ""):
        raise ValueError("Registered MetaTable objects must expose a non-empty uid.")
    return str(uid)


__all__ = [
    "MarketsManagementMode",
    "MarketsMetaTableRegistrationResult",
    "build_markets_registration_requests",
    "markets_foreign_key_target_fullnames",
    "markets_meta_table_fullname",
    "markets_meta_table_models",
    "register_markets_meta_tables",
]
