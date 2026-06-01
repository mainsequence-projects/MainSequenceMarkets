"""Packaged ms-markets MetaTable migrations."""

from __future__ import annotations

from .registry import MIGRATION_MODEL_REGISTRY, migration_model_registry

__all__ = [
    "MIGRATION_MODEL_REGISTRY",
    "migration_model_registry",
]
