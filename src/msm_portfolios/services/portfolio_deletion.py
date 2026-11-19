"""Delete portfolios with their own datasets (ADR 0049, issue 93).

`DELETE /api/v1/portfolio/{uid}/`, `POST /api/v1/portfolio/bulk-delete/` and the remote
`POST /api/v1/rows/portfolio/delete/` run these functions, and
`POST /api/v1/portfolio/bulk-delete/preflight/` reports what they would do.

A portfolio is deleted with its rows in its seven Markets datasets (weights, values,
rebalance state, analytics, event ledger, state and cash flows) in one MetaTables
transaction, or not at all. Two kinds of reference refuse it before anything is sent:

- account history, the virtual funds and account target rows that name the portfolio.
  It is kept for as long as the account exists (ADR 0049 decision 1).
- a table other than the portfolio's own Markets tables whose `RESTRICT` key references
  the portfolio, such as a provider's contract instance, while it holds rows of the
  portfolio or when Markets cannot check it. Markets never deletes rows in another
  application's table (ADR 0047, ADR 0050 decision 2).

After the transaction commits, MetaTables rebuilds the stored update statistics of
each dataset table that lost rows, so a portfolio re-created under the same identifier
starts from scratch instead of at the deleted portfolio's last time index.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mainsequence.logconf import logger as _mainsequence_logger

from msm.api.http import TableImpact, TableImpactNode
from msm.repositories.base import MarketsRepositoryContext
from msm.storage_instances import PROVIDER_TABLE_DELETE_GUIDANCE, provider_owned_table_uid
from msm_portfolios.repositories import portfolio_deletion as portfolio_deletion_repository
from msm_portfolios.repositories.portfolio_deletion import (
    ACCOUNT_HISTORY_REFERENCES,
    PORTFOLIO_DATASET_TABLES,
)
from msm_portfolios.time_index.portfolios.storage import PortfoliosStorage, PortfolioWeightsStorage

logger = _mainsequence_logger.bind(sub_application="markets", component="portfolio_deletion")


class PortfolioDeleteConflictError(ValueError):
    """A reference refuses the portfolio delete. Nothing was deleted."""


ACCOUNT_HISTORY_GUIDANCE = (
    "Account history is kept for as long as the account exists (ADR 0049); retire the "
    "portfolio instead."
)
_HISTORY_BLOCKERS = {
    "virtual_funds": (
        "{count} virtual fund{plural} target it (VirtualFundTable.target_portfolio_uid, "
        "ON DELETE RESTRICT)."
    ),
    "target_positions": (
        "{count} account target-position row{plural} name it "
        "(TargetPositionsStorage.portfolio_uid, ON DELETE RESTRICT)."
    ),
}
_CONTRACT_KEY = ("portfolio_identifier", "unique_identifier")
"""The key every portfolio contract instance copies from the contract (ADR 0047)."""
_CATALOGUED_DATASETS = (
    ("values_meta_table_uid", PortfoliosStorage),
    ("weights_meta_table_uid", PortfolioWeightsStorage),
)
_CONFLICT_MARKERS = ("foreign key", "violates", "referenced", "restrict", "constraint")
_COUNT_CHUNK = 500


@dataclass(frozen=True)
class ForeignPortfolioTable:
    """A table outside the portfolio's own Markets tables with a ``RESTRICT`` key to it.

    ``unavailable`` says why its rows cannot be counted; such a table blocks every
    portfolio it is checked for.
    """

    label: str
    uid: str | None = None
    constraint: str | None = None
    relation: str | None = None
    column: str | None = None
    target_column: str | None = None
    portfolio_relation: str | None = None
    meta_table: Any = None
    unavailable: str | None = None

    @property
    def key(self) -> str:
        return f"{self.uid or self.label}:{self.constraint or ''}"


@dataclass(frozen=True)
class PortfolioDeleteImpact:
    """MetaTables' delete impact for the portfolio table, and the tables to check."""

    impact: TableImpact | None
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    foreign_tables: tuple[ForeignPortfolioTable, ...] = ()


