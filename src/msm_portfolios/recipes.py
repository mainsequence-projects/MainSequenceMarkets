"""What a producer reuses instead of writing it (ADR 0060, decision 6).

Each recipe is built only on the series operations (``SignalWeightsSeries``,
``PortfolioWeightsSeries``, ``PortfolioValuesSeries``), the registry row classes and
the engine nodes, so it works the same under the ``runtime`` and the ``remote`` row
backend. A producer supplies what is its own (prices, private state tables, strategy and
calendar configuration, and its eligibility rules, applied before it calls a recipe)
and never sends Markets a table uid.

=========================  ===========================================================
``publish_signal_weights``  create a signal's metadata on its first publication and
                            publish observations
``signal_history``          first and last observation of many signals; their latest
                            observations as time by asset matrices
``portfolio_history``       a portfolio's values newest first, with the total count
``weights_as_of``           each portfolio's latest weights at or before a time
``portfolio_preflight``     why a portfolio cannot run yet
``run_portfolios``          run many portfolios' chains in one joined MetaTables run and
                            publish their weights and values; list what failed
``run_portfolio``           the same for one portfolio
``end_signal``              delete a signal's weights and metadata in one Markets call
``delete_private_series``   delete a producer's private rows of portfolios, calendars or
                            accounts, in the order their keys demand
=========================  ===========================================================
"""

from __future__ import annotations

import datetime as dt
import math
import numbers
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from msm_portfolios.services.series import PUBLISH_MAX_ROWS, SeriesBounds, SeriesPublication

TIME_INDEX = "time_index"
ASSET = "asset_identifier"

Observations = Mapping[dt.datetime, Mapping[str, float]]


# Signals -------------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalPublication:
    """What ``publish_signal_weights`` wrote, and the signal after it."""

    signal_uid: str
    written: int
    skipped: int
    assets: tuple[str, ...]
    first_time: dt.datetime | None
    last_time: dt.datetime | None
    row_count: int
    created_metadata: bool


def publish_signal_weights(
    signal_uid: str,
    observations: Observations,
    *,
    description: str | None = None,
) -> SignalPublication:
    """Publish ``observations`` (time -> {asset unique_identifier: weight}) of a signal.

    Creates the signal's ``SignalMetadata`` row on its first publication (its manager is
    the caller), or updates its description when ``description`` differs. Each
    observation is the signal's whole set of weights at its time: an asset the signal
    held that an observation leaves out is written at ``0``; an empty observation
    closes every held asset. Markets refuses the whole call, writing nothing, when a
    time is naive, a weight is not a finite number, an asset is unknown, or an
    observation is at or before the signal's last stored time; publishing the same
    observations again writes nothing. A history longer than one call is published in
    several calls, oldest first.
    """

    from msm_portfolios.api import SignalMetadata, SignalWeightsSeries
    from msm_portfolios.series_nodes import whole_time_batches
    from msm_portfolios.time_index.metadata import ensure_signal_metadata

    pending = _validated_observations(observations)
    created = ensure_signal_metadata(SignalMetadata, signal_uid, description)
    rows: list[dict[str, Any]] = []
    for time, weights in pending:
        if not weights:
            weights = {asset: 0.0 for asset in _held_assets(SignalWeightsSeries, signal_uid)}
            if not weights:
                raise ValueError(
                    f"Observation at {time.isoformat()} has no weights and the signal holds "
                    "nothing to close."
                )
        rows.extend(
            {TIME_INDEX: time, ASSET: asset, "signal_weight": weight}
            for asset, weight in weights.items()
        )
    written = skipped = 0
    publication: SeriesPublication | None = None
    for batch in whole_time_batches(
        sorted(rows, key=lambda row: row[TIME_INDEX]), PUBLISH_MAX_ROWS
    ):
        publication = SignalWeightsSeries.publish(signal_uid, batch)
        written += publication.written
        skipped += publication.skipped
    assert publication is not None
    return SignalPublication(
        signal_uid=signal_uid,
        written=written,
        skipped=skipped,
        assets=tuple(SignalWeightsSeries.assets(signal_uid)),
        first_time=publication.first_time,
        last_time=publication.last_time,
        row_count=publication.row_count,
        created_metadata=created,
    )


