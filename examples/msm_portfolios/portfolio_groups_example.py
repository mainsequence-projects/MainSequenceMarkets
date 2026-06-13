from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import (  # noqa: E402
    EXAMPLE_METATABLE_NAMESPACE,
    EXAMPLE_NAMESPACE_ENV,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm  # noqa: E402
from msm.api.calendars import Calendar, CalendarType  # noqa: E402
from msm.api.portfolios import Portfolio, PortfolioGroup  # noqa: E402

EXAMPLE_PORTFOLIO_UNIQUE_IDENTIFIER = "example-grouped-portfolio"
EXAMPLE_PORTFOLIO_GROUPS = [
    {
        "unique_identifier": "example-core-portfolios",
        "display_name": "Example Core Portfolios",
        "description": "Portfolios used in core allocation workflows.",
    },
    {
        "unique_identifier": "example-crypto-portfolios",
        "display_name": "Example Crypto Portfolios",
        "description": "Portfolios with crypto asset exposure.",
    },
]


def run_portfolio_group_workflow() -> dict[str, Any]:
    """Create one portfolio and assign it to multiple portfolio groups."""

    msm.start_engine(
        models=[
            "Calendar",
            "IndexType",
            "Index",
            "SignalMetadata",
            "Portfolio",
            "PortfolioGroup",
            "PortfolioGroupMembership",
        ],
    )

    calendar = Calendar.upsert(
        unique_identifier="EXAMPLE_GROUP_PORTFOLIO_CALENDAR",
        display_name="Example Group Portfolio Calendar",
        calendar_type=CalendarType.TRADING,
        timezone="UTC",
        source="example",
        source_identifier="portfolio_groups_example",
        valid_from=dt.date(2026, 1, 1),
        valid_to=dt.date(2026, 12, 31),
    )
    portfolio = Portfolio.upsert(
        unique_identifier=EXAMPLE_PORTFOLIO_UNIQUE_IDENTIFIER,
        calendar_uid=calendar.uid,
    )
    groups = [PortfolioGroup.add(**payload) for payload in EXAMPLE_PORTFOLIO_GROUPS]
    memberships = [
        PortfolioGroup.add_portfolio(
            portfolio_group_uid=group.uid,
            portfolio_uid=portfolio.uid,
        )
        for group in groups
    ]

    portfolios_in_first_group = PortfolioGroup.get_portfolios(
        portfolio_group_uid=groups[0].uid,
    )
    groups_for_portfolio = PortfolioGroup.get_groups_for_portfolio(
        portfolio_uid=portfolio.uid,
    )

    return {
        "calendar": calendar,
        "portfolio": portfolio,
        "groups": groups,
        "memberships": memberships,
        "portfolios_in_first_group": portfolios_in_first_group,
        "groups_for_portfolio": groups_for_portfolio,
    }


def main() -> None:
    print(run_portfolio_group_workflow())


if __name__ == "__main__":
    main()