@dataclass(frozen=True)
class _PlannedDelete:
    """One portfolio as the counting read found it, with what blocks its delete."""

    uid: str
    unique_identifier: str
    row_counts: dict[str, int]
    history_blockers: tuple[str, ...] = ()
    foreign_blockers: tuple[str, ...] = ()

    @property
    def blockers(self) -> list[str]:
        return [*self.history_blockers, *self.foreign_blockers]

    @property
    def label(self) -> str:
        return f"Portfolio {self.unique_identifier!r}"

    def preflight(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "unique_identifier": self.unique_identifier,
            "row_counts": dict(self.row_counts),
            "blockers": self.blockers,
        }


def portfolio_delete_impact(
    *,
    timeout: int | float | tuple[float, float] | None = None,
) -> PortfolioDeleteImpact:
    """MetaTables' delete impact for the portfolio table, with the tables to check.

    Every ``RESTRICT`` key into the portfolio table from a table other than the
    portfolio's seven datasets, ``VirtualFund`` and ``TargetPositionsStorage`` is
    resolved to the table and column that hold it, so the delete can count that
    table's rows of each portfolio. A table Markets cannot view or read is kept with
    the reason, and blocks. An unavailable impact is a warning: the database still
    applies every key when the delete runs.
    """

    from msm.models import PortfolioTable
    from msm.services.table_impact import delete_rows_impact

    base = delete_rows_impact(PortfolioTable)
    foreign: dict[str, ForeignPortfolioTable] = {}
    if base.impact is not None:
        nodes = {node.id: node for node in base.impact.nodes}
        root = nodes.get(base.impact.root_uid)
        portfolio_relation = (
            _relation(root.physical_schema, root.physical_table_name)
            if root is not None and root.physical_table_name
            else None
        )
        own_uids, own_names = _own_reference_tables()
        for edge in base.impact.edges:
            if edge.kind != "foreign_key" or edge.effect != "restrict":
                continue
            if edge.target != base.impact.root_uid:
                continue
            node = nodes.get(edge.source)
            if _is_own_reference(node, own_uids=own_uids, own_names=own_names):
                continue
            table = _impact_table(
                node,
                constraint=edge.name,
                portfolio_table_uid=base.impact.root_uid,
                portfolio_relation=portfolio_relation,
                timeout=timeout,
            )
            foreign.setdefault(table.key, table)
    return PortfolioDeleteImpact(
        impact=base.impact,
        warnings=list(base.warnings),
        blockers=list(base.blockers),
        foreign_tables=tuple(foreign.values()),
    )


def delete_portfolio_record(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    impact: PortfolioDeleteImpact | None = None,
) -> dict[str, Any] | None:
    """Delete one portfolio with its rows in its seven datasets, in one transaction.

    Returns ``None`` when the portfolio does not exist. Raises
    `PortfolioDeleteConflictError` when account history or another application's table
    references it; then nothing is deleted. ``deleted_rows`` counts the rows per
    dataset just before the delete ran. After the transaction commits, the stored
    update statistics of each dataset table that lost rows are rebuilt; the datasets
    whose statistics could not be are listed in ``statistics_not_refreshed``.
    """

    portfolio_uid = _canonical_uid(uid)
    impact = impact if impact is not None else portfolio_delete_impact(timeout=context.timeout)
    planned = _plan(context, [portfolio_uid], impact=impact).get(portfolio_uid)
    if planned is None or not _delete_planned(context, planned, impact=impact):
        return None
    not_refreshed = _refresh_statistics(context, [planned])
    return _deleted_response(planned, not_refreshed[planned.uid])


