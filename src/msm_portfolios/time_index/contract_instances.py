"""Contract-plus-instance factories for the portfolio time-series contracts (ADR 0047).

``PortfoliosTS``, ``PortfolioWeightsTS``, ``SignalWeightsTS`` and the engine
outputs ``PortfolioRebalanceStateTS``, ``PortfolioCalendarEventsTS`` and
``PortfolioEventLedgerTS`` are storage contracts: ms-markets owns their columns,
dtypes, time index and index names. The core tables declared in
``msm_portfolios.time_index.portfolios.storage`` and
``msm_portfolios.time_index.signals.storage`` are the Markets-owned instance. A
provider builds its own instance with the factories here, under its own
MetaTables namespace and physical-name app segment, migrates it with its own
provider and binds its updaters to it with ``output_table=``.
``PortfoliosUpdater`` also takes ``weights_output_table=`` and
``rebalance_output_table=`` for the updaters it builds internally. The MetaTable
identifier of an instance is stable and derived from the contract name and the
instance key: ``PortfoliosTS.<instance_key>``, prefixed with the namespace when
that namespace is not the default Markets one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import ForeignKeyConstraint, Index, MetaData, Table
from sqlalchemy.orm import DeclarativeBase

from metatables import PlatformTimeIndexMetaTable, schema_index_name, schema_table_name
from msm.base import MARKETS_TABLE_APP, MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.assets.core import AssetTable
from msm.models.calendars import CalendarTable
from msm.models.portfolios.core import PortfolioTable
from msm.models.portfolios.signals import SignalMetadataTable
from msm.settings import markets_identifier, markets_namespace
from msm_portfolios.time_index.portfolios.storage import (
    PortfolioCalendarEventsStorage,
    PortfolioEventLedgerStorage,
    PortfolioRebalanceStateStorage,
    PortfoliosStorage,
    PortfolioWeightsStorage,
)
from msm_portfolios.time_index.signals.storage import SignalWeightsStorage

CONTRACT_INSTANCE_CONTRACT_COMPONENT = "storage_contract"
CONTRACT_INSTANCE_KEY_COMPONENT = "instance_key"

PORTFOLIOS_CONTRACT = "PortfoliosTS"
PORTFOLIO_WEIGHTS_CONTRACT = "PortfolioWeightsTS"
SIGNAL_WEIGHTS_CONTRACT = "SignalWeightsTS"
PORTFOLIO_REBALANCE_STATE_CONTRACT = "PortfolioRebalanceStateTS"
PORTFOLIO_CALENDAR_EVENTS_CONTRACT = "PortfolioCalendarEventsTS"
PORTFOLIO_EVENT_LEDGER_CONTRACT = "PortfolioEventLedgerTS"

_INSTANCE_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class ContractForeignKey:
    """One foreign key the contract requires on every instance."""

    source_column: str
    target_table: type[Any]
    target_column: str
    ondelete: str = "RESTRICT"


@dataclass(frozen=True)
class PortfolioStorageContract:
    """The Markets-owned definition of one portfolio time-series contract."""

    name: str
    core_storage: type[PlatformTimeIndexMetaTable]
    foreign_keys: tuple[ContractForeignKey, ...]
    dimension: str

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.core_storage.__table__.columns)

    @property
    def time_index_name(self) -> str:
        return str(self.core_storage.__time_index_name__)

    @property
    def index_names(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self.core_storage.__index_names__)


PORTFOLIO_STORAGE_CONTRACTS: Mapping[str, PortfolioStorageContract] = {
    PORTFOLIOS_CONTRACT: PortfolioStorageContract(
        name=PORTFOLIOS_CONTRACT,
        core_storage=PortfoliosStorage,
        foreign_keys=(
            ContractForeignKey("portfolio_identifier", PortfolioTable, "unique_identifier"),
        ),
        dimension="portfolio_identifier",
    ),
    PORTFOLIO_WEIGHTS_CONTRACT: PortfolioStorageContract(
        name=PORTFOLIO_WEIGHTS_CONTRACT,
        core_storage=PortfolioWeightsStorage,
        foreign_keys=(
            ContractForeignKey("portfolio_identifier", PortfolioTable, "unique_identifier"),
            ContractForeignKey("asset_identifier", AssetTable, "unique_identifier"),
        ),
        dimension="portfolio_identifier",
    ),
    SIGNAL_WEIGHTS_CONTRACT: PortfolioStorageContract(
        name=SIGNAL_WEIGHTS_CONTRACT,
        core_storage=SignalWeightsStorage,
        foreign_keys=(
            ContractForeignKey("signal_uid", SignalMetadataTable, "signal_uid"),
            ContractForeignKey("asset_identifier", AssetTable, "unique_identifier"),
        ),
        dimension="signal_uid",
    ),
    PORTFOLIO_REBALANCE_STATE_CONTRACT: PortfolioStorageContract(
        name=PORTFOLIO_REBALANCE_STATE_CONTRACT,
        core_storage=PortfolioRebalanceStateStorage,
        foreign_keys=(
            ContractForeignKey("portfolio_identifier", PortfolioTable, "unique_identifier"),
            ContractForeignKey("asset_identifier", AssetTable, "unique_identifier"),
        ),
        dimension="portfolio_identifier",
    ),
    PORTFOLIO_CALENDAR_EVENTS_CONTRACT: PortfolioStorageContract(
        name=PORTFOLIO_CALENDAR_EVENTS_CONTRACT,
        core_storage=PortfolioCalendarEventsStorage,
        foreign_keys=(
            ContractForeignKey("calendar_identifier", CalendarTable, "unique_identifier"),
        ),
        dimension="calendar_identifier",
    ),
    PORTFOLIO_EVENT_LEDGER_CONTRACT: PortfolioStorageContract(
        name=PORTFOLIO_EVENT_LEDGER_CONTRACT,
        core_storage=PortfolioEventLedgerStorage,
        foreign_keys=(
            ContractForeignKey("portfolio_identifier", PortfolioTable, "unique_identifier"),
            ContractForeignKey("asset_identifier", AssetTable, "unique_identifier"),
            ContractForeignKey("amount_asset_identifier", AssetTable, "unique_identifier"),
            ContractForeignKey("price_asset_identifier", AssetTable, "unique_identifier"),
            ContractForeignKey("valuation_asset_identifier", AssetTable, "unique_identifier"),
        ),
        dimension="portfolio_identifier",
    ),
}


def portfolio_storage_contract(name: str) -> PortfolioStorageContract:
    """Return the definition of one portfolio time-series contract by name."""

    try:
        return PORTFOLIO_STORAGE_CONTRACTS[str(name)]
    except KeyError as exc:
        raise ValueError(
            f"Unknown portfolio storage contract {name!r}; expected one of "
            f"{sorted(PORTFOLIO_STORAGE_CONTRACTS)}."
        ) from exc


def contract_instance_key(instance_key: str) -> str:
    """Normalize and validate a caller-chosen instance key."""

    normalized = str(instance_key).strip().lower()
    if not _INSTANCE_KEY_PATTERN.fullmatch(normalized):
        raise ValueError(
            "instance_key must be 1-63 lowercase letters, digits or underscores and start "
            f"with a letter or digit; got {instance_key!r}."
        )
    return normalized


def contract_instance_identifier(contract: str, instance_key: str) -> str:
    """Return the authored MetaTable identifier for one instance: ``<Contract>.<key>``."""

    return f"{portfolio_storage_contract(contract).name}.{contract_instance_key(instance_key)}"


def contract_instance_table_name(
    contract: str,
    instance_key: str,
    *,
    storage_app: str = MARKETS_TABLE_APP,
) -> str:
    """Return the physical table name of one instance in one app segment."""

    definition = portfolio_storage_contract(contract)
    return schema_table_name(
        storage_app,
        definition.name.lower(),
        suffix=contract_instance_key(instance_key),
    )


def contract_instance_identity_components(contract: str, instance_key: str) -> dict[str, str]:
    """Return the storage-identity components of one instance."""

    definition = portfolio_storage_contract(contract)
    return {
        CONTRACT_INSTANCE_CONTRACT_COMPONENT: definition.name,
        CONTRACT_INSTANCE_KEY_COMPONENT: contract_instance_key(instance_key),
    }


def configured_contract_instance_storage(
    contract: str,
    *,
    instance_key: str,
    namespace: str | None = None,
    storage_app: str = MARKETS_TABLE_APP,
    base: type[DeclarativeBase] | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build the storage class for one instance of one portfolio time-series contract.

    ``namespace`` is the MetaTables namespace that owns the instance; it defaults
    to the active Markets namespace, which is right only for the Markets
    deployment itself. ``storage_app`` is the physical-name app segment, for
    example ``my_provider``. ``base`` is the provider's SQLAlchemy
    declarative base when the provider migrates the instance with its own
    Alembic provider; the contract's foreign-key target tables are copied into
    that base's metadata so SQLAlchemy can resolve the constraints, exactly as
    ``examples/msm/indices/extension_owned_index_storage.py`` does. With the
    default ``MarketsBase`` the instance lives in the Markets registry.

    The result has the contract's columns, dtypes, nullability, time index and
    index names. Its MetaTable identifier is ``<Contract>.<instance_key>``,
    namespace-prefixed when ``namespace`` is not the default Markets namespace.
    """

    definition = portfolio_storage_contract(contract)
    key = contract_instance_key(instance_key)
    resolved_namespace = markets_namespace(namespace)
    resolved_app = str(storage_app).strip()
    if not resolved_app:
        raise ValueError("storage_app must be a non-empty app segment.")
    return _configured_contract_instance_storage(
        definition.name,
        key,
        resolved_namespace,
        resolved_app,
        base or MarketsBase,
    )