@dataclass(frozen=True)
class SignalHistory:
    """``bounds``: each signal's first and last time and row count. ``latest``: each
    signal's latest observations, a time (rows) by asset (columns) matrix of weights."""

    bounds: dict[str, SeriesBounds]
    latest: dict[str, pd.DataFrame] = field(default_factory=dict)


def signal_history(signal_uids: Sequence[str], *, latest: int = 0) -> SignalHistory:
    """First and last observation of ``signal_uids`` in one call, and with ``latest > 0``
    each signal's ``latest`` most recent observations as a time by asset matrix."""

    from msm_portfolios.api import SignalWeightsSeries

    uids = list(dict.fromkeys(str(uid) for uid in signal_uids))
    if not uids:
        return SignalHistory(bounds={})
    bounds = {item.key: item for item in SignalWeightsSeries.bounds(uids)}
    matrices: dict[str, pd.DataFrame] = {}
    if latest > 0:
        for uid in uids:
            matrices[uid] = _latest_observations(SignalWeightsSeries, uid, latest)
    return SignalHistory(bounds=bounds, latest=matrices)


def end_signal(signal_uid: str) -> dict[str, Any]:
    """Delete a signal's weights and its ``SignalMetadata`` row in one Markets call.

    Only the signal's manager may end it; a portfolio that still names the signal
    refuses the delete (the database's ``RESTRICT`` key) and nothing is deleted.
    """

    from msm_portfolios.api import SignalMetadata

    return SignalMetadata.end(signal_uid)


def end_signals(signal_uids: Sequence[str]) -> dict[str, Any]:
    """End several signals in one Markets call: each one's weights and ``SignalMetadata``.

    Every signal that may go is deleted in one transaction. A signal that is missing,
    that the caller does not manage, or that a portfolio still names is listed in
    ``failed`` with the reason and never stops the others (issue 126).
    """

    from msm_portfolios.api import SignalMetadata

    return SignalMetadata.end_many(signal_uids)


# Portfolios ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioHistory:
    """A page of a portfolio's values, newest first, and the portfolio's value count."""

    portfolio_identifier: str
    count: int
    values: pd.DataFrame
    next_offset: int | None


def portfolio_history(
    portfolio_identifier: str, *, limit: int = 100, offset: int = 0
) -> PortfolioHistory:
    """A portfolio's values newest first (``limit`` rows from ``offset``), with the total count."""

    from msm_portfolios.api import PortfolioValuesSeries

    (bounds,) = PortfolioValuesSeries.bounds([portfolio_identifier])
    page = PortfolioValuesSeries.window(
        [portfolio_identifier], newest_first=True, limit=limit, offset=offset
    )
    values = page.frame().sort_index(ascending=False)
    return PortfolioHistory(
        portfolio_identifier=portfolio_identifier,
        count=bounds.row_count,
        values=values,
        next_offset=page.next_offset,
    )


def weights_as_of(
    portfolio_identifiers: Sequence[str], at: dt.datetime | None = None
) -> pd.DataFrame:
    """Each portfolio's latest executed weights at or before ``at`` (now when ``None``).

    Indexed by ``(time_index, portfolio_identifier, asset_identifier)``; a portfolio
    without weights by then has no rows.
    """

    from msm_portfolios.api import PortfolioWeightsSeries

    identifiers = list(dict.fromkeys(str(value) for value in portfolio_identifiers))
    if not identifiers:
        return pd.DataFrame()
    return PortfolioWeightsSeries.last(identifiers, at=at, by="key").frame()


@dataclass(frozen=True)
class PortfolioPreflight:
    """Whether a portfolio can run now; ``reasons`` says why not."""

    ready: bool
    reasons: tuple[str, ...]
    signal_uid: str
    signal_first_time: dt.datetime | None
    signal_last_time: dt.datetime | None


