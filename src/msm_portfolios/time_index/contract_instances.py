"""An application's private portfolio state tables, declared as classes (ADR 0060, 0066).

``PortfolioRebalanceStateTS``, ``PortfolioCalendarEventsTS`` and
``PortfolioEventLedgerTS`` are storage contracts: ms-markets owns their columns,
dtypes, time index, index names, foreign keys, lookup indexes and storage layout. An
application that runs a portfolio keeps this state private: it declares its own
instance with a ``class`` statement on the contract's base here, under its own
MetaTables namespace and physical-name app segment, migrates it with its own
provider, and binds the engine to it (``rebalance_output_table=``,
``event_ledger_output_table=``, the calendar events updater's ``output_table=``)::

    class MyRebalanceState(PortfolioRebalanceStateInstance, MyBase):
        __instance_key__ = "main"
        __metatable_namespace__ = "my-app"
        __markets_storage_app__ = "my_app"

The MetaTable identifier of an instance is stable and derived from the contract name
and the instance key: ``PortfolioRebalanceStateTS.<instance_key>``, prefixed with the
namespace when that namespace is not the default Markets one. ``msm.storage_instances``
describes the attributes.

An instance may reference a registry row with the contract's foreign keys; that key,
from the private table to Markets, is the only coupling between them. Markets never
discovers, counts or reads such a table. The application deletes its private rows
before it deletes a registry row (``msm_portfolios.recipes.delete_private_series``).

Portfolio weights and portfolio values are not instances: they are published to
Markets' own tables (``msm_portfolios.api.PortfolioWeightsSeries`` and
``PortfolioValuesSeries``). A computed signal (``SignalWeights``) writes the
application's own ``SignalWeightsTS`` instance, declared on
``msm_portfolios.time_index.signals.storage.SignalWeightsInstance``, and publishes the
same rows to Markets' ``SignalWeightsTS`` (``SignalWeightsSeries``).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import ForeignKeyConstraint, Index, MetaData, Table

from metatables import schema_index_name
from msm.models.assets.core import AssetTable
from msm.models.calendars import CalendarTable
from msm.models.portfolios.core import PortfolioTable
from msm.storage_instances import TimeIndexInstance, add_unique_index, core_identifier
from msm_portfolios.time_index.portfolios.storage import (
    PortfolioCalendarEventsStorage,
    PortfolioEventLedgerStorage,
    PortfolioRebalanceStateStorage,
)


@dataclass(frozen=True)
class ContractForeignKey:
    """One foreign key the contract requires on every instance."""

    source_column: str
    target_table: type[Any]
    target_column: str
    ondelete: str = "RESTRICT"


class PortfolioContractInstance(TimeIndexInstance):
    """The base of the three portfolio contracts' instance bases.

    Each contract states the foreign keys every instance has
    (``__contract_foreign_keys__``). Every instance also gets the core's lookup indexes
    (its non-unique indexes) and, where the core declares one, a copy of its storage
    layout: the event ledger's, whose default secondary index name exceeds PostgreSQL's
    limit.
    """

    __abstract__ = True
    __contract_foreign_keys__: ClassVar[tuple[ContractForeignKey, ...]]

    @classmethod
    def _instance_description(cls, key: str) -> str:
        core = cls.__core_storage__
        return (
            f"{core.__metatable_description__} Instance "
            f"{key!r} of the {core_identifier(core)} contract."
        )

    @classmethod
    def _instance_table(cls, table_name: str, metadata: MetaData, info: dict[str, Any]) -> Table:
        core = cls.__core_storage__
        # Column objects, not names: a name resolves only inside the table's own MetaData.
        constraints = [
            ForeignKeyConstraint(
                [foreign_key.source_column],
                [foreign_key.target_table.__table__.c[foreign_key.target_column]],
                ondelete=foreign_key.ondelete,
            )
            for foreign_key in cls.__contract_foreign_keys__
        ]
        table = Table(
            table_name,
            metadata,
            *(column._copy() for column in core.__table__.columns),
            *constraints,
            schema=core.__table__.schema,
            info=dict(info),
        )
        add_unique_index(table, [str(name) for name in core.__index_names__])
        for column_names in contract_lookup_indexes(cls):
            Index(
                schema_index_name(table_name, column_names, unique=False),
                *(table.c[column_name] for column_name in column_names),
            )
        return table

    @classmethod
    def _instance_attributes(cls) -> dict[str, Any]:
        layout = getattr(cls.__core_storage__, "__storage_layout__", None)
        return {"__storage_layout__": copy.deepcopy(layout)} if layout else {}


def contract_lookup_indexes(
    contract: type[PortfolioContractInstance],
) -> tuple[tuple[str, ...], ...]:
    """Columns of each non-unique index the contract's core declares; every instance gets them."""

    return tuple(
        tuple(column.name for column in index.columns)
        for index in sorted(contract.__core_storage__.__table__.indexes, key=lambda item: item.name)
        if not index.unique
    )


class PortfolioRebalanceStateInstance(PortfolioContractInstance):
    """The base of a ``PortfolioRebalanceStateTS`` instance (rebalance intents and fills)."""

    __abstract__ = True
    __core_storage__ = PortfolioRebalanceStateStorage
    __contract_foreign_keys__ = (
        ContractForeignKey("portfolio_identifier", PortfolioTable, "unique_identifier"),
        ContractForeignKey("asset_identifier", AssetTable, "unique_identifier"),
    )


class PortfolioCalendarEventsInstance(PortfolioContractInstance):
    """The base of a ``PortfolioCalendarEventsTS`` instance (session open and close events)."""

    __abstract__ = True
    __core_storage__ = PortfolioCalendarEventsStorage
    __contract_foreign_keys__ = (
        ContractForeignKey("calendar_identifier", CalendarTable, "unique_identifier"),
    )


class PortfolioEventLedgerInstance(PortfolioContractInstance):
    """The base of a ``PortfolioEventLedgerTS`` instance (the position-aware engine's ledger)."""

    __abstract__ = True
    __core_storage__ = PortfolioEventLedgerStorage
    __contract_foreign_keys__ = (
        ContractForeignKey("portfolio_identifier", PortfolioTable, "unique_identifier"),
        ContractForeignKey("asset_identifier", AssetTable, "unique_identifier"),
        ContractForeignKey("amount_asset_identifier", AssetTable, "unique_identifier"),
        ContractForeignKey("price_asset_identifier", AssetTable, "unique_identifier"),
        ContractForeignKey("valuation_asset_identifier", AssetTable, "unique_identifier"),
    )


PORTFOLIO_CONTRACT_INSTANCES: tuple[type[PortfolioContractInstance], ...] = (
    PortfolioRebalanceStateInstance,
    PortfolioCalendarEventsInstance,
    PortfolioEventLedgerInstance,
)
"""The portfolio contracts an application keeps private (ADR 0060, decision 7)."""


__all__ = [
    "PORTFOLIO_CONTRACT_INSTANCES",
    "ContractForeignKey",
    "PortfolioCalendarEventsInstance",
    "PortfolioContractInstance",
    "PortfolioEventLedgerInstance",
    "PortfolioRebalanceStateInstance",
    "contract_lookup_indexes",
]
