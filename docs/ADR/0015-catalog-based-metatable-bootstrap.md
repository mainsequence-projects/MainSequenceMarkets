# 0015. Catalog-Based MetaTable Bootstrap

## Status

Accepted

This ADR supersedes the lazy and on-demand registration decision from
[ADR 0009](0009-lazy-metatable-runtime-resolution.md). ADR 0008 still owns the
`*Table` SQLAlchemy declaration and `msm.api.*` user-facing row model split.

## Context

`ms-markets` currently resolves MetaTable runtime state lazily from row
operations. A call such as `Asset.upsert(...)` can attach to existing tables or,
when `MSM_AUTO_REGISTER_NAMESPACE` is set, register the required tables on
demand.

That behavior is no longer the desired architecture:

- registration can happen during ordinary row operations, which obscures when
  database resources are created;
- row operations can mix runtime resolution, table lookup, schema registration,
  and business writes in the same call path;
- first-use runtime resolution creates noisy logs and makes examples look like
  they are doing more than the business operation requested by the user;
- database-backed table registration needs a durable catalog instead of relying
  on process memory and repeated backend lookup heuristics;
- duplicate or stale platform registration state is hard to diagnose because the
  code can discover one table, try to register another, and surface a conflict
  after the business operation has already started.

The correct lifecycle is startup-based: an application initializes the requested
markets schema set once, then all later row operations use the initialized
runtime. Registration should never happen as a side effect of `upsert`,
`filter`, `delete`, or other row operations.

## Decision

Move `ms-markets` MetaTable registration to a catalog-based bootstrap.

The registration lifecycle becomes:

1. application initialization calls one explicit bootstrap entrypoint;
2. bootstrap resolves the requested table declarations and their dependencies;
3. bootstrap reads the markets MetaTable catalog;
4. tables already present in the catalog are attached, not registered again;
5. missing tables are registered in dependency order;
6. each successful registration is written back to the catalog with the real
   platform MetaTable UID, namespace, and SQLAlchemy table name;
7. bootstrap returns one immutable `MarketsRuntime` for the process;
8. row operations use that runtime and never register or attach lazily.

The same rule applies to optional pricing MetaTables. Pricing startup through
`msm_pricing.bootstrap.create_pricing_schemas(...)` must use the maintenance
catalog instead of re-running direct registration for core asset/index tables.

### Catalog Table

Add an internal catalog table owned by `ms-markets` under
`msm.maintenance.models`. This is maintenance infrastructure, not a normal
domain model under `msm.models`.

The catalog stores one row per registered markets SQLAlchemy table name.
The minimum row contract is:

| Field | Meaning |
| --- | --- |
| `uid` | Catalog row identity. |
| `namespace` | Markets namespace used for the logical table. |
| `table_name` | SQLAlchemy table name, for example `ms_markets__asset`. |
| `description` | Platform MetaTable description returned by registration or discovery. |
| `model_name` | SQLAlchemy table declaration class name, for example `AssetTable`. |
| `meta_table_uid` | Platform `MetaTable.uid` returned by registration or discovery. |
| `contract_hash` | Local hash of the table contract used to detect drift. |
| `sdk_version` | `ms-markets` version that wrote the catalog row. |
| `created_at` | First catalog insertion timestamp. |
| `updated_at` | Last catalog update timestamp. |

The uniqueness rule is the SQLAlchemy table name. Names are globally unique in
`ms-markets`; namespace-specific model imports append the namespace suffix to
the physical table name, for example `ms_markets__asset__mainsequence_examples`.

```text
table_name
```

The catalog stores the platform response identity fields needed by row
operations, but it does not persist physical storage names. The catalog is
MetaTable-specific and does not store a DataNode-versus-MetaTable discriminator.

### Catalog Bootstrap

The catalog itself is the only special bootstrap resource. It is initialized by
the explicit startup flow before any application tables are processed. After the
catalog exists, all markets MetaTable decisions go through it.

