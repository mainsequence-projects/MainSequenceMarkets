"""Configurable execution choices for rebalances that trade at observed prices (ADR 0058).

The rebalance strategy base enforces the facts: a fill uses an observed price strictly
after the signal, at or after the earliest moment, inside a session, and carries its
price's time. Everything else is a modelling choice and lives here, in a hash-bearing
policy whose defaults are the owner's decisions:

- when shares are sized: at the decision, or at each asset's fill;
- how much negative cash is allowed: none, a fraction of NAV, or a fixed amount in the
  portfolio's currency (only for a portfolio with a ledger);
- whether sells are booked before buys at the same instant;
- how too little cash is shared among buys at the same instant;
- what happens to a buy that cash cannot cover once the rebalance's sells have filled;
- whether the portfolio calendar gates the earliest moment and the session check.

``PortfolioRebalance`` runs the policy on a ``RebalanceBook``, which tracks shares and
cash in the portfolio's currency, in units of the NAV at the portfolio's first rebalance
(ADR 0059: prices in another currency are converted at the last observed FX rate). A
strategy with its own bars fills each order in slices, one per bar, and the policy's
cash rules apply to each bar's slices as they apply to whole orders (#90).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

SHARE_TOLERANCE = 1e-12
INSUFFICIENT_CASH = "insufficient_cash"
# Why an expired order's remainder was dropped: its signal passed the strategy's lifetime.
SIGNAL_LIFETIME = "signal_lifetime"


class ExecutionPolicy(BaseModel):
    """Hash-bearing execution choices; the defaults are the owner's decisions (ADR 0058)."""

    model_config = ConfigDict(extra="forbid")

    sizing: Literal["at_decision", "at_fill"] = Field(
        default="at_decision",
        description=(
            "When share counts are fixed. at_decision: once for every asset of the "
            "rebalance, target weight x NAV / price with the last prices observed before "
            "the earliest moment. at_fill: each asset at its own fill, with the NAV and "
            "its price then."
        ),
    )
    negative_cash: Literal["not_allowed", "fraction_of_nav", "fixed_amount"] = Field(
        default="not_allowed",
        description=(
            "How much negative cash a buy may use. not_allowed (the default): only the "
            "cash on hand. fraction_of_nav: down to negative_cash_limit x NAV. "
            "fixed_amount: down to negative_cash_limit in the portfolio's currency, only "
            "for a portfolio with a ledger, whose initial NAV gives the book a currency."
        ),
    )
    negative_cash_limit: float = Field(
        default=0.0,
        ge=0.0,
        allow_inf_nan=False,
        description=(
            "The limit of negative_cash: a fraction of NAV, or an amount in the "
            "portfolio's currency. 0 when negative cash is not allowed."
        ),
    )
    sells_before_buys: bool = Field(
        default=True,
        description="Book sells before buys at the same instant, so their cash pays the buys.",
    )
    cash_shortfall_allocation: Literal["pro_rata"] = Field(
        default="pro_rata",
        description=(
            "How buys at the same instant share too little cash. pro_rata: each fills the "
            "same fraction of what it would trade then: its order, or the slice of it a "
            "strategy's bar allows."
        ),
    )
    uncovered_buys: Literal["cut_and_cancel"] = Field(
        default="cut_and_cancel",
        description=(
            "A buy that cash cannot cover waits for the rebalance's pending sells. Once they "
            "have filled, cut_and_cancel fills what the cash allows and cancels the rest, "
            "recording the reason."
        ),
    )
    calendar_gating: Literal["portfolio_calendar", "none"] = Field(
        default="portfolio_calendar",
        description=(
            "portfolio_calendar: the earliest moment waits for the portfolio calendar's "
            "session, and a fill price must be inside one (market_open < t <= "
            "market_close). none: neither applies; any observed price after the signal "
            "counts."
        ),
    )

    @model_validator(mode="after")
    def _limit_matches_the_setting(self) -> ExecutionPolicy:
        if self.negative_cash == "not_allowed" and self.negative_cash_limit != 0.0:
            raise ValueError("negative_cash_limit must be 0 when negative cash is not allowed.")
        if self.negative_cash != "not_allowed" and self.negative_cash_limit <= 0.0:
            raise ValueError(f"negative_cash={self.negative_cash!r} needs a positive limit.")
        return self

    def negative_cash_allowance(self, nav: float, unit_value: float | None) -> float:
        """Return the negative cash a buy may use, in the book's unit, at a NAV of ``nav``.

        ``unit_value`` is one book unit in the portfolio's currency: the ledger's
        initial NAV. Only a fixed amount needs it.
        """
        if self.negative_cash == "not_allowed":
            return 0.0
        if self.negative_cash == "fraction_of_nav":
            return self.negative_cash_limit * nav
        if unit_value is None:
            raise ValueError(
                "A fixed-amount negative cash limit needs a portfolio with a ledger: its "
                "initial NAV gives the rebalance's book a currency (ADR 0059)."
            )
        return self.negative_cash_limit / unit_value

    def cash_floor(self, nav: float) -> float:
        """Return the lowest cash the ledger may reach, in the portfolio's currency."""
        if self.negative_cash == "not_allowed":
            return 0.0
        if self.negative_cash == "fraction_of_nav":
            return -self.negative_cash_limit * nav
        return -self.negative_cash_limit

    def open_book(
        self,
        *,
        intent_id: str,
        signal_time_index: pd.Timestamp,
        earliest_time_index: pd.Timestamp,
        target_weights: dict[str, float],
        held: dict[str, float],
        cash: float,
        decision_prices: dict[str, float],
        unit_value: float | None = None,
    ) -> RebalanceBook:
        """Open a rebalance at its decision, the instant before its earliest moment.

        ``held`` and ``cash`` are the portfolio's shares and cash then, in the book's
        unit: the NAV at the first rebalance is 1. The decision NAV values them at
        ``decision_prices``, the last prices observed before the earliest moment. With
        ``sizing`` at the decision every order is fixed here: target weight x decision
        NAV / decision price, less the shares held.
        """
        book = RebalanceBook(
            intent_id=intent_id,
            signal_time_index=signal_time_index,
            earliest_time_index=earliest_time_index,
            target_weights={asset: float(value) for asset, value in target_weights.items()},
            cash=float(cash),
            held={
                asset: float(shares)
                for asset, shares in held.items()
                if abs(float(shares)) > SHARE_TOLERANCE
            },
            unit_value=unit_value,
        )
        assets = sorted(
            set(book.held)
            | {
                asset
                for asset, weight in book.target_weights.items()
                if abs(weight) > SHARE_TOLERANCE
            }
        )
        missing = [asset for asset in assets if asset not in decision_prices]
        if missing:
            raise ValueError(
                "No observed price before the rebalance's earliest moment "
                f"{earliest_time_index.isoformat()} for {', '.join(missing)}; its shares "
                "cannot be sized."
            )
        book.decision_nav = book.cash + sum(
            shares * float(decision_prices[asset]) for asset, shares in book.held.items()
        )
        if not math.isfinite(book.decision_nav) or book.decision_nav <= 0.0:
            raise ValueError(f"Rebalance {intent_id} has a non-positive NAV at its decision.")
        for asset in assets:
            price = float(decision_prices[asset])
            shares = book.held.get(asset, 0.0)
            weight = shares * price / book.decision_nav
            target_weight = book.target_weights.get(asset, 0.0)
            order = BookOrder(weight_at_decision=weight, decision_price=price)
            if self.sizing == "at_decision":
                order.size(target_weight * book.decision_nav / price, shares)
            else:
                order.side = order_side(target_weight - weight)
            book.orders[asset] = order
        return book

    def size_at_fill(
        self,
        book: RebalanceBook,
        *,
        fill_prices: dict[str, float],
        nav: float,
    ) -> None:
        """Size the open orders of ``fill_prices`` not sized yet: ``sizing="at_fill"``.

        Each is sized at its own fill, target weight x ``nav`` / its fill price, less
        the shares held. An order sized at the decision is left as it is.
        """
        for asset in sorted(fill_prices):
            order = book.orders.get(asset)
            if order is None or order.status != "open" or order.order_shares is not None:
                continue
            order.size(
                book.target_weights.get(asset, 0.0) * nav / fill_prices[asset],
                book.held.get(asset, 0.0),
            )

    def step(
        self,
        book: RebalanceBook,
        *,
        time_index: pd.Timestamp,
        fill_prices: dict[str, float],
        last_prices: dict[str, float],
        slices: dict[str, float] | None = None,
    ) -> list[BookEntry]:
        """Apply one instant: the assets of ``fill_prices`` may trade at those prices.

        ``last_prices`` values the holdings for the NAV at this instant. Without
        ``slices`` each order may trade all it has open. A strategy that fills an order
        over several bars gives each order's slice for this bar instead: at most that
        many shares (a non-negative magnitude) trade, in the order's direction and never
        more than it has open; an order with no slice does not trade. The cash rules
        then apply to the slices: buys short of cash fill the same fraction of their
        slices. Returns one entry per asset that filled, partly filled or was
        cancelled.
        """
        candidates = [
            asset
            for asset in sorted(fill_prices)
            if asset in book.orders and book.orders[asset].status == "open"
        ]
        if not candidates:
            return []
        nav = book.nav(last_prices)
        self.size_at_fill(
            book, fill_prices={asset: fill_prices[asset] for asset in candidates}, nav=nav
        )
        wanted: dict[str, float] = {}
        for asset in candidates:
            order = book.orders[asset]
            shares = order.remaining_shares
            if slices is not None:
                shares = math.copysign(
                    min(abs(shares), max(float(slices.get(asset, 0.0)), 0.0)), shares
                )
                if order.side != "none" and abs(shares) <= SHARE_TOLERANCE:
                    continue
            wanted[asset] = shares
        sells = [asset for asset in wanted if book.orders[asset].side == "sell"]
        buys = [asset for asset in wanted if book.orders[asset].side == "buy"]
        unchanged = [asset for asset in wanted if book.orders[asset].side == "none"]
        entries: list[BookEntry] = []
        if self.sells_before_buys:
            entries += self._fill_in_full(book, sells, wanted, fill_prices, nav)
            entries += self._fill_in_full(book, unchanged, wanted, fill_prices, nav)
            entries += self._fill_buys(book, buys, wanted, fill_prices, nav)
        else:
            entries += self._fill_buys(book, buys, wanted, fill_prices, nav)
            entries += self._fill_in_full(book, sells, wanted, fill_prices, nav)
            entries += self._fill_in_full(book, unchanged, wanted, fill_prices, nav)
        return entries

    @staticmethod
    def _fill_in_full(
        book: RebalanceBook,
        assets: list[str],
        wanted: dict[str, float],
        prices: dict[str, float],
        nav: float,
    ) -> list[BookEntry]:
        return [book.fill(asset, wanted[asset], prices[asset], nav) for asset in assets]

    def _fill_buys(
        self,
        book: RebalanceBook,
        assets: list[str],
        wanted: dict[str, float],
        prices: dict[str, float],
        nav: float,
    ) -> list[BookEntry]:
        if not assets:
            return []
        needed = sum(wanted[asset] * prices[asset] for asset in assets)
        available = book.cash + self.negative_cash_allowance(nav, book.unit_value)
        fraction = 1.0
        if needed > available + SHARE_TOLERANCE:
            # pro_rata: every buy fills the same fraction of what it would trade now.
            fraction = max(available, 0.0) / needed if needed > 0.0 else 0.0
        sells_pending = book.has_pending_sells()
        entries = []
        for asset in assets:
            shares = wanted[asset] * fraction
            if fraction >= 1.0:
                entries.append(book.fill(asset, wanted[asset], prices[asset], nav))
            elif sells_pending:
                # The rest waits for the cash of the rebalance's pending sells.
                if shares > SHARE_TOLERANCE:
                    entries.append(book.fill(asset, shares, prices[asset], nav))
            else:
                entries.append(
                    book.fill(
                        asset,
                        shares,
                        prices[asset],
                        nav,
                        cancel_reason=INSUFFICIENT_CASH,
                    )
                )
        return entries


