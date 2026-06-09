from __future__ import annotations

from pydantic import ConfigDict

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace
from apps.v1.schemas.common import PaginatedResponse


def _curve_contract():
    prepare_apps_v1_import_namespace()
    from msm_pricing.api import Curve

    return Curve


Curve = _curve_contract()


class CurveListResponse(PaginatedResponse[Curve]):
    model_config = ConfigDict(extra="ignore")
