from __future__ import annotations

from msm.base import MarketsBase
from msm.models.assets import AssetTable

from .models.pricing_details import AssetCurrentPricingDetailsTable


def pricing_sqlalchemy_models() -> list[type[MarketsBase]]:
    """Return pricing SQLAlchemy models in MetaTable dependency order."""

    return [
        AssetTable,
        AssetCurrentPricingDetailsTable,
    ]


__all__ = ["pricing_sqlalchemy_models"]
