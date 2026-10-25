# Platform

The platform concept owns shared integration primitives between `msm` and the
Main Sequence runtime. It is the foundation for MetaTable registration, market
TimeIndexTableUpdater behavior, and common ORM helpers.

## Scope

Platform utilities answer these questions:

- How do market-domain SQLAlchemy models register as Main Sequence MetaTables?
- What shared base class and schema naming rules do market models use?
- How do market-specific updaters normalize storage and configuration?
- Which helpers should remain common across accounts, assets, execution, and
  portfolios?

## Primary Modules

- `msm.base`: shared SQLAlchemy base, market schema settings, and model mixins.
- `msm.models.registration`: MetaTable registration helpers for market-domain models.
- `migrations`: the MetaTables Alembic provider and package-owned model registry.
- `msm.settings`: shared markets constants such as the canonical asset identity
  dimension.
- `msm.identity`: keeps the identities ms-markets derives stable when an updater
  or configuration class moves; see [Identity Stability](#identity-stability).
- `msm.time_index.accounts`: account holdings updaters.
- `msm.time_index.assets`: asset-specific TimeIndexTableUpdater package, including
  `AssetSnapshot` and shared asset-indexed behavior in
  `msm.time_index.assets.asset_indexed`.
- `msm.time_index.execution`: execution updaters for orders, order events,
  and trades.
- `msm.time_index.indices`: index-specific TimeIndexTableUpdater package, including
  timestamped index facts and canonical `IndexTable` source-table foreign keys.
- `msm.time_index.utils`: shared TimeIndexTableUpdater utilities that are not tied to one
  model concept, including source-table contracts, timestamp normalization,
  stamped-frame behavior, and namespace defaulting.
- `msm_portfolios.time_index`: portfolio construction updaters that build on
  the shared markets TimeIndexTableUpdater machinery. Core account virtual-fund storage
  lives under `msm.time_index.accounts`.
- `cli`: explicit command-line helpers, including
  `msm copy-msm-skills` for installing packaged ms-markets agent skills into a
  host CodeRepository and `msm rename-preflight` for moving a host project to
  the 3.0 names ([Upgrading To 3.0](../../../upgrading-to-3.md)).

## Key Contracts

Platform primitives should stay low-level. They should not know about business
logic for a specific concept such as pricing, portfolio construction, or asset
translation.

Asset-indexed TimeIndexTableUpdater subclasses should use `AssetIndexedUpdater` for asset
scope and namespace behavior. Timestamped asset facts should use
`AssetTimestampedUpdater` plus `AssetUpdaterConfiguration`, with schema,
indexes, dtypes, nullability, and source-table foreign keys declared only on the
storage MetaTable. The broad legacy compatibility names were removed;
asset-indexed TimeIndexTableUpdater code should use the explicit asset-indexed base classes
directly.

See [MetaTable Registration](meta_table_registration.md) for runtime attachment
and model registration concepts. See [Migrations](../migrations/index.md) for
the admin-owned schema creation and evolution workflow.

### Identity Stability

Several persisted identities are derived from class import paths. MetaTables
hashes each updater's and each configuration class's `{module, qualname}` into
the producer's `update_hash`. ms-markets hashes class paths into `signal_uid`,
the portfolio configuration hash and the rebalance strategy revision. The
strategy revision also includes the `update_hash` of each declared dependency,
and it is part of every ledger event revision that replay compares.

`compute_signal_uid`, `compute_portfolio_configuration_hash` and
`compute_strategy_revision` pass their payload through
`msm.identity.stable_identity_payload` before hashing. It maps moved class paths
back to their pre-rename paths (`PRE_RENAME_MODULES` and
`PRE_RENAME_CLASS_NAMES`) and replaces each nested updater's hash with
`pre_rename_update_hash(...)`, so a package rename leaves these identities
unchanged. MetaTables' own `update_hash` is not covered: a moved updater gets a
new `TimeIndexTableUpdate` record on its first run and continues from its output
table's last observation.

`tests/identity/test_pinned_identities.py` pins each of these identities, the
physical table names and the updater class paths. Changing a pinned value is an
identity rotation; make it only on purpose and record it in the changelog.

The `msm` import path is side-effect free. Installing the package makes the
ms-markets skill bundle available as package data, but skills are copied into a
host CodeRepository only when a user runs
`msm copy-msm-skills --path <code-repository>`.
That command writes to `.agents/skills/ms_markets/` and leaves Main Sequence
scaffold skills and repository-state files untouched. It also writes
`.agents/skills/ms_markets/PINNED_FROM.txt` so host CodeRepositories can see which
installed ms-markets version supplied the copied skills. The command is blocked
when the target path is the ms-markets source checkout because that checkout is
also the packaged skill source.

## Extension Notes

Add behavior here only when at least two concept packages need the same platform
primitive. If TimeIndexTableUpdater behavior is specific to one concept, keep it in that
concept package first. If it is shared TimeIndexTableUpdater machinery and not model-shaped,
place it under `msm.time_index.utils`.

Repository-level maintenance workflows live in Open Agent skills under
`.agents/skills/`. Use `.agents/skills/library_maintenance/SKILL.md` when making
relevant library changes so implementation, docs, examples, tutorials, changelog,
and validation stay aligned.

## Related Concepts

- [Models](../models/index.md)
- [Accounts](../accounts/index.md)
- [Assets](../assets/index.md)
- [Portfolios](../../msm_portfolios/portfolios/index.md)
