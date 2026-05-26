"""User-facing typed API contracts for ms-markets."""

from .assets import (
    Asset,
    AssetCreate,
    AssetUpdate,
    AssetUpsert,
)

__all__ = [
    "Asset",
    "AssetCreate",
    "AssetUpdate",
    "AssetUpsert",
]
