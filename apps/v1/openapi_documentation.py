"""OpenAPI documentation derived from canonical markets model metadata."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from msm.api.base import MarketsMetaTableRow


def apply_metatable_documentation(openapi_schema: dict[str, Any]) -> None:
    """Enrich row schemas from their backing MetaTable without duplicating descriptions."""

    schemas = openapi_schema.get("components", {}).get("schemas", {})
    for row_model in _model_subclasses(MarketsMetaTableRow):
        schema = schemas.get(row_model.__name__)
        table_model = getattr(row_model, "__table__", None)
        sqlalchemy_table = getattr(table_model, "__table__", None)
        if not isinstance(schema, dict) or sqlalchemy_table is None:
            continue

        description = getattr(table_model, "__metatable_description__", None)
        if isinstance(description, str) and description.strip():
            schema["description"] = description.strip()

        properties = schema.get("properties", {})
        for field_name, property_schema in properties.items():
            if field_name not in sqlalchemy_table.c or not isinstance(property_schema, dict):
                continue
            column_info = sqlalchemy_table.c[field_name].info or {}
            label = column_info.get("label")
            field_description = column_info.get("description")
            if isinstance(label, str) and label.strip():
                property_schema.setdefault("title", label.strip())
            if isinstance(field_description, str) and field_description.strip():
                property_schema.setdefault("description", field_description.strip())


def _model_subclasses(root: type[MarketsMetaTableRow]) -> Iterator[type[MarketsMetaTableRow]]:
    seen: set[type[MarketsMetaTableRow]] = set()
    pending = list(root.__subclasses__())
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        pending.extend(model.__subclasses__())
        yield model


__all__ = ["apply_metatable_documentation"]