def bulk_delete_portfolio_records(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> dict[str, Any]:
    """Delete each portfolio with its datasets, each in its own transaction.

    One read counts every selected portfolio. A portfolio that is missing or refused is
    reported in ``failed`` and the others are still deleted. After the transactions,
    each dataset table that lost rows has its stored update statistics rebuilt once,
    for every portfolio the request deleted.
    """

    target_uids = _unique_uids(uids)
    impact = portfolio_delete_impact(timeout=context.timeout)
    plan = _plan(context, target_uids, impact=impact)
    deleted: list[_PlannedDelete] = []
    failed: list[dict[str, str]] = []
    for uid in target_uids:
        planned = plan.get(uid)
        try:
            done = planned is not None and _delete_planned(context, planned, impact=impact)
        except PortfolioDeleteConflictError as exc:
            failed.append({"uid": uid, "detail": str(exc)})
            continue
        if not done:
            failed.append({"uid": uid, "detail": f"Portfolio {uid} was not found."})
            continue
        deleted.append(planned)
    not_refreshed = _refresh_statistics(context, deleted)
    count = len(deleted)
    if count == 0:
        detail = "No portfolios were deleted."
    else:
        detail = (
            f"Deleted {count} portfolio{'s' if count != 1 else ''} with "
            f"{'its' if count == 1 else 'their'} datasets."
        )
    if failed:
        detail += f" {len(failed)} could not be deleted."
    stale = [
        table.key
        for table in PORTFOLIO_DATASET_TABLES
        if any(table.key in keys for keys in not_refreshed.values())
    ]
    if stale:
        detail += f" {_not_refreshed_text(stale)}"
    return {
        "detail": detail,
        "deleted_count": count,
        "deleted": [_deleted_response(item, not_refreshed[item.uid]) for item in deleted],
        "failed": failed,
    }


def preflight_bulk_delete_portfolio_records(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[uuid.UUID | str],
) -> dict[str, Any]:
    """Report what deleting the portfolios removes and what blocks it, without deleting.

    It runs the delete's own checks: the same counting read and the same tables of
    other applications, so a portfolio it allows is deleted unless its references
    change in between.
    """

    target_uids = _unique_uids(uids)
    impact = portfolio_delete_impact(timeout=context.timeout)
    plan = _plan(context, target_uids, impact=impact)
    portfolios: list[dict[str, Any]] = []
    blockers: list[str] = []
    history_blocked = foreign_blocked = False
    for uid in target_uids:
        planned = plan.get(uid)
        if planned is None:
            blockers.append(f"Portfolio {uid} was not found.")
            continue
        portfolios.append(planned.preflight())
        blockers.extend(f"{planned.label}: {blocker}" for blocker in planned.blockers)
        history_blocked = history_blocked or bool(planned.history_blockers)
        foreign_blocked = foreign_blocked or bool(planned.foreign_blockers)
    blockers.extend(impact.blockers)
    warnings = list(impact.warnings)
    if history_blocked:
        warnings.append(ACCOUNT_HISTORY_GUIDANCE)
    if foreign_blocked:
        warnings.append(PROVIDER_TABLE_DELETE_GUIDANCE)
    allowed = bool(target_uids) and not blockers
    matched = len(portfolios)
    detail = (
        f"{matched} portfolio{' is' if matched == 1 else 's are'} ready for deletion with "
        f"{'its' if matched == 1 else 'their'} datasets."
        if allowed
        else "The portfolio selection cannot be deleted as submitted."
    )
    return {
        "allowed": allowed,
        "detail": detail,
        "matched_count": matched,
        "blockers": blockers,
        "warnings": warnings,
        "impact": impact.impact,
        "portfolios": portfolios,
    }


# The delete ------------------------------------------------------------------------------


def _delete_planned(
    context: MarketsRepositoryContext,
    planned: _PlannedDelete,
    *,
    impact: PortfolioDeleteImpact,
) -> bool:
    """Run one portfolio's transaction: ``False`` when it vanished in between."""

    if planned.blockers:
        raise PortfolioDeleteConflictError(_refusal(planned))
    try:
        result = portfolio_deletion_repository.delete_portfolio(
            context,
            uid=planned.uid,
            unique_identifier=planned.unique_identifier,
        )
    except Exception as exc:
        if not _is_delete_conflict(exc):
            raise
        # A key the checks did not see, or a row written since: name it if it shows now.
        current = _plan(context, [planned.uid], impact=impact).get(planned.uid)
        if current is not None and current.blockers:
            raise PortfolioDeleteConflictError(_refusal(current)) from exc
        raise PortfolioDeleteConflictError(
            f"{planned.label} cannot be deleted; nothing was deleted. {exc}{_restrict_hint(impact)}"
        ) from exc
    if not result.get("rows"):
        # The guard stopped the list: the portfolio vanished, was renamed, or account
        # history named it in between. Nothing was deleted.
        current = _plan(context, [planned.uid], impact=impact).get(planned.uid)
        if current is None:
            return False
        if current.blockers:
            raise PortfolioDeleteConflictError(_refusal(current))
        raise PortfolioDeleteConflictError(
            f"{planned.label} changed while it was being deleted; nothing was deleted. "
            "Retry the delete."
        )
    return True


def _deleted_response(planned: _PlannedDelete, not_refreshed: Sequence[str]) -> dict[str, Any]:
    detail = f"{planned.label} deleted with its datasets."
    if not_refreshed:
        detail += f" {_not_refreshed_text(not_refreshed)}"
    return {
        "detail": detail,
        "uid": planned.uid,
        "unique_identifier": planned.unique_identifier,
        "deleted_count": 1,
        "deleted_rows": dict(planned.row_counts),
        "statistics_not_refreshed": list(not_refreshed),
    }


def _refusal(planned: _PlannedDelete) -> str:
    text = f"{planned.label} cannot be deleted; nothing was deleted. {' '.join(planned.blockers)}"
    if planned.history_blockers:
        text += f" {ACCOUNT_HISTORY_GUIDANCE}"
    if planned.foreign_blockers:
        text += f" {PROVIDER_TABLE_DELETE_GUIDANCE}"
    return text


def _restrict_hint(impact: PortfolioDeleteImpact) -> str:
    if not impact.foreign_tables:
        return ""
    tables = ", ".join(dict.fromkeys(table.label for table in impact.foreign_tables))
    return (
        f" Tables of other applications whose RESTRICT keys can refuse it: {tables}. "
        f"{PROVIDER_TABLE_DELETE_GUIDANCE}"
    )


def _is_delete_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _CONFLICT_MARKERS)


