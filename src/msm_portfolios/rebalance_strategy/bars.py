"""Strategies that trade at their own bars, a slice of a fixed order per bar (#90).

A bar strategy sizes each rebalance once, at its decision, as ``ImmediateSignal``
does: target weight x NAV / price, with each asset's last bar strictly before the
earliest moment, the first of the strategy's bars after the signal. At every bar its
``bar_slices`` decide how much of each order may trade there, and its
``execution_policy`` books the slices on the rebalance's book of shares and cash
(``RebalanceStrategyBase._transitions_at_own_bars``).

The book's unit is the NAV at the portfolio's first rebalance, the ledger's
``initial_nav`` (ADR 0065, decision 7). A strategy whose capacity is in money or volume
turns it into shares of the book with that unit, which the book carries.
"""

from __future__ import annotations

from pydantic import Field

from .base import RebalanceStrategyBase
from .execution_policy import ExecutionPolicy, RebalanceBook


class BarStrategy(RebalanceStrategyBase):
    """A strategy with its own bars, run by the same execution policy as the others."""

    execution_policy: ExecutionPolicy = Field(
        default_factory=ExecutionPolicy,
        description=(
            "Execution choices for the strategy's fills (ADR 0058, #90): sizing time, "
            "negative cash limit, sells before buys, cash shortfall allocation and "
            "uncovered buys. A strategy with its own bars reads no calendar, so "
            "calendar_gating has nothing to gate."
        ),
    )

    def fill_policy(self) -> ExecutionPolicy:
        return self.execution_policy


class SizedBarStrategy(BarStrategy):
    """A bar strategy whose capacity is in money or volume.

    Its book's unit is the portfolio's initial NAV (ADR 0065, decision 7): a bar's
    capacity of ``q`` shares is ``q / unit`` shares of the book, and an amount ``a`` at
    price ``p`` is ``a / (unit x p)``.
    """

    @staticmethod
    def book_unit(book: RebalanceBook) -> float:
        """One unit of ``book`` in the portfolio's currency: its initial NAV."""
        if book.unit_value is None or book.unit_value <= 0:
            raise ValueError(
                "A strategy sized in money or volume needs the book's unit, the "
                "portfolio's initial NAV (ADR 0065)."
            )
        return float(book.unit_value)

    def shares_for_quantity(self, quantity: float, *, book: RebalanceBook) -> float:
        """Return a quantity of the asset as shares of the book."""
        return quantity / self.book_unit(book)

    def shares_for_notional(self, notional: float, price: float, *, book: RebalanceBook) -> float:
        """Return an amount in the portfolio's currency, at ``price``, as shares of the book."""
        return notional / (self.book_unit(book) * price)


__all__ = ["BarStrategy", "SizedBarStrategy"]