def portfolio_preflight(
    portfolio_configuration: Any, *, portfolio_identifier: str | None = None
) -> PortfolioPreflight:
    """Why the portfolio of ``portfolio_configuration`` cannot run yet.

    A signal whose weights arrive through ``publish_signal_weights`` (an
    ``ApplicationWeights`` signal) must have a published observation; a signal that
    computes its weights is computed by the run. With ``portfolio_identifier``, a
    retired portfolio is reported too: it publishes nothing dated at or after its
    retirement.
    """

    from msm_portfolios.api import SignalWeightsSeries

    signal = _signal_of(portfolio_configuration)
    (bounds,) = SignalWeightsSeries.bounds([str(signal.signal_uid)])
    portfolio = None
    if portfolio_identifier is not None:
        from msm.api.portfolios import Portfolio

        portfolio = Portfolio.get_by_unique_identifier(portfolio_identifier)
    return _preflight(signal, bounds, portfolio)


def _signal_of(portfolio_configuration: Any) -> Any:
    build = portfolio_configuration.portfolio_build_configuration
    return build.backtesting_weights_configuration.signal_weights_instance


def _preflight(signal: Any, bounds: SeriesBounds, portfolio: Any | None) -> PortfolioPreflight:
    reasons: list[str] = []
    signal_uid = str(signal.signal_uid)
    if bounds.row_count == 0 and not signal.computes_weights:
        reasons.append(
            f"Signal {signal_uid} has no published observation; publish its weights with "
            "publish_signal_weights first."
        )
    if portfolio is not None and getattr(portfolio, "retired_at", None) is not None:
        reasons.append(
            f"Portfolio {portfolio.unique_identifier!r} is retired from "
            f"{portfolio.retired_at.isoformat()} (ADR 0049)."
        )
    return PortfolioPreflight(
        ready=not reasons,
        reasons=tuple(reasons),
        signal_uid=signal_uid,
        signal_first_time=bounds.first_time,
        signal_last_time=bounds.last_time,
    )


@dataclass(frozen=True)
class PortfolioRun:
    """What a run of one portfolio wrote: the portfolio row, the weights and values it
    published (``None`` when nothing was new) and whether this run made the first
    rebalance."""

    portfolio: Any
    weights: SeriesPublication | None
    values: SeriesPublication | None
    first_rebalance: bool


@dataclass(frozen=True)
class PortfolioRunFailure:
    """A portfolio ``run_portfolios`` could not run or publish, and why.

    ``portfolio_identifier`` is ``None`` when the portfolio's row could not be resolved;
    ``position`` is the configuration's place in the call. ``error`` is what stopped it:
    the preflight's refusal, its own node's error, or that of a dependency it needs.
    """

    position: int
    portfolio_identifier: str | None
    detail: str
    error: BaseException


@dataclass(frozen=True)
class PortfolioRuns:
    """What ``run_portfolios`` did: each portfolio that ran, in the order given, and
    each one that failed, with its reason."""

    ran: tuple[PortfolioRun, ...]
    failed: tuple[PortfolioRunFailure, ...]


def run_portfolios(
    portfolio_configurations: Sequence[Any],
    *,
    rebalance_output_table: Any = None,
    event_ledger_output_table: Any = None,
    namespace: str | None = None,
    portfolio_resolver: Any = None,
) -> PortfolioRuns:
    """Run many portfolios' chains in one MetaTables run and publish their weights and values.

    The heads of the run are the portfolios' ledgers (``PortfolioEngine``, into
    ``event_ledger_output_table``, the producer's private ``PortfolioEventLedgerTS``
    instance). MetaTables joins their graphs by update uid (``run_updaters``, MetaTables
    ADR 0031), so a dependency several portfolios share, such as their valuation source,
    their calendar events or a strategy's declared input, runs once, before every node
    that reads it. Each ledger's graph holds its rebalance state (into
    ``rebalance_output_table``, the private ``PortfolioRebalanceStateTS`` instance),
    which computes and publishes a signal that computes its weights before it reads it,
    and the signal's own inputs. After the run each portfolio publishes the weights and values its
    ledger projects (ADR 0065), creates its ``Portfolio`` row when it does not exist
    (its manager is the caller) and records its signal on it. A first run starts at the
    signal's first observation.

    A portfolio the preflight refuses, whose row cannot be resolved, whose ledger or a
    dependency it needs fails, or whose publication fails is listed in ``failed`` with
    the reason; it never stops the others.
    """

    return _run_portfolios(
        [(configuration, None) for configuration in portfolio_configurations],
        rebalance_output_table=rebalance_output_table,
        event_ledger_output_table=event_ledger_output_table,
        namespace=namespace,
        portfolio_resolver=portfolio_resolver,
    )