# Update statistics -----------------------------------------------------------------------

_STATISTICS_REFRESH_CUTOFF = "9999-12-31T00:00:00+00:00"
"""A ``delete_after_date`` cutoff later than any stored row, so the refresh deletes
nothing, not even rows a portfolio re-created under the same identifier wrote since."""


def _refresh_statistics(
    context: MarketsRepositoryContext,
    deleted: Sequence[_PlannedDelete],
) -> dict[str, list[str]]:
    """Rebuild MetaTables' stored update statistics of each dataset table that lost rows.

    The delete's statements are plain deletes, which leave the progress MetaTables
    stores for each table (``index_stats``) as it was (MetaTables#117): the deleted
    identifiers keep their last time index until the next insert into the table
    rebuilds it, and a portfolio re-created under the same identifier whose updater
    writes first would resume from it. ``TimeIndexMetaTable.delete_after_date``
    rebuilds the table's statistics from its rows and replaces the stored ones. It
    runs once per table, after every transaction of the request, scoped to the
    deleted identifiers, with a cutoff that matches no row.
    ``set-last-update-index-time`` would not do: it merges into the stored statistics
    and keeps the deleted entries. Remove this once MetaTables#117 is fixed.

    A failure, such as the rebuild exceeding MetaTables' statement timeout on a
    large table, does not undo the delete. It is logged, and the answer lists, per
    deleted portfolio uid, the datasets whose statistics were not refreshed.
    """

    not_refreshed: dict[str, list[str]] = {item.uid: [] for item in deleted}
    for table in PORTFOLIO_DATASET_TABLES:
        affected = [item for item in deleted if item.row_counts.get(table.key, 0) > 0]
        if not affected:
            continue
        identifiers = [item.unique_identifier for item in affected]
        try:
            meta_table = table.model.get_time_index_meta_table()
            if meta_table is None:
                raise RuntimeError(
                    f"{table.model.__name__} is not attached to a backend TimeIndexMetaTable."
                )
            meta_table.delete_after_date(
                _STATISTICS_REFRESH_CUTOFF,
                dimension_filters={"portfolio_identifier": identifiers},
                timeout=context.timeout,
            )
        except Exception:
            logger.exception(
                "Portfolio delete could not refresh a dataset table's update statistics",
                dataset=table.key,
                portfolio_identifiers=identifiers,
            )
            for item in affected:
                not_refreshed[item.uid].append(table.key)
    return not_refreshed