def configured_portfolios_storage(
    *,
    instance_key: str,
    namespace: str | None = None,
    storage_app: str = MARKETS_TABLE_APP,
    base: type[DeclarativeBase] | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build one ``PortfoliosTS`` instance (portfolio values)."""

    return configured_contract_instance_storage(
        PORTFOLIOS_CONTRACT,
        instance_key=instance_key,
        namespace=namespace,
        storage_app=storage_app,
        base=base,
    )


def configured_portfolio_weights_storage(
    *,
    instance_key: str,
    namespace: str | None = None,
    storage_app: str = MARKETS_TABLE_APP,
    base: type[DeclarativeBase] | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build one ``PortfolioWeightsTS`` instance (executed portfolio weights)."""

    return configured_contract_instance_storage(
        PORTFOLIO_WEIGHTS_CONTRACT,
        instance_key=instance_key,
        namespace=namespace,
        storage_app=storage_app,
        base=base,
    )


def configured_signal_weights_storage(
    *,
    instance_key: str,
    namespace: str | None = None,
    storage_app: str = MARKETS_TABLE_APP,
    base: type[DeclarativeBase] | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build one ``SignalWeightsTS`` instance (raw signal weights)."""

    return configured_contract_instance_storage(
        SIGNAL_WEIGHTS_CONTRACT,
        instance_key=instance_key,
        namespace=namespace,
        storage_app=storage_app,
        base=base,
    )


def configured_portfolio_rebalance_state_storage(
    *,
    instance_key: str,
    namespace: str | None = None,
    storage_app: str = MARKETS_TABLE_APP,
    base: type[DeclarativeBase] | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build one ``PortfolioRebalanceStateTS`` instance (rebalance intents and fills)."""

    return configured_contract_instance_storage(
        PORTFOLIO_REBALANCE_STATE_CONTRACT,
        instance_key=instance_key,
        namespace=namespace,
        storage_app=storage_app,
        base=base,
    )


def configured_portfolio_calendar_events_storage(
    *,
    instance_key: str,
    namespace: str | None = None,
    storage_app: str = MARKETS_TABLE_APP,
    base: type[DeclarativeBase] | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build one ``PortfolioCalendarEventsTS`` instance (session open and close events)."""

    return configured_contract_instance_storage(
        PORTFOLIO_CALENDAR_EVENTS_CONTRACT,
        instance_key=instance_key,
        namespace=namespace,
        storage_app=storage_app,
        base=base,
    )


def configured_portfolio_event_ledger_storage(
    *,
    instance_key: str,
    namespace: str | None = None,
    storage_app: str = MARKETS_TABLE_APP,
    base: type[DeclarativeBase] | None = None,
) -> type[PlatformTimeIndexMetaTable]:
    """Build one ``PortfolioEventLedgerTS`` instance (the position-aware engine's ledger)."""

    return configured_contract_instance_storage(
        PORTFOLIO_EVENT_LEDGER_CONTRACT,
        instance_key=instance_key,
        namespace=namespace,
        storage_app=storage_app,
        base=base,
    )


def contract_columns_satisfied(contract: str, column_names: Any) -> bool:
    """Return whether a registered table exposes every contract column.

    A provider may add columns beyond the contract; Markets reads the contract
    columns and ignores the rest.
    """

    definition = portfolio_storage_contract(contract)
    return set(definition.column_names).issubset({str(name) for name in column_names or ()})


@lru_cache(maxsize=256)
def _configured_contract_instance_storage(
    contract_name: str,
    instance_key: str,
    namespace: str,
    storage_app: str,
    base: type[DeclarativeBase],
) -> type[PlatformTimeIndexMetaTable]:
    definition = portfolio_storage_contract(contract_name)
    table_name = contract_instance_table_name(contract_name, instance_key, storage_app=storage_app)
    authored_identifier = contract_instance_identifier(contract_name, instance_key)
    resolved_identifier = markets_identifier(authored_identifier, namespace=namespace)
    table = _copy_contract_table(
        definition,
        table_name=table_name,
        metadata=base.metadata,
        info={
            "namespace": namespace,
            "identifier": resolved_identifier,
            "markets_storage_app": storage_app,
        },
    )
    class_suffix = re.sub(r"[^a-zA-Z0-9_]+", "_", f"{instance_key}_{storage_app}")
    attributes: dict[str, Any] = {
        "__module__": __name__,
        "__table__": table,
        "__metatable_identifier__": authored_identifier,
        "__metatable_namespace__": namespace,
        "__markets_storage_app__": storage_app,
        "__metatable_description__": (
            f"{definition.core_storage.__metatable_description__} Instance "
            f"{instance_key!r} of the {definition.name} contract."
        ),
        "__metatable_extra_hash_components__": contract_instance_identity_components(
            contract_name, instance_key
        ),
        "__time_index_name__": definition.time_index_name,
        "__index_names__": list(definition.index_names),
    }
    cadence = getattr(definition.core_storage, "__cadence__", None)
    if cadence not in (None, ""):
        attributes["__cadence__"] = cadence
    return type(
        f"{definition.core_storage.__name__}_{class_suffix}",
        (MarketsTimeIndexMetaTableMixin, base),
        attributes,
    )


def _copy_contract_table(
    definition: PortfolioStorageContract,
    *,
    table_name: str,
    metadata: MetaData,
    info: Mapping[str, Any],
) -> Table:
    existing = metadata.tables.get(table_name)
    if isinstance(existing, Table):
        return existing

    constraints: list[ForeignKeyConstraint] = []
    for foreign_key in definition.foreign_keys:
        target = _target_table(foreign_key.target_table, metadata=metadata)
        constraints.append(
            ForeignKeyConstraint(
                [foreign_key.source_column],
                [f"{target.fullname}.{foreign_key.target_column}"],
                ondelete=foreign_key.ondelete,
            )
        )
    columns = [column._copy() for column in definition.core_storage.__table__.columns]
    table = Table(
        table_name,
        metadata,
        *columns,
        *constraints,
        schema=definition.core_storage.__table__.schema,
        info=dict(info),
    )
    Index(
        schema_index_name(table_name, definition.index_names, unique=True),
        *(table.c[column_name] for column_name in definition.index_names),
        unique=True,
    )
    return table


def _target_table(model: type[Any], *, metadata: MetaData) -> Table:
    """Return the FK target table inside ``metadata``, copying it from the core registry if needed."""

    core_table: Table = model.__table__
    if core_table.metadata is metadata:
        return core_table
    existing = metadata.tables.get(core_table.key)
    if isinstance(existing, Table):
        return existing
    return core_table.to_metadata(metadata)


__all__ = [
    "CONTRACT_INSTANCE_CONTRACT_COMPONENT",
    "CONTRACT_INSTANCE_KEY_COMPONENT",
    "PORTFOLIOS_CONTRACT",
    "PORTFOLIO_CALENDAR_EVENTS_CONTRACT",
    "PORTFOLIO_EVENT_LEDGER_CONTRACT",
    "PORTFOLIO_REBALANCE_STATE_CONTRACT",
    "PORTFOLIO_STORAGE_CONTRACTS",
    "PORTFOLIO_WEIGHTS_CONTRACT",
    "SIGNAL_WEIGHTS_CONTRACT",
    "ContractForeignKey",
    "PortfolioStorageContract",
    "configured_contract_instance_storage",
    "configured_portfolio_calendar_events_storage",
    "configured_portfolio_event_ledger_storage",
    "configured_portfolio_rebalance_state_storage",
    "configured_portfolio_weights_storage",
    "configured_portfolios_storage",
    "configured_signal_weights_storage",
    "contract_columns_satisfied",
    "contract_instance_identifier",
    "contract_instance_identity_components",
    "contract_instance_key",
    "contract_instance_table_name",
    "portfolio_storage_contract",
]
