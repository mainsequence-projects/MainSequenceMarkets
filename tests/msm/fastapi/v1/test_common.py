from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from apps.v1.schemas.resource_contracts import (
    ResourceCollection,
    build_resource_collection,
)


class ExampleRow(BaseModel):
    uid: str
    label: str


def test_resource_collection_validates_canonical_shape() -> None:
    response = ResourceCollection[ExampleRow].model_validate(
        {
            "items": [{"uid": "row-2", "label": "Second"}],
            "pageInfo": {
                "pageIndex": 1,
                "pageSize": 1,
                "totalItems": 2,
                "hasNextPage": False,
                "hasPreviousPage": True,
            },
        }
    )

    assert response.model_dump(by_alias=True) == {
        "items": [{"uid": "row-2", "label": "Second"}],
        "pageInfo": {
            "pageIndex": 1,
            "pageSize": 1,
            "totalItems": 2,
            "hasNextPage": False,
            "hasPreviousPage": True,
        },
    }


def test_build_resource_collection_builds_exact_page_info() -> None:
    response = build_resource_collection(
        limit=2,
        offset=2,
        total_items=5,
        items=[
            ExampleRow(uid="row-3", label="Third"),
            ExampleRow(uid="row-4", label="Fourth"),
        ],
    )

    assert response.model_dump(by_alias=True) == {
        "items": [
            {"uid": "row-3", "label": "Third"},
            {"uid": "row-4", "label": "Fourth"},
        ],
        "pageInfo": {
            "pageIndex": 1,
            "pageSize": 2,
            "totalItems": 5,
            "hasNextPage": True,
            "hasPreviousPage": True,
        },
    }


def test_build_resource_collection_rejects_misaligned_offset() -> None:
    with pytest.raises(ValueError, match="aligned"):
        build_resource_collection(items=[], limit=2, offset=1, total_items=0)


def test_resource_collection_rejects_negative_total() -> None:
    with pytest.raises(ValidationError, match="totalItems"):
        ResourceCollection[ExampleRow].model_validate(
            {
                "items": [],
                "pageInfo": {
                    "pageIndex": 0,
                    "pageSize": 25,
                    "totalItems": -1,
                    "hasNextPage": False,
                    "hasPreviousPage": False,
                },
            }
        )
