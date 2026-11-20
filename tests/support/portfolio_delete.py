"""The portfolio delete's helpers that the account delete with portfolios shares."""

from __future__ import annotations


def series_index(table) -> str:
    """The dataset's index that leads with ``portfolio_identifier`` (revisions 0026, 0031)."""

    (name,) = [index.name for index in table.model.__table__.indexes if not index.unique]
    return name
