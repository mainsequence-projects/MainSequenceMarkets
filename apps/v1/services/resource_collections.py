"""Thin HTTP-boundary helpers for canonical resource collections."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from fastapi import HTTPException

from apps.v1.schemas.resource_contracts import ResourceCollection, build_resource_collection

ResourceT = TypeVar("ResourceT")


def resource_collection_response(
    *,
    items: Sequence[ResourceT],
    limit: int,
    offset: int,
    total_items: int,
) -> ResourceCollection[ResourceT]:
    try:
        return build_resource_collection(
            items=items,
            limit=limit,
            offset=offset,
            total_items=total_items,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


__all__ = ["resource_collection_response"]
