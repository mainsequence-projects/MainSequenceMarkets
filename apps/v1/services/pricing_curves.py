from __future__ import annotations

from apps.v1.runtime_bootstrap import ensure_apps_v1_pricing_runtime
from apps.v1.schemas.pricing_curves import Curve


def list_pricing_curves(
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    curve_type: str | None = None,
    index_uid: str | None = None,
    source: str | None = None,
) -> dict:
    ensure_apps_v1_pricing_runtime()
    return Curve.list(
        limit=limit,
        offset=offset,
        search=search,
        curve_type=curve_type,
        index_uid=index_uid,
        source=source,
    )
