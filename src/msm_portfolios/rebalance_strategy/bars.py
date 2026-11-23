"""Strategies that trade at their own bars, a slice of a fixed order per bar (#90).

A bar strategy sizes each rebalance once, at its decision, as ``ImmediateSignal``
does: target weight x NAV / price, with each asset's last bar strictly before the
earliest moment, the first of the strategy's bars after the signal. At every bar its
``bar_slices`` decide how much of each order may trade there, and its
``execution_policy`` books the slices on the rebalance's book of shares and cash
(``RebalanceStrategyBase._transitions_at_own_bars``).

The book's unit is the NAV at the portfolio's first rebalance. A strategy whose
capacity is in money or volume needs that unit in the portfolio's currency:
``total_notional`` is it.
"""

from __future__ import annotations

from pydantic import Field

from .base import RebalanceStrategyBase
from .execution_policy import ExecutionPolicy


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
    """A bar strategy whose capacity is in money or volume, with a size in money."""

    total_notional: float = Field(
        gt=0,
        description=(
            "The money one unit of the strategy's book stands for, in the portfolio's "
            "currency: the portfolio's NAV at its first rebalance. It turns a bar's "
            "volume or liquidity capacity into shares of the decided order, and a "
            "fixed-amount negative cash limit into the book's unit. Required: whoever "
            "runs the strategy gives it, and there is no default size (#113)."
        ),
    )

    def book_unit_value(self, ledger_unit_value: float | None) -> float:
        """The book's unit is ``total_notional``, with or without a ledger."""
        del ledger_unit_value
        return self.total_notional

    def shares_for_quantity(self, quantity: float) -> float:
        """Return a quantity of the asset as shares of the book."""
        return quantity / self.total_notional

    def shares_for_notional(self, notional: float, price: float) -> float:
        """Return an amount in the portfolio's currency, at ``price``, as shares of the book."""
        return notional / (self.total_notional * price)


__all__ = ["BarStrategy", "SizedBarStrategy"]