@dataclass
class BookOrder:
    """One asset's order in a rebalance, in the book's share unit."""

    weight_at_decision: float
    decision_price: float
    target_shares: float | None = None
    order_shares: float | None = None
    remaining_shares: float = 0.0
    filled_shares: float = 0.0
    side: Literal["buy", "sell", "none"] = "none"
    status: Literal["open", "filled", "cancelled", "expired"] = "open"

    def size(self, target_shares: float, held: float) -> None:
        self.target_shares = target_shares
        self.order_shares = target_shares - held
        self.remaining_shares = self.order_shares
        self.side = order_side(self.order_shares)


@dataclass(frozen=True)
class BookEntry:
    """What one instant did to one asset's order.

    ``status`` is the order's: ``partial`` while some of it is still open,
    ``complete`` once all of it filled, ``cancelled`` once its remainder was cut,
    ``expired`` once its signal passed the strategy's lifetime and its remainder was
    dropped. ``shares`` may be zero for a cancellation, an expiry or an unchanged
    holding.
    ``fill_fraction`` is the part of the order still open before this instant that
    filled: the ledger scales its own order by it.
    """

    asset_identifier: str
    shares: float
    price: float
    weight_before: float
    weight_after: float
    status: Literal["partial", "complete", "cancelled", "expired"]
    fill_fraction: float = 1.0
    cancelled_shares: float = 0.0
    cancel_reason: str | None = None


