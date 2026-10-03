# 0045. Squashed Initial Schema And Namespaced Packages

## Status

Accepted and implemented in 3.0.0. Supersedes the `0001`–`0017` revision history
and the `cli`/`command_center` exclusion in
[ADR 0044](0044-namespaced-migration-provider-package.md). Resolves
[MainSequenceMarkets#12](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/12),
[#14](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/14) and
[#15](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/15).
Amends ADRs [0034](0034-command-center-asset-monitor-helpers.md),
[0037](0037-index-formula-and-custom-calculation-framework.md),
[0042](0042-position-cash-flow-portfolio-accounting.md) and
[0043](0043-sdk-9-metatables-client-hard-cut.md), and withdraws the 2.0.2
CHANGELOG promise that revisions `0001`–`0017` stay unchanged.

## Context

No MetaTables runtime holds an applied ms-markets history; `0001`–`0017` only
ran on the retired shared backend (#12). That history altered tables repeatedly,
and `0010` ran PostgreSQL-only SQL, so it could not build the schema on the
MetaTables local SQLite runtime (#15). The wheel also still installed top-level
`cli`, `command_center` and `.agents` entries (#14).

## Decision

- One revision, `0018_initial_schema`, generated from the models, creates the
  whole schema on PostgreSQL and on the local SQLite runtime. It never reuses a
  2.x revision ID: under a reused `0001`, a database at the old `0001` would pass
  as already at head and skip every table. MetaTables 0.1.12
  runs `JSONB` as JSON, `Numeric` as SQLite numbers and `postgresql_where`
  predicates there. The provider key `msm:<namespace>`, `MarketsAlembicVersion`
  and its table are unchanged.
- `cli` is renamed `msm_cli` and `command_center` is renamed
  `msm_command_center`, siblings of `msm_migrations`. The `msm` console script is
  unchanged. Bundled skills ship inside `msm_cli/_skills/ms_markets`. The wheel
  installs only `msm`, `msm_cli`, `msm_command_center`, `msm_migrations`,
  `msm_portfolios` and `msm_pricing`.

## Consequences

- A database at any 2.x revision fails with Alembic's unknown-revision error.
  With 2.x still installed, run
  `metatables migrations downgrade base --provider msm_migrations:migration`,
  then install 3.0.0 and upgrade from empty.
- Imports of `cli` and `command_center` change to `msm_cli` and
  `msm_command_center`.
- Later schema changes are new revisions after `0018`. MetaTables generates them
  as batch blocks, which run on both engines.
