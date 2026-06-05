# 0024. Namespace-Scoped Alembic Version Locations

## Status

Accepted

Project-side package relocation is implemented. SDK support for provider-owned
`version_locations` and `version_path` has been implemented in
`mainsequence-sdk`, and the `ms-markets` provider now passes the active namespace
version location to the SDK.

## Context

ADR 0022 moved `ms-markets` to the SDK-managed Alembic migration workflow.
ADR 0023 made the generated physical names deterministic and namespace-aware.
That exposed a remaining lifecycle gap: the Alembic revision files are still
stored in one shared folder:

```text
src/msm/migrations/
  env.py
  script.py.mako
  versions/
    0001_migration.py
    0002_migration.py
```

The provider owns more than the core `msm` package. It includes models from
`msm`, `msm_portfolios`, and `msm_pricing`, plus DataNode storage tables. Keeping
the migration environment under `src/msm/migrations` makes the package boundary
look wrong: the migration stream is not a core-markets-only module.

The larger correctness problem is namespace scope. `MSM_AUTO_REGISTER_NAMESPACE`
changes authored SQLAlchemy table names:

```text
default namespace:
  ms_markets__asset

mainsequence.examples namespace:
  ms_markets__asset__mainsequence_examples
```

Those are different physical schemas from Alembic's point of view. A revision
generated for `mainsequence.examples` can contain DDL for
`ms_markets__asset__mainsequence_examples`. If the active namespace later
changes, the provider metadata points at different physical table names while
Alembic still reads the same revision files. That makes the revision stream
ambiguous and can produce false autogenerate diffs or apply the wrong DDL
history to the wrong namespace.

The database version table already has to be namespace-specific:

```text
ms_markets__alembic_version
ms_markets__alembic_version__mainsequence_examples
```

The file-system revision graph must have the same namespace boundary.

Alembic supports this directly. It can read from configured
`version_locations`, and `command.revision(...)` accepts `version_path=...` to
write a new revision into a selected version directory.

## Decision

Move the `ms-markets` Alembic environment out of `src/msm` into an independent
migration package, and make revision files namespace-scoped.

The target package is:

```text
src/migrations/
  __init__.py
  env.py
  registry.py
  script.py.mako
  versions/
    default/
      __init__.py
    mainsequence_examples/
      __init__.py
      0001_migration.py
      0002_migration.py
      0003_migration.py
      0004_migration.py
```

The existing revision files currently under `src/msm/migrations/versions/` are
the `mainsequence.examples` namespace history. They must be moved into
`src/migrations/versions/mainsequence_examples/` during this migration of
the migration environment. They must not be treated as the default namespace
baseline and must not be copied into `src/migrations/versions/default/`.

The provider import path becomes:

```text
migrations:migration
```

`src/msm/migrations` should not remain the canonical provider package. During a
transition it may contain only a compatibility import with no `env.py`, no
`script.py.mako`, and no revision files:

```python
from migrations import migration
```

The independent migration package owns the single provider for all package-owned
tables:

- `msm` domain tables;
- `msm_portfolios` tables;
- `msm_pricing` tables;
- DataNode storage tables;
- the markets MetaTable catalog table;
- the package Alembic version table.

### Namespace Slug

The active migration namespace maps to one deterministic directory slug.

Rules:

- default package namespace with no `MSM_AUTO_REGISTER_NAMESPACE`:
  `default`;
- explicit namespace:
  normalize to lowercase, replace non-alphanumeric characters with `_`, collapse
  repeated `_`, and trim leading/trailing `_`;
- if the normalized slug is empty, fail;
- if the slug is too long for practical path use, append a short deterministic
  digest.

Examples:

```text
None / package default       -> default
mainsequence.examples        -> mainsequence_examples
client-a.production          -> client_a_production
```

The slug is a file-system concern only. It does not replace
`migration_namespace`, table names, or the Alembic version table name.

### One Active Version Location

Each SDK migration command must configure Alembic with only the active
namespace's version directory.

Good:

```text
active namespace = mainsequence.examples
version_locations = src/migrations/versions/mainsequence_examples
```

Bad:

```text
version_locations =
  src/migrations/versions/default
  src/migrations/versions/mainsequence_examples
  src/migrations/versions/client_a
```

Normal `current`, `revision`, `upgrade`, and `downgrade` commands must
not load every namespace directory at once. Each namespace is an independent
revision graph. Loading all of them together creates multiple unrelated heads
and makes Alembic treat independent namespace histories as one branched graph.

### Revision Generation

The SDK migration CLI must pass Alembic's selected `version_path` when creating
revisions:

```python
command.revision(
    config,
    message=message,
    autogenerate=True,
    rev_id=rev_id,
    head=head,
    version_path=active_namespace_versions_path,
)
```

The sequential revision ID scan must also scan only the active namespace's
version directory. A namespace with no revisions starts at `0001` regardless of
other namespace histories.

### Upgrade And Current

`current`, `upgrade`, and `downgrade` paths must use the same active namespace
version directory and the matching namespace-specific database version table.

For `MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples`, the command should
read/write:

