from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from apps.v1.schemas.common import PaginatedResponse, build_paginated_response


class ExampleRow(BaseModel):
    uid: str
    label: str


def test_paginated_response_validates_shared_shape() -> None:
    response = PaginatedResponse[ExampleRow].model_validate(
        {
            "count": 2,
            "next": "http://testserver/example/?limit=1&offset=2",
            "previous": "http://testserver/example/?limit=1&offset=0",
            "results": [{"uid": "row-2", "label": "Second"}],
        }
    )

    assert response.model_dump() == {
        "count": 2,
        "next": "http://testserver/example/?limit=1&offset=2",
        "previous": "http://testserver/example/?limit=1&offset=0",
        "results": [{"uid": "row-2", "label": "Second"}],
    }


def test_build_paginated_response_builds_limit_offset_envelope() -> None:
    response = build_paginated_response(
        request_url="http://testserver/example/?search=row&limit=2&offset=2",
        limit=2,
        offset=2,
        count=5,
        results=[
            ExampleRow(uid="row-3", label="Third"),
            ExampleRow(uid="row-4", label="Fourth"),
        ],
    )

    assert response.model_dump() == {
        "count": 5,
        "next": "http://testserver/example/?search=row&limit=2&offset=4",
        "previous": "http://testserver/example/?search=row&limit=2&offset=0",
        "results": [
            {"uid": "row-3", "label": "Third"},
            {"uid": "row-4", "label": "Fourth"},
        ],
    }


def test_build_paginated_response_trims_extra_row_and_derives_next() -> None:
    response = build_paginated_response(
        request_url="http://testserver/example/?limit=2&offset=0",
        limit=2,
        offset=0,
        results=[
            ExampleRow(uid="row-1", label="First"),
            ExampleRow(uid="row-2", label="Second"),
            ExampleRow(uid="row-3", label="Third"),
        ],
    )

    assert response.model_dump() == {
        "count": 3,
        "next": "http://testserver/example/?limit=2&offset=2",
        "previous": None,
        "results": [
            {"uid": "row-1", "label": "First"},
            {"uid": "row-2", "label": "Second"},
        ],
    }


def test_paginated_response_rejects_negative_count() -> None:
    with pytest.raises(ValidationError, match="count"):
        PaginatedResponse[ExampleRow].model_validate(
            {
                "count": -1,
                "next": None,
                "previous": None,
                "results": [],
            }
        )
