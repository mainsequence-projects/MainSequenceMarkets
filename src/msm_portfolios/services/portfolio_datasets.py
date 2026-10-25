"""Markets catalog of portfolio dataset instances (ADR 0047, decision 5).

A provider registers, per portfolio, the ``PortfoliosTS``, ``PortfolioWeightsTS``
and ``SignalWeightsTS`` instances that hold its rows, and reconciles the values
instance after each run. The read services in
:mod:`msm_portfolios.services.portfolio_reads` resolve the table from this
catalog and read it by uid; a portfolio with no catalog row reads the
Markets-owned core tables. The service mirrors
:mod:`msm.services.indices.availability`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import column, func, or_, select, table

from msm.api.base import operation_result_rows
from msm.models import PortfolioDatasetAvailabilityTable, PortfolioTable, SignalMetadataTable
from msm.repositories.base import (
    MarketsOperationContext,
    compile_markets_statement,
    execute_markets_operation,
)
from msm.repositories.crud import search_model, update_model, upsert_model
from msm_portfolios.time_index.contract_instances import (
    PORTFOLIO_WEIGHTS_CONTRACT,
    PORTFOLIOS_CONTRACT,
    SIGNAL_WEIGHTS_CONTRACT,
    contract_columns_satisfied,
    portfolio_storage_contract,
)

PortfolioDatasetPopulationState = Literal["populated", "compatible_empty", "unavailable"]
MetaTableLookup = Callable[[Sequence[str]], Sequence[Any]]

MAX_RECONCILE_SELECTORS = 500
NOT_RECONCILED_ERROR_CODE = "not_reconciled"


class PortfolioDatasetServiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PortfolioDatasetRegistration(PortfolioDatasetServiceModel):
    """The instance tables a producer declares for one portfolio."""

    portfolio_uid: uuid.UUID
    values_meta_table_uid: str = Field(min_length=1, max_length=255)
    weights_meta_table_uid: str | None = Field(default=None, min_length=1, max_length=255)
    signal_meta_table_uid: str | None = Field(default=None, min_length=1, max_length=255)


class PortfolioDatasetState(PortfolioDatasetServiceModel):
    """One reconciled catalog row."""

    portfolio_uid: uuid.UUID
    portfolio_identifier: str
    values_meta_table_uid: str
    weights_meta_table_uid: str | None = None
    signal_meta_table_uid: str | None = None
    population_state: PortfolioDatasetPopulationState
    row_count: int | None = Field(default=None, ge=0)
    earliest_time_index: dt.datetime | None = None
    latest_time_index: dt.datetime | None = None
    reconciled_at: dt.datetime
    error: str | None = None


class PortfolioDatasetReconciliationResult(PortfolioDatasetServiceModel):
    portfolio_uids: tuple[uuid.UUID, ...]
    states: tuple[PortfolioDatasetState, ...]
    skipped_portfolio_uids: tuple[uuid.UUID, ...] = ()
    """Portfolios that resolved but have no catalog row; they read the core tables."""


def default_meta_table_lookup(uids: Sequence[str]) -> Sequence[Any]:
    """Return the visible ``TimeIndexMetaTable`` rows for ``uids`` through the MetaTables API."""

    from metatables import TimeIndexMetaTable

    values = [str(item) for item in uids if str(item)]
    if not values:
        return ()
    return TimeIndexMetaTable.filter_by_body(uid__in=values, limit=len(values), offset=0)


def register_portfolio_datasets(
    context: MarketsOperationContext,
    registration: PortfolioDatasetRegistration | Mapping[str, Any],
    *,
    verify_tables: bool = True,
    reconcile: bool = True,
    meta_table_lookup: MetaTableLookup | None = None,
) -> PortfolioDatasetState:
    """Record which instance tables hold one portfolio's datasets, then reconcile.

    Each declared table must be visible to the Markets workload and expose the
    contract's columns and index names; a provider may add columns beyond the
    contract. When the portfolio has a ``signal_uid`` and a signal table is
    declared, ``SignalMetadata.meta_table_uid`` is set to the same instance so
    both references stay coherent. With ``reconcile=False`` the row is written
    as ``unavailable`` with error code ``not_reconciled`` until the first run.
    """

    typed = (
        registration
        if isinstance(registration, PortfolioDatasetRegistration)
        else PortfolioDatasetRegistration.model_validate(registration)
    )
    portfolio = _portfolio_row(context, portfolio_uid=typed.portfolio_uid)
    if portfolio is None:
        raise LookupError(f"Portfolio {typed.portfolio_uid!s} was not found")

    declared = {
        PORTFOLIOS_CONTRACT: typed.values_meta_table_uid,
        PORTFOLIO_WEIGHTS_CONTRACT: typed.weights_meta_table_uid,
        SIGNAL_WEIGHTS_CONTRACT: typed.signal_meta_table_uid,
    }
    if verify_tables:
        lookup = meta_table_lookup or default_meta_table_lookup
        requested = [uid for uid in declared.values() if uid]
        visible = {str(getattr(item, "uid", "")): item for item in lookup(requested)}
        for contract_name, uid in declared.items():
            if not uid:
                continue
            meta_table = visible.get(str(uid))
            if meta_table is None:
                raise LookupError(
                    f"{contract_name} instance {uid!r} is not a visible TimeIndexMetaTable"
                )
            verify_contract_instance(contract_name, meta_table)

    existing = _catalog_rows(context, portfolio_uids=[typed.portfolio_uid])
    now = dt.datetime.now(dt.UTC)
    values: dict[str, Any] = {
        "uid": existing[0]["uid"] if existing else uuid.uuid4(),
        "portfolio_uid": typed.portfolio_uid,
        "values_meta_table_uid": typed.values_meta_table_uid,
        "weights_meta_table_uid": typed.weights_meta_table_uid,
        "signal_meta_table_uid": typed.signal_meta_table_uid,
        "population_state": "unavailable",
        "row_count": None,
        "earliest_time_index": None,
        "latest_time_index": None,
        "reconciled_at": now,
        "error_code": NOT_RECONCILED_ERROR_CODE,
        "error_message": "Registered; the values instance has not been reconciled yet.",
    }
    persisted = operation_result_rows(
        upsert_model(
            context,
            model=PortfolioDatasetAvailabilityTable,
            values=values,
            conflict_columns=("portfolio_uid",),
        )
    )
    row = persisted[0] if persisted else values

    signal_uid = portfolio.get("signal_uid")
    if typed.signal_meta_table_uid and signal_uid:
        _bind_signal_metadata_table(
            context,
            signal_uid=str(signal_uid),
            meta_table_uid=typed.signal_meta_table_uid,
        )

    if reconcile:
        result = reconcile_portfolio_dataset_availability(
            context,
            portfolio_uids=[typed.portfolio_uid],
            meta_table_lookup=meta_table_lookup,
        )
        if result.states:
            return result.states[0]
    return _state_from_row(portfolio=portfolio, row=row)


def reconcile_portfolio_dataset_availability(
    context: MarketsOperationContext,
    *,
    portfolio_uids: Sequence[uuid.UUID | str] = (),
    portfolio_identifiers: Sequence[str] = (),
    meta_table_lookup: MetaTableLookup | None = None,
) -> PortfolioDatasetReconciliationResult:
    """Reconcile the values instance of a bounded set of catalogued portfolios.

    Portfolios are grouped by values table uid, so each instance is aggregated
    once however many portfolios it holds. A portfolio without a catalog row is
    reported in ``skipped_portfolio_uids`` and keeps reading the core tables.
    """

    normalized_uids = tuple(dict.fromkeys(uuid.UUID(str(item)) for item in portfolio_uids))
    normalized_identifiers = tuple(
        dict.fromkeys(str(item).strip() for item in portfolio_identifiers if str(item).strip())
    )
    if not normalized_uids and not normalized_identifiers:
        raise ValueError(
            "portfolio dataset reconciliation requires explicit portfolio UIDs or identifiers"
        )
    if len(normalized_uids) + len(normalized_identifiers) > MAX_RECONCILE_SELECTORS:
        raise ValueError(
            f"portfolio dataset reconciliation accepts at most {MAX_RECONCILE_SELECTORS} selectors"
        )

    portfolios = _portfolio_rows(
        context,
        portfolio_uids=normalized_uids,
        portfolio_identifiers=normalized_identifiers,
    )
    by_uid = {uuid.UUID(str(row["uid"])): row for row in portfolios}
    resolved_identifiers = {str(row["unique_identifier"]) for row in portfolios}
    missing_uids = set(normalized_uids) - set(by_uid)
    missing_identifiers = set(normalized_identifiers) - resolved_identifiers
    if missing_uids or missing_identifiers:
        raise LookupError(
            "portfolio dataset reconciliation selectors were not found: "
            f"uids={sorted(map(str, missing_uids))}, "
            f"identifiers={sorted(missing_identifiers)}"
        )

    catalog_rows = _catalog_rows(context, portfolio_uids=list(by_uid))
    catalogued = {uuid.UUID(str(row["portfolio_uid"])): row for row in catalog_rows}
    skipped = tuple(sorted((uid for uid in by_uid if uid not in catalogued), key=str))

    groups: dict[str, list[uuid.UUID]] = {}
    for portfolio_uid, row in catalogued.items():
        groups.setdefault(str(row["values_meta_table_uid"]), []).append(portfolio_uid)

    lookup = meta_table_lookup or default_meta_table_lookup
    visible = {str(getattr(item, "uid", "")): item for item in lookup(sorted(groups))} if groups else {}

    states: list[PortfolioDatasetState] = []
    for values_uid, members in groups.items():
        identifiers = {
            str(by_uid[member]["unique_identifier"]): member for member in members
        }
        meta_table = visible.get(values_uid)
        try:
            if meta_table is None:
                raise LookupError(
                    f"PortfoliosTS instance {values_uid!r} is not a visible TimeIndexMetaTable"
                )
            verify_contract_instance(PORTFOLIOS_CONTRACT, meta_table)
            aggregates = _values_aggregates(
                context,
                meta_table=meta_table,
                portfolio_identifiers=sorted(identifiers),
            )
        except Exception as exc:
            for member in members:
                states.append(
                    _write_state(
                        context,
                        portfolio=by_uid[member],
                        catalog_row=catalogued[member],
                        aggregate=None,
                        error=exc,
                    )
                )
            continue
        for identifier, member in identifiers.items():
            states.append(
                _write_state(
                    context,
                    portfolio=by_uid[member],
                    catalog_row=catalogued[member],
                    aggregate=aggregates.get(identifier, {}),
                    error=None,
                )
            )

    states.sort(key=lambda item: item.portfolio_identifier)
    return PortfolioDatasetReconciliationResult(
        portfolio_uids=tuple(sorted(by_uid, key=str)),
        states=tuple(states),
        skipped_portfolio_uids=skipped,
    )


def list_portfolio_dataset_states(
    context: MarketsOperationContext,
    *,
    portfolio_uids: Sequence[uuid.UUID | str],
) -> tuple[PortfolioDatasetState, ...]:
    """Return the catalog rows of the requested portfolios, without reconciling."""

    normalized = tuple(dict.fromkeys(uuid.UUID(str(item)) for item in portfolio_uids))
    if not normalized:
        return ()
    portfolios = {
        uuid.UUID(str(row["uid"])): row
        for row in _portfolio_rows(context, portfolio_uids=normalized, portfolio_identifiers=())
    }
    states = []
    for row in _catalog_rows(context, portfolio_uids=list(normalized)):
        portfolio = portfolios.get(uuid.UUID(str(row["portfolio_uid"])))
        if portfolio is None:
            continue
        states.append(_state_from_row(portfolio=portfolio, row=row))
    return tuple(sorted(states, key=lambda item: item.portfolio_identifier))


def verify_contract_instance(contract: str, meta_table: Any) -> None:
    """Raise ``ValueError`` unless a registered table satisfies the contract.

    The table must expose every contract column and declare the contract's
    time index and index names. Extra provider columns are allowed.
    """

    definition = portfolio_storage_contract(contract)
    columns = _meta_table_column_names(meta_table)
    if not contract_columns_satisfied(contract, columns):
        missing = sorted(set(definition.column_names) - set(columns))
        raise ValueError(
            f"{definition.name} instance {getattr(meta_table, 'uid', '')!s} is missing contract "
            f"columns {missing}"
        )
    index_names = {str(item) for item in (getattr(meta_table, "table_index_names", None) or ())}
    if index_names and not set(definition.index_names).issubset(index_names):
        raise ValueError(
            f"{definition.name} instance {getattr(meta_table, 'uid', '')!s} declares index names "
            f"{sorted(index_names)}; the contract requires {list(definition.index_names)}"
        )


def _values_aggregates(
    context: MarketsOperationContext,
    *,
    meta_table: Any,
    portfolio_identifiers: Sequence[str],
) -> dict[str, dict[str, Any]]:
    physical_name = str(getattr(meta_table, "physical_table_name", "") or "")
    if not physical_name:
        raise ValueError("PortfoliosTS instance has no physical table name")
    schema = getattr(meta_table, "physical_schema", None)
    values = table(
        physical_name,
        column("time_index"),
        column("portfolio_identifier"),
        schema=None if schema in (None, "", "public") else str(schema),
    )
    statement = (
        select(
            values.c.portfolio_identifier,
            func.count().label("row_count"),
            func.min(values.c.time_index).label("earliest_time_index"),
            func.max(values.c.time_index).label("latest_time_index"),
        )
        .where(values.c.portfolio_identifier.in_(list(portfolio_identifiers)))
        .group_by(values.c.portfolio_identifier)
    )
    rows = operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(statement, context=context, operation="select"),
            context=context,
        )
    )
    return {str(row["portfolio_identifier"]): row for row in rows}


def _write_state(
    context: MarketsOperationContext,
    *,
    portfolio: Mapping[str, Any],
    catalog_row: Mapping[str, Any],
    aggregate: Mapping[str, Any] | None,
    error: Exception | None,
) -> PortfolioDatasetState:
    values: dict[str, Any] = {
        "uid": catalog_row.get("uid") or uuid.uuid4(),
        "portfolio_uid": uuid.UUID(str(catalog_row["portfolio_uid"])),
        "values_meta_table_uid": catalog_row["values_meta_table_uid"],
        "weights_meta_table_uid": catalog_row.get("weights_meta_table_uid"),
        "signal_meta_table_uid": catalog_row.get("signal_meta_table_uid"),
        "reconciled_at": dt.datetime.now(dt.UTC),
    }
    if error is not None:
        values.update(
            population_state="unavailable",
            row_count=None,
            earliest_time_index=None,
            latest_time_index=None,
            error_code=type(error).__name__[:128],
            error_message=str(error)[:1024],
        )
    else:
        row_count = int((aggregate or {}).get("row_count") or 0)
        values.update(
            population_state="populated" if row_count else "compatible_empty",
            row_count=row_count,
            earliest_time_index=(aggregate or {}).get("earliest_time_index"),
            latest_time_index=(aggregate or {}).get("latest_time_index"),
            error_code=None,
            error_message=None,
        )
    persisted = operation_result_rows(
        upsert_model(
            context,
            model=PortfolioDatasetAvailabilityTable,
            values=values,
            conflict_columns=("portfolio_uid",),
        )
    )
    row = persisted[0] if persisted else values
    return _state_from_row(portfolio=portfolio, row=row)


def _bind_signal_metadata_table(
    context: MarketsOperationContext,
    *,
    signal_uid: str,
    meta_table_uid: str,
) -> None:
    rows = operation_result_rows(
        search_model(
            context,
            model=SignalMetadataTable,
            filters={"signal_uid": signal_uid},
            limit=1,
        )
    )
    if not rows:
        return
    update_model(
        context,
        model=SignalMetadataTable,
        uid=rows[0]["uid"],
        values={"meta_table_uid": meta_table_uid},
        returning=False,
    )


def _portfolio_row(
    context: MarketsOperationContext,
    *,
    portfolio_uid: uuid.UUID,
) -> dict[str, Any] | None:
    rows = _portfolio_rows(context, portfolio_uids=(portfolio_uid,), portfolio_identifiers=())
    return rows[0] if rows else None


def _portfolio_rows(
    context: MarketsOperationContext,
    *,
    portfolio_uids: Sequence[uuid.UUID],
    portfolio_identifiers: Sequence[str],
) -> list[dict[str, Any]]:
    statement = select(PortfolioTable)
    conditions = []
    if portfolio_uids:
        conditions.append(PortfolioTable.uid.in_(list(portfolio_uids)))
    if portfolio_identifiers:
        conditions.append(PortfolioTable.unique_identifier.in_(list(portfolio_identifiers)))
    if not conditions:
        return []
    statement = statement.where(or_(*conditions)) if len(conditions) > 1 else statement.where(
        conditions[0]
    )
    return operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(statement, context=context, operation="select"),
            context=context,
        )
    )


def _catalog_rows(
    context: MarketsOperationContext,
    *,
    portfolio_uids: Sequence[uuid.UUID],
) -> list[dict[str, Any]]:
    if not portfolio_uids:
        return []
    return operation_result_rows(
        search_model(
            context,
            model=PortfolioDatasetAvailabilityTable,
            in_filters={"portfolio_uid": list(portfolio_uids)},
            limit=len(portfolio_uids),
        )
    )


def _meta_table_column_names(meta_table: Any) -> tuple[str, ...]:
    values: list[str] = []
    for item in getattr(meta_table, "columns", None) or ():
        name = item.get("name") if isinstance(item, Mapping) else getattr(item, "name", None)
        if name not in (None, ""):
            values.append(str(name))
    return tuple(values)


def _state_from_row(*, portfolio: Mapping[str, Any], row: Mapping[str, Any]) -> PortfolioDatasetState:
    error = row.get("error_message")
    if error and row.get("error_code"):
        error = f"{row['error_code']}: {error}"
    return PortfolioDatasetState(
        portfolio_uid=uuid.UUID(str(portfolio["uid"])),
        portfolio_identifier=str(portfolio["unique_identifier"]),
        values_meta_table_uid=str(row["values_meta_table_uid"]),
        weights_meta_table_uid=row.get("weights_meta_table_uid"),
        signal_meta_table_uid=row.get("signal_meta_table_uid"),
        population_state=row["population_state"],
        row_count=row.get("row_count"),
        earliest_time_index=row.get("earliest_time_index"),
        latest_time_index=row.get("latest_time_index"),
        reconciled_at=row["reconciled_at"],
        error=error,
    )


__all__ = [
    "MAX_RECONCILE_SELECTORS",
    "NOT_RECONCILED_ERROR_CODE",
    "MetaTableLookup",
    "PortfolioDatasetPopulationState",
    "PortfolioDatasetReconciliationResult",
    "PortfolioDatasetRegistration",
    "PortfolioDatasetState",
    "default_meta_table_lookup",
    "list_portfolio_dataset_states",
    "reconcile_portfolio_dataset_availability",
    "register_portfolio_datasets",
    "verify_contract_instance",
]
