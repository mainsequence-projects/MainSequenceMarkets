"""A producer's own tables of a portfolio graph, declared as classes (ADR 0066).

Its computed signals' table, its calendar events, and its portfolios' rebalance state and
ledger, on the producer's own declarative base. They are top-level class statements, so a
node Job run imports them by their address (ADR 0067). Only ``msm_portfolios`` is imported,
so the portfolio tests may use them.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import sqlalchemy_naming_convention
from msm_portfolios.time_index.contract_instances import (
    PortfolioCalendarEventsInstance,
    PortfolioEventLedgerInstance,
    PortfolioRebalanceStateInstance,
)
from msm_portfolios.time_index.signals.storage import SignalWeightsInstance


class ProducerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class Producer:
    __instance_key__ = "main"
    __metatable_namespace__ = "a-producer"
    __markets_storage_app__ = "a_producer"


class ProducerSignalWeights(SignalWeightsInstance, Producer, ProducerBase):
    pass


class ProducerCalendarEvents(PortfolioCalendarEventsInstance, Producer, ProducerBase):
    pass


class ProducerRebalanceState(PortfolioRebalanceStateInstance, Producer, ProducerBase):
    pass


class ProducerEventLedger(PortfolioEventLedgerInstance, Producer, ProducerBase):
    pass


__all__ = [
    "ProducerCalendarEvents",
    "ProducerEventLedger",
    "ProducerRebalanceState",
    "ProducerSignalWeights",
]