The catalog bootstrap must be deterministic:

- if the catalog already exists, attach to it;
- if the catalog does not exist, create it once;
- if catalog creation conflicts with an existing platform table, resolve the
  existing platform MetaTable and backfill the catalog reference;
- if the catalog cannot be resolved or created, fail startup before registering
  any application table.

### Application Table Bootstrap

For each requested table, bootstrap uses this order:

1. read the catalog row for the requested table name;
2. if a catalog row exists, resolve the referenced platform `MetaTable` and
   attach it to the runtime;
3. if no catalog row exists, try one explicit platform lookup using the expected
   table name so pre-catalog installations can be imported without duplicate
   registration;
4. if platform lookup finds an existing table, write a catalog row and attach it;
5. if neither catalog nor platform lookup finds a table, register the table;
6. after successful registration, write the catalog row using the platform
   response;
7. if registration returns a duplicate-table conflict, treat it as catalog drift
   and fail with a repair/import instruction rather than hiding it behind a row
   operation error.

Foreign-key dependencies must still be registered or attached parent-first. The
catalog row for a parent table provides the platform `MetaTable.uid` needed by
child table registration.

### Process Runtime Contract

Bootstrap may run only once per process.

Repeated calls with the same bootstrap configuration may return the cached
runtime. A second call with a different namespace, data source, management mode,
or requested model set must fail before changing the active runtime.

The active runtime is immutable for row operations. A row class whose required
tables are not present in the active runtime must fail with a startup error such
as:

```text
Asset requires AssetTable, but the active markets runtime was initialized
without that table. Include AssetTable in the process bootstrap.
```

Row operations must not call registration, auto-registration, or platform
discovery. They should only resolve table handles from the active runtime.

### Environment Variables

`MSM_AUTO_REGISTER_NAMESPACE` must stop meaning "register lazily on first row
operation."

If the variable remains supported, it should only provide a startup default
namespace for examples or local development. The explicit bootstrap call is still
required to create or attach schemas. No environment variable should make
business row operations mutate schema state.

### Logging

Startup logs should be concise and lifecycle-oriented:

- one line when catalog bootstrap starts;
- one line when an existing catalog is attached;
- one line for each table registered because it was missing;
- one line for each pre-catalog table imported into the catalog;
- one final summary with attached count, registered count, imported count, and
  skipped count.

Attaching tables that already exist in the catalog should normally be `debug`,
not `info`, unless the user explicitly requests verbose bootstrap logs.

## Success Criteria

This ADR is implemented only when:

- row operations cannot register MetaTables;
- application startup has one explicit catalog-based bootstrap path;
- requested tables already in the catalog are not registered again;
- missing requested tables are registered once and written to the catalog;
- pre-catalog platform tables can be imported or produce a clear repair error;
- startup is process-idempotent for the same configuration and rejects different
  runtime configurations;
- documentation and examples explain that schema bootstrap belongs in
  application initialization, not in ordinary row workflows.

## Implementation Tasks

### Stage 1: Catalog Contract

- [x] Add a `MarketsMetaTableCatalogTable` declaration for registered markets
  MetaTable identities.
- [x] Add a typed API/internal helper for catalog rows without exposing catalog
  mutation as a normal user workflow.
- [x] Add a unique `table_name` index for catalog row identity.
- [x] Store the platform `MetaTable.uid`, namespace, table name, description,
  and real storage hash returned by the backend.
- [x] Keep the catalog MetaTable-specific and omit any DataNode-versus-MetaTable
  discriminator column.
- [x] Store a local table-contract hash so bootstrap can detect schema drift.

### Stage 2: Catalog Bootstrap Flow

- [x] Add the explicit catalog bootstrap step before application MetaTable
  registration.
- [x] Move the catalog bootstrap implementation under `msm.maintenance` while
  keeping the public `msm.start_engine(...)` entrypoint stable.