@dataclass
class RebalanceBook:
    """Shares and cash while one rebalance runs, in the book's unit.

    The unit is the NAV at the portfolio's first rebalance: it never rescales, so an
    asset's shares change only when it fills, and the row of that fill records them.
    """

    intent_id: str
    signal_time_index: pd.Timestamp
    earliest_time_index: pd.Timestamp
    target_weights: dict[str, float]
    cash: float
    held: dict[str, float] = field(default_factory=dict)
    orders: dict[str, BookOrder] = field(default_factory=dict)
    decision_nav: float = 1.0
    # One book unit in the portfolio's currency, when a ledger gives it one.
    unit_value: float | None = None

    def nav(self, last_prices: dict[str, float]) -> float:
        value = self.cash
        for asset, shares in self.held.items():
            if abs(shares) <= SHARE_TOLERANCE:
                continue
            price = last_prices.get(asset)
            if price is None:
                raise ValueError(f"Rebalance {self.intent_id} has no price for {asset}.")
            value += shares * price
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"Rebalance {self.intent_id} has a non-positive NAV.")
        return value

    def expire(self, last_prices: dict[str, float], nav: float) -> list[BookEntry]:
        """End every open order: its signal passed the strategy's lifetime.

        Each keeps the shares it filled; what is left of it is dropped and recorded
        as ``cancelled_shares``, with the reason ``signal_lifetime``. Nothing trades.
        ``last_prices`` value the holdings for the weights; ``nav`` is the book's NAV
        at them.
        """
        entries = []
        for asset in sorted(self.orders):
            order = self.orders[asset]
            if order.status != "open":
                continue
            held = self.held.get(asset, 0.0)
            price = float(last_prices.get(asset, order.decision_price))
            dropped = order.remaining_shares
            order.remaining_shares = 0.0
            order.status = "expired"
            weight = held * price / nav
            entries.append(
                BookEntry(
                    asset_identifier=asset,
                    shares=0.0,
                    price=price,
                    weight_before=weight,
                    weight_after=weight,
                    status="expired",
                    fill_fraction=0.0,
                    cancelled_shares=dropped,
                    cancel_reason=SIGNAL_LIFETIME,
                )
            )
        return entries

    def has_pending_sells(self) -> bool:
        return any(
            order.status == "open" and order.side == "sell" for order in self.orders.values()
        )

    def fill(
        self,
        asset: str,
        shares: float,
        price: float,
        nav: float,
        *,
        cancel_reason: str | None = None,
    ) -> BookEntry:
        order = self.orders[asset]
        before = self.held.get(asset, 0.0)
        open_shares = order.remaining_shares
        self.cash -= shares * price
        self.held[asset] = before + shares
        order.filled_shares += shares
        order.remaining_shares -= shares
        cancelled = 0.0
        if cancel_reason is not None:
            cancelled = order.remaining_shares
            order.remaining_shares = 0.0
            order.status = "cancelled"
        elif abs(order.remaining_shares) <= SHARE_TOLERANCE:
            order.remaining_shares = 0.0
            order.status = "filled"
        status: Literal["partial", "complete", "cancelled"] = (
            "cancelled"
            if order.status == "cancelled"
            else "complete"
            if order.status == "filled"
            else "partial"
        )
        return BookEntry(
            asset_identifier=asset,
            shares=shares,
            price=price,
            weight_before=before * price / nav,
            weight_after=self.held[asset] * price / nav,
            status=status,
            fill_fraction=(
                shares / open_shares if abs(open_shares) > SHARE_TOLERANCE else 1.0
            ),
            cancelled_shares=cancelled,
            cancel_reason=cancel_reason,
        )


def order_side(shares: float | None) -> Literal["buy", "sell", "none"]:
    """Return the side of an order of ``shares``: buy, sell, or none when about zero."""
    if shares is None:
        return "none"
    if shares > SHARE_TOLERANCE:
        return "buy"
    if shares < -SHARE_TOLERANCE:
        return "sell"
    return "none"


__all__ = [
    "INSUFFICIENT_CASH",
    "SIGNAL_LIFETIME",
    "BookEntry",
    "BookOrder",
    "ExecutionPolicy",
    "RebalanceBook",
    "order_side",
]
