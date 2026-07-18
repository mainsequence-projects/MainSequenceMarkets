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
(typed `msm.api` row APIs, explicit MetaTable runtime attachment, and DataNode
helpers for time-indexed facts).

## Installing MS Markets Agent Skills

Use the `msm` CLI when a host Main Sequence project should receive the
ms-markets agent skills:

```bash
msm copy-msm-skills --path .
```

The command copies the packaged bundle into `.agents/skills/ms_markets/`,
overwrites only matching skill folders under that namespace, and writes
`.agents/skills/ms_markets/PINNED_FROM.txt` with the installed ms-markets
version. It does not touch `.agents/skills/mainsequence`, project-state files,
or `AGENTS.md`.

Run it only from a separate host project. The CLI rejects the ms-markets source
checkout to avoid deleting the package-owned skill bundle.

Do not rely on `import msm` for this setup. Imports are side-effect free and do
not copy skills into the current working tree.

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
6. [Derived Indexes](06-derived-indexes.md) — versioned calculated Index
   definitions, pure previews, source bindings, publication, repair, and
   canonical consumption.
