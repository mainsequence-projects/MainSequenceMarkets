from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm


def main() -> None:
    """Register separate index convention and curve identity rows for pricing."""

    msm.start_engine(
        models=["IndexType", "Index"],
    )

    from msm.api.indices import Index, IndexType
    from msm.constants import (
        INDEX_TYPE_INTEREST_RATE,
        INDEX_TYPE_INTEREST_RATE_DEFINITION,
    )
    from msm_pricing.api import Curve, IndexConventionDetails
    from msm_pricing.bootstrap import attach_pricing_schemas

    attach_pricing_schemas(
        models=[
            "IndexType",
            "Index",
            "IndexConventionDetails",
            "Curve",
        ],
    )

    IndexType.upsert(**INDEX_TYPE_INTEREST_RATE_DEFINITION.as_payload())
    index = Index.upsert(
        unique_identifier="USD-SOFR",
        index_type=INDEX_TYPE_INTEREST_RATE,
        display_name="USD SOFR",
        provider="example",
    )

    IndexConventionDetails.upsert(
        index_uid=index.uid,
        index_family="overnight",
        convention_dump={
            "currency_code": "USD",
            "day_counter_code": "Actual360",
            "fixing_calendar_code": "US",
            "period": "1D",
            "settlement_days": 0,
            "business_day_convention": "Following",
        },
        source="example",
    )

    curve = Curve.upsert(
        unique_identifier="USD-SOFR-DISCOUNT",
        display_name="USD SOFR Discount Curve",
        curve_type="discount",
        interpolation_method="log_linear",
        compounding="continuous",
        source="example",
    )

    print(
        "registered index convention "
        f"{index.unique_identifier} and curve {curve.unique_identifier}"
    )


if __name__ == "__main__":
    main()
