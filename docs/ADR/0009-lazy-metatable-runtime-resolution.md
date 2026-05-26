# 0009. Lazy MetaTable Runtime Resolution

## Status

Accepted

This ADR supersedes the explicit-bootstrap requirement in ADR 0008 for normal
user-facing row operations. ADR 0008 still owns the `*Table` schema declaration
and `msm.api.*` Pydantic row split.

## Context

ADR 0008 introduced user-facing row classes such as `msm.api.assets.Asset` and
schema declarations such as `msm.models.AssetTable`. It deliberately required
callers to run `create_schemas(...)` before row operations:

```python
Asset.create_schemas(...)
Asset.upsert(...)
```

That is too much platform lifecycle ceremony for ordinary library use. Most
production applications should not create schemas during request or job logic.
They should assume the platform-managed MetaTables already exist and simply use
the typed row API:

```python
from msm.api.assets import Asset

asset = Asset.upsert(unique_identifier="BTC", asset_type="crypto")
```

The library still needs a way to support examples, notebooks, and development
scripts where schemas may not exist yet. That support must be opt-in, because
silent schema creation in production can hide deployment mistakes, slow down
the first real operation, and create resources in the wrong namespace.

## Decision

Typed row operations must lazily resolve their required MetaTable runtime on
first use.

By default, row operations assume required schemas are already registered. A
call such as `Asset.upsert(...)` should:

1. resolve the active or cached runtime for `Asset.__required_tables__`;
2. attach to already-registered platform MetaTables for those tables;
3. execute the requested row operation.

If the required MetaTables cannot be resolved and auto-registration is not
enabled, the operation must fail with a clear runtime error. The error should
name the row class, name the missing table declarations, and tell the caller
how to register them:

```text
Asset requires registered markets MetaTables for AssetTable.
Run Asset.create_schemas(...) during application initialization, or set
MSM_AUTO_REGISTER_NAMESPACE for development/example auto-registration.
```

The default path must not create schemas.

### Opt-In Auto-Registration

The library will support an environment variable:

```text
MSM_AUTO_REGISTER_NAMESPACE=<namespace>
```

When this variable is set and a row class is used before its required tables are
registered, the row API may call `create_schemas(...)` for exactly the required
tables and the configured namespace. For example:

```python
from msm.api.assets import Asset

Asset.upsert(unique_identifier="example-btc", asset_type="crypto")
```

with:

```text
MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples
```

may register `Asset.__required_tables__` once in the process before running the
upsert.

Auto-registration must be narrow:

- register only the tables declared by the row class `__required_tables__`;
- preserve dependency order through the existing bootstrap/model selection
  machinery;
- use the environment namespace as the registration namespace;
- fail loudly if another incompatible runtime already exists in the process;
- never accept row payload fields as namespace or registration configuration.

Production applications normally leave `MSM_AUTO_REGISTER_NAMESPACE` unset.

### Process-Level Registration Cache

Each row class may expose an internal flag for ergonomics, but correctness must
come from a process-level runtime registry keyed by registration configuration.
A single boolean such as `Asset._schema_registered = True` is not sufficient
because table resolution depends on namespace, selected model set, management
mode, data source, and other bootstrap inputs.

The runtime layer should track keys shaped like:

```text
(namespace, management_mode, data_source_uid, selected_required_tables)
```

The exact key type is an implementation detail, but it must prevent this unsafe
sequence:

```python
Asset.upsert(...)       # resolves/registers in one namespace
Portfolio.upsert(...)   # silently switches to another namespace
```

Repeated use of the same row class and compatible required-table set should be
process-idempotent and should not repeat schema registration or platform table
lookup work unnecessarily.

### Public API Contract

The intended user experience is:

```python
from msm.api.assets import Asset

asset = Asset.upsert(unique_identifier="BTC", asset_type="crypto")
crypto_assets = Asset.filter(asset_type="crypto")
```

Explicit initialization remains supported for applications that want controlled
startup preflight:

```python
import msm

msm.create_schemas(models=["Asset", "OpenFigiDetails"])
```

or:

```python
Asset.create_schemas()
```

The difference is that explicit initialization is no longer mandatory for row
API calls when the platform tables are already registered.

## Implementation Tasks

- [x] Add lazy runtime resolution to the shared `MarketsRow` base.
- [x] Add an attach/discover path that resolves registered MetaTables without
  creating schemas.
- [x] Add `MSM_AUTO_REGISTER_NAMESPACE` handling for opt-in development/example
  schema creation.
- [x] Add a process-level runtime/schema cache keyed by compatible registration
  inputs instead of relying on a single class boolean.
- [x] Update row-operation bootstrap errors to name missing required tables and
  show the explicit initialization and auto-registration options.
- [x] Update examples so normal row operations do not call
  `msm.create_schemas(...)` unless the example is specifically demonstrating
  explicit bootstrap.
- [x] Update docs and tutorials to explain the default attach-first behavior,
  the explicit startup preflight option, and the auto-registration environment
  variable.
- [x] Add tests for default attach behavior, missing-table errors,
  auto-registration, idempotence, and incompatible runtime rejection.

## Consequences

User code becomes simpler and better aligned with the domain API. A normal
consumer can work with `Asset`, `Portfolio`, `Order`, and other row classes
without thinking about MetaTable registration on every script or request.

Production remains safe because the default behavior attaches to existing
tables and does not create schemas. Missing registration is still surfaced as a
runtime/deployment error instead of being hidden.

Examples and notebooks can become lighter by setting
`MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples` when they want self-setup
behavior.

The implementation must be careful about runtime identity. The library cannot
silently change namespace or table mappings after SQLAlchemy models and
MetaTable handles are already resolved in the process.

## Non-Goals

This ADR does not remove `msm.create_schemas(...)` or row-level
`create_schemas(...)`. Those remain the explicit schema preflight APIs.

This ADR does not make schema creation the default. Auto-registration only
exists when `MSM_AUTO_REGISTER_NAMESPACE` is set.

This ADR does not change SQLAlchemy `*Table` declarations or the `msm.api.*`
row-model package boundary from ADR 0008.
