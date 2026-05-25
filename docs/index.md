# MainSequence Markets

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
- Financial engines for pricing, analytics, and lifecycle workflows.
- Application-management helpers for dashboards, APIs, scheduled jobs, and platform
  deployment surfaces.
- Agent-ready project structure for future Main Sequence agent capabilities.

The initial core modules were migrated from `mainsequence-sdk/mainsequence/markets`
into `src/msm`.

## Documentation Map

- [Getting Started](getting-started.md)
- [Tutorial](tutorial/index.md)
- [Knowledge Base](knowledge/index.md)
- [Architecture Decision Records](ADR/README.md)
- [Changelog](changelog.md)
- [API Reference](reference/index.md)