```text
revision files:
  src/migrations/versions/mainsequence_examples/

database version table:
  ms_markets__alembic_version__mainsequence_examples

physical tables:
  ms_markets__<concept>__mainsequence_examples
```

For the default package namespace, the command should read/write:

```text
revision files:
  src/migrations/versions/default/

database version table:
  ms_markets__alembic_version

physical tables:
  ms_markets__<concept>
```

### SDK Provider Contract

The SDK `AlembicMetaTableMigration` provider needs an explicit namespace version
location contract. Acceptable API shapes are:

```python
AlembicMetaTableMigration(
    ...,
    script_location="migrations:",
    version_location="migrations:versions/mainsequence_examples",
)
```

or:

```python
AlembicMetaTableMigration(
    ...,
    script_location="migrations:",
    version_location_factory=namespace_version_location,
)
```

The second shape is better for `ms-markets` because the version directory is
derived from `markets_namespace()` at import time.

The SDK config builder must:

- resolve the active namespace version directory from the provider;
- create the directory before `revision` writes into it;
- set Alembic `version_locations` to that single directory;
- set Alembic `path_separator=os`;
- pass `version_path` into `command.revision(...)`;
- ensure `ScriptDirectory` scans only the active namespace directory for heads
  and sequential revision IDs;
- include the active version location in `mainsequence migrations current`
  status output so users can see which graph is active.

### File Layout

The canonical provider package should be independent from `msm`:

```text
src/
  msm/
  msm_portfolios/
  msm_pricing/
  migrations/
```

This avoids implying that migrations are a sub-feature of core `msm`. The
provider is package-level infrastructure for the whole distribution.

The independent package still imports model graphs from the owning packages:

```python
from msm.models import markets_sqlalchemy_models
from msm_portfolios.models import portfolio_sqlalchemy_models
from msm_pricing.meta_tables import pricing_sqlalchemy_models
```

No domain package should import `migrations` during normal runtime startup.
Only the SDK migration CLI imports the provider.

## Consequences

### Positive

- Revision files, database version tables, and namespace-specific physical
  table names have the same scope.
- Changing `MSM_AUTO_REGISTER_NAMESPACE` no longer points Alembic at a revision
  graph generated for another namespace.
- `msm`, `msm_portfolios`, and `msm_pricing` keep clearer package boundaries.
- New namespaces can start with their own `0001` migration without colliding
  with existing namespace histories.
- The SDK CLI can report exactly which namespace graph it is using.

### Negative

- The SDK migration provider needs a version-location extension.
- Existing revision files must be moved once into the namespace directory they
  were generated for. For the current repository state, that directory is
  `src/migrations/versions/mainsequence_examples/`.
- The provider import path changes from `msm.migrations:migration` to
  `migrations:migration`.
- Tooling must prevent accidental revision creation in the root `versions/`
  directory.

### Non-Goals

- Do not merge all namespace histories into one Alembic branch graph.
- Do not keep revision files directly under `versions/`.
- Do not generate YAML or JSON migration manifests.
- Do not change SQLAlchemy model declarations for this decision.
- Do not change the runtime catalog attach lifecycle.

## Implementation Tasks

- [x] Add SDK support for an active provider `version_location` or
      `version_location_factory`.
- [x] Update the SDK Alembic config builder to set `version_locations` to only
      the active namespace directory.
- [x] Update SDK revision generation to pass Alembic `version_path`.
- [x] Update SDK sequential revision ID scanning to scan only the active
      namespace directory.
- [x] Verify SDK `current`, `upgrade`, and `downgrade` use the shared Alembic
      config builder, so they inherit the active version location.
- [x] Include the active namespace version location in SDK migration CLI status
      output.
- [x] Wire the `ms-markets` provider to pass `version_locations` and
      `version_path` from the active namespace version location.
- [x] Create `src/migrations/` as the canonical provider package.
- [x] Move the provider, Alembic `env.py`, `script.py.mako`, and registry code
      from `src/msm/migrations/` to `src/migrations/`.
- [x] Add namespace slug helper tests for default, dotted namespace, dashed
      namespace, and long namespace inputs.
- [x] Move the existing revision files from `src/msm/migrations/versions/` into
      `src/migrations/versions/mainsequence_examples/` because the current
      history belongs to `MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples`.
      Do not move or copy those files into the default namespace directory.
- [x] Leave `src/msm/migrations/__init__.py` as a temporary compatibility import
      only. Current docs and examples must use `migrations:migration`.
- [x] Update docs and examples to use `mainsequence migrations ... --provider
      migrations:migration`.
- [ ] Add a validation test that changing `MSM_AUTO_REGISTER_NAMESPACE` changes
      the active version directory and Alembic version table together.
- [ ] Add a validation test that revision generation never writes directly to
      `versions/`.

## Validation

This ADR is implemented only when:

- `mainsequence migrations revision --provider migrations:migration` writes
  into the active namespace directory;
- `mainsequence migrations current --provider migrations:migration` reports
  the active version location and the namespace-specific version table;
- `mainsequence migrations upgrade --provider migrations:migration head`
  reads only the active namespace graph;
- creating a revision under one namespace does not change the heads reported for
  another namespace;
- no revision files remain directly under `src/migrations/versions/`.
