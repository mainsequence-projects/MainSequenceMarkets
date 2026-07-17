# Services

The services concept owns application-level orchestration. Services compose
repositories and domain helpers into operations that are easier for application
code, jobs, CLIs, and agents to call.

## Scope

Services answer these questions:

- Which repository calls should be exposed as a workflow?
- Which arguments should application code pass without knowing persistence
  details?
- Which multi-step operation deserves one stable public function?

## Primary Modules

- `msm.services.assets`: asset CRUD-oriented service helpers over repository
  operations.
- `msm.services.assets.openfigi`: OpenFIGI provider integration for search,
  mapping, API-key resolution from the `OPEN_FIGI_API_KEY` Main Sequence
  secret, normalization, MetaTable row construction, and asset snapshot frame
  construction.
- `msm.services.accounts`: account registry, account allocation-model, target
  allocation, position-set, virtual-fund allocation, and account-facing
  snapshot workflows.
- `msm.services.accounts.virtual_funds`: virtual-fund creation and lookup
  workflows over repository operations.
- `msm.services.accounts.account_virtual_allocations`: account holdings to
  virtual-fund allocation planner and apply step.
- `msm.services.portfolios`: core portfolio identity, portfolio group, and
  portfolio group membership workflows over repository operations.
- `msm.services.holdings`: DataNode frame builders and validators for account
  holdings tables.
- `msm.services.target_positions`: account target-position frame builders,
  validators, snapshot readers, and explicit portfolio expansion helpers.
- `msm.services.__init__`: service import surface.

## Key Contracts

Services should be thin until there is a real workflow to orchestrate. They
should not duplicate repository query construction, DataNode normalization, or
pricing runtime logic.

When services need the current asset display snapshot for account holdings,
target positions, virtual funds, or asset detail responses, use the shared
asset reference read service. It resolves the latest `AssetSnapshotsStorage`
row per asset in the backend instead of scanning snapshot rows and selecting
the newest timestamp in Python.

Provider services may compose table declarations and DataNodes when the provider response
needs to produce multiple library-owned objects. For example, the OpenFIGI
service builds `msm.models.AssetTable`, `msm.models.OpenFigiAssetDetailsTable`, and an
`msm.data_nodes.assets.AssetSnapshot` frame from the same provider row.
Ticker-only asset intake should use the OpenFIGI mapping helper with explicit
market, exchange, and security context; raw tickers should not be persisted as
canonical `Asset.unique_identifier` values when a provider FIGI can be resolved.
OpenFIGI requests read credentials from the Main Sequence secret
`OPEN_FIGI_API_KEY`; set it in
`www.main-sequence.app/app/main_sequence_workbench/secrets` before using the
provider query helpers.

Typed row operations that should return FastAPI-ready Pydantic objects belong in
`msm.api`, for example `msm.api.assets.Asset.upsert(...)`,
`msm.api.portfolios.Portfolio.upsert(...)`, or
`msm.api.execution.OrderManager.create_batch(...)`. Services remain the place
for workflows that compose providers, repositories, and DataNodes.

Use `msm.data_nodes.assets.AssetSnapshot` directly for snapshot rows:
`AssetSnapshot.build_frame(...)` validates row payloads, and
`AssetSnapshot().set_snapshots(...)` binds rows to a node before running it.
Each snapshot payload must carry its own `time_index`; the DataNode does not
apply one timestamp to a batch.

The `msm.services` package export surface is lazy. Importing a provider helper
such as `msm.services.assets.openfigi` should not initialize unrelated
repository or platform dependencies.

## Extension Notes

Add a service when a workflow composes multiple repositories, needs validation
across concept boundaries, or should become a stable application-facing API.
Keep direct CRUD helpers in repositories until orchestration is needed.

## Related Concepts

- [Repositories](../repositories/index.md)
- [Models](../models/index.md)
- [Accounts](../accounts/index.md)
- [Portfolios](../../msm_portfolios/portfolios/index.md)
