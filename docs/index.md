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

The general style of `msm` is to keep user-facing code typed and
domain-oriented. Application code operates on Pydantic row objects such as
`Asset`, `Account`, and `OrderManager`; schema code works with SQLAlchemy
`*Table` declarations such as `AssetTable`; timestamped facts live in DataNodes.

```python
from msm.api.assets import Asset       # row object — application code
from msm.models import AssetTable       # SQLAlchemy declaration — schema code
```

The full runtime model — the three layers, `start_engine()` as attachment (not
schema creation), migrations-before-runtime, and `MSM_AUTO_REGISTER_NAMESPACE` —
is documented once in [Core Concepts](concepts.md). Read it before the rest of
the docs.

## Documentation Map

- [Getting Started](getting-started.md)
- [Core Concepts](concepts.md)
- [Tutorial](tutorial/index.md)
- [FastAPI v1](fast_api/v1/index.md)
- [Command Center](command_center/index.md)
- Package reference: [msm](knowledge/msm/index.md),
  [msm_portfolios](knowledge/msm_portfolios/index.md),
  [msm_pricing](knowledge/msm_pricing/index.md)
- [Architecture Decision Records](ADR/README.md)
- [Changelog](changelog.md)
- [API Reference](reference/index.md)
