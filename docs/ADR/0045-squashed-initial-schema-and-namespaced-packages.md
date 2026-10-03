# 0045. Squashed Initial Schema And Namespaced Packages

## Status

Accepted and implemented in 3.0.0. Supersedes the `0001`–`0017` revision history
and the `cli`/`command_center` exclusion in
[ADR 0044](0044-namespaced-migration-provider-package.md). Resolves
[MainSequenceMarkets#12](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/12),
[#14](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/14) and
[#15](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/15).

## Context

No MetaTables runtime holds an applied ms-markets history; `0001`–`0017` only
ran on the retired shared backend (#12). That history altered tables repeatedly,
and `0010` ran PostgreSQL-only SQL, so it could not build the schema on the
MetaTables local SQLite runtime (#15). The wheel also still installed top-level
`cli`, `command_center` and `.agents` entries (#14).

## Decision

- One revision, `0001_initial_schema`, generated from the models, creates the
  whole schema on PostgreSQL and on the local SQLite runtime. MetaTables 0.1.12
  runs `JSONB` as JSON, `Numeric` as SQLite numbers and `postgresql_where`
  predicates there. The provider key `msm:<namespace>`, `MarketsAlembicVersion`
  and its table are unchanged.
- `cli` is renamed `msm_cli` and `command_center` is renamed
  `msm_command_center`, siblings of `msm_migrations`. The `msm` console script is
  unchanged. Bundled skills ship inside `msm_cli/_skills/ms_markets`. The wheel
  installs only `msm`, `msm_cli`, `msm_command_center`, `msm_migrations`,
  `msm_portfolios` and `msm_pricing`.

## Consequences

- A database at a 2.x revision cannot upgrade: drop its ms-markets tables, then
  apply 3.0.0 from empty.
- Imports of `cli` and `command_center` change to `msm_cli` and
  `msm_command_center`.
- Later schema changes are new revisions after `0001`. MetaTables generates them
  as batch blocks, which run on both engines.
