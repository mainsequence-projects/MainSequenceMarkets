from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_AUTO_REGISTER_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_AUTO_REGISTER_ENV, EXAMPLE_METATABLE_NAMESPACE)


def main() -> None:
    """Register an index convention row and a curve identity row for pricing."""

    from msm.api.indices import Index
    from msm_pricing.api import Curve, IndexConventionDetails

    index = Index.upsert(
        unique_identifier="USD-SOFR",
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
        index_uid=index.uid,
        interpolation_method="log_linear",
        compounding="continuous",
        source="example",
    )

    print(f"registered curve {curve.unique_identifier} for index {index.unique_identifier}")


if __name__ == "__main__":
    main()
