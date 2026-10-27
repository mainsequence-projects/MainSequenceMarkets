"""Canonical Index value storage."""

from __future__ import annotations

import datetime
import re
import uuid
from functools import lru_cache
from typing import Any, ClassVar

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index as SqlIndex,
    String,
    Table,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from metatables import PlatformTimeIndexMetaTable, schema_index_name

from msm.base import (
    MARKETS_TABLE_APP,
    MarketsBase,
    MarketsTimeIndexMetaTableMixin,
    markets_table_name,
)
from msm.models.index_formulas import IndexFormulaDefinitionTable
from msm.models.indices import IndexTable
from msm.settings import INDEX_IDENTIFIER_DIMENSION

INDEX_VALUES_CADENCE_COMPONENT = "cadence"
INDEX_VALUES_STORAGE_NAME_COMPONENT = "storage_name"


class IndexValuesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Schema anchor for canonical Index observations.

    Production datasets with a stable frequency use
    :func:`configured_index_values_storage` so cadence participates in the
    MetaTable identity and physical table name.
    """

    __metatable_identifier__ = "IndexValuesTS"
    __metatable_description__ = (
        "Schema anchor for canonical Index values keyed by (time_index, index_identifier). "
        "Stable-frequency publication uses a cadence-configured physical storage table so "
        "frequency is part of dataset identity and table naming."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", INDEX_IDENTIFIER_DIMENSION]
    __metatable_extra_hash_components__ = {"storage_name": "index_values"}
    __table_args__ = (
        SqlIndex(None, INDEX_IDENTIFIER_DIMENSION, "time_index"),
        SqlIndex(None, "definition_uid"),
        SqlIndex(None, "observation_status"),
    )

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp at which the canonical Index observation applies.",
        },
    )
    index_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{IndexTable.__table__.fullname}.unique_identifier", ondelete="RESTRICT"),
        nullable=False,
        info={
            "label": "Index Identifier",
            "description": "Canonical Index.unique_identifier for the published observable.",
        },
    )
    value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Index Value",
            "description": "Canonical value of the Index at the observation timestamp.",
        },
    )
    definition_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IndexFormulaDefinitionTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=True,
        info={
            "label": "Definition UID",
            "description": (
                "Exact immutable formula version used for a formula observation; "
                "null when custom code publishes the Index value."
            ),
        },
    )
    observation_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        info={
            "label": "Observation Status",
            "description": (
                "Optional readiness or quality state such as ready, preliminary, stale, "
                "partial, or corrected, independent of how the value was produced."
            ),
        },
    )
    source_as_of: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Source As Of",
            "description": (
                "Latest source-observation timestamp contributing to the value, when meaningful."
            ),
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": (
                "Bounded observation or calculation provenance not represented by canonical columns."
            ),
        },
    )


def index_values_storage_identity_components(*, cadence: str) -> dict[str, str]:
    """Return storage-identity components for one canonical Index-value cadence."""

    normalized_cadence = str(cadence).strip().lower()
    if not normalized_cadence:
        raise ValueError("Index value storage cadence must be a non-empty string")
    if re.fullmatch(r"[1-9][0-9]*(?:s|m|h|d|w|mo|q|y)", normalized_cadence) is None:
        raise ValueError(
            "Index value storage cadence must use a canonical interval such as "
            "1m, 5m, 1h, 1d, 1w, 1mo, 1q, or 1y"
        )
    return {
        INDEX_VALUES_STORAGE_NAME_COMPONENT: "index_values",
        INDEX_VALUES_CADENCE_COMPONENT: normalized_cadence,
    }


def index_values_output_table_name(*, cadence: str) -> str:
    """Return the frequency-specific physical table name for canonical Index values."""

    components = index_values_storage_identity_components(cadence=cadence)
    return markets_table_name(
        MARKETS_TABLE_APP,
        "index_values",
        suffix=components[INDEX_VALUES_CADENCE_COMPONENT],
    )


def configured_index_values_storage(
    *,
    cadence: str,
    namespace: str | None = None,
    storage_app: str | None = None,
    base: type[Any] | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build one canonical Index-value storage class for a stable cadence.

    By default this is Markets' own ``ms_markets__index_values__t_<cadence>`` in
    the Markets namespace. A provider that publishes Index values owns its table
    (ADR 0047, decision 4): it passes its ``namespace``, its ``storage_app`` and,
    when its own Alembic provider migrates the table, its declarative ``base``.
    The table is then ``<storage_app>__index_values__t_<cadence>`` in that
    namespace, with the same columns, foreign keys, grain and authored identifier
    ``IndexValuesTS.<cadence>``; the Index dataset catalog discovers it like the
    Markets table.
    """

    components = index_values_storage_identity_components(cadence=cadence)
    normalized_cadence = components[INDEX_VALUES_CADENCE_COMPONENT]
    if namespace is None and storage_app is None and base is None:
        return _configured_index_values_storage(normalized_cadence)

    from msm.settings import markets_namespace

    app = str(storage_app or "").strip()
    if not app or app == MARKETS_TABLE_APP:
        raise ValueError(
            "A provider Index-value table needs its own storage_app; "
            f"{MARKETS_TABLE_APP!r} names the Markets table."
        )
    return _provider_index_values_storage(
        normalized_cadence, markets_namespace(namespace), app, base or MarketsBase
    )


