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
  mapping, normalization, MetaTable row construction, and asset snapshot frame
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

Provider services may compose models and DataNodes when the provider response
needs to produce multiple library-owned objects. For example, the OpenFIGI
service builds `msm.models.Asset`, `msm.models.OpenFigiDetails`, and an
`msm.data_nodes.assets.AssetSnapshot` frame from the same provider row.

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
