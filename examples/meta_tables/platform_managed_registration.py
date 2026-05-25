from __future__ import annotations

from msm.meta_tables import register_markets_meta_tables
from msm.repositories import MarketsRepositoryContext


def register_platform_managed_markets(data_source_uid: str) -> MarketsRepositoryContext:
    """Register all msm SQLAlchemy models and return an execution context."""

    registration = register_markets_meta_tables(
        data_source_uid=data_source_uid,
        management_mode="platform_managed",
        labels=["markets"],
        open_for_everyone=False,
        protect_from_deletion=True,
    )
    return MarketsRepositoryContext(
        target_meta_table_uid_by_fullname=registration.target_meta_table_uid_by_fullname,
        limits={"max_rows": 1000, "statement_timeout_ms": 15000},
    )


if __name__ == "__main__":
    raise SystemExit(
        "Call register_platform_managed_markets(data_source_uid) from your "
        "application setup code with the platform data-source UID selected by "
        "your workspace configuration."
    )
