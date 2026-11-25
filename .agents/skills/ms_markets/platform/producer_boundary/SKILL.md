---
name: mainsequence-markets-producer-boundary
description: Read this before designing how an application meets ms-markets — any application that computes or receives signal weights, runs portfolios, or keeps its own tables next to the Markets registries. It states the rule (Markets reads and writes only its own tables; data crosses by publish or keep), how to choose per dataset, the recipes a producer reuses, how to build private state tables, what a producer never does, a template for the producer's own boundary ADR, and a verification checklist (ADR 0060).
---

# Main Sequence Markets: the producer boundary

ms-markets is the base other applications build on. Any application that computes
or receives signals, runs portfolios, or keeps data next to the Markets registries is
a *producer*. This skill is how a producer meets Markets. ADR 0060 is the decision.

## The rule

**Markets reads and writes only its own tables.** No route, row operation, service,
Job or command of ms-markets takes a table uid, name or namespace from a caller and
reads, counts, checks or deletes what it names.

Data crosses the boundary of ms-markets in two ways, and no third:

- **Publish.** The application sends rows to a Markets operation. Markets stores them
  in its own table and serves them. The rows are Markets' from then on.
- **Keep.** The application keeps data in its own tables and serves or shares it
  itself. Markets holds nothing about it.

The test for every design: **would Markets need to read my table for this to work?**
If yes, the design is wrong. Publish the rows, or keep them and serve them yourself.

## Choosing, per dataset

| Dataset | Choice | Why |
| --- | --- | --- |
| Signal weights the application receives | Publish (`SignalWeightsSeries`) | A series Markets defines for a registry row; every reader reads it the same way |
| Signal weights the application computes | Keep in its own signal table **and** publish (`SignalWeightsSeries`) | The signal is its own node: its table is the node's output, which the application's rebalance reads; every other reader reads Markets |
| Executed weights and values of a registered portfolio | Publish (`PortfolioWeightsSeries`, `PortfolioValuesSeries`) | Same |
| Rebalance state, calendar events, event ledger | Keep (private state tables) | Only the engine that runs the portfolio needs them |
| Prices the application owns, its own analytics, anything else | Keep | Not a Markets series |
| A portfolio that must not be shared | Do not register it in Markets | Publishing shares the rows with every reader of Markets |

A published row is stored once, in Markets. A producer keeps no copy of it and has no
table for it, with one exception: a signal it computes is its own node, which writes the
producer's own signal table and publishes the same rows to Markets (ADR 0060, amended on
2026-11-24).

## What a producer supplies and what it reuses

The producer supplies what is its own: the price source, the private state tables, the
strategy and calendar configuration, and its eligibility rules (which assets or owners
it accepts). It applies its rules **before** it calls a recipe. Everything else is a
recipe in `msm_portfolios.recipes`, built only on the series operations, so each works
under the `runtime` and the `remote` row backend:

| Recipe | Signature | What it does |
| --- | --- | --- |
| `publish_signal_weights` | `(signal_uid, observations, *, description=None) -> SignalPublication` | Creates the signal's `SignalMetadata` on its first publication, publishes `{time: {asset: weight}}` observations, answers written/skipped rows, assets, first and last time |
| `signal_history` | `(signal_uids, *, latest=0) -> SignalHistory` | First and last observation of many signals in one call; with `latest`, each signal's latest observations as a time by asset matrix |
| `portfolio_history` | `(portfolio_identifier, *, limit=100, offset=0) -> PortfolioHistory` | A portfolio's values newest first, with the total count |
| `weights_as_of` | `(portfolio_identifiers, at=None) -> DataFrame` | Each portfolio's latest executed weights at or before `at` |
| `portfolio_preflight` | `(portfolio_configuration, *, portfolio_identifier=None) -> PortfolioPreflight` | Why a portfolio cannot run yet (a published signal with no observation, a retired portfolio) |
| `run_portfolios` | `(portfolio_configurations, *, rebalance_output_table=None, event_ledger_output_table=None, namespace=None, portfolio_resolver=None, updaters=(), node_job=None, max_parallel_nodes=-1) -> PortfolioRuns` | Runs every portfolio's ledger, and the producer's own `updaters`, in one joined MetaTables run (`run_updaters`): a dependency they share (prices, calendar events, a computed signal and its inputs, a strategy's input) runs once; a computed signal's node writes its table and publishes before the rebalances that read it; then each portfolio publishes the weights and values its ledger projects and creates or updates its `Portfolio` row. With `node_job`, each node runs in its own run of that Job, independent ones at the same time, up to `max_parallel_nodes` (ADR 0067). Answers `ran` (a `PortfolioRun` each, in the order given), `failed` (position, identifier, reason, error) and `updaters` (each updater's MetaTables outcome); a refused or failed portfolio never stops the others. The per-tick call |
| `run_portfolio` | `(portfolio_configuration, *, rebalance_output_table=None, event_ledger_output_table=None, namespace=None, portfolio_resolver=None, portfolio_description=None, node_job=None, max_parallel_nodes=-1) -> PortfolioRun` | `run_portfolios` for one portfolio: answers what was written and whether a first rebalance happened, or raises what stopped it |
| `end_signal` | `(signal_uid) -> dict` | Deletes a signal's weights and its metadata in one Markets call |
| `end_signals` | `(signal_uids) -> dict` | Ends several signals in one Markets call and one transaction; answers `ended`, and `failed` with each refused or missing signal's reason, which never stops the others |
| `delete_private_series` | `(tables, *, portfolios=(), calendars=(), accounts=(), signals=()) -> dict[str, int]` | Deletes the producer's private rows of the given keys, a table before the tables it references, before the registry delete |

The series operations are the primitive; use them directly when no recipe fits.
Each takes a `key` (`signal_uid`, or the portfolio's `unique_identifier`):

| Operation | Signature |
| --- | --- |
| `publish` | `(key, rows) -> SeriesPublication` — one key, one transaction, at most `PUBLISH_MAX_ROWS` (10,000) rows; equal rows skipped, a different row refuses the call |
| `window` | `(keys, start=None, end=None, columns=None, [assets=None,] limit=5000, offset=0, newest_first=False) -> SeriesRows` — `next_offset` pages |
| `last` | `(keys, at=None, [by="key"\|"asset",] inclusive=True, [assets=None]) -> SeriesRows` |
| `bounds` | `(keys) -> list[SeriesBounds]` — first and last time and row count per key |
| `assets` | `(key) -> list[str]` |
| `delete_after` | `(key, time) -> SeriesDeletion` — deletes the key's rows after `time`, so they can be published again |

`SeriesRows.frame()` gives a DataFrame indexed like the table. Only the row's manager
publishes to it or deletes it (`managed_by`, below).

### Worked example: from weights to a published portfolio

```python
import datetime as dt

from msm.client import MarketsClient
from msm.api.remote import use_remote_backend
from msm_portfolios import recipes
from msm_portfolios.contrib.signals import ApplicationWeights, ApplicationWeightsConfig

use_remote_backend(MarketsClient.from_environment().backend)  # every Markets call goes to the API

signal = ApplicationWeights.from_signal_configuration(
    ApplicationWeightsConfig(provider="my-app", key="model-a")
)
# The application's own rules run first: which assets, which owners it accepts.
weights = {dt.datetime(2026, 3, 2, 21, tzinfo=dt.UTC): {"AAA": 0.6, "BBB": 0.4}}
recipes.publish_signal_weights(signal.signal_uid, weights, description="Model A")

configuration = build_portfolio_configuration(signal)  # the application's strategy and prices
print(recipes.portfolio_preflight(configuration))
run = recipes.run_portfolio(
    configuration,
    rebalance_output_table=MyRebalanceState,  # private, below
    event_ledger_output_table=MyEventLedger,  # private, below
    portfolio_resolver=my_resolver,
)
print(run.weights, run.values, run.first_rebalance)
history = recipes.portfolio_history(run.portfolio.unique_identifier)
```

`ApplicationWeights.publish(observations)` is the same as `publish_signal_weights` for
that signal. It is no node: the rebalance reads it from Markets.

A signal the application computes (`MarketCap`, `FixedWeights`, or its own subclass of
`SignalWeights`) is its own node of the portfolio DAG, with the application's own signal
table as `output_table=` (below). In a run, MetaTables runs the updaters its
`dependencies()` names, then the signal: its update writes the signal's metadata when it is
missing or changed, publishes the new rows to Markets (with the manager check) and returns
them for its table. The rebalance depends on it (`signal_weights`) and reads its table: its
window, and each asset's last row before it. A first run starts at the signal's first
observation.

```python
signal = FixedWeights.from_signal_configuration(
    fixed_weights_config,
    output_table=MySignals,  # private, below
    namespace="my-app",
)
```

Every portfolio of a tick goes in one call, so what they share runs once (issue #133):

```python
runs = recipes.run_portfolios(
    [configuration_a, configuration_b],
    rebalance_output_table=MyRebalanceState,
    event_ledger_output_table=MyEventLedger,
    portfolio_resolver=my_resolver,
)
for failure in runs.failed:
    print(failure.position, failure.portfolio_identifier, failure.detail)
```

On a hosted runtime the same call runs each node in its own run of the producer's node
Job, independent nodes at the same time (ADR 0067). The producer's other updaters join
the same graph, so what they share with the portfolios runs once:

```python
runs = recipes.run_portfolios(
    [configuration_a, configuration_b],
    rebalance_output_table=MyRebalanceState,
    event_ledger_output_table=MyEventLedger,
    portfolio_resolver=my_resolver,
    updaters=[my_report],             # outcomes in runs.updaters
    node_job="Updater node",          # the node Job's spec.name
    max_parallel_nodes=8,
)
```

- The node Job's script is `from msm_portfolios.node_job import run_node; run_node()`.
  Declare the Job in the workflow file and give the Job that calls `run_portfolios`
  `runner` access to it (`docs/knowledge/msm_portfolios/portfolios/index.md`,
  "A Producer's Own Updaters And Parallel Runs").
- A node Job run is a new process. Every table is a top-level class statement
  (ADR 0066), and a node reads another node's result from its table only.
- `node_job` is refused on a local runtime: develop and test without it.

`PortfolioWeights.run()` and `PortfolioValues.run()` publish what the ledger holds and
run nothing; the recipes are the way to run a portfolio.

## Managers

`Portfolio.managed_by` and `SignalMetadata.managed_by` name the principal that created
the row, recorded by Markets from the acting identity: `branch:<uid>` for a workload
of a code repository branch (every Job, release and Agent of one application in one
Environment), `user:<uid>` for a person or any other identity. A caller never sends
it. `publish`, `delete_after` and the row's delete refuse any other caller with 403.
A row created before ADR 0060 has no manager and accepts no publish until an
Organization admin assigns one:

```bash
msm registry assign-manager --manager branch:<branch uid> --portfolio <identifier> --execute
```

The `msm` command imports only `msm`. To assign signals, add `--attach module:callable`:
a callable of yours that attaches the runtime and imports `msm_portfolios.api`.

## Private state tables

Declare each private state table with a class statement on a contract base of
`msm_portfolios.time_index.contract_instances`, at the top level of a module of the
application (`my_app/tables.py`), in its own namespace, migrated by its own provider:

```python
from msm_portfolios.time_index.contract_instances import (
    PortfolioEventLedgerInstance,
    PortfolioRebalanceStateInstance,
)


class MyRebalanceState(PortfolioRebalanceStateInstance, MyBase):
    __instance_key__ = "main"
    __metatable_namespace__ = "my-app"
    __markets_storage_app__ = "my_app"


class MyEventLedger(PortfolioEventLedgerInstance, MyBase):
    __instance_key__ = "main"
    __metatable_namespace__ = "my-app"
    __markets_storage_app__ = "my_app"
```

`MyBase` is the application's own declarative base, for its hand-written tables too,
and its provider targets `MyBase.metadata` (`platform/metatable_migrations` has the
template).

The signals the application computes share one table of its own, an instance of
`SignalWeightsTS` keyed by `signal_uid`:

```python
from msm_portfolios.time_index.signals.storage import SignalWeightsInstance


class MySignals(SignalWeightsInstance, MyBase):
    __instance_key__ = "signals"
    __metatable_namespace__ = "my-app"
    __markets_storage_app__ = "my_app"
```

A signal node refuses Markets' own `SignalWeightsTS`: only publishing writes it.

Bind the engine to them: `rebalance_output_table=` and `event_ledger_output_table=` on
`run_portfolios`, `run_portfolio`, `PortfolioValues` and `PortfolioWeights`, and `output_table=` on the
calendar events updater. Each other Markets storage has its own contract base
(`<Contract>Instance`, `msm.storage_instances`), declared the same way. Every instance
states `__instance_key__`, `__metatable_namespace__` and `__markets_storage_app__` and
inherits the application's base: none falls back to Markets' own. A node Job run
imports each class by `module:qualname`, so never build one in a function or in the
script that is run. An interpolated-price table is such an instance, keyed by its
configuration (`portfolios/portfolio_workflow`).

A private table may reference a registry row with a physical foreign key (each
contract gives its instances its keys to `Portfolio.unique_identifier`,
`Asset` and `Calendar`) and declares its delete action. That key points from the
application to Markets and is the only coupling between them, in the application's
metadata too: the key passes Markets' own column object, and no Markets table is
copied there. Markets does not discover, count or name the table:

- a registry delete deletes Markets' own rows and lets the database apply every key;
- a `RESTRICT` key that refuses answers 409 with the database's message;
- the application deletes its own rows first, in key order:

```python
recipes.delete_private_series([MyLedger, MyRebalanceState], portfolios=[identifier])
# then DELETE /api/v1/portfolio/{uid}/ (Markets deletes the published series with it)
recipes.delete_private_series([MySignals], signals=[signal_uid])
recipes.end_signal(signal_uid)  # a computed signal's rows in MySignals would refuse it
```

## What a producer never does

- Grant Markets (`markets-api` or `migrate-markets`) a role on its tables or namespace.
- Register a table with Markets, or send Markets a table uid, name or namespace.
- Keep a namespace for Markets to read.
- Keep a copy, an instance or a cache of a published series. A computed signal's own
  table is the one exception: its node writes it and publishes the same rows.
- Write a Markets table directly with its own MetaTables grant instead of publishing.
- Name another application, connector or product in ms-markets.

## Template: the producer's boundary ADR

Each application records its boundary in an ADR of its own, with these sections:

1. **What it does today**: the datasets it computes or receives, and where they live.
2. **What it publishes**: each series (`SignalWeightsSeries`, `PortfolioWeightsSeries`,
   `PortfolioValuesSeries`), for which signals and portfolios, through which recipe.
3. **What stays private**: each table it keeps, its namespace, its keys to Markets
   registry rows and their delete actions.
4. **Where each read comes from afterwards**: per read, the recipe or series operation
   (`signal_history`, `portfolio_history`, `weights_as_of`, `window`, `last`) or its own
   table.
5. **Delete order**: `delete_private_series` over which tables (its computed signals'
   table included), then which Markets deletes (`end_signal`, the portfolio delete).
6. **Business rules that do not change**: eligibility, ownership, schedules; applied
   before each recipe.
7. **Rollout in each Environment**: `msm registry assign-manager` for rows that predate
   it, `msm series publish` for history held in its own instances, verification, then a
   later revision of its own that drops those instances.

## Moving existing history

Nothing moves by itself. A person runs, in each Environment:

1. `msm registry assign-manager --manager branch:<uid> --unmanaged --attach
   module:callable` (dry run), then with `--execute`, so the application's workloads may
   publish to their rows. Without `--attach`, only portfolios are assigned.
2. `msm series publish module:callable` (dry run), then with `--execute`. The callable
   returns `msm_portfolios.series_history.SeriesHistoryPublish(source=<instance class>,
   series="signal-weights" | "portfolio-weights" | "portfolio-values", keys=[...])`.
   It reads the instance with the operator's own access, publishes key by key and
   compares `bounds`; the source is unchanged.
3. A later revision of the application drops its instances once every key is verified.

## Checklist

- [ ] No role on any of the application's tables or namespaces is held by a Markets
      workload (`markets-api`, `migrate-markets`).
- [ ] No table uid, name or namespace of the application appears in a call to Markets.
- [ ] The application has no table for portfolio weights or values, and no signal table
      but its computed signals' own, which their nodes write and publish every run.
- [ ] Every read of those series goes through a recipe or a series operation.
- [ ] Private tables are class statements on the contract bases, at the top level of a
      module, listed by the application's provider, and deleted with
      `delete_private_series` before registry deletes.
- [ ] The metadata the application's provider targets holds no Markets table.
- [ ] A new Environment needs no person's step for Markets beyond the application's own
      access to the Markets API (and, once, `assign-manager` for rows that predate
      ADR 0060).