def _not_refreshed_text(datasets: Sequence[str]) -> str:
    return (
        "MetaTables could not refresh the stored update statistics of "
        f"{', '.join(datasets)}; see statistics_not_refreshed."
    )


# The checks ------------------------------------------------------------------------------


def _plan(
    context: MarketsRepositoryContext,
    uids: Sequence[str],
    *,
    impact: PortfolioDeleteImpact,
) -> dict[str, _PlannedDelete]:
    """Count the portfolios' rows in one read and check every other table once.

    Each table from the impact is checked for every portfolio; a catalogued instance
    another application owns, for the portfolios whose catalog row names it.
    """

    counted = portfolio_deletion_repository.count_portfolio_delete_rows(context, uids=uids)
    checks: dict[str, tuple[ForeignPortfolioTable, set[str]]] = {
        table.key: (table, {row["unique_identifier"] for row in counted.values()})
        for table in impact.foreign_tables
    }
    # An instance the impact already lists is checked for every portfolio.
    impact_uids = {table.uid for table in impact.foreign_tables if table.uid}
    for row in counted.values():
        for table_uid in _catalogued_instances(row):
            if table_uid in impact_uids:
                continue
            if table_uid not in checks:
                checks[table_uid] = (_catalog_table(table_uid, timeout=context.timeout), set())
            checks[table_uid][1].add(row["unique_identifier"])
    counts = {
        key: _count_foreign_rows(table, sorted(identifiers), timeout=context.timeout)
        for key, (table, identifiers) in checks.items()
        if identifiers
    }

    plan: dict[str, _PlannedDelete] = {}
    for uid, row in counted.items():
        identifier = row["unique_identifier"]
        foreign_blockers: list[str] = []
        for key, (table, identifiers) in checks.items():
            if identifier not in identifiers:
                continue
            found = counts[key]
            if isinstance(found, str):
                foreign_blockers.append(_unchecked_blocker(table, found))
            elif found.get(identifier, 0) > 0:
                foreign_blockers.append(_rows_blocker(table, found[identifier]))
        plan[uid] = _PlannedDelete(
            uid=uid,
            unique_identifier=identifier,
            row_counts={table.key: row[table.key] for table in PORTFOLIO_DATASET_TABLES},
            history_blockers=tuple(_history_blockers(row)),
            foreign_blockers=tuple(foreign_blockers),
        )
    return plan


def _history_blockers(row: Mapping[str, Any]) -> list[str]:
    blockers = []
    for key, _model, _column in ACCOUNT_HISTORY_REFERENCES:
        count = int(row.get(key) or 0)
        if count > 0:
            blockers.append(
                _HISTORY_BLOCKERS[key].format(count=count, plural="s" if count != 1 else "")
            )
    return blockers


def _rows_blocker(table: ForeignPortfolioTable, count: int) -> str:
    rows = f"{count} row that references" if count == 1 else f"{count} rows that reference"
    return (
        f"{_owner_phrase(table)} holds {rows} it ({_key_phrase(table)}); "
        "Markets does not delete them."
    )


def _unchecked_blocker(table: ForeignPortfolioTable, reason: str) -> str:
    return (
        f"{_owner_phrase(table)} references portfolios ({_key_phrase(table)}) and could not be "
        f"checked for rows of this portfolio: {reason}"
    )


def _owner_phrase(table: ForeignPortfolioTable) -> str:
    if table.uid is None:
        return table.label
    return f"Table {table.label}, which another application owns,"


