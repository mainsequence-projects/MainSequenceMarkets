from __future__ import annotations

from typing import Any

from msm.base import markets_meta_table_identifier
from msm.migrations.registry import migration_model_registry

REVISION = "0001_initial"
EXPECTED_CURRENT_REVISION = None
MIGRATION_NAMESPACE = None


def affected_models() -> list[type[Any]]:
    return migration_model_registry()


def operations() -> list[dict[str, Any]]:
    return [
        {
            "op": "add_column",
            "table_identifier": markets_meta_table_identifier(model),
            "column": {
                "name": str(column.name),
                "data_type": str(column.type),
                "nullable": bool(column.nullable),
                "primary_key": bool(column.primary_key),
            },
            "contract": {
                "operation": "initial_contract",
            },
        }
        for model in affected_models()
        for column in model.__table__.columns
    ]

