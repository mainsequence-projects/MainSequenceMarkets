from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm_portfolios.portfolio_equal_weights_example import (  # noqa: E402
    build_equal_weight_portfolio,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-run-data-nodes",
        action="store_true",
        help="Skip DataNode publication; by default the full dependency tree is published.",
    )
    args = parser.parse_args()
    build_equal_weight_portfolio(run_data_nodes=not args.no_run_data_nodes)


if __name__ == "__main__":
    main()
