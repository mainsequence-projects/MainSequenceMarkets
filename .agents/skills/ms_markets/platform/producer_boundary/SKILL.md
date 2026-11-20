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
| Signal weights of a registered signal | Publish (`SignalWeightsSeries`) | A series Markets defines for a registry row; every reader reads it the same way |
| Executed weights and values of a registered portfolio | Publish (`PortfolioWeightsSeries`, `PortfolioValuesSeries`) | Same |
| Rebalance state, calendar events, event ledger | Keep (private state tables) | Only the engine that runs the portfolio needs them |
| Prices the application owns, its own analytics, anything else | Keep | Not a Markets series |
| A portfolio that must not be shared | Do not register it in Markets | Publishing shares the rows with every reader of Markets |

A published row is stored once, in Markets. A producer keeps no copy of it and has no
table for it.

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
| `portfolio_preflight` | `(portfolio_configuration, *, portfolio_identifier=None) -> PortfolioPreflight` | Why a portfolio cannot run yet (a published signal with no observation, a ledger portfolio, a retired portfolio) |
| `run_portfolio` | `(portfolio_configuration, *, rebalance_output_table=None, namespace=None, portfolio_resolver=None, portfolio_description=None) -> PortfolioRun` | Runs the chain in order (signal, prices and calendar events, rebalance state, weights, values) from the signal's first observation, creates or updates the `Portfolio` row, publishes, answers what was written and whether a first rebalance happened |
| `end_signal` | `(signal_uid) -> dict` | Deletes a signal's weights and its metadata in one Markets call |
| `delete_private_series` | `(tables, *, portfolios=(), calendars=(), accounts=()) -> dict[str, int]` | Deletes the producer's private rows of the given keys, a table before the tables it references, before the registry delete |

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
    portfolio_resolver=my_resolver,
)
print(run.weights, run.values, run.first_rebalance)
history = recipes.portfolio_history(run.portfolio.unique_identifier)
```

`ApplicationWeights.publish(observations)` is the same as `publish_signal_weights` for
that signal. A signal that computes its weights (`MarketCap`, `FixedWeights`, ...)
is published by `run_portfolio`, or by its own `run()`.

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

Build the private state tables with the factories of
`msm_portfolios.time_index.contract_instances`, in the application's own namespace,
migrated by the application's own provider:

```python
from msm_portfolios.time_index.contract_instances import (
    configured_portfolio_calendar_events_storage,
    configured_portfolio_event_ledger_storage,
    configured_portfolio_rebalance_state_storage,
)

MyRebalanceState = configured_portfolio_rebalance_state_storage(
    instance_key="main", namespace="my-app", storage_app="my_app", base=MyBase
)
```

Bind the engine to them: `rebalance_output_table=` on `PortfoliosUpdater`,
`PortfolioWeights` and `run_portfolio`, and `output_table=` on the calendar events and
ledger updaters. `configured_time_index_instance` builds an instance of any other
Markets storage.

A private table may reference a registry row with a physical foreign key (the
factories copy the contract's keys to `Portfolio.unique_identifier`, `Asset` and
`Calendar`) and declares its delete action. That key points from the application to
Markets and is the only coupling between them. Markets does not discover, count or
name the table:

- a registry delete deletes Markets' own rows and lets the database apply every key;
- a `RESTRICT` key that refuses answers 409 with the database's message;
- the application deletes its own rows first, in key order:

```python
recipes.delete_private_series([MyLedger, MyRebalanceState], portfolios=[identifier])
# then DELETE /api/v1/portfolio/{uid}/ (Markets deletes the published series with it)
```

## What a producer never does

- Grant Markets (`markets-api` or `migrate-markets`) a role on its tables or namespace.
- Register a table with Markets, or send Markets a table uid, name or namespace.
- Keep a namespace for Markets to read.
- Keep a copy, an instance or a cache of a published series.
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
5. **Delete order**: `delete_private_series` over which tables, then which Markets
   deletes (`end_signal`, the portfolio delete).
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
- [ ] The application has no table for signal weights, portfolio weights or values.
- [ ] Every read of those series goes through a recipe or a series operation.
- [ ] Private tables are built with the factories and deleted with
      `delete_private_series` before registry deletes.
- [ ] A new Environment needs no person's step for Markets beyond the application's own
      access to the Markets API (and, once, `assign-manager` for rows that predate
      ADR 0060).