def run_portfolio(
    portfolio_configuration: Any,
    *,
    rebalance_output_table: Any = None,
    event_ledger_output_table: Any = None,
    namespace: str | None = None,
    portfolio_resolver: Any = None,
    portfolio_description: str | None = None,
) -> PortfolioRun:
    """Run one portfolio's chain and publish its weights and values, as ``run_portfolios``.

    Raises what stopped it: ``ValueError`` for a portfolio ``portfolio_preflight`` finds
    not ready, otherwise its own error or a dependency's. ``portfolio_description``
    replaces the description the configuration gives.
    """

    runs = _run_portfolios(
        [(portfolio_configuration, portfolio_description)],
        rebalance_output_table=rebalance_output_table,
        event_ledger_output_table=event_ledger_output_table,
        namespace=namespace,
        portfolio_resolver=portfolio_resolver,
    )
    if runs.failed:
        raise runs.failed[0].error
    return runs.ran[0]


@dataclass
class _Prepared:
    position: int
    identifier: str
    values: Any
    weights: Any
    engine: Any


def _run_portfolios(
    entries: Sequence[tuple[Any, str | None]],
    *,
    rebalance_output_table: Any,
    event_ledger_output_table: Any,
    namespace: str | None,
    portfolio_resolver: Any,
) -> PortfolioRuns:
    from msm_portfolios.api import SignalWeightsSeries
    from msm_portfolios.time_index import PortfolioValues

    failed: dict[int, PortfolioRunFailure] = {}

    def fail(position: int, identifier: str | None, error: BaseException) -> None:
        failed[position] = PortfolioRunFailure(
            position=position, portfolio_identifier=identifier, detail=str(error), error=error
        )

    signals = [_signal_of(configuration) for configuration, _description in entries]
    signal_uids = list(dict.fromkeys(str(signal.signal_uid) for signal in signals))
    bounds = (
        {item.key: item for item in SignalWeightsSeries.bounds(signal_uids)}
        if signal_uids
        else {}
    )
    prepared: list[_Prepared] = []
    for position, ((configuration, description), signal) in enumerate(zip(entries, signals)):
        identifier: str | None = None
        try:
            preflight = _preflight(signal, bounds[str(signal.signal_uid)], None)
            if not preflight.ready:
                raise ValueError("The portfolio cannot run: " + " ".join(preflight.reasons))
            values_node = PortfolioValues(
                portfolio_configuration=configuration,
                portfolio_resolver=portfolio_resolver,
                portfolio_description=description,
                rebalance_output_table=rebalance_output_table,
                event_ledger_output_table=event_ledger_output_table,
                namespace=namespace,
            )
            identifier = str(values_node.prepare_portfolio().unique_identifier)
            weights_node = values_node._ensure_portfolio_weights_node()
            engine = weights_node.ensure_portfolio_engine()
            if preflight.signal_first_time is not None:
                for node in (values_node, weights_node, weights_node.portfolio_rebalance):
                    node.OFFSET_START = preflight.signal_first_time
            prepared.append(_Prepared(position, identifier, values_node, weights_node, engine))
        except Exception as error:
            fail(position, identifier, error)

    errors = _run_ledgers([item.engine for item in prepared])
    published: dict[int, tuple[Any, Any, Any]] = {}
    for item in prepared:
        error = errors[id(item.engine)]
        if error is not None:
            fail(item.position, item.identifier, error)
            continue
        try:
            weights = item.weights.run()
            result = item.values.run()
        except Exception as error:
            fail(item.position, item.identifier, error)
            continue
        published[item.position] = (result["portfolio"], weights, result["portfolio_values"])
    ran = []
    for item in prepared:
        if item.position not in published:
            continue
        portfolio, weights, values = published[item.position]
        ran.append(
            PortfolioRun(
                portfolio=portfolio,
                weights=weights,
                values=values,
                # The run wrote the portfolio's first weights: every row it has is new.
                first_rebalance=weights is not None and weights.row_count == weights.written,
            )
        )
    return PortfolioRuns(ran=tuple(ran), failed=tuple(failed[key] for key in sorted(failed)))


