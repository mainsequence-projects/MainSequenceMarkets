"""Plan or apply a scoped rollback for legacy midnight portfolio values."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

import msm_portfolios  # noqa: E402
from msm_portfolios.services import (  # noqa: E402
    apply_legacy_midnight_portfolio_timestamp_repair,
    plan_legacy_midnight_portfolio_timestamp_repair,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portfolio-identifier",
        action="append",
        required=True,
        help="Portfolio unique identifier. Repeat only for a multi-portfolio dry run.",
    )
    parser.add_argument("--start", required=True, help="Inclusive ISO timestamp to inspect.")
    parser.add_argument("--end", required=True, help="Inclusive ISO timestamp to inspect.")
    parser.add_argument("--session-label", default="regular")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply one portfolio-scoped tail rollback. Omit for the default dry run.",
    )
    args = parser.parse_args(argv)

    if args.apply and len(args.portfolio_identifier) != 1:
        parser.error("--apply requires exactly one --portfolio-identifier")

    runtime = msm_portfolios.start_engine(
        models=["Calendar", "CalendarSession", "Portfolio", "PortfoliosStorage"]
    )
    plan = plan_legacy_midnight_portfolio_timestamp_repair(
        args.portfolio_identifier,
        start=args.start,
        end=args.end,
        session_label=args.session_label,
        repository_context=runtime.context,
    )
    payload: dict = {"plan": plan.to_dict()}
    if args.apply:
        result = apply_legacy_midnight_portfolio_timestamp_repair(
            plan,
            timeout=runtime.context.timeout,
        )
        payload["result"] = result
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.apply and not result["delete_count_matches_plan"]:
        return 3
    return 2 if plan.issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
