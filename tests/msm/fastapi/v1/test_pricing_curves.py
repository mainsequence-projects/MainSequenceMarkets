from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.schemas.pricing_curves import Curve


def _curve_row(
    *,
    uid: uuid.UUID | None = None,
    index_uid: uuid.UUID | None = None,
) -> Curve:
    return Curve(
        uid=uid or uuid.uuid4(),
        unique_identifier="USD-SOFR-DISCOUNT",
        display_name="USD SOFR Discount Curve",
        curve_type="discount",
        index_uid=index_uid or uuid.uuid4(),
        interpolation_method="log_linear_discount",
        compounding="compounded_annual",
        source="unit-test",
        metadata_json={"provider": "test"},
    )


def test_pricing_curve_list_uses_paginated_source_list(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    row = _curve_row(index_uid=index_uid)
    captured: dict[str, object] = {}

    def fake_list_curves(**kwargs):
        captured.update(kwargs)
        return {"count": 2, "limit": kwargs["limit"], "offset": kwargs["offset"], "results": [row]}

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.list_pricing_curves",
        fake_list_curves,
    )

    client = TestClient(app)
    response = client.get(
        "/api/v1/pricing/curves/",
        params={
            "limit": 1,
            "offset": 0,
            "search": "SOFR",
            "curve_type": "discount",
            "index_uid": str(index_uid),
            "source": "unit-test",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "count": 2,
        "next": (
            "http://testserver/api/v1/pricing/curves/?limit=1&offset=1&search=SOFR"
            f"&curve_type=discount&index_uid={index_uid}&source=unit-test"
        ),
        "previous": None,
        "results": [
            {
                "uid": str(row.uid),
                "unique_identifier": "USD-SOFR-DISCOUNT",
                "display_name": "USD SOFR Discount Curve",
                "curve_type": "discount",
                "index_uid": str(index_uid),
                "interpolation_method": "log_linear_discount",
                "compounding": "compounded_annual",
                "source": "unit-test",
                "metadata_json": {"provider": "test"},
            }
        ],
    }
    assert captured == {
        "limit": 1,
        "offset": 0,
        "search": "SOFR",
        "curve_type": "discount",
        "index_uid": str(index_uid),
        "source": "unit-test",
    }


def test_pricing_curve_list_returns_400_for_source_value_error(monkeypatch) -> None:
    def fake_list_curves(**_kwargs):
        raise ValueError("bad curve filter")

    monkeypatch.setattr(
        "apps.v1.routers.pricing_curves.list_pricing_curves",
        fake_list_curves,
    )

    client = TestClient(app)
    response = client.get("/api/v1/pricing/curves/")

    assert response.status_code == 400
    assert response.json() == {"detail": "bad curve filter"}