def _key_phrase(table: ForeignPortfolioTable) -> str:
    name = f" {table.constraint}" if table.constraint else ""
    return f"RESTRICT key{name}"


def _catalogued_instances(row: Mapping[str, Any]) -> Iterable[str]:
    """Instances another application owns that the catalog row names for the portfolio."""

    for column, core_storage in _CATALOGUED_DATASETS:
        owned = provider_owned_table_uid(row.get(column), core_storage=core_storage)
        if owned is not None:
            yield owned


# Tables of other applications ------------------------------------------------------------


def _own_reference_tables() -> tuple[set[str], set[str]]:
    """The uids and table names of the Markets tables the delete handles itself."""

    models = [
        *(table.model for table in PORTFOLIO_DATASET_TABLES),
        *(model for _key, model, _column in ACCOUNT_HISTORY_REFERENCES),
    ]
    uids = {str(uid) for uid in (model.get_meta_table_uid() for model in models) if uid}
    names = {str(model.__table__.name) for model in models}
    return uids, names


def _is_own_reference(
    node: TableImpactNode | None,
    *,
    own_uids: set[str],
    own_names: set[str],
) -> bool:
    if node is None or node.type != "meta_table":
        return False
    if node.uid and str(node.uid) in own_uids:
        return True
    from msm.settings import markets_namespace

    in_markets = not node.namespaces or markets_namespace() in node.namespaces
    return in_markets and node.physical_table_name in own_names


def _impact_table(
    node: TableImpactNode | None,
    *,
    constraint: str | None,
    portfolio_table_uid: str,
    portfolio_relation: str | None,
    timeout: Any,
) -> ForeignPortfolioTable:
    """Resolve a ``restrict`` edge's source to the table and column that hold the key."""

    if node is None or node.type != "meta_table" or not node.uid:
        return ForeignPortfolioTable(
            label="A table you cannot view",
            constraint=constraint,
            unavailable="Markets cannot view that table.",
        )
    label = _table_label(node.identifier or node.physical_table_name, node.uid)
    meta_table, error = _load_meta_table(node.uid, timeout=timeout)
    if meta_table is None:
        return ForeignPortfolioTable(label=label, uid=node.uid, constraint=constraint, unavailable=error)
    key = _portfolio_key(meta_table, portfolio_table_uid=portfolio_table_uid, constraint=constraint)
    if key is None:
        return ForeignPortfolioTable(
            label=label,
            uid=node.uid,
            constraint=constraint,
            unavailable="its key to the portfolio table could not be read.",
        )
    return ForeignPortfolioTable(
        label=label,
        uid=node.uid,
        constraint=constraint,
        relation=_relation(
            getattr(meta_table, "physical_schema", None) or node.physical_schema,
            getattr(meta_table, "physical_table_name", None) or node.physical_table_name,
        ),
        column=key[0],
        target_column=key[1],
        portfolio_relation=portfolio_relation,
        meta_table=meta_table,
    )


def _catalog_table(table_uid: str, *, timeout: Any) -> ForeignPortfolioTable:
    """A catalogued instance another application owns, keyed as the contract requires."""

    meta_table, error = _load_meta_table(table_uid, timeout=timeout)
    if meta_table is None:
        return ForeignPortfolioTable(label=table_uid, uid=table_uid, unavailable=error)
    return ForeignPortfolioTable(
        label=_table_label(getattr(meta_table, "identifier", None), table_uid),
        uid=table_uid,
        relation=_relation(
            getattr(meta_table, "physical_schema", None),
            getattr(meta_table, "physical_table_name", None),
        ),
        column=_CONTRACT_KEY[0],
        target_column=_CONTRACT_KEY[1],
        meta_table=meta_table,
    )


def _load_meta_table(table_uid: str, *, timeout: Any) -> tuple[Any, str | None]:
    from metatables import MetaTable

    try:
        return MetaTable.get_by_uid(str(table_uid), timeout=timeout), None
    except Exception as exc:
        logger.warning("Portfolio delete could not read a referencing table", table_uid=table_uid)
        return None, f"Markets could not read that table ({exc})."


