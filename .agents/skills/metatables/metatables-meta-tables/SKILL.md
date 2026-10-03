---
name: metatables-meta-tables
description: "Author and query application tables through the installed MetaTables Python client. Covers SQLAlchemy contracts, external registration and governed SQL in consuming applications. Excludes client-library implementation, API/server changes and repository tooling."
---

# MetaTables client contracts and queries

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

Use the installed `metatables` client. The API catalog resource, the client
resource model, and a SQLAlchemy authoring class have different responsibilities.
Read `docs/concepts/architecture.md` and
`docs/concepts/table-contracts-and-lifecycle.md` before choosing a workflow.

For actual endpoint support, consult `docs/reference/capabilities.md`. Do not
infer API support from the presence of an inherited client method. Platform
identity and Git source facts use SDK imports. Table operations use the client's automatic hosted discovery or an explicit
`METATABLES_API_URL`; the API selects the effective DataSource. See
`docs/client/installation-and-connection.md`. Local development runs the same API
with SQLite behind it; ordinary clients never open local table files. Local
workspaces use one persistent SQLite database for system and user tables per
checkout; Git branches share it.
A hosted API's deployment declares and initializes its runtime DataSource; Local
Settings explicitly initializes or selects the SQLite file. Startup never runs
Alembic. See `docs/operations/catalog-migrations.md`.

## Authoring decisions

Establish row meaning, ownership, DataSource, physical schema/name, namespace,
logical identifier, time grain if any, and foreign-key targets from the task and
existing models. Clarify only unresolved choices that materially change the
contract. Preserve the user's existing authorization and scope.

- Managed application tables use `PlatformManagedMetaTable` or
  `PlatformTimeIndexMetaTable` and the migration-provider workflow. Use the
  [migrations skill](../metatables-migrations/SKILL.md) for creation and
  evolution.
- Existing externally owned tables use `register_external_sqlalchemy_model` with
  their actual physical binding. Registration does not create the physical table;
  see `docs/client/register-existing-tables.md` and `src/metatables/examples/external_table.py`.
- `backend_managed` is a separate low-level API provisioning intent. Do not use it
  as a substitute for ordinary managed application-table migrations.

A UID is catalog identity. An optional identifier is unique in the connected catalog.
A physical binding is DataSource + schema + table name. A catalog
namespace groups resources and grants; it is not a SQL schema. Contract hashes
are fingerprints, not table identity. See `docs/concepts/identity-and-scope.md`.

## SQLAlchemy contract rules

Use `src/metatables/examples/tables.py` as the tested pattern. Declare an explicit
application-prefixed physical name with `schema_table_name(app, concept)`, a
stable logical identifier, and an intention-rich `__metatable_description__`.
Give columns useful `info={"label": ..., "description": ...}` metadata. Explain
row grain and downstream meaning rather than repeating types.

Keep foreign keys and indexes in SQLAlchemy metadata. Reference explicit physical
names using `ForeignKey`/`ForeignKeyConstraint`; do not ask users to hand-author
catalog target UIDs. Alembic renders physical DDL; catalog finalization introspects
it. The client column contract does not itself serialize all FK/index metadata.

For a `PlatformTimeIndexMetaTable`, declare time first in `__index_names__`, the
full observation grain, and a timezone-aware time column. Prefer `time_index` as
the time name for updater compatibility. The mixin automatically creates the
unique index for the full grain; add only additional lookup indexes. Declare
`__cadence__` when the stable observation interval is known.

Physical names remain stable across schema changes. Evolve through new Alembic
revisions; do not recompute identity from columns or rewrite applied history.

## Queries and mutations

Read `docs/client/query-and-mutate.md` and `src/metatables/examples/query.py`. Use
`compile_sqlalchemy_statement` with bound parameters. The request sends SQL and
selects one DataSource; the API executes as the authenticated user, and the
selected database backend enforces Reader/Writer permissions on the tables
actually touched. The API does not parse SQL for authorization. The compiler can
resolve DataSource and dialect from the selected runtime; supply both explicitly
for offline compilation. Preserve execution mode, row limits and timeouts.

There is no declared table list: `MetaTableOperationScopeTable`,
`MetaTableOperationScope` and `scope_tables` were intentionally removed. Do not
recreate them, add per-query registration checks, or parse SQL to enforce a client
scope. Use existing physical bindings in SQLAlchemy models. Registration and
schema evolution belong to their lifecycle workflows. For older applications,
use the [legacy upgrade skill](../metatables-upgrade-legacy-app/SKILL.md) and
`docs/client/upgrade-legacy-app.md`.

`operation="select"` selects read execution; the other labels select write
execution. The label does not classify the SQL. Database permissions enforce
access; row/time limits and transaction handling remain in the API. Refer to the
query guide for engine-specific statement/batch behavior. Application DDL belongs
to the separate migration-provider workflow.

Column search is supported. Description search, search-index refresh, and
legacy convenience sharing/label actions are not supported API workflows.
Use `get_access`, `set_access` and `revoke_access` for supported Reader/Writer
sharing. Labels can be changed through the documented table PATCH path. Authorization is
owned by the API catalog; see `docs/concepts/permissions-namespaces-labels.md`.

Updater output rollback uses `TimeIndexMetaTable.delete_after_date` with an
inclusive time cutoff and explicit dimension/coordinate scope when appropriate.
A null cutoff requires a scope. Do not replace that workflow with ad hoc SQL.
Deletion/cascade requires edit access, relevant protection checks, and explicit
cascade intent; it is not an administrator-role bypass or migration repair.

On a TimescaleDB DataSource, time-index tables are hypertables. Their compression
and retention policies are set only through `TimeIndexMetaTable.set_timescale_policies`
(Writer) and read with `get_timescale_policies`. Do not add policies to table
contracts or Alembic revisions; to keep them in code, call the client from a
bootstrap Job. Retention permanently drops older chunks, including backfills.

## Validation

Check authored models, normalization, physical naming, FK targets, and time grain
against the actual workflow. Run relevant behavior tests and the example tests.
State whether validation used local contracts, a disposable database, or a
configured service. Never claim an end-to-end deployment result from an import
check. Preserve published contracts unless the task authorizes their evolution.

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