def _run_ledgers(engines: Sequence[Any]) -> dict[int, BaseException | None]:
    """Run every ledger in one joined MetaTables run; each one's error, ``None`` if it ran.

    A node that fails stops only the ledgers that need it (MetaTables ADR 0031). An
    error raised before any node started stops them all.
    """

    from metatables import UpdatersFailedError, run_updaters

    if not engines:
        return {}
    try:
        outcomes = run_updaters(list(engines))
    except UpdatersFailedError as error:
        outcomes = error.outcomes
    except Exception as error:
        return {id(engine): error for engine in engines}
    return {
        id(engine): (
            None
            if outcome.state == "succeeded"
            else outcome.error
            or RuntimeError(f"The ledger {engine.update_hash} did not run ({outcome.state}).")
        )
        for engine, outcome in zip(engines, outcomes)
    }


# Private rows --------------------------------------------------------------------------

PRIVATE_KEY_COLUMNS = {
    "portfolios": "portfolio_identifier",
    "calendars": "calendar_identifier",
    "accounts": "account_uid",
}


def delete_private_series(
    tables: Sequence[type],
    *,
    portfolios: Sequence[str] = (),
    calendars: Sequence[str] = (),
    accounts: Sequence[str] = (),
) -> dict[str, int]:
    """Delete the producer's own rows of ``portfolios``, ``calendars`` or ``accounts``.

    ``tables`` are the producer's private storage classes (built with
    ``configured_portfolio_rebalance_state_storage`` and the other factories, bound to
    its own tables). Each table is cleared of the rows whose ``portfolio_identifier``,
    ``calendar_identifier`` or ``account_uid`` is given, in one transaction, a table
    before the tables it references. Run it before the registry delete: a private
    ``RESTRICT`` key on a registry row refuses that delete while rows remain. The
    statements run on the producer's own runtime (its MetaTables grants), never on the
    Markets API. Answers the rows deleted per table.
    """

    from sqlalchemy import delete, func, select
    from sqlalchemy.schema import sort_tables

    from msm.repositories.base import (
        MarketsRepositoryContext,
        compile_markets_statement,
        compile_markets_statements,
        execute_markets_operation,
        execute_markets_write,
        resolve_markets_sql_target,
    )

    keys = {
        PRIVATE_KEY_COLUMNS[name]: [str(value) for value in values]
        for name, values in (
            ("portfolios", portfolios),
            ("calendars", calendars),
            ("accounts", accounts),
        )
        if values
    }
    if not keys or not tables:
        return {}
    by_table = {model.__table__: model for model in tables}
    ordered = list(reversed(sort_tables(by_table)))
    context = MarketsRepositoryContext()
    statements: list[Any] = []
    counts: dict[str, int] = {}
    for table in ordered:
        conditions = [
            table.c[column].in_(values) for column, values in keys.items() if column in table.c
        ]
        if not conditions:
            raise ValueError(
                f"{by_table[table].__name__} has none of the columns {sorted(keys)}; it holds "
                "no rows of the given keys."
            )
        condition = conditions[0] if len(conditions) == 1 else conditions[0] | conditions[1]
        for extra in conditions[2:]:
            condition = condition | extra
        result = execute_markets_operation(
            compile_markets_statement(
                select(func.count().label("row_count")).select_from(table).where(condition),
                context=context,
                operation="select",
            ),
            context=context,
        )
        counts[table.name] = int((result.get("rows") or [{}])[0].get("row_count") or 0)
        statements.append(delete(table).where(condition))
    data_source_uid, dialect = resolve_markets_sql_target(context)
    execute_markets_write(
        compile_markets_statements(
            statements,
            context=context,
            operation="delete",
            data_source_uid=data_source_uid,
            dialect=dialect,
        ),
        context=context,
    )
    return counts


