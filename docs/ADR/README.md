# Architecture Decision Records

This folder records important implementation decisions for `ms-markets`.

Use one Markdown file per decision:

```text
0001-short-title.md
```

Recommended sections:

- Status
- Context
- Decision
- Consequences

## Core Decisions

- [0005. Pricing Package Refactor](0005-pricing-package-refactor.md)
- [0006. Asset Package Boundary](0006-asset-package-boundary.md)
- [0008. MetaTable Table And API Model Split](0008-metatable-table-and-api-model-split.md)
- [0019. msm_portfolios Package Boundary](0019-msm-portfolios-package-boundary.md)
- [0022. Thin Alembic MetaTable Migration Integration](0022-alembic-metatable-migration-alignment.md)
- [0023. Deterministic Alembic Schema And Identifier Naming](0023-deterministic-alembic-naming.md)
- [0024. Namespace-Scoped Alembic Version Locations](0024-namespace-scoped-alembic-version-locations.md)
- [0025. Direct MetaTable Runtime Binding](0025-direct-metatable-runtime-binding.md)
- [0026. Explicit Pricing Market Data Sets](0026-explicit-pricing-market-data-sets.md)
- [0027. Account Target Position Portfolio Exposure](0027-account-target-position-portfolio-exposure.md)
- [0028. Core Calendar Reference Data Model](0028-core-calendar-reference-data.md)
- [0029. Account Holdings To Virtual Fund Allocation Policy](0029-account-holdings-virtual-fund-allocation-policy.md)
- [0030. Explicit Portfolio Price Source Dependency](0030-explicit-portfolio-price-source-dependency.md)
- [0031. Generic Portfolio Valuation Source](0031-generic-portfolio-valuation-source.md)
- [0032. Portfolio Groups As Many-To-Many Classification](0032-portfolio-group-many-to-many.md)
- [0033. Pricing Valuation Position Boundary](0033-pricing-valuation-position-boundary.md)
- [0035. Pricing Curve Identity And Market-Data Curve Bindings](0035-pricing-curve-identity-and-market-data-curve-bindings.md)
- [0036. Prepared Pricing Valuation Context](0036-prepared-pricing-valuation-context.md)
- [0037. Core Index Value, Definition, And Calculation Framework](0037-core-derived-index-definition-and-calculation-framework.md)
- [0038. Index User API, FastAPI Exploration, And Safe Bulk Deletion](0038-index-user-api-fastapi-exploration-and-safe-deletion.md)

## Command Center Decisions

- [0034. Command Center Asset Monitor Helpers](0034-command-center-asset-monitor-helpers.md)

## FastAPI v1 Decisions

- [0001. Calendar CRUD And Summary Route](fast_api/v1/0001-calendar-crud-route.md)
- [0002. Command Center Adapter Discovery](fast_api/v1/0002-command-center-adapter-discovery.md)
- [0003. Fixed Income Pricer API](fast_api/v1/0003-fixed-income-pricer-api.md)
- [0004. Reusable Delete Impact Contract](fast_api/v1/0004-delete-impact-contract.md)
