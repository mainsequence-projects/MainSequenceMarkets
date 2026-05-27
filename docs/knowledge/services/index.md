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
- `msm.services.funds`: fund creation and lookup workflows over repository
  operations.
- `msm.services.portfolios`: portfolio and portfolio asset detail workflows over
  repository operations.
- `msm.services.holdings` and `msm.services.target_positions`: DataNode frame
  builders and validators for holdings and target position tables.
- `msm.services.__init__`: service import surface.

## Key Contracts

Services should be thin until there is a real workflow to orchestrate. They
should not duplicate repository query construction, DataNode normalization, or
pricing runtime logic.

Provider services may compose table declarations and DataNodes when the provider response
needs to produce multiple library-owned objects. For example, the OpenFIGI
service builds `msm.models.AssetTable`, `msm.models.OpenFigiDetailsTable`, and an
`msm.data_nodes.assets.AssetSnapshot` frame from the same provider row.
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
- [Portfolios](../portfolios/index.md)
