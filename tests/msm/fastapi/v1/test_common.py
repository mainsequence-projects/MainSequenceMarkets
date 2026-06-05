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
            "limit": 1,
            "offset": 1,
            "results": [{"uid": "row-2", "label": "Second"}],
        }
    )

    assert response.model_dump() == {
        "count": 2,
        "limit": 1,
        "offset": 1,
        "results": [{"uid": "row-2", "label": "Second"}],
    }


def test_build_paginated_response_builds_common_envelope() -> None:
    response = build_paginated_response(
        count=3,
        limit=2,
        offset=0,
        results=[ExampleRow(uid="row-1", label="First")],
    )

    assert response.model_dump() == {
        "count": 3,
        "limit": 2,
        "offset": 0,
        "results": [{"uid": "row-1", "label": "First"}],
    }


def test_paginated_response_rejects_negative_pagination_values() -> None:
    for field in ("count", "limit", "offset"):
        payload = {
            "count": 0,
            "limit": 1,
            "offset": 0,
            "results": [],
            field: -1,
        }
        with pytest.raises(ValidationError, match=field):
            PaginatedResponse[ExampleRow].model_validate(payload)
