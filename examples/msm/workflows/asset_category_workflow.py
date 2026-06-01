from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.assets.asset_category_workflow import (
    main,
    run_asset_category_workflow,
)

__all__ = ["main", "run_asset_category_workflow"]


if __name__ == "__main__":
    main()
