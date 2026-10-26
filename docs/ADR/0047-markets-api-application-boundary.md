# 0047. Markets API As The Application Boundary

## Status

Proposed. Drafted 2026-10-25 from an analysis of this repository, of how
applications consume it, and of the installed MetaTables and SDK contracts. The
`development` branch has since moved to MetaTables 0.1.51, whose namespace and
table roles (`owner`, `editor`, `data_writer`, `data_viewer`, `metadata_viewer`)
replace the Reader and Writer vocabulary used below; the grant boundaries this
ADR draws are unchanged by that rename, and implementation uses the role names.

Migration path step 1 is implemented on `development` except per-service
ownership and Team scoping policy, which is still open (see "Implementation
notes" at the end). Steps 2 to 4 are not implemented.

It builds on [ADR 0008](0008-metatable-table-and-api-model-split.md) (row
objects separate from table declarations), [ADR 0030](0030-explicit-portfolio-price-source-dependency.md)
(explicit upstream references for portfolio inputs), [ADR 0037](0037-index-formula-and-custom-calculation-framework.md)
and [ADR 0038](0038-index-user-api-and-fastapi-exploration.md) (Index datasets
catalogued by table uid) and [ADR 0041](0041-installable-provider-http-toolkit.md)
(installable HTTP contracts). It changes nothing in those decisions. It amends
[ADR 0043](0043-sdk-9-metatables-client-hard-cut.md) in one respect: the row
API gains a remote backend, so a consumer no longer needs the MetaTables client
to use `msm.api`.

## Context

### Two surfaces that do not meet

`ms-markets` ships two application surfaces:

- The row API under `msm.api`. `Asset.filter()`, `Portfolio.get_by_uid()` and
  the rest resolve the process runtime, compile a SQLAlchemy statement in
  `msm.repositories.crud` and execute it through `MetaTable.execute_operation`.
  The MetaTables client authenticates as the process: a developer locally, the
  workload User when hosted.
- The FastAPI application under `apps/v1`, deployed as the `markets-api`
  release with 158 operations. It verifies the caller with
  `install_request_identity` and then executes every query as its own
  workload User. No service reads `User.get_logged_user()`; the only
  caller-aware code is the Index actor, which sets a display hint.

No application calls the second surface from code. The README advertises an
`msm.client` package of client-facing wrappers; it does not exist. Every
consumer uses the first surface, which makes it a MetaTables principal with
grants on `mainsequence.markets`.

### What consumers look like today

A consumer application, for example an analytics API that serves the Command
Center, imports `msm`, `msm_portfolios` and `msm_pricing`, attaches dozens of
MetaTables at startup, compiles raw SQL against ms-markets table classes and
writes Index rows through the row API. Its workload User needs Reader on the
whole `mainsequence.markets` namespace, Writer on the Index tables it edits and
view on the repository branches whose deployments own those tables. It pins an
exact ms-markets release because the imported table classes must match the
schema the Markets migration Job applied, and it applies no per-user
authorization of its own.

A provider application extends the ontology with sidecar tables and computes
portfolios. A project mixin that changes only the physical-name prefix still
registers every table in the `mainsequence.markets` namespace, so the provider's
Team is granted Writer on the whole Markets namespace. Providers also write
Asset, Account, Portfolio, Index, Calendar or AssetCategory rows directly.

### Why the current boundary is wrong

- Access is table-shaped, not domain-shaped. Markets cannot say "this Team
  sees these portfolios" or "only the author retires this formula". A Reader
  grant on the namespace is all or nothing, and Writer on a table is full
  control of it.
- Audit loses the person. MetaTables records the consumer workload as the
  actor of every read and write, never the user in the browser.
- Schema coupling crosses deployments. Consumers must install the exact
  release the Markets deployment migrated to and redeploy in lockstep.
- The core time-index tables are multi-tenant. `PortfoliosTS`,
  `PortfolioWeightsTS` and `SignalWeightsTS` hold rows from every provider,
  partitioned by `portfolio_identifier` and `signal_uid`. MetaTables grants are
  per table, so every provider that runs the portfolio engine needs Writer on
  Markets tables. This, more than any sidecar, is why providers end up as
  co-owners of the Markets namespace.
- The Markets API carries no authority because nobody calls it, so it stays a
  pass-through without policy. The two problems reinforce each other.

The in-process design is right for one audience: the Markets deployment's own
API, migration Job and updater Jobs, which must read and write the tables
they own. The mistake is using that producer path as the integration surface
for other applications.

### What the platform already provides

- MetaTables recommends one namespace per application, owned by a Team per
  Environment, and enforces grants in the database as the caller's own role.
- The SDK request identity carries the caller, its Teams and, on a
  requester-bound call, the person the call works for. `acts_for_requester`
  lets an application be authorized as that person; MetaTables honours the
  requester on read-only query paths.
- `metatables.endpoint` discovers a release by name in the caller's
  Environment with `ResourceRelease.filter_admin` and obtains a bearer token
  through `resolve_runtime_access`. That is a complete application-to-application
  call mechanism, used today only to reach MetaTables.
- `msm_portfolios` updaters already accept any output table that matches the
  storage contract (`output_table` in `msm_portfolios.time_index.base`), and
  `configured_interpolated_prices_storage` already builds a contract-identical
  table under a different physical name.
- Index already catalogues datasets by table uid in
  `IndexDatasetAvailabilityTable`, discovers them through
  `TimeIndexMetaTable.filter_by_body`, and reads values by `meta_table_uid`.

## Decision

### 1. One owner per table, and the Markets API as the boundary for registries

The ontology has three tiers with different rules:

| Tier | Examples | Writer | Other applications |
| --- | --- | --- | --- |
| Shared registries | Asset, Account, Portfolio, Index, Calendar, AssetCategory, OrderManager | Markets, through its API | Read and write through the Markets API, or read as the person |
| Time-index facts | portfolio values and weights, signal weights, bars, trades, holdings, curves | The producer, in its own namespace | Read by table uid, through the Markets API or as the person |
| Extension-owned tables | provider account details, bar configurations, universes | The provider, in its own namespace | Through the provider's own API |

The Markets API becomes the only way another application creates, updates or
deletes a registry row. Direct MetaTables access to `mainsequence.markets` is
reserved for the Markets deployment itself. No other Team is Writer on that
namespace.

### 2. A contracts package and a remote row backend

Split the distribution along the ADR 0008 seam:

- `ms-markets-contracts`: the Pydantic row and payload models under `msm.api`,
  the HTTP contracts under `msm.api.http`, constants and the storage layout
  contracts. No SQLAlchemy, no `metatables`, no QuantLib.
- `ms-markets`: everything else, including models, repositories, migrations,
  time-index updaters and the FastAPI application.

Add `msm.client`, the package the README already names. It is a typed HTTP
client over the `apps/v1` OpenAPI document that returns `msm.api` row models.
It discovers the `markets-api` release in the caller's Environment and
authenticates exactly as `metatables.endpoint` does for MetaTables. The row
classes get a pluggable backend: `runtime`, the current compiled-SQL path, for
the Markets deployment and producers; `remote`, the client, for every other
application. `Portfolio.get_by_uid()` is the same call under both.

Consumers depend on `ms-markets-contracts` with a `>=2,<3` range. The wire
contract, not the table schema, is the compatibility promise.

### 3. Authorization in the Markets API

Every handler and service authorizes against one identity: the requester on a
requester-bound call, the caller otherwise, never both. The `markets-api`
resource declares `acts_for_requester: true` in its workflow. Only an
Organization admin can enable it: the declaration takes effect only when the
person who pushes it is an Organization admin, and otherwise the resource fails
before it deploys. Services enforce
domain policy: ownership and Team scoping for
portfolios, accounts, indexes and formula definitions, and application-level
permissions such as "this application may register accounts". Writes keep
running as the Markets workload, whose Writer grant is the single place writes
are allowed; the API's policy decides who may trigger them.

### 4. Provider-owned namespaces and sidecars

Each provider registers its tables in its own catalog namespace, owned by a
Team per Environment whose members are the provider's workloads. The existing
project mixins must declare `__metatable_namespace__`; inheriting
`mainsequence.markets` from `MarketsMetaTableMixin` is a defect of the current
extension pattern and is withdrawn.

A sidecar table keyed one-to-one by a core uid remains the extension
mechanism, with these rules:

- A physical foreign key to a core table is allowed and declares its delete
  action. It is data integrity, not access; Markets' impact preflight and
  related-table discovery depend on it.
- A provider that wants Markets to hydrate its sidecar on registry reads
  grants the Markets workload Reader on that table. The grant points from the
  extension to the core, never the reverse.
- Extension migrations reference core tables by physical name and the stable
  `uid` column, as `examples/msm/indices/extension_owned_index_storage.py`
  does with a metadata copy, instead of importing the core class. ms-markets
  promises the uid column of each registry table as a stable contract.
- Registries that several applications populate gain a `managed_by`
  discriminator and an external reference, so "accounts of provider X" is a
  core filter rather than a join.

### 5. Contract plus instances for time series, with a Markets catalog

`PortfoliosTS`, `PortfolioWeightsTS` and `SignalWeightsTS` become storage
contracts with any number of instances. ms-markets owns the contract: columns,
dtypes, time index and index names. A provider owns its instances: a
`<provider>__portfoliosts` table in the provider's namespace, migrated by the
provider's migration provider, written by the provider's updaters with
`output_table=`. The existing
core tables remain the Markets-owned instance for portfolios Markets computes
itself. A provider may add columns beyond the contract; Markets reads the
contract columns and ignores the rest.

Markets keeps the catalog. A `PortfolioDatasetAvailabilityTable`, mirroring
the Index one, records for each portfolio the values table uid, the weights
table uid, the signal table uid, population state and latest time. The
provider registers these through the Markets API when it creates the
portfolio and reconciles them after each run. `SignalMetadataTable` gains the
same reference to its instance.

The Markets read services resolve the table from the catalog and read it by
uid through `TimeIndexTableRef`, filtered by `portfolio_identifier`. A request
for several portfolios groups them by table uid, reads each table once and
returns one `core.tabular_frame@v1` frame. The fan-out is bounded by the
number of providers, not of portfolios. Comparing portfolios computed by two
different providers is therefore one call whose two sources live in two
namespaces.

Who may read is a separate, narrow grant: the Markets workload gets Reader on
each provider's time-series tables, or the call is requester-bound and the
person's own grants apply. Ad hoc analysis across providers runs as the person
with a `UNION ALL` over contract-identical tables.

Markets may still compute portfolios for callers that have no provider. It is
then one more producer writing its own instance. Nothing in this decision
depends on Markets running an engine; signals, strategies and engines stay
with providers, as `msm_portfolios` intends.

## Worked example: a provider account sidecar

A broker provider keeps its account details in a one-to-one sidecar on
`ms_markets__account.uid` with cascade delete, including application-encrypted
credential columns. Today the sidecar is registered in `mainsequence.markets`.
Listing registrations compiles a join over both tables and runs it as the
provider workload. Registration runs `Account.upsert`, an upsert on the sidecar
and a holdings snapshot as three separate MetaTables requests.

Under this ADR:

- The sidecar moves to the provider's namespace. Its foreign key, its encrypted
  columns and the provider's migration provider are unchanged. The encrypted
  columns are the reason the sidecar must stay provider-owned: only a process
  holding the provider's keyring can open them. `include` never returns them:
  Markets skips every column the catalog marks as application-encrypted and
  drops any encryption-envelope value, so a `data_viewer` grant for `include`
  exposes only the plain columns.
- `Account.upsert` and the active-flag update go through the Markets account
  create and update routes, `POST /api/v1/account/` and
  `PATCH /api/v1/account/{uid}/`. The holdings snapshot uses the existing
  `addAccountHoldings` route. Atomicity is unchanged; a composite register
  route on Markets could later make it better than today.
- The list query pages on the sidecar, which duplicates the paper flag and the
  unique identifier, and hydrates core columns with one batch lookup by uid.
  Adding the account name and the active flag to the sidecar removes the join
  from the common path.
- The provider's Team drops Writer on `mainsequence.markets`.

## Worked example: a provider-computed portfolio

A provider Job builds a tracking portfolio from its own signal and its own
price bars. Today it writes five time-index tables, all registered in
`mainsequence.markets`: its bars and interpolated prices, which it migrates,
and signal weights, portfolio values and portfolio weights, which are Markets'
shared tables. It also upserts the Calendar and Portfolio rows.
`PortfolioTable` has producer uid columns, but `portfolio_values()` in
`msm_portfolios.services.portfolio_reads` selects from the fixed core table and
ignores them.

Under this ADR:

- The provider declares its own portfolio values, portfolio weights and signal
  weights instances through the storage factories ms-markets exposes for the
  three contracts, in the provider's namespace, migrated by the provider. Its
  bars and interpolated prices move to that namespace too.
- The provider's signal updater and `PortfoliosUpdater` are bound to those
  instances with `output_table=`. The signal, the strategy and the engine code
  stay in the provider's repository.
- The Portfolio row is created through the Markets API with the three table
  uids, the calendar and the strategy configuration. After each run the Job
  reconciles the portfolio dataset availability.
- The provider's Team is Writer on its own namespace only and grants the
  Markets workload Reader on its three time-series tables.
- A consumer obtains the portfolio values frame for portfolios from several
  providers through one Markets route.

## Migration path

1. Markets API: add `acts_for_requester`, the acting-identity helper and
   per-service policy; add account create and update, formula save, activate,
   retire and preview, batch lookups by uid, `include` hydration and
   multi-portfolio frames; add the portfolio dataset catalog and switch the
   read services to it. Fix the README's `msm.client` line until the package
   exists.
2. Packaging: publish `ms-markets-contracts` and `msm.client` with the remote
   row backend.
3. Providers: declare their namespace in their mixins, move existing tables
   with a namespace move, declare contract instances for portfolios and
   signals, bind updaters to them, backfill from their own updaters, register the
   catalog rows, and replace direct registry writes with API calls. Drop
   Writer on `mainsequence.markets`.
4. Consumers: switch each consumer route family by route family, portfolio
   reads first, then index authoring, then holdings and pricing; remove
   `start_engine`, drop the namespace grants, and replace the exact pin with the
   contracts range. New applications start on the client and hold no tables.

## Consequences

- Grants become narrow and point one way: providers write their own
  namespace; Markets reads what providers share with it; consumers hold no
  table grants.
- The person is the actor of registry writes and of requester-bound reads,
  in both the Markets policy and the MetaTables audit.
- Pure consumers stop depending on the MetaTables client and on the Markets
  schema. Producers and extensions still move with the MetaTables client for
  their own tables, which is unavoidable for table owners.
- Markets takes on a versioned public contract, batch routes and policy code.
  This is centralized work traded for lockstep churn across every consumer.
- Reads that spanned one table may span several. The fan-out is bounded by
  provider count and hidden behind one route.
- Existing shared time-series tables keep serving Markets-computed portfolios;
  provider rows in them are backfilled into provider instances once.
- The row API has two backends until the runtime backend becomes internal to
  the Markets deployment and its producers.

## Non-goals

- A generic SQL endpoint on the Markets API. It would recreate raw table
  access over HTTP. Ad hoc cross-namespace queries run as the person through
  MetaTables.
- Row-level ownership inside shared tables. MetaTables grants are per table
  by design; this ADR works with that rather than against it.
- Moving signals, strategies or engines into Markets.

## Implementation notes

### 2026-10-25: step 1, decision 5 (contract plus instances, catalog)

Implemented in `msm_portfolios.time_index.contract_instances`,
`msm.models.portfolio_dataset_availability`, Alembic revision `0021`,
`msm_portfolios.services.portfolio_datasets` and
`msm_portfolios.services.portfolio_reads`. Deviations and refinements:

- The catalog row is one per portfolio, carrying the values, weights and
  signal instance uids together, as this ADR lists them. The reconciled
  population state, row count and time bounds describe the values instance;
  weights and signal instances are catalogued but not aggregated. The Index
  catalog has one row per (Index, dataset) because every cadence table is a
  dataset in its own right; for a portfolio the values series is the dataset
  and the other two are its supporting facts.
- An instance is named `<storage_app>__<contract>__<instance_key>` and
  identified as `<Contract>.<instance_key>`, namespace-prefixed outside the
  default Markets namespace. Decision 5's `<provider>__portfoliosts` is
  therefore `<provider>__portfoliosts__<instance_key>`; the key keeps two
  instances of one provider distinct.
- Registration verifies each declared table against the contract (columns and
  index names) through the MetaTables catalog before writing the row, and
  reconciles at once; `reconcile=False` leaves the row `unavailable` with error
  code `not_reconciled` until the first run. A provider that adds columns
  passes verification.
- Reads use `TimeIndexTableRef` for catalogued instances and keep the compiled
  SQL path for the core tables, so a portfolio without a catalog row behaves
  exactly as before. Reconciliation aggregates provider instances with one
  compiled `count`, `min`, `max` statement per instance; this needs the Markets
  workload to hold `data_viewer` on the instance, which is the grant this ADR
  asks providers to give.
- Signals: `SignalMetadataTable.meta_table_uid` is set by registration when the
  portfolio has a `signal_uid`, so a signal read without a portfolio still
  resolves its instance.
- The engine outputs follow the same pattern. `PortfolioRebalanceStateTS`,
  `PortfolioCalendarEventsTS` and `PortfolioEventLedgerTS` are contracts with
  factories in `contract_instances`, and `PortfoliosUpdater` takes
  `weights_output_table=` and `rebalance_output_table=` for the
  `PortfolioWeights` and `PortfolioRebalance` updaters it builds, so a provider
  can keep every row of a computed portfolio in its own namespace. Output
  tables do not enter `update_hash`; MetaTables keys each update record by
  update hash and output table, so a provider-bound updater gets its own record
  without a new identity. The catalog still records values, weights and signal
  instances only.
- Deletes respect the catalog. Markets does not delete rows in a table another
  application owns: weight and signal-weight deletes return 409 for such a
  portfolio, and portfolio and signal deletes remove the Markets rows and list
  the instances they left in place in `retained_datasets`.

### 2026-10-25: step 1, decision 3 (acting identity)

Implemented in `apps/v1/identity.py`. `acting_identity()` returns the requester
on a requester-bound call and the caller otherwise, never both, and `None`
outside an authenticated request so local scripts and direct service calls keep
working. `registry_write` wraps every `apps/v1` service that creates, updates or
deletes a registry row and records resource, action, row uid and acting identity
after a successful write. The Index actor is derived from the acting identity.

Deviations and open items:

- No Markets registry table has an author or owner column, so "recording the
  acting user" is a structured log record on the `apps.v1.identity` logger, not
  a column write. The hook is the place a column is filled once one exists.
- Ownership and Team scoping policies are not enforced yet; the helper gives
  every service one identity to authorize against, and the platform's own
  grants still apply to requester-bound reads.
- Application-level permission ("this application may register accounts") is
  enforced by `apps.v1.policy`: an application (workload identity) triggers a
  registry write only when the `MARKETS_REGISTRY_WRITERS` constant lists its
  User uid for that resource or for `"*"`; otherwise the route returns `403`.
  People, requester-bound calls, Organization admins and calls outside a
  request are not restricted by it. A missing constant allows no application;
  an unreadable or malformed one fails closed with `503`.
- `acts_for_requester: true` on the `markets-api` resource is required for a
  requester to be present. It is declared in
  `.mainsequence/workflows/ms-markets-api.yaml`, and it takes effect only when
  the person who pushes that file is an Organization admin. A push by anyone
  else makes the `markets-api` resource fail before it deploys. Every push of
  a branch that carries the declaration must therefore come from an
  Organization admin.

### 2026-10-25: step 1, missing routes

Added to `apps/v1`: account create and update; formula save, activate, retire
and preview over `FormulaIndex`; batch lookups by uid (`uid__in`) for assets,
accounts, portfolios and indexes; multi-portfolio values and weights frames;
portfolio dataset registration, read and reconcile. Each follows the existing
router and service layout, carries a Command Center contract and is registered
in the adapter operation registry. Deviations and refinements:

- Batch lookups are `GET <resource>/by-uids/?uid__in=` with repeated or
  comma-separated uids, at most 500, returning the found rows in request order
  inside a `ResourceCollection` without paging, search or a discovery route.
  They are lookups, not collections, so they carry no
  `command-center.resource_collection@v1` contract.
- The multi-portfolio frames are `GET /portfolio/values/` and
  `GET /portfolio/weights/` with `portfolio_uid__in`; every uid must be a
  portfolio. `order` and `limit` apply to the merged result.
- `include` hydration lives on the by-uid lookups: `include=<sidecar MetaTable
  uid>` resolves the sidecar from the MetaTables catalog, requires a
  single-column foreign key to the core table's `uid` (the sidecar rule of
  decision 4), reads each sidecar once for the returned uids as the Markets
  workload and attaches rows under `includes[<uid>]`. It works for a sidecar in
  any namespace today, including `mainsequence.markets`, so a provider's
  account listing can move before step 3. Columns the catalog marks as
  application-encrypted (MetaTables ADR 0025) are never selected, and any value
  that is an encryption envelope is dropped. Search-driven list routes do not take
  `include`; a consumer pages on its own sidecar and hydrates by uid, which is
  the direction the worked example needs.
- Formula save takes the Index identity from the stored row and accepts only
  the definition and inputs, so a route cannot change identity fields while
  storing a formula; `PATCH /index/{uid}/` remains the identity update.
