# MainSequence Markets

<p align="center">
  <img src="img/main-sequence-markets/main_sequence_markets_primary_wordmark_transparent.png" alt="MainSequence Markets" width="640"/>
</p>

`ms-markets` is the financial markets extension layer for the Main Sequence platform.
It provides the package foundation for reusable market-domain models, engines, and
application surfaces.

The import package is:

```python
import msm
```

## Intended Uses

1. Build financial markets projects and applications on top of Main Sequence.
2. Create a Main Sequence project foundation that can grow into agentic financial
   workflows and operational tools.

## Initial Scope

- Market-domain ORM and persistence abstractions.
- Optional financial engines for pricing and analytics through `msm_pricing`.
- Core market lifecycle workflows through `msm`.
- Application-management helpers for dashboards, APIs, scheduled jobs, and platform
  deployment surfaces.
- Agent-ready project structure for future Main Sequence agent capabilities.

The initial core modules were migrated from `mainsequence-sdk/mainsequence/markets`
into `src/msm`.

## Library Style

The general style of `msm` is to keep user-facing code typed and domain-oriented.
Application code should operate on Pydantic row objects such as `Asset`,
`Account`, and `OrderManager`, while schema registration code works with
SQLAlchemy MetaTable declarations such as `AssetTable`, `AccountTable`, and
`OrderManagerTable`. Timestamped execution facts such as orders, events, and
trades are DataNode storage contracts, not duplicate row MetaTables.

```python
from msm.api.assets import Asset
from msm.models import AssetTable
```

Row objects expose class methods such as `upsert(...)`, `filter(...)`, and
lifecycle helpers where the domain needs them. Mutation and lookup methods use
the active runtime created during process initialization; they do not attach to
MetaTables or register schemas on first row use. `start_engine()` is the
explicit runtime attachment entrypoint and resolves already-registered backend
tables by each model's SQLAlchemy table name after SDK-managed migrations are
current. Schema mutation belongs to the SDK migration command with
`--provider migrations:migration`.
`MSM_AUTO_REGISTER_NAMESPACE` is only a namespace default for examples or local
development; it does not make row operations register schemas. Lower-level
repository helpers remain available when a workflow needs direct access to
registered table handles or raw platform operation payloads.

## Documentation Map

- [Getting Started](getting-started.md)
- [Tutorial](tutorial/index.md)
- [FastAPI v1](fast_api/v1/index.md)
- [Command Center](command_center/index.md)
- [Knowledge Base](knowledge/index.md)
- [Architecture Decision Records](ADR/README.md)
- [Changelog](changelog.md)
- [API Reference](reference/index.md)