def _portfolio_key(
    meta_table: Any,
    *,
    portfolio_table_uid: str,
    constraint: str | None,
) -> tuple[str, str] | None:
    """The table's single-column key to ``Portfolio.uid`` or ``Portfolio.unique_identifier``."""

    for foreign_key in getattr(meta_table, "foreign_keys", None) or []:
        if str(foreign_key.target_table_uid or "") != str(portfolio_table_uid):
            continue
        if constraint and foreign_key.name and foreign_key.name != constraint:
            continue
        source, target = list(foreign_key.source_columns), list(foreign_key.target_columns)
        if len(source) == 1 and len(target) == 1 and target[0] in ("uid", "unique_identifier"):
            return str(source[0]), str(target[0])
    return None


def _count_foreign_rows(
    table: ForeignPortfolioTable,
    identifiers: Sequence[str],
    *,
    timeout: Any,
) -> dict[str, int] | str:
    """Rows per portfolio identifier in ``table``, or why they cannot be counted."""

    if table.unavailable is not None:
        return table.unavailable
    if table.target_column == "uid" and table.portfolio_relation is None:
        return "its key references Portfolio.uid and the portfolio table's name is unknown."
    counts: dict[str, int] = {}
    for start in range(0, len(identifiers), _COUNT_CHUNK):
        chunk = identifiers[start : start + _COUNT_CHUNK]
        try:
            result = table.meta_table.run_query(
                _count_sql(table, chunk),
                max_rows=len(chunk),
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("Portfolio delete could not count a referencing table", table_uid=table.uid)
            return f"the count query failed ({exc})."
        for row in _query_rows(result):
            identifier = str(row.get("portfolio_identifier"))
            counts[identifier] = counts.get(identifier, 0) + int(row.get("row_count") or 0)
    return counts


def _count_sql(table: ForeignPortfolioTable, identifiers: Sequence[str]) -> str:
    keys = ", ".join(_quote_literal(identifier) for identifier in identifiers)
    column = _quote_identifier(str(table.column))
    if table.target_column == "unique_identifier":
        return (
            f"SELECT {column} AS portfolio_identifier, COUNT(*) AS row_count "
            f"FROM {table.relation} WHERE {column} IN ({keys}) GROUP BY {column}"
        )
    identifier_column = _quote_identifier("unique_identifier")
    uid_column = _quote_identifier("uid")
    return (
        f"SELECT p.{identifier_column} AS portfolio_identifier, COUNT(*) AS row_count "
        f"FROM {table.relation} AS t JOIN {table.portfolio_relation} AS p "
        f"ON t.{column} = p.{uid_column} WHERE p.{identifier_column} IN ({keys}) "
        f"GROUP BY p.{identifier_column}"
    )


def _query_rows(result: Any) -> list[Mapping[str, Any]]:
    if not isinstance(result, Mapping):
        return []
    rows = result.get("results")
    if rows is None:
        rows = result.get("rows")
    return [row for row in rows or [] if isinstance(row, Mapping)]


def _relation(schema: str | None, table_name: str | None) -> str | None:
    if not table_name:
        return None
    parts = [part for part in (schema, table_name) if part]
    return ".".join(_quote_identifier(str(part)) for part in parts)


def _table_label(identifier: str | None, table_uid: str) -> str:
    if identifier in (None, ""):
        return str(table_uid)
    return f"{identifier} ({table_uid})"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _canonical_uid(uid: uuid.UUID | str) -> str:
    return str(uuid.UUID(str(uid)))


def _unique_uids(uids: Sequence[uuid.UUID | str]) -> list[str]:
    return list(dict.fromkeys(_canonical_uid(uid) for uid in uids))


__all__ = [
    "ACCOUNT_HISTORY_GUIDANCE",
    "ForeignPortfolioTable",
    "PortfolioDeleteConflictError",
    "PortfolioDeleteImpact",
    "bulk_delete_portfolio_records",
    "delete_portfolio_record",
    "portfolio_delete_impact",
    "preflight_bulk_delete_portfolio_records",
]
