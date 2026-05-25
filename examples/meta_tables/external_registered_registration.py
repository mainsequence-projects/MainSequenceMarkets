from __future__ import annotations

from sqlalchemy import Engine

from msm.base import MarketsBase
from msm.meta_tables import markets_meta_table_fullname, register_markets_meta_tables
from msm.models import markets_sqlalchemy_models
from msm.repositories import MarketsRepositoryContext


def create_physical_tables(engine: Engine) -> None:
    """Application-owned DDL path for external_registered mode."""

    for model in markets_sqlalchemy_models():
        model.__table__.create(bind=engine, checkfirst=True)


def register_external_markets(
    data_source_uid: str,
    *,
    storage_hash_by_fullname: dict[str, str] | None = None,
) -> MarketsRepositoryContext:
    """Register externally managed markets tables for governed execution."""

    registration = register_markets_meta_tables(
        data_source_uid=data_source_uid,
        management_mode="external_registered",
        storage_hash_by_fullname=storage_hash_by_fullname or _default_storage_hashes(),
        labels=["markets"],
        introspect=True,
    )
    return MarketsRepositoryContext(
        target_meta_table_uid_by_fullname=registration.target_meta_table_uid_by_fullname,
        limits={"max_rows": 1000, "statement_timeout_ms": 15000},
    )


def _default_storage_hashes() -> dict[str, str]:
    return {
        markets_meta_table_fullname(model): model.__table__.name
        for model in markets_sqlalchemy_models()
        if issubclass(model, MarketsBase)
    }