@lru_cache(maxsize=64)
def _configured_index_values_storage(
    normalized_cadence: str,
) -> type[PlatformTimeIndexMetaTable]:
    components = index_values_storage_identity_components(cadence=normalized_cadence)
    table_name = index_values_output_table_name(cadence=normalized_cadence)
    table = _copy_index_values_table(table_name)
    class_suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", normalized_cadence)
    return type(
        f"IndexValuesStorage_{class_suffix}",
        (MarketsTimeIndexMetaTableMixin, MarketsBase),
        {
            "__module__": __name__,
            "__table__": table,
            "__metatable_identifier__": f"IndexValuesTS.{normalized_cadence}",
            "__metatable_description__": (
                "Canonical Index value history at "
                f"{normalized_cadence} cadence, keyed by "
                "(time_index, index_identifier), for custom and formula observables."
            ),
            "__metatable_extra_hash_components__": components,
            "__time_index_name__": IndexValuesStorage.__time_index_name__,
            "__cadence__": normalized_cadence,
            "__index_names__": list(IndexValuesStorage.__index_names__),
        },
    )


@lru_cache(maxsize=64)
def _provider_index_values_storage(
    normalized_cadence: str,
    namespace: str,
    storage_app: str,
    base: type[Any],
) -> type[PlatformTimeIndexMetaTable]:
    from msm.settings import markets_identifier

    components = index_values_storage_identity_components(cadence=normalized_cadence)
    table_name = markets_table_name(storage_app, "index_values", suffix=normalized_cadence)
    authored_identifier = f"IndexValuesTS.{normalized_cadence}"
    table = _copy_index_values_table(
        table_name,
        metadata=base.metadata,
        info={
            "namespace": namespace,
            "identifier": markets_identifier(authored_identifier, namespace=namespace),
            "markets_storage_app": storage_app,
        },
    )
    class_suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", f"{storage_app}_{normalized_cadence}")
    return type(
        f"IndexValuesStorage_{class_suffix}",
        (MarketsTimeIndexMetaTableMixin, base),
        {
            "__module__": __name__,
            "__table__": table,
            "__metatable_identifier__": authored_identifier,
            "__metatable_namespace__": namespace,
            "__markets_storage_app__": storage_app,
            "__metatable_description__": (
                f"Index value history at {normalized_cadence} cadence published by "
                f"{storage_app}, keyed by (time_index, index_identifier)."
            ),
            "__metatable_extra_hash_components__": components,
            "__time_index_name__": IndexValuesStorage.__time_index_name__,
            "__cadence__": normalized_cadence,
            "__index_names__": list(IndexValuesStorage.__index_names__),
        },
    )


def require_cadenced_index_values_storage(
    output_table: type[PlatformTimeIndexMetaTable],
) -> str:
    """Return a storage cadence or reject a mixed/unspecified-frequency target."""

    cadence = getattr(output_table, "__cadence__", None)
    if cadence in (None, ""):
        raise ValueError(
            "canonical Index values require a cadence-specific storage table; "
            "build one with configured_index_values_storage(cadence=...)"
        )
    normalized_cadence = index_values_storage_identity_components(cadence=str(cadence))[
        INDEX_VALUES_CADENCE_COMPONENT
    ]
    hash_components = getattr(output_table, "__metatable_extra_hash_components__", {})
    if hash_components.get(INDEX_VALUES_STORAGE_NAME_COMPONENT) != "index_values" or (
        hash_components.get(INDEX_VALUES_CADENCE_COMPONENT) != normalized_cadence
    ):
        raise ValueError(
            "canonical Index values require cadence-specific storage hash components; "
            "build the table with configured_index_values_storage(cadence=...)"
        )
    identifier = str(getattr(output_table, "__metatable_identifier__", ""))
    if not identifier.endswith(f"IndexValuesTS.{normalized_cadence}"):
        raise ValueError(
            "canonical Index values require a cadence-specific IndexValuesTS identifier; "
            "build the table with configured_index_values_storage(cadence=...)"
        )
    return normalized_cadence


def _copy_index_values_table(
    table_name: str,
    *,
    metadata: Any = None,
    info: dict[str, Any] | None = None,
) -> Table:
    metadata = MarketsBase.metadata if metadata is None else metadata
    existing = metadata.tables.get(table_name)
    if isinstance(existing, Table):
        return existing

    from msm.storage_instances import markets_reference_table

    index_table = markets_reference_table(IndexTable.__table__, metadata, ["unique_identifier"])
    definition_table = markets_reference_table(
        IndexFormulaDefinitionTable.__table__, metadata, ["uid"]
    )
    columns = [column._copy() for column in IndexValuesStorage.__table__.columns]
    table = Table(
        table_name,
        metadata,
        *columns,
        ForeignKeyConstraint(
            [INDEX_IDENTIFIER_DIMENSION],
            [f"{index_table.fullname}.unique_identifier"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["definition_uid"],
            [f"{definition_table.fullname}.uid"],
            ondelete="RESTRICT",
        ),
        schema=IndexValuesStorage.__table__.schema,
        info=dict(info if info is not None else (IndexValuesStorage.__table__.info or {})),
    )
    SqlIndex(
        schema_index_name(table_name, IndexValuesStorage.__index_names__, unique=True),
        *(table.c[column_name] for column_name in IndexValuesStorage.__index_names__),
        unique=True,
    )
    SqlIndex(
        schema_index_name(
            table_name,
            [INDEX_IDENTIFIER_DIMENSION, "time_index"],
            unique=False,
        ),
        table.c.index_identifier,
        table.c.time_index,
    )
    SqlIndex(
        schema_index_name(table_name, ["definition_uid"], unique=False),
        table.c.definition_uid,
    )
    SqlIndex(
        schema_index_name(table_name, ["observation_status"], unique=False),
        table.c.observation_status,
    )
    return table


__all__ = [
    "INDEX_VALUES_CADENCE_COMPONENT",
    "INDEX_VALUES_STORAGE_NAME_COMPONENT",
    "IndexValuesStorage",
    "configured_index_values_storage",
    "index_values_storage_identity_components",
    "index_values_output_table_name",
    "require_cadenced_index_values_storage",
]
