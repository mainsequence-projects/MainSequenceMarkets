# ADR 0010: Import external tables and views through the database backend contract

Date: 2026-09-30

Status: Accepted.

Implementation status: Implemented in the backend contract, API routes, Python
client and Vite import/Rows views. Verification and boundaries are recorded below.

Owner: MetaTables API. The Python client and Vite application consume its contract.

Clarified 2026-10-01 (MetaTables #9): default compiler calls discover the API's
runtime DataSource automatically. Selecting an imported MetaTable for an optional
external read uses that table's registered source through `read_rows()` or
`iter_rows()` and the same API. It does not mutate the default, replace Environment
selection or authorize external writes. Arbitrary external SQL and joins remain
outside this implementation; SQL selection of another source reports a specific
policy conflict. Client guides must show the working external read workflow and
must not present `data_source_uid` alone as enabling arbitrary external SQL.

Related decisions: [ADR 0002: Administration and ownership](0002-application-administration-and-table-ownership.md),
[ADR 0007: Database-enforced table access](0007-database-enforced-table-access.md),
[ADR 0008: Database backend contract](0008-mysql-mssql-table-workflows.md), and
[ADR 0009: Shared CredentialStore](0009-shared-credential-store.md).

Accepted follow-up, 2026-09-30: [ADR 0012](0012-bounded-data-transfer-and-safe-retries.md)
applies common byte/deadline budgets and incremental client consumption to these
structured reads. External read-only admission and preview consistency limits
remain in force. Local transfer verification is complete; hosted driver verification remains pending.

## Context and required outcome

An administrator has registered an existing database, potentially using a
read-only database account. They need to discover its tables and views, select
relations, and import their definitions as MetaTables. Users with the appropriate
MetaTable or namespace grants must then be able to inspect and read those
relations. They must not have to write a table contract for every physical object.

Import means recording metadata in the runtime's existing MetaTables catalog.
It does not copy data or acquire ownership of the external schema. No external
database needs a MetaTables catalog, a migration, or permission to create roles
merely to participate in this workflow.

### Historical Django behavior

The implementation is present in `tdag-django` commit `fe3d326e2`, including:

- `docs/tdag/ts_manager/adr/adr-022-import-metatables-from-physical-data-sources.md`;
- `timeseries_orm/tdag/ts_manager/views/meta_tables.py`, action
  `import_from_data_source`;
- `timeseries_orm/tdag/ts_manager/metatable_import/`, particularly `service.py`,
  `graph.py`, `contracts.py`, `result.py`, and the dialect readers.

That service exposed the `meta-tables/import-from-data-source` action, discovered
the default schema, included views, followed foreign keys, generated contracts,
and created or refreshed externally owned registrations. It offered dry runs,
strict or partial outcomes, namespace assignment, and stale-row reporting.
PostgreSQL/TimescaleDB, MySQL, and MSSQL readers produced a shared snapshot shape.

Reuse those semantics and useful algorithms through the current API architecture.
The Django models, SDK-backed catalog mutations, and `supports_*` flags do not
belong in this API. Historical support for foreign tables also does not prove that
the current query and permission adapters can safely support them.

## Gaps recorded before implementation

Inspection date: 2026-09-30. Paths below are relative to this repository unless
explicitly identified as belonging to the Vite application.

| Area | Current evidence | Required change |
| --- | --- | --- |
| HTTP workflow | Generated OpenAPI has `POST /meta-tables/register/` and `POST /meta-tables/{uid}/introspect/`, but no import action. `src/metatables/api/app/routes/table_registration.py` requires one caller-authored contract. | One import operation with discovery, preview, selection, reconciliation, and structured results. |
| Discovery | `TableBackend` in `src/metatables/api/backend/backends/contracts.py` introspects a known name. It has no relation discovery or batch introspection contract. | Add narrow discovery and read operations to this existing facet. |
| External source resolution | `CatalogDataSourceProvider.get()` calls `RuntimeStorageBinding.require_execution_source()`. A saved non-runtime source cannot be used by table operations. | Resolve sources according to the authorized operation; preserve the runtime restriction for managed DDL, migrations, and caller-written SQL. |
| Restart invariants | `RuntimeBootstrap.inspect()` in `src/metatables/api/app/bootstrap.py` rejects any `MetaTable` or `PhysicalOperation` referencing another source. | Permit externally owned MetaTables on registered sources, while keeping physical mutation journals and managed tables bound to the runtime source. |
| View access | `postgresql_access.py` and `sqlite_access.py` require ordinary tables. `hosted.py` rejects MySQL objects other than base tables and MSSQL objects other than user tables. | Explicit view admission and read semantics. Changing an introspection query alone is insufficient. |
| Physical metadata | `MetaTable.kind` distinguishes relational and time-index tables. Contract normalization preserves extra physical fields but does not validate `relation_kind` as a first-class invariant. | Validate physical relation kind independently of the existing logical kind. A view is a relational MetaTable. |
| Names and types | `catalog_rules.py` and `table_contracts.py` impose an unqualified 63-character table-name rule; `models.py` stores `String(63)`. Some type validation retains PostgreSQL assumptions. | Preserve legal external identifiers and native types through adapter normalization, without truncation or executing catalog expressions. |
| Refresh | `register_catalog_entry()` resolves an existing physical identity and returns it; it does not implement bulk contract refresh and stale comparison. | Reuse its ownership/grant invariants and add explicit refresh orchestration. |
| Security synchronization | `backends/access.py::_changed` reacts to every MetaTable, table grant, and namespace change. Runtime `refresh_policies()` only considers the selected source. | Reconcile the affected runtime permission graph only. External import must not fail because unrelated runtime SQL security needs repair. |
| Query transport | `table_sql.py` accepts caller-written SQL and obtains a restricted database identity. There is no general relational row-read endpoint accepting only structured column/filter inputs. | A bounded server-generated relation read for sources whose read-only credentials cannot provision caller roles. |
| Frontend | The Vite application's `src/api.ts` and `SourceQueryBuilder.tsx` send DataSource SQL to `/meta-tables/run-query/`. | Add import preview/results and table/view browsing against the new API contracts. Sending that existing SQL request to an external source will still fail. |

Useful existing primitives include physical identity uniqueness, external schema
ownership, table/namespace Reader and Writer grants, projection repositories,
introspection, catalog-only unregistration, engine registration, and the injected
CredentialStore. The design extends these primitives.

## Decision

### 1. One runtime catalog, with explicitly resolved physical sources

Keep one selected DataSource for the runtime catalog and all platform-managed
tables, time-index outputs, migrations, and physical mutation journals. Imported
MetaTables reference an existing DataSource row in that same catalog through
`data_source_uid`; their data remains in that source.

Extend the existing source resolver with a typed operation purpose. The request
service authorizes the actor before resolving credentials. The resolver then
checks source status, storage access, runtime binding where required, and obtains
credentials from the existing runtime-injected CredentialStore.

| Operation purpose | Permitted physical source |
| --- | --- |
| Managed creation, migration, time-index write, arbitrary SQL | Selected runtime source, retaining existing admission rules. |
| Relation discovery and introspection | Registered enabled source; discovery requires administration. |
| Bounded relation read | Source recorded on the authorized MetaTable; an external source never borrows the runtime catalog connection. |

This amends ADR 0008's selected-source-only rule for external discovery and
bounded reads. It does not make changing the default source a prerequisite for
import. Runtime startup validates references and ownership locally; it must not
connect to every external source or become unavailable when one is offline.

Source UID alone must not establish physical separation. An administrator could
register another connection to the runtime database under a different UID or host
alias. Source admission must identify that case and reject the external-account
read path; it cannot bypass runtime restrictions through duplicate registrations.
Adapters use database identity and the runtime ownership markers, not just a
comparison of configured host strings. Unverifiable identity must fail closed
where it could expose the runtime catalog.

Local and hosted runtimes use the same resolver, import service, and adapters.
`METATABLES_LOCAL_RUNTIME` continues to select runtime setup. No import-mode
environment variable, alternate local endpoint, second credential store, or
generic capability registry is introduced.

### 2. Extend the existing backend contract

Add these conceptual operations to `DatabaseBackend.tables` in
`src/metatables/api/backend/backends/contracts.py`; retain `backend_for(source)` as the only
engine dispatch point:

```text
discover_relations(scope, page, context) -> RelationPage
introspect_relations(relations, context) -> RelationSnapshotBatch
read_relation(relation, selection, admission, context) -> RelationRows
```

Extend the existing `access` facet with admission for a server-generated relation
read. An admission is an internal, request-scoped resource bound to the actor,
source, relation, and operation. It cannot authorize arbitrary SQL and is never
a credential or permission token returned to the client.

| Shared API/service responsibility | Engine adapter responsibility |
| --- | --- |
| Actor/source/table grants, namespace assignment, selection, FK traversal, contract reconciliation, transactions, results, and audit | Physical discovery, object identity, relation kind, native types, identifier quoting, parameter binding, connection/session setup, cancellation, and engine access enforcement |
| Catalog ownership and lifecycle rules | Read-only inspection of the external catalog |
| Validated structured selection and output limits | Compiling and executing the bounded read against the resolved relation |

Use small typed values: `RelationIdentity(schema, name)`,
`RelationSummary(kind, identity)`, `RelationSnapshot`, and per-relation failures.
Snapshots include columns in ordinal order, native and normalized types,
nullability, primary/unique keys, indexes, and ordered FK columns and targets.
Index expressions and server defaults are descriptive metadata, never SQL to
execute during import.

Import holds one backend inspection context for discovery and the selected
relations' FK closure. Each frontier is reflected as a batch, reusing one source
connection and one Inspector cache; shared orchestration must not open a new
connection or rediscover the schema for each relation. SQLAlchemy 2.1 or later
provides native bulk reflection for PostgreSQL and MSSQL. MySQL and SQLite use
the same multi-relation interface, retaining the dialect's cached definitions
where their metadata operations are per object. Engine differences stay in the
adapter. Before publication, recheck all successful snapshots in one fresh batch
and close that source connection before changing catalog records.
Source SELECT checks also use one batch statement with zero-row projections.
Only a failed check is subdivided to report the affected relations individually;
valid selections do not pay one network round trip per relation for permission
checks. A failed read transaction is reset with its read-only settings restored.

PostgreSQL and TimescaleDB share relation discovery. MySQL and MSSQL implement
the same contract using their catalogs. SQLite implements it for the API-owned
local database only; importing arbitrary SQLite filesystem paths remains outside
the registration model. Adapters bound to remote sources are usable from either
a SQLite local runtime or a hosted runtime. Shared services contain no engine
switches or separate local/hosted import implementations.

### 3. Relation identity, contract, and scope

- Initially discover one explicit schema, defaulting to the source's configured
  default. For MySQL this is the configured database. Do not scan every database
  or recursively cross schema boundaries.
- Identify a relation by source UID, schema, and exact physical name. Namespace
  and logical identifier do not identify a physical object. Preserve quoting and
  case according to the source engine's comparison rules, including when the
  runtime catalog engine has different collation rules.
- Widen physical-name persistence and transport together to accommodate supported
  engine identifiers. Keep stricter generated-name rules for managed tables.
  External names must not be trimmed, lowercased, silently renamed, or truncated.
  Store the names returned by source resolution, and use binary comparison for
  physical identity in the runtime catalog. The source adapter resolves input
  names according to source collation; the catalog must not merge distinct
  PostgreSQL names just because it happens to run on case-insensitive MySQL or
  MSSQL. Update the uniqueness constraint and lookup together, under the catalog
  lock, and reject ambiguous resolution.
- Import ordinary/partitioned tables and regular views. Do not expose TimescaleDB
  internal chunks, system catalogs, MetaTables catalog/version tables, temporary
  objects, synonyms, or internal schemas. Materialized views and foreign tables
  require explicit adapter/read tests before inclusion; report them as unsupported
  when explicitly selected.
- Store validated `table_contract.physical.relation_kind = table | view` and the
  introspection snapshot. Default existing contracts without a kind to `table`.
  Use `MetaTable.kind = relational`; do not infer a time-index updater from a
  timestamp column. No new editable `writable` or capability flag is needed.
- Preserve keys as observed. Views and keyless tables need no fabricated primary
  key. Map composite keys accurately. Retain native types in the snapshot; types
  that cannot be safely serialized cause a clear relation-level failure, not an
  invented PostgreSQL type or silently dropped column.

Every created row has `management_mode = external_registered`,
`schema_management_mode = external_registered`, and active physical provisioning:
the relation already exists and passes inspection. Import checks source SELECT
permission with a zero-row projection; it does not fetch application rows or
evaluate their serialization. Bounded row reads validate actual returned values.
Runtime import success additionally requires caller admission and a bounded read
probe after catalog publication. Runtime permission repair
may temporarily block admission despite an active physical relation, following
ADR 0007; report that state explicitly as described below. A stored snapshot does
not mean an offline source will remain readable indefinitely.

### 4. Existing authorization, with an explicit view boundary

Discovery reveals objects that do not yet have MetaTable grants. Require the
existing platform-admin fact for discovery, dry runs, and creation of imported
registrations, matching DataSource management. Listing registered sources remains
available to ordinary active members. Existing table Writer access controls
refresh, sharing, and unregistration; administration must not overwrite a
registration the actor cannot edit. Namespace assignment uses its existing rule.

New registrations receive the existing creator Writer grant. Namespace grants
remain live inheritance; import does not copy them into permanent direct grants.
Administration alone does not grant read access to another user's registered
table. No DataSource sharing model or parallel permission vocabulary is added.

Both `read_only` and `read_write` DataSources can be imported. `disabled` sources
cannot be inspected or read. These storage settings bound physical operations;
they do not replace MetaTable authorization.

#### Read-only source invariant

For a read-only external DataSource, MetaTables must create or modify nothing in
the source database. Discovery, import, refresh, reads, sharing, and unregistration
must never issue DDL, DML, role/user creation, `GRANT`/`REVOKE`, migrations, or
permission repair there. This includes helper schemas, temporary tables, copied
views, bookkeeping tables, and credential/key storage. Use the existing database
account to inspect metadata and read the authorized relations.

Imported MetaTable records, snapshots, projections, namespaces, and application
grants are persisted only in the existing writable runtime catalog. Sharing an
imported relation updates those application grants; it does not change the
external database's permissions. The external source's credentials continue to
use the runtime's CredentialStore.

`storage_access_mode=read_only` enforces this boundary even if the supplied
database account happens to have broader privileges. Insufficient database read
permissions produce an actionable error; the API must not retry with an
administrative account or attempt to create missing privileges. This rule applies
equally to local and hosted runtimes. A read-only external source is not a
candidate for the writable runtime catalog.

#### Reads from external sources with read-only credentials

Provide a bounded relational read that accepts a MetaTable UID, selected columns,
typed predicates, sort columns/directions, and limits. The API checks Reader or
Writer access, derives the physical identity from the catalog, and generates the
statement. Inputs cannot contain SQL fragments, functions, joins, subqueries,
arbitrary physical names, or user-supplied contracts. Values are bound parameters;
identifiers come from the validated relation snapshot and are dialect quoted.
Select explicit catalog columns rather than `*`, so new physical columns are not
automatically exposed before refresh.

For non-runtime sources, execution uses the source's registered database account.
It performs no role creation, `GRANT`, schema mutation, or external security
initialization. The source owner must provision the account's intended read
permissions. MetaTables cannot promise per-user database identities or per-user
row-level security for a shared external account: existing API grants control who
can request the registered relation's output.

For the selected runtime source, keep restricted caller sessions and native
permission reconciliation. Never execute a public row-read request using the
runtime catalog owner's unrestricted connection. Pending runtime security repair
continues to block reads that need those sessions.

Both cases use the same service, structured read contract, existing grants, and
backend access facet. The distinction follows source ownership and execution
authority, not local versus hosted mode.

#### Views

A grant on an imported view authorizes the view's output. It does not grant direct
access to its underlying tables. Imported views are always read-only through
MetaTables, even if the database considers a view updatable. Writer permits
catalog management and sharing subject to existing rules, not view DML or DDL.

This is a deliberate amendment to ADR 0007's blanket view exclusion. View security
cannot be reduced to allowing another object type: PostgreSQL has owner/invoker
view semantics, MySQL has `SQL SECURITY`, and SQL Server can apply ownership
chaining. See the official [PostgreSQL view documentation](https://www.postgresql.org/docs/17/sql-createview.html),
[MySQL view documentation](https://dev.mysql.com/doc/refman/8.4/en/create-view.html),
and [SQL Server permission checks](https://learn.microsoft.com/en-us/sql/relational-databases/security/permissions-database-engine?view=sql-server-ver17).

The external source owner defines and maintains view output and its dependencies.
Import must not rewrite a view, transfer its ownership, grant its dependencies to
MetaTables users, or claim that a read-only transaction neutralizes every routine
a view might invoke. Discovery/read access to an external database is an explicit
trust in that database's owner, as is registering its credentials.

For views in the selected runtime database, adapter admission must additionally
protect the runtime catalog and privileged routines. Validate dependency closure
and execution context using engine metadata; reject protected catalog references,
unknown/cross-database dependencies, and unsafe elevated execution. Preserve the
existing routine restrictions. SQLite resolves the approved view's dependency reads only for the private,
server-generated bounded SELECT. Its public arbitrary-SQL identity is never
expanded: SQLite reports a caller-defined CTE name as the same origin as a view,
so a general origin-name allowlist would leak ungranted base tables. Consequently
arbitrary SQL on a SQLite view still requires its underlying table grants. Native
hosted engines retain their own view privilege semantics.
If a safe view admission cannot be established, return a specific relation error
and leave it unregistered. All supported engines must pass the view tests below
before the implementation is considered complete.

#### Arbitrary SQL and writes

`run-query` and `execute-operation` retain ADR 0007's restricted database sessions
and runtime binding. They must never fall back to shared external credentials or
infer safety from `operation=select`. No SQL parser or authorization allowlist is
introduced. Native runtime view grants, once safely established above, must be
tested through these endpoints as well as through the bounded reader.

The required first external-source workflow is discovery, import, metadata
refresh, bounded reads, grants, and unregistration. Arbitrary SQL against a
non-runtime source, cross-source joins, and external DML are outside this decision.
The frontend and client must expose the working bounded reader for these sources,
rather than route users to an unavailable SQL explorer. This limitation must be
documented explicitly; successful import cannot be presented as arbitrary SQL
support. Existing supported table writes on the runtime source keep their current
rules. Views never receive write privileges.

### 5. API contract and import algorithm

Use `GET /data-sources/{source_uid}/relations/` for lightweight name discovery.
It calls the existing backend discovery contract, returning visible names, table
or view kind, existing catalog UID, and whether the caller can import or refresh
each object. It requires the same administrator authorization as import and never
reflects every column, plans changes, or writes to either database. Discovery has
the shared deadline and metadata response bound, without the 200-relation import
batch limit. This lets the site show selectable objects immediately.

Use `POST /meta-tables/import-from-data-source/` for preview and import. Its dry-run
form computes the same plan as a committed request. Import state stays outside
`/runtime-context/`. The site uses the Command Center SDK transfer list to select
individual or all shown objects, submits exact names with FK expansion disabled,
and batches larger selections in groups of up to 200. Each batch commits
independently; a failure stops subsequent batches and preserves completed results.

Proposed request:

```json
{
  "data_source_uid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "physical_schema": "public",
  "relation_names": ["orders", "customer_orders_view"],
  "exclude_relation_names": [],
  "include_views": true,
  "follow_foreign_keys": true,
  "refresh_existing": true,
  "namespace": null,
  "dry_run": true,
  "strict": true
}
```

Omitting `relation_names` selects the supported visible relations in that schema.
An explicitly empty selection is invalid. Exclusions always win, including during
FK expansion. Omitting `namespace` uses a stable source-specific namespace, such
as `external-<full-source-uid>`; display-name changes do not move existing tables.
Leave logical identifiers null by default. Existing identifiers, descriptions,
labels, grants, namespaces, and deletion protections survive metadata refresh.

1. Authenticate and authorize; resolve source and credentials once. Require an
   initialized runtime catalog, but no runtime SQL permission repair for external
   discovery/import. Confirm storage access before external network calls.
2. Discover and introspect selected relations through the backend contract. Follow
   visible FK targets only in the selected source/schema. Maintain a visited set
   and bounded graph size; include cycles and self-references without recursion
   loops. View dependency validation is distinct from FK graph expansion.
3. Produce a plan matching existing rows by physical identity. Allocate new UIDs
   in memory, resolve FK references in a second pass, and build normalized
   contracts. A missing, excluded, hidden, or out-of-scope FK target produces a
   warning and no broken projection. Do not leak inaccessible target MetaTable
   identities in responses.
4. Validate ownership, existing Writer grants, contracts, view admission,
   supported reflected types, and read access. Separate read-only permission planning from
   permission installation: discovery and dry runs must never invoke a validator
   that installs grants or revokes existing privileges. A runtime inspection probe
   may use the API's inspection authority but is not proof of caller admission;
   the public reader always needs the restricted session described above.
   A dry run stops here with no catalog, namespace, grant, projection, search,
   or credential changes and sends no physical mutation statements. It may
   perform a zero-row SELECT permission check; it does not fetch application rows.
5. For a real import, acquire the catalog lock and recheck source configuration,
   grants, namespace rules, and matching identities. A changed source or physical
   shape invalidates the plan. Concurrent identical imports converge on the same
   UIDs through the physical identity constraint and locked reconciliation.
6. Create or refresh successful external rows and their column/index/FK/search
   projections in one catalog transaction. Reuse existing registration and
   projection helpers; add explicit refresh primitives rather than copying the
   HTTP registration implementation. Refresh never converts a managed or
   time-index table, changes physical identity, or takes ownership of DDL.
7. Reconcile only affected runtime permission policies when necessary, then commit
   and return per-relation outcomes. For runtime relations, verify a read under
   the admitted caller identity before reporting usable registration. Follow
   ADR 0007's durable pending/recovery protocol where native privilege changes
   cannot share the catalog transaction; incomplete admission is not an import
   success and remains closed to reads. Imports from non-runtime sources must
   neither delete runtime policies nor trigger their initialization. Namespace
   changes that also affect runtime tables still require normal reconciliation.

`strict=true` is the proposed default: any selected-relation failure prevents all
catalog writes. With `strict=false`, preflight failures are reported and the valid
set is committed together; unresolved FK edges to failed members become warnings.
A catalog persistence failure rolls back that entire valid set, so reported
successes always refer to committed rows. Fatal source/authorization failures
never become an empty successful import. Optional unresolved FK edges alone do
not fail strict mode.

Strict atomicity describes catalog publication, not transactional grant DDL on
every engine. In particular, runtime MySQL permission reconciliation may leave
durable pending catalog work after a failure, as ADR 0007 already specifies.
Return that state explicitly and keep admission closed until repair completes;
do not report rollback of changes that have committed. Imports from non-runtime
sources do not perform native permission reconciliation and retain the single
catalog-transaction behavior above.

Return source/schema/namespace, `dry_run`, `committed`, counts, per-relation
`would_create`, `would_update`, `created`, `updated`, `unchanged`, or `failed`,
safe error codes, warnings, and stale candidates. Only committed/existing rows
have authoritative MetaTable UIDs; planned UUIDs do not promise future identity.
Use the normal API error envelope for fatal errors, and structured diagnostics
for rejected strict plans. Never return passwords, DSNs, raw driver diagnostics,
or view definitions containing sensitive literals.

Stale detection compares only a successfully completed, unfiltered scan of the
same source/schema with its existing external registrations. Partial selections,
excluded objects, failed pages, and permission-filtered visibility cannot prove
deletion. Report `not_visible_in_scan` as a candidate, without deleting or marking
the table inactive. Unregistration remains an explicit authorized catalog action
and must never drop an externally owned table or view.

Start with bounded synchronous imports: at most 200 selected relations including
FK expansion, a 60-second operation deadline, and bounded snapshot/report sizes.
Use the selected engine’s bounded metadata inspection; large import selections
require explicit names. Exceeding a limit fails the plan before
mutation and asks for a smaller selection; do not silently truncate or introduce
an untracked background task. Physical metadata can change between inspection
and commit; fail observed drift and require refresh on later read-shape mismatch.
No distributed transaction or lock on the external owner's DDL is promised.

Add `POST /meta-tables/{uid}/read/` for the structured reader described above.
Reuse existing row serialization, result limits, and cancellation primitives.
Keyless relations support bounded previews; pagination without a unique ordering
must not promise a stable snapshot across requests. Lost credentials, disabled
sources, missing relations, or shape drift produce distinct actionable errors.
Permission revocation is checked on every request; a cached connection or result
must not preserve revoked access.

### 6. Delivery and integration

1. **Contracts and catalog:** normalized relation types, identifier/type handling,
   migrations for name widths, source-purpose resolution, bootstrap invariants,
   and source-scoped security hooks. Backfill missing relation kinds as tables;
   preserve UIDs, credentials, grants, and existing managed-table behavior.
2. **Backend vertical slices:** discovery, introspection, safe view admission, and
   bounded reading through each engine adapter. Prove external read-only accounts
   need no role/DDL privileges and runtime views cannot expose protected objects.
3. **Import service and routes:** preview, graph reconciliation, refresh, atomic
   persistence, typed failures, OpenAPI, and catalog-only deletion checks.
4. **Clients:** thin Python import/read methods and Vite DataSource import preview,
   selection, results, and table/view row browsing. Use Command Center SDK
   navigation, components, styling, and themes. Keep DataSources in their existing
   menu; use existing administration/Writer checks for actions. Display a view as
   a view, with working reads and no physical mutation action.
5. **Documentation:** update API references, external-table examples, permission
   explanations, engine matrix, and client workflow/skill references after the
   behavior is verified. User guides describe the implemented bounded reader and
   retain the restrictions on external SQL and physical writes.

Ship the import workflow only when imported tables and views can actually be read.
Do not release a registration-only milestone as completed functionality.

## Acceptance criteria

Use the existing database contract/Compose harness. Mocks establish orchestration
behavior; actual drivers and databases establish engine support.

- Exercise PostgreSQL (including the supported older version), TimescaleDB, MySQL,
  and MSSQL external sources using accounts with catalog visibility and SELECT,
  but no schema, role, or grant administration. Test from a local SQLite runtime
  and hosted catalogs, including a different catalog/source engine pairing.
- Exercise ordinary tables and regular views in the local SQLite runtime and
  every hosted runtime. Verify the same import and read contracts across modes.
- Import then read a table, keyless table, view, nested view, quoted identifier,
  legal long identifier, composite key, cyclic FK graph, and representative native
  types. Confirm inaccessible/system/internal relations stay excluded. Verify
  duplicate and differently cased names using each source's comparison behavior.
- Verify Reader/Writer, User/Team, namespace inheritance, revocation, and admin
  boundaries. A view grant permits its output and no direct read of ungranted base
  tables. Reject view DML, protected-catalog views, unsafe runtime routines, and
  injected names/filters. Exercise native runtime SQL view permissions too.
  Registering a host alias or second credential for the runtime database must not
  turn it into an unrestricted external read source.
- Keep runtime SQL security deliberately uninitialized or in repair while saving
  an external source, previewing, importing, reading it, and unregistering it.
  All of these external operations work; unrelated runtime SQL remains blocked.
- Prove dry runs change nothing, strict failures roll back all changes, partial
  plans report accurate committed results, repeated/concurrent imports reuse
  identities, and refresh preserves grants and ownership. FK projections never
  point at rolled-back imports. Check both transactional and nontransactional
  native permission reconciliation where runtime sources are involved.
- Restart after import: the catalog is accepted, external rows persist, and an
  offline external source does not prevent API startup or unrelated operations.
  Test credential resolution through both ADR 0009 providers without disclosure.
- Prove external discovery/import/read/unregistration executes no physical DDL,
  DML, role changes, or MetaTables migrations on the external source. Verify
  connection cleanup on cancellation, timeout, failure, and client disconnect.
- Verify the same absence of external mutations during refresh, sharing, grant
  revocation, and failure recovery, including no temporary/helper objects. Test
  both a genuinely read-only database account and a more privileged account on a
  DataSource configured as `read_only`. Only runtime catalog records and grants
  may change; missing external read privileges must never trigger privilege
  creation or a retry with stronger credentials.
- Verify frontend import followed by a real row read through the API, with the
  Python client exercising the same endpoints. Release every test listener and
  process after verification. Record tested versions and remaining limitations
  before marking this decision implemented.

## Alternatives and consequences

**Loop over the current registration endpoint in Vite.** Rejected: it still needs
caller-authored contracts, cannot discover relations, breaks FK reconciliation,
and preserves both external-source and view blockers.

**Port the Django service and dialect registry wholesale.** Rejected: it would
duplicate the current backend registry, credentials, and authorization rules.

**Require every external source to become the selected runtime.** Rejected: it
would move the catalog and require database/role write privileges just to inspect
an external read-only database.

**Run arbitrary external SQL as the saved connection user.** Rejected: it cannot
enforce per-MetaTable grants. Parsing SQL to recover those grants would reverse
ADR 0007. The bounded reader is a deliberately smaller operation that the server
constructs from an authorized relation.

**Import metadata now and defer all reads.** Rejected: it would recreate the
registration-without-interaction gap.

The proposal adds a real external-relation workflow while retaining one catalog,
one authorization vocabulary, and one engine registry. Its costs are an explicit
external-read admission path, careful view security, cross-engine identifier/type
normalization, and a broader integration matrix. Full external SQL exploration
and external writes remain separate decisions; this ADR must not imply their
availability.


## Implementation and verification record

- Shared orchestration: `src/metatables/api/backend/operations/import_relations.py`; engine
  discovery, read-only sessions and safe runtime-view validation:
  `src/metatables/api/backend/backends/relation_tables.py`, selected by the existing registry.
- Published commands/results: `src/metatables/api/backend/contracts/relation_import.py` and
  `src/metatables/api/app/routes/table_import.py`. Existing introspect handles Writer refresh.
- Migration `0007_external_relation_names` widens hosted physical names to 128
  characters. SQLite retains its descriptive legacy VARCHAR width without a table
  rebuild; SQLite does not enforce that width. Missing relation kinds read as table.
- Python `MetaTable.import_from_data_source()` and `read_rows()` use these routes.
  Vite provides DataSource Import, external relation browsing, and Rows with
  Writer definition refresh, using Command Center SDK controls and layout.
- Test evidence is `tests/database_backend/test_relation_import.py` and the
  existing database suite, with real PostgreSQL 17.6, TimescaleDB 2.22.0/PG17,
  MySQL 8.4.6, SQL Server 2022 CU20/ODBC 18, and SQLite. SQL Server is run separately
  on this development host to avoid memory pressure. Database tests are manual
  local checks; the runner now starts engines sequentially by default.
- The external tests use a SQLite runtime catalog with remote physical engines;
  runtime imports use each engine's own catalog. Hosted cross-engine catalog/source
  combinations and older PostgreSQL releases were not separately verified here.
- Discovery preserves exact names returned by database reflection; clients must
  select those names, including case, rather than depend on collation aliases.
  Materialized views, foreign tables and synonyms are not importable.
- Import deadline is 60 seconds, with 200 relations, 256 KiB per snapshot, 8 MiB
  aggregate metadata, and 1 MiB report limits. Row reads allow 1,000 rows and 8 MiB.
  A committed runtime import reports a failed caller read probe explicitly;
  physical availability does not hide pending permission repair.
- Import batching regression coverage is in `tests/contracts/test_relation_batching.py`.
  A 200-relation external import uses two read connections: one for discovery
  and planning, and one for the fresh bulk schema recheck. Permission checks use
  one batch statement without fetching rows. These focused checks use
  temporary SQLite files; they do not start containers or verify live hosted
  database engines.
- Physical database identity (server/database identity, or SQLite device/inode)
  is compared with the current runtime connection before external reads. This
  blocks runtime aliases even when an account cannot see protected catalog tables.
- The tests reject every external statement except reads, reflection and session
  settings. They cover read-only accounts, refresh, revocation, idempotency and
  unregistration with runtime SQL security uninitialized. Runtime view tests
  reject direct and CTE access to base tables without grants.
- Verification results: 56 database contract tests passed on each of the five
  engines (280 executions). The full repository run passed 753 tests with 85
  environment-specific skips; subsequent focused checks passed 19 tests after
  the final SQLite read-only connection and database identity changes.
- Frontend TypeScript, 71 transport/tab and component-boundary tests, SDK theme
  audit and production build
  run without interacting with the user's browser. A visual browser review is not
  recorded as completed.
