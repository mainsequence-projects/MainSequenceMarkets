# 0044. Namespaced Migration Provider Package

## Status

Accepted and implemented. Supersedes the provider package location in
[ADR 0024](0024-namespace-scoped-alembic-version-locations.md) and the
`migrations:migration` provider reference in
[ADR 0043](0043-sdk-9-metatables-client-hard-cut.md). The namespace-scoped
version locations, provider key, model registry, version-table binding, and
revision history those ADRs record are unchanged.

Tracked by
[MainSequenceMarkets#14](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/14).

## Context

ADR 0024 moved the Alembic provider from `src/msm/migrations` to a top-level
`src/migrations` package because the provider covers `msm`, `msm_portfolios`,
and `msm_pricing`, not only core `msm`. The wheel therefore installed a
top-level `migrations` package into `site-packages`.

`migrations` is the default package name of the MetaTables scaffold, so other
distributions and applications use it too:

- `valmer-connectors` ships a top-level `migrations` package with the same file
  paths (`migrations/__init__.py`, `migrations/env.py`,
  `migrations/versions/...`). Installing both non-editable overwrites one
  Alembic provider with the other.
- Applications with their own top-level `migrations` package are shadowed when
  the repository root is not first on `sys.path`. A provider that keeps the
  client default `version_location_prefix="migrations:versions"` resolves its
  version directory inside the ms-markets package instead of its own.
- `migrations:migration` does not identify which provider it loads.

The revision files must still ship. Runtime code attaches to already-registered
MetaTables and never creates tables, so the installed package is the only way a
consuming organization can create or upgrade the ms-markets schema to the
revision head that matches the installed models.

## Decision

Rename the provider package to `msm_migrations`, a sibling of `msm_portfolios`
and `msm_pricing`, and ship only namespaced packages for migrations.

- The canonical provider reference is `msm_migrations:migration`.
- The provider sets both `script_location="msm_migrations:"` and
  `version_location_prefix="msm_migrations:versions"`, so no path falls back to
  the client default `migrations:versions`.
- `package="msm"` is unchanged. The backend provider key is
  `<package>:<namespace>`, so the applied history stays bound to the same key.
  `MarketsAlembicVersion`, its identifier, its table name, and revision IDs
  `0001`–`0017` are unchanged.
- `msm.migrations:migration` remains a compatibility alias that imports the same
  provider object.
- No top-level `migrations` shim is shipped. A shim would keep the
  `migrations/__init__.py` file collision with other distributions, which is
  the defect this decision removes.
- The unreachable `versions/default` directory is removed. `markets_namespace()`
  never returns an empty namespace, so the provider never selects it.
  `versions/mainsequence_examples` stays because the examples namespace uses it.
- The wheel no longer force-includes `script.py.mako`; the package build already
  includes it.

## Consequences

- Admin commands use
  `metatables migrations ... --provider msm_migrations:migration`.
- Commands, scripts, or imports that use the top-level `migrations:migration`
  reference against ms-markets must switch to `msm_migrations:migration` or the
  `msm.migrations:migration` alias.
- Existing databases continue from their current revision; no data migration or
  version-table rewrite is required.
- The top-level `cli` and `command_center` packages named in the same issue are
  not changed by this decision.
