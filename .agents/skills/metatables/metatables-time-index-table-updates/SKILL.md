---
name: metatables-time-index-table-updates
description: "Build or review TimeIndexTableUpdater producers, configuration hashing, dependencies, incremental frames and table readers in applications using the MetaTables Python client. Excludes client-library implementation, API routes, scheduling and runtime administration."
---

# MetaTables client time-index producers

## Client scope

Apply this skill to applications that consume the installed `metatables` Python
client. It covers application-facing models and workflows. Client-library
implementation, this repository's development/release tooling, and API internals
have separate ownership.

In a copied skill, resolve the `docs/` and `src/metatables/examples/` paths below relative to
this skill's `references/` directory. The client CLI bundles the matching version's
guides and examples there, including their linked documents. In the MetaTables
source checkout, read the same paths from the repository root.

For application development and mutation tests, use the
[local development skill](../metatables-local-development/SKILL.md) to select and
verify local SQLite before writing, then return to the intended environment after
verification within the requested scope.

Read `docs/client/build-an-updater.md`,
`docs/concepts/time-index-tables-and-updates.md`, and the tested
`src/metatables/examples/updater.py`. Use `docs/client/read-existing-time-index-tables.md` and
`src/metatables/examples/reader.py` for consumers that only need existing output.

The storage contract is a `PlatformTimeIndexMetaTable` SQLAlchemy class. The
producer is a `TimeIndexTableUpdater`; the API record is `TimeIndexTableUpdate`.
Use the [table skill](../metatables-meta-tables/SKILL.md) for storage design and the
[migrations skill](../metatables-migrations/SKILL.md) for table evolution. API
route behavior is documented in `docs/api/time-index-and-updates.md` and supported
capabilities in `docs/reference/capabilities.md`.

## Establish the contract

Infer dataset meaning, time grain, identity dimensions, output columns, upstream
choices, first-run/backfill bounds, and whether identity must be preserved from
the task and existing code. Clarify only unresolved choices that change the
published contract. Keep storage description, namespace, identifier, cadence,
columns, and FK/index metadata on the authoring model, not the updater config.
Write table and column descriptions by the rules in the
[table discovery skill](../metatables-table-discovery/SKILL.md); see
`src/metatables/examples/tables.py`.

Migrate and bind the output class before constructing the producer. Pass explicit
`config` and `output_table`; do not create/register tables inside `update()`.
The optional `hash_namespace` separates producer identities, **not output tables**.
A test namespace alone does not protect shared physical rows. Use a disposable
output binding or explicitly authorized row scope for mutation tests.

## Configuration and dependencies

Use `TimeIndexTableUpdateConfig` with described `Field` values and realistic
examples where useful. Fields affect `update_hash` by default. Values that change
output, source selection, dependencies, or producer scope must stay hashed.
Keep implementation constants in `ClassVar` or runtime configuration. For a
strictly descriptive Pydantic field, the supported exclusion is
`json_schema_extra={"hash_excluded": True}`; do not invent alternate markers.

The client owns configuration version 2 serialization/validation. A configured
upstream authoring class hashes by its bound table UID and must already be bound.
`output_table` is a constructor contract, not an ordinary config field. Removed
configuration forms and `test_node` are unsupported; use explicit namespaces.

Declare a deterministic `dependencies()` mapping. Executable dependencies are
other updater instances; read-only dependencies are `TimeIndexTableRef` objects.
References contribute lineage and reads without executing a producer. Do not
construct a changing dependency graph inside `update()`.

## Incremental output

Use `UpdateStatistics` to determine the next interval, including a first-run
fallback. Return rows matching the bound storage contract and avoid full-history
writes unless the task explicitly needs them.

Every non-empty frame must put `time_index` first and use exactly
`datetime64[ns, UTC]` for that index level. Construct it explicitly with
`pd.DatetimeIndex(..., dtype="datetime64[ns, UTC]")`; timestamp normalization alone
can retain microsecond precision. For a MultiIndex, declare all dimension levels
in storage-grain order and keep payload columns separate.

The time-index mixin creates the unique index for the complete observation grain.
Do not duplicate it manually. Additional indexes and foreign keys belong in
SQLAlchemy/Alembic metadata and should use application-prefixed physical names.
Changing a table contract requires a new migration, not an updater config field.

## Tail repair

Use the documented `TimeIndexMetaTable.delete_after_date` workflow for updater
output rollback. The cutoff is inclusive. Supply `dimension_filters` to select
value sets or `index_coordinates` to select exact streams. A null cutoff requires
one of those scopes and deletes all rows only in that scope. An unscoped null
cutoff must fail. Do not replace this workflow with direct connections, SQL,
truncation, or private endpoints.

The API route is `/time-index-meta-tables/{uid}/delete-after-date/`; deployment
prefixes belong in `METATABLES_API_URL`. See `docs/client/query-and-mutate.md`.

## Review and verification

Check hashing effects, deterministic dependencies, incremental bounds, configured
output identity, time dtype, dimension order, columns, and tail-delete scope.
Use the relevant updater tests and executable example tests. Report what was
actually exercised: pure frame logic, disposable storage, or a configured API.
Do not claim a scheduling/release workflow from producer tests. If a published
contract decision remains unknown, resolve that decision while continuing any
independent authorized work.

## Bounded transfers and recovery

Read `docs/client/bounded-transfers.md` for transfer contract v1. Prefer
`MetaTable.iter_rows()` for structured relation batches and
`TimeIndexTableRef.iter_batches()` for typed time-index frames. Existing complete
DataFrame readers have row, serialized-byte, and elapsed-time budgets; increase
client collection budgets deliberately or narrow the selection. Offset pages do
not provide a snapshot, and iterators do not prefetch.

Uploads remain sequential, with at most 10,000 rows and byte checks per chunk.
Each chunk commits independently. Preserve an explicit operation UUID and input
for restart recovery. On an uncertain outcome, inspect `upload_receipt()` before
resubmitting; do not assign a fresh key to bypass uncertainty. Administrator
reconciliation requires verified physical evidence. This workflow uses the Main
Sequence API and has no Artifact or temporary-URL dependency.

A 429 `transfer_capacity_exceeded` or 503 `database_connections_busy` means the
API was at capacity and nothing ran. Retry after `Retry-After`, an upload with the
same operation UUID; it is not an uncertain outcome.