- [x] Implement catalog attach-or-create behavior for the catalog table itself.
- [x] Implement catalog read before registering any requested application table.
- [x] Implement parent-first attach/register ordering using catalog rows for FK
  target `MetaTable.uid` resolution.
- [x] Add a pre-catalog import path for platform tables that exist but do not
  yet have catalog rows.
- [x] Convert duplicate-registration conflicts into catalog drift or repair
  errors with a clear remediation message.
- [x] Validate imported or attached platform-managed physical tables for
  missing columns, extra columns, expected index names, index columns, and
  index uniqueness before exposing them to row APIs.

### Stage 3: Runtime Semantics

- [x] Replace lazy row-operation runtime resolution with active-runtime lookup.
- [x] Remove on-demand `MSM_AUTO_REGISTER_NAMESPACE` registration from row
  operations.
- [x] Keep startup idempotent for identical bootstrap configuration.
- [x] Reject a second bootstrap call with a different namespace, data source,
  management mode, or requested model set.
- [x] Make missing runtime tables fail with an initialization error that names
  the missing table declarations.

### Stage 4: Documentation And Examples

- [x] Update the platform MetaTable registration docs to describe the
  catalog-based startup workflow.
- [x] Update tutorials to show schema bootstrap as process initialization.
- [x] Update examples so row workflows assume runtime initialization already
  happened or call the explicit bootstrap at the top of `main()`.
- [x] Update pricing startup documentation so optional pricing tables use the
  same catalog bootstrap path.
- [x] Update ADR 0009 status text to mark its lazy-registration behavior
  superseded by this ADR.
- [x] Update the changelog for the behavior change.

### Stage 5: Tests

- [x] Add tests for catalog attach when requested tables already exist.
- [x] Add tests for missing catalog rows causing registration and catalog write.
- [x] Add tests for pre-catalog platform table import.
- [x] Add tests proving row operations do not register schemas.
- [x] Add tests for idempotent same-config startup and rejected different-config
  startup.
- [x] Add tests for clear catalog drift and duplicate-registration errors.

Stage 5 evidence:

- `tests/msm/maintenance/test_catalog_bootstrap.py` covers catalog attach,
  missing-row registration plus catalog write, pre-catalog platform table import,
  catalog contract drift, duplicate-registration drift errors, catalog table
  attach, and stale physical index signatures.
- `tests/msm/maintenance/test_metatable_catalog.py` covers the catalog table
  identity contract, uniqueness constraints, platform physical identity indexes,
  platform-returned MetaTable values, and deterministic contract hashing.
- `tests/msm/bootstrap/test_bootstrap.py` covers idempotent same-config startup,
  rejected different-config startup, active-runtime row lookup, missing table
  errors, and the fact that `resolve_runtime(...)` does not register or attach
  when no runtime exists.
- `tests/msm/api/test_assets.py` and `tests/msm/api/test_rows.py` cover public
  row APIs using the active runtime and failing before row operations when the
  runtime or required tables are missing.

## Consequences

The library becomes more explicit and operationally safer. Startup owns schema
lifecycle. Business row operations become business operations only.

This removes the surprising behavior where setting an environment variable can
cause `Asset.upsert(...)` to create platform tables. It also reduces noisy logs
from first row use because registration work is concentrated in one known
bootstrap phase.

The tradeoff is that scripts and examples need a visible initialization step.
That is acceptable because database schema creation is infrastructure work, not
ordinary row API behavior.

The implementation must include a migration/import path for existing
installations that registered tables before the catalog existed. Otherwise the
first catalog-based bootstrap would try to register tables that already exist
and recreate the duplicate-table conflict this ADR is meant to remove.

## Non-Goals

This ADR does not design a schema migration engine. Contract drift should be
detected and reported, not silently migrated.

This ADR does not change the `*Table` versus `msm.api.*` API split from
ADR 0008.

This ADR does not define DataNode registration or DataNode storage cataloging.
The scope is markets MetaTables and the runtime used by row APIs.
