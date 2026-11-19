"""The Markets datasets that hold a portfolio's rows (ADR 0049, ADR 0050).

Each dataset is a Markets table keyed by ``portfolio_identifier``, whose ``RESTRICT``
key on ``Portfolio.unique_identifier`` lets a portfolio row go only after its rows
there. Core ``msm`` does not define these tables and does not import the package that
does (ADR 0019). That package registers them here when it defines them, and the
account delete reads them here to delete an account's portfolios with it (issue 91).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PortfolioDatasetTable:
    """One Markets dataset keyed by ``portfolio_identifier``.

    ``catalog_column`` names the ``PortfolioDatasetAvailability`` column that can place
    the portfolio's rows in another application's instance of the table instead
    (ADR 0047). Markets never deletes rows there.
    """

    key: str
    model: type[Any]
    catalog_column: str | None = None

    @property
    def table_name(self) -> str:
        return str(self.model.__table__.name)


_registered: tuple[PortfolioDatasetTable, ...] = ()


def register_portfolio_dataset_tables(tables: Sequence[PortfolioDatasetTable]) -> None:
    """Register the portfolio datasets, in the order a delete clears them.

    Each model must carry an actual key from ``portfolio_identifier`` to
    ``Portfolio.unique_identifier``; a matching column name is not proof. A later
    registration replaces this one.
    """

    from msm.models import PortfolioDatasetAvailabilityTable, PortfolioTable

    global _registered
    registered = tuple(tables)
    keys = [table.key for table in registered]
    if len(set(keys)) != len(keys):
        raise ValueError(f"Portfolio dataset keys must be unique, got {keys}.")
    target = f"{PortfolioTable.__table__.fullname}.unique_identifier"
    catalog_columns = PortfolioDatasetAvailabilityTable.__table__.columns
    for table in registered:
        column = table.model.__table__.columns.get("portfolio_identifier")
        if column is None or not any(key.target_fullname == target for key in column.foreign_keys):
            raise ValueError(
                f"{table.model.__name__}.portfolio_identifier must have a foreign key to {target}."
            )
        if table.catalog_column is not None and table.catalog_column not in catalog_columns:
            raise ValueError(
                f"{table.catalog_column!r} is not a column of "
                f"{PortfolioDatasetAvailabilityTable.__table__.name}."
            )
    _registered = registered


def portfolio_dataset_tables() -> tuple[PortfolioDatasetTable, ...]:
    """The registered portfolio datasets, in the order a delete clears them.

    Raises `RuntimeError` when none are registered: a portfolio row cannot be deleted
    without its rows in them.
    """

    if not _registered:
        raise RuntimeError(
            "No portfolio datasets are registered in this process, so a portfolio cannot "
            "be deleted with its rows. The portfolio storages register them when they are "
            "imported."
        )
    return _registered


__all__ = [
    "PortfolioDatasetTable",
    "portfolio_dataset_tables",
    "register_portfolio_dataset_tables",
]