# Helpers -------------------------------------------------------------------------------


def _held_assets(series: Any, signal_uid: str) -> list[str]:
    latest = series.last([signal_uid], by="asset").rows
    return sorted(str(row[ASSET]) for row in latest if row.get("signal_weight") not in (None, 0.0))


def _latest_observations(series: Any, signal_uid: str, count: int) -> pd.DataFrame:
    """The ``count`` latest observations of a signal, a time by asset matrix, oldest first."""

    times: list[dt.datetime] = []
    rows: list[dict[str, Any]] = []
    offset = 0
    while len(times) <= count:
        page = series.window([signal_uid], newest_first=True, limit=5_000, offset=offset)
        for row in page.rows:
            if row[TIME_INDEX] not in times:
                if len(times) == count:
                    break
                times.append(row[TIME_INDEX])
            rows.append(row)
        else:
            if page.next_offset is None:
                break
            offset = page.next_offset
            continue
        break
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame[TIME_INDEX] = pd.to_datetime(frame[TIME_INDEX], utc=True)
    return frame.pivot(index=TIME_INDEX, columns=ASSET, values="signal_weight").sort_index()


def _validated_observations(
    observations: Observations,
) -> list[tuple[dt.datetime, dict[str, float]]]:
    if not isinstance(observations, Mapping) or not observations:
        raise ValueError("publish needs at least one observation: {time: {asset: weight}}.")
    validated: dict[dt.datetime, dict[str, float]] = {}
    for time, weights in observations.items():
        if not isinstance(time, dt.datetime):
            raise TypeError(f"Observation times must be datetimes; got {type(time).__name__}.")
        if time.tzinfo is None or time.utcoffset() is None:
            raise ValueError(f"Observation time {time.isoformat()} has no timezone.")
        utc_time = pd.Timestamp(time).tz_convert("UTC").to_pydatetime()
        if not isinstance(weights, Mapping):
            raise TypeError(
                f"Observation at {utc_time.isoformat()} must map asset identifiers to weights."
            )
        validated[utc_time] = {
            _validated_asset(asset, utc_time): _validated_weight(weight, asset, utc_time)
            for asset, weight in weights.items()
        }
    return sorted(validated.items())


def _validated_asset(asset: Any, time: dt.datetime) -> str:
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError(
            f"Observation at {time.isoformat()} has an empty or non-string asset identifier "
            f"{asset!r}."
        )
    return asset


def _validated_weight(weight: Any, asset: str, time: dt.datetime) -> float:
    if isinstance(weight, bool) or not isinstance(weight, numbers.Real):
        raise TypeError(f"Weight of {asset!r} at {time.isoformat()} is not a number: {weight!r}.")
    if not math.isfinite(weight):
        raise ValueError(f"Weight of {asset!r} at {time.isoformat()} is not finite: {weight!r}.")
    return float(weight)


__all__ = [
    "PortfolioHistory",
    "PortfolioPreflight",
    "PortfolioRun",
    "PortfolioRunFailure",
    "PortfolioRuns",
    "SignalHistory",
    "SignalPublication",
    "delete_private_series",
    "end_signal",
    "portfolio_history",
    "portfolio_preflight",
    "publish_signal_weights",
    "run_portfolio",
    "run_portfolios",
    "signal_history",
    "weights_as_of",
]
