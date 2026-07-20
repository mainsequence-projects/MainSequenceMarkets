from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any, Literal

from msm.models import IndexTable


IndexJoinKind = Literal["uid", "unique_identifier"]


@dataclass(frozen=True)
class IndexRelationshipProvider:
    """Authoritative, opt-in relationship between an extension table and Index."""

    key: str
    label: str
    owning_package: str
    storage_kind: str
    storage_model: type[Any]
    join_kind: IndexJoinKind
    join_column: str
    relationship_type: str = "direct"
    on_delete: str = "RESTRICT"
    exploration_capability: Literal["none", "count", "summary", "values"] = "count"
    meta_table_resolver: Callable[[], Any | None] | None = None

    def __post_init__(self) -> None:
        for field_name in ("key", "label", "owning_package", "storage_kind", "join_column"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"Index relationship provider {field_name} cannot be empty")
        foreign_key = require_index_foreign_key(
            self.storage_model,
            source_column=self.join_column,
            join_kind=self.join_kind,
        )
        actual_on_delete = str(foreign_key.ondelete or "RESTRICT").upper().replace(" ", "_")
        declared_on_delete = str(self.on_delete).upper().replace(" ", "_")
        if actual_on_delete != declared_on_delete:
            raise ValueError(
                f"Index relationship provider on_delete={self.on_delete!r} does not match "
                f"the actual foreign key action {foreign_key.ondelete or 'RESTRICT'!r}"
            )

    def resolve_meta_table(self) -> Any | None:
        if self.meta_table_resolver is not None:
            return self.meta_table_resolver()
        get_meta_table = getattr(self.storage_model, "get_meta_table", None)
        return get_meta_table() if callable(get_meta_table) else None


_PROVIDERS: dict[str, IndexRelationshipProvider] = {}
_PROVIDERS_LOCK = RLock()


def register_index_relationship_provider(
    provider: IndexRelationshipProvider,
    *,
    replace: bool = False,
) -> None:
    """Register one extension-owned Index relationship after proving its real FK."""

    with _PROVIDERS_LOCK:
        if provider.key in _PROVIDERS and not replace:
            raise ValueError(f"Index relationship provider {provider.key!r} is already registered")
        _PROVIDERS[provider.key] = provider


def unregister_index_relationship_provider(key: str) -> None:
    with _PROVIDERS_LOCK:
        _PROVIDERS.pop(str(key), None)


def list_index_relationship_providers() -> tuple[IndexRelationshipProvider, ...]:
    with _PROVIDERS_LOCK:
        return tuple(_PROVIDERS[key] for key in sorted(_PROVIDERS))


def require_index_foreign_key(
    storage_model: type[Any],
    *,
    source_column: str,
    join_kind: IndexJoinKind,
) -> Any:
    """Return the matching SQLAlchemy FK or reject column-name-only relationships."""

    table = getattr(storage_model, "__table__", None)
    if table is None:
        raise ValueError("Index relationship providers require a SQLAlchemy storage model")
    target_column = "uid" if join_kind == "uid" else "unique_identifier"
    for foreign_key in table.foreign_keys:
        if (
            foreign_key.parent.name == source_column
            and foreign_key.column.table.fullname == IndexTable.__table__.fullname
            and foreign_key.column.name == target_column
        ):
            return foreign_key
    raise ValueError(
        f"{storage_model.__name__}.{source_column} must have an actual foreign key to "
        f"{IndexTable.__table__.fullname}.{target_column}; a matching column name is not proof"
    )


__all__ = [
    "IndexRelationshipProvider",
    "list_index_relationship_providers",
    "register_index_relationship_provider",
    "require_index_foreign_key",
    "unregister_index_relationship_provider",
]
