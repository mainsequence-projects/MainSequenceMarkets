# Tutorial

This tutorial walks you through building a markets project with `ms-markets`
end to end: registering canonical assets and categories, materializing market
calendars, publishing account holdings and target positions, constructing a
two-stage equal-weights portfolio, and connecting priceable instruments through
the optional pricing extra. Each chapter builds on the previous one in the order
a real project would follow.

## Prerequisites

Before starting, set up your environment with
[Getting Started](../getting-started.md) and read
[Core Concepts](../concepts.md) for the runtime model that the chapters assume
(typed `msm.api` row APIs, explicit MetaTable runtime attachment, and TimeIndexTableUpdater
helpers for time-indexed facts).

### Prepare the schema before starting runtime code

1. Install the locked dependencies, including MetaTables 0.1.33 or later.
2. For local ms-markets schema development, verify the local MetaTables runtime
   and use `metatables --local migrations upgrade --provider msm_migrations:migration head`.
   For a hosted environment, the ms-markets deployment's migration Job applies
   this provider before the API rolls out; do not run it from your laptop.
3. Start tutorial code with `msm.start_engine(...)` only after the tables have
   been finalized. A consuming project uses the schema owned by the ms-markets
   deployment and migrates only its own providers.

Run `python examples/msm/platform/metatable_migration_lifecycle.py` for a safe,
print-only walkthrough. The shared runner batches inspections automatically and
reconciles the catalog even at the current revision. Changed, non-empty authored
descriptions, labels, and column metadata refresh during finalization without a
new revision; empty values preserve existing metadata. The shared MetaTables API
must support that payload too. See
[Migrations](../knowledge/msm/migrations/index.md) for the workflow and timing logs.

## Installing MS Markets Agent Skills

Use the `msm` CLI when a host Main Sequence CodeRepository should receive the
ms-markets agent skills:

```bash
msm copy-msm-skills --path .
```

The command copies the packaged bundle into `.agents/skills/ms_markets/`,
overwrites only matching skill folders under that namespace, and writes
`.agents/skills/ms_markets/PINNED_FROM.txt` with the installed ms-markets
version. It does not touch `.agents/skills/mainsequence`, repository-state files,
or `AGENTS.md`.

Run it only from a separate host CodeRepository. The CLI rejects the ms-markets source
checkout to avoid deleting the package-owned skill bundle.

Do not rely on `import msm` for this setup. Imports are side-effect free and do
not copy skills into the current working tree.

## Serving tutorial resources to Command Center

When exposing the tutorial's assets, calendars, accounts, portfolios, indexes,
or pricing resources through `apps/v1`, consume the canonical
[Command Center resource contracts](../fast_api/v1/resource_contracts.md).
Every collection returns `items` plus authoritative `pageInfo`, while its
sibling `/discovery/` endpoint owns identity, controls, columns, and authorized
bulk actions. Detail and summary operations remain distinct resource-specific
boundaries.

Provider CodeRepositories can reuse these boundaries directly from
`msm.api.http`. The [provider adapter HTTP toolkit](../fast_api/v1/provider_adapter_toolkit.md)
also supplies bulk-preflight helpers, sanitized structured errors, and
owner-scoped observable-operation primitives, so connectors do not need to
copy the infrastructure from this repository's `apps/v1` tree.

## The path

1. [Assets and Categories](01-assets.md) — runtime setup, asset types and
   constants, categories, currency assets, bond assets, and asset snapshots.
2. [Calendars](02-calendars.md) — materialize durable market, settlement,
   fixing, and custom calendar facts.
3. [Accounts and Holdings](03-accounts.md) — account holdings, target positions,
   and virtual-fund allocation.
4. [Portfolios](04-portfolios.md) — the equal-weights two-stage portfolio
   construction workflow.
5. [Pricing Instruments](05-pricing.md) — pricing instrument identity, bond
   pricing, and extending the schema.
6. [Formula And Custom Indexes](06-index-formulas.md) — custom publication,
   mixed Asset/Index formulas, exact source bindings, preview, lifecycle, and
   deterministic publication.
