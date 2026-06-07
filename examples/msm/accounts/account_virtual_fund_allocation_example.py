from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.accounts.account_portfolio_full_workflow import (  # noqa: E402
    run_account_portfolio_full_workflow,
)


def run_account_virtual_fund_allocation_example(
    *,
    prepare_portfolio_schema: bool = True,
    run_portfolio_data_nodes: bool = True,
    apply_plan: bool = False,
):
    """Run the full account workflow with the virtual-fund allocation extension."""

    return run_account_portfolio_full_workflow(
        prepare_portfolio_schema=prepare_portfolio_schema,
        use_portfolio_example=True,
        run_portfolio_data_nodes=run_portfolio_data_nodes,
        run_virtual_fund_allocation=True,
        apply_virtual_fund_allocation=apply_plan,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-schema-prep",
        action="store_true",
        help="Skip portfolio interpolation schema preparation.",
    )
    parser.add_argument(
        "--no-run-portfolio-data-nodes",
        action="store_true",
        help="Skip portfolio DataNode publication when creating the source account workflow.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="After printing the dry-run plan, publish the virtual-fund holdings.",
    )
    args = parser.parse_args()
    run_account_virtual_fund_allocation_example(
        prepare_portfolio_schema=not args.skip_schema_prep,
        run_portfolio_data_nodes=not args.no_run_portfolio_data_nodes,
        apply_plan=args.apply,
    )


if __name__ == "__main__":
    main()
