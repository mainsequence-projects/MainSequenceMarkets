"""Which events a price includes (ADR 0065).

A valuation source's prices are at the level its producer chose. Adjusted prices, the
default, include every event of the asset, whatever its type: a stock's dividends, as if
reinvested, and its splits; a bond's coupons and its redemption. A source states another
level in its configuration's ``events_in_price``: a tuple naming exactly the event types
its prices include, ``()`` for unadjusted prices. A source that states none, a
``TimeIndexTableRef`` among them, is adjusted (decision 13).
"""

from __future__ import annotations

from typing import Any, Literal

ADJUSTED: Literal["adjusted"] = "adjusted"

EventsInPrice = Literal["adjusted"] | tuple[str, ...]
"""``"adjusted"``, or exactly the event types the prices include."""


def events_in_price(source: Any) -> EventsInPrice:
    """The events the prices of ``source`` include, from its configuration."""

    value = getattr(getattr(source, "config", None), "events_in_price", None)
    if value is None or value == ADJUSTED:
        return ADJUSTED
    return tuple(str(event_type) for event_type in value)


def price_includes(in_price: EventsInPrice, event_type: str) -> bool:
    """Whether prices at the level ``in_price`` include ``event_type``."""

    return in_price == ADJUSTED or event_type in in_price


__all__ = ["ADJUSTED", "EventsInPrice", "events_in_price", "price_includes"]
