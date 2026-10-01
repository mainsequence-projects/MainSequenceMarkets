# ADR 0002: Application administration and table ownership

> Amendment (2026-10-01): [ADR 0013](0013-application-owned-migrations.md) establishes application-owned
> client Alembic execution using the configured environment connection. Its DDL
> privileges belong to the environment database role. It supersedes this ADR's
> conflicting application-migration execution and credential restrictions;
> governed API operations and MetaTables system migrations remain separate.


Date: 2026-09-29

Status: Accepted and implemented; application migrations amended by [ADR 0013](0013-application-owned-migrations.md).

Owner: MetaTables API. Scope: application administration and resource
authorization, with client and Admin UI consumers.

Related decision: [ADR 0001: One API execution path with SQLite for local development](0001-unified-api-storage-and-local-sqlite.md).

User guide: [Security model](../../security/index.md), including permission matrices,
ownership/sharing examples, and implementation status.

## Context

MetaTables owns its catalog, table lifecycle, and resource authorization. The
platform supplies trusted User identity, current Team membership, and whether
the caller is an Organization admin through the Main Sequence SDK. It does not
own MetaTables table grants or decide which user can operate a particular table.

Application administration and table ownership are different authorities. A user
who creates a table must be able to maintain, share, migrate, and delete it
without asking an Organization admin. Restricting migrations, metadata changes,
updater execution, or deletion to admins would break that workflow. Separate
curator, schema-maintainer, and updater-operator roles are unnecessary for the
initial model.

Before this decision, the catalog contained `MetaTableGrant` and `NamespaceGrant` records with
view/edit flags, copied namespace grants, and locally maintained Team membership.
DataSource management and bootstrap used creator ownership. This decision replaces
those policies. Current behavior is documented in
[Permissions, namespaces, and labels](../../concepts/permissions-namespaces-labels.md).

## Decision

### 1. Separate application administration from table access

Use the platform's Organization admin fact for application administration. Do
not create an application-owned Organization, Environment, or duplicate platform
role model. User and Team UIDs are external principal references, not tenant
relationships. The SDK transports trusted facts; it does not implement
MetaTables permission policy.

An admitted application user can create a managed table or register an external
table in an available DataSource, subject to supported capabilities and physical
lifecycle checks. Creation does not require an existing grant on a nonexistent
table. It must not allow a caller to take ownership of an already registered
table by repeating registration.

| Application operation | Ordinary application user | Organization admin |
| --- | --- | --- |
| Enter the application and browse permitted resources | Yes | Yes |
| Create or register a table in an available DataSource | Yes | Yes |
| Configure, validate, disable, or remove DataSources | No | Yes |
| Select the runtime mode or runtime DataSource where supported | No | Yes |
| Initialize or upgrade MetaTables system tables | No | Yes |
| Destroy a local runtime database through Settings | No | Yes |
| Change application-wide Settings and security policies | No | Yes |
| Manage grants across the application and recover orphaned resources | No | Yes |

Admin admission applies before catalog creation. It must use platform-supplied
facts independently of application grant tables, avoiding a bootstrap dependency
on the database being initialized. The first caller does not acquire
administrative authority merely by configuring a pending source. Any admitted
Organization admin can administer an existing runtime; the registration creator
does not have exclusive authority.

Organization admin status grants global security administration, including the
ability to grant or restore table access. Ordinary table operations still use
the table-access evaluator: an admin can explicitly grant themselves Writer
access, with an audit record. This makes access explicit; it does not promise
confidentiality against someone authorized to change all grants.

### 2. Reader and Writer are the only table access levels

**Writer means owner/full control of the table.** There is no separate Owner
role. Multiple Users and Teams can have Writer access. Writer includes Reader.

| Table operation | Reader | Writer / Owner |
| --- | --- | --- |
| View metadata, schema, and permitted lineage | Yes | Yes |
| Read, query, preview, and export data | Yes | Yes |
| Insert, update, upsert, and delete rows | No | Yes |
| Roll back time-index data | No | Yes |
| Edit descriptions, labels, and table configuration | No | Yes |
| Run application-table migrations and finalize contracts | No | Yes |
| Register, configure, and operate the table's updaters | No | Yes |
| Manage the table's dependencies | No | Yes |
| Grant, change, or revoke Reader/Writer access to the table | No | Yes |
| Delete managed storage or unregister an external table | No | Yes |

Creating a table and granting its creator Writer access form one catalog
transaction. Creator attribution remains historical metadata; it is not an
irrevocable permission or an additional authorization path.

Readers cannot modify data, metadata, execution state, or grants. Writers can
share Reader or Writer access with other platform Users and Teams on their own
tables without accessing global Security administration. A Writer can revoke
another Writer's direct grant. Any remaining independent grants still apply;
Organization admins provide recovery if a resource loses all Writers.

### 3. Evolve the existing central grant model

Evolve `MetaTableGrant` as the authoritative model for direct table grants instead
of introducing a second ownership or access registry. Each record points to one
MetaTable and one principal. Together these records cover the catalog's tables.

| Field | Meaning |
| --- | --- |
| `uid` | Identity of the grant record |
| `meta_table_uid` | Foreign key to the controlled MetaTable |
| `principal_kind` | `user` or `team` |
| `principal_uid` | Platform User or Team UID |
| `access_level` | `reader` or `writer` |
| `granted_by_user_uid` | User who established or last changed the grant |
| `created_at`, `updated_at` | Grant creation and modification times |

Enforce uniqueness on `(meta_table_uid, principal_kind, principal_uid)`. Absence
of a grant is not Reader access. Empty access is represented by revocation, not
by a third level. The existing view/edit flags must have an explicit transition
to Reader/Writer semantics in the security schema revision.

Store grants and their audit history in the selected runtime database alongside
the catalog and default table data. Record grant creation, changes, and revocation
with the acting User, target, previous/new access, and time; deleting a current
grant must not erase its history. Attribution fields alone are not an audit log.

Grant mutations must recheck the caller's current Writer or administrative
authority in the mutation transaction. Never accept a submitted owner UID, Team
list, or admin flag as proof of authority. Referenced principals must be selected
or validated through the supported SDK identity interfaces.

### 4. Resolve effective access from current facts and live inheritance

Default deny. Effective table access is the strongest applicable Reader/Writer
grant from:

1. Direct User grants on the table.
2. Grants to the caller's current platform Teams on the table.
3. User and Team grants on the table's current namespace.

Do not introduce explicit deny rules in the initial model. Labels classify
resources and never grant permissions. A DataSource's availability or connection
configuration is not a table-access grant.

Team identity and membership remain platform-owned. Replace independent local
membership administration with trusted platform facts obtained through the SDK.
Any cached membership or admin facts must have an explicit freshness/revocation
contract; missing or expired facts must not manufacture elevated access.

Namespace inheritance is live. Removing or reducing a namespace grant removes
or reduces the access it supplies to current member tables. Moving a table stops
inheritance from its old namespace and starts inheritance from its new namespace.
Independent direct or Team grants remain effective. Do not retain permanent
copies of old namespace grants or silently convert them into direct grants.

Changing a table's namespace changes access and must be presented that way in
the UI. The caller needs Writer access to the table and authorization for the
destination namespace. Table ownership alone cannot alter global namespace
grants or use an arbitrary namespace name to acquire access. Namespace-wide
grant administration belongs to application Security in the initial version.

Revoking one grant does not erase other grants. Effective-access responses must
explain each contributing source, including the Team or namespace responsible,
and show access that would remain after a proposed revocation.

### 5. Enforce table authority across the full lifecycle

Use one server-side evaluator for details, lists, counts, search, lineage, SQL,
row mutations, lifecycle operations, updater workflows, and grant management.
The browser and Python client consume the same decisions. Hiding a UI control
does not replace API enforcement.

A query needs access to every table it actually reads or writes. Client-declared
scope alone is not evidence of the objects a SQL statement accesses. Migration
targets and execution authority must cover only authorized tables/schema work;
authorization on one table must not implicitly authorize every table in a source.

Multi-table migrations and cascades require the appropriate access to every
affected table before effects occur. Read-only dependencies require Reader
access to their input tables. An updater requires Writer access to its output
and Reader access to its inputs; executing upstream producers also requires
Writer access to their outputs. Linking a dependency never grants access to it.
Updater configuration, run-state mutations, and recovery use the output table's
Writer authority rather than a new updater role.

Full table control does not bypass data integrity or physical ownership rules.
Reserved tables, active runs, deletion protections, dependency constraints,
read-only/disabled DataSources, and unsupported engine capabilities retain their
lifecycle checks. External-table removal unregisters catalog metadata without
dropping externally owned storage. System tables and permission records are not
ordinary user tables that a Writer can modify through data or migration APIs.

Local and hosted execution use the same permission evaluator and grant model.
Runtime initialization continues to require explicit action as specified by
ADR 0001; no automatic migrations or local permission bypass are introduced.
Independent Git discovery and unregistered local branches remain supported.

### 6. Reflect the two layers in the UI

The application interface is available to admitted users and shows only their
permitted resources. Table Writers see lifecycle, updater, and sharing actions
on the table page. Its **Access** panel manages direct grants and explains
effective User/Team access, including inheritance and revocation effects.

Global **Settings** and **Security** administration are for Organization admins.
Global Security can inspect and change grants across the catalog and recover
orphaned resources. Application administration is not a prerequisite for a
Writer to operate or share their own table. API responses supply effective
permissions to the UI; the frontend must not reconstruct the policy itself.

The Admin navigation area is mounted only for `is_admin: true` from the API.
Settings and Security live under a shared `/admin/*` route guard at
`/admin/settings` and `/admin/security`. Data Sources appears once in the catalog
menu at `/data-sources`, with public list/detail routes and authorized source
management actions in the same pages. Remove legacy `/admin/data-sources/*`
routes without redirects. Runtime DataSource selection remains admin-only in Settings.
Old Settings and Security URLs redirect to the guarded routes.
Settings can mount before catalog initialization only after admin admission.
Non-admins retain table Access panels and their permitted table operations.

## Superseded amendment: block direct application migration connections (2026-09-29)

Superseded on 2026-10-01 by ADR 0013. The following text records the prior decision.

A client holding a database connection can execute DDL outside the API's table
checks, and API revocation cannot revoke an already-open connection. Checking
only an Alembic registry table does not authorize all objects the connection can
change. The user explicitly selected blocking this path until API-mediated
execution exists.

Both local and hosted runtimes therefore reject direct application migration
connection requests with 409 `direct_migration_connections_disabled`, after table
authorization. No local SQLite exception, PostgreSQL role issuance, or admin
exception is provided. CLI current/upgrade/downgrade and database autogeneration
fail before reservations or transport. Offline scaffolding and handwritten
revision authoring remain available. Application migration execution and its
acceptance criterion below are deferred, not represented as implemented.

Writer remains the required table authority for future API-mediated schema work.
Admin-run packaged system migrations remain available through Settings and do not
issue a client connection. This amendment supersedes ADR 0001's direct application
migration connection behavior while preserving its unified runtime and explicit
bootstrap requirements.

Platform admin and active-Team facts are additive read-only fields on existing
SDK User responses. Admission uses the bounded runtime cache defined below.
The signed caller assertion, platform directory permissions, and platform
authentication mechanisms are unchanged.

### Amendment: bounded platform-fact caching (2026-09-29)

This amendment replaces the requirement to fetch User facts on every request.
Repeated User and Environment lookups added seconds to ordinary table reads and
runtime initialization without changing their results.

- Each API runtime owns a bounded in-memory User-fact cache (at most 1,024 entries),
  keyed by caller User UID and developer/hosted lookup path. A successful lookup
  is usable for one hour, measured with a monotonic clock. Reads do not extend
  its lifetime. The developer's startup lookup seeds the cache with the same
  expiry; the first application request does not repeat it.
- Concurrent misses or expired entries for the same key share one SDK lookup.
  Valid cache hits perform no platform request. Failures, malformed facts,
  inactive Users and mismatched User UIDs do not populate the cache. Expired
  facts are never used after a failed refresh; admission returns 503 and a later
  request may retry. Missing caller proofs still fail before cache access.
- Platform Team membership, admin status and User deactivation changes become
  visible on the first request after expiry, at most one hour after a successful
  lookup for new admissions. Already admitted operations are not retroactively
  cancelled. Table and namespace grants remain live catalog decisions, including
  grant mutation checks; those grants and effective permissions are not cached.
- Runtime Environment display metadata has a separate bounded cache keyed by
  Environment UID, also for one hour. Verified, not-found and unavailable
  descriptors share this lifetime; an unavailable result never becomes verified
  without another successful SDK lookup. This cache does not decide access.
- Startup, worker replacement and runtime-mode changes create new caches. SDK
  account/endpoint changes require restarting that API runtime; cache hits do not
  perform account revalidation. No credentials, membership registry, global SDK
  cache policy, new platform endpoint or environment variable is introduced.
- `/runtime-context/` continues to produce current bootstrap, DataSource and
  runtime state and retains `Cache-Control: no-store`. Only its platform metadata
  lookups are cached. This is separate from client ADR 0003's endpoint cache.
- The Admin shares identical in-flight GETs within the same transport and runtime
  context. Aborting one subscriber does not cancel another; a short cancellation
  deferral lets development effect remounts share the request. Completed responses
  are not retained. Mutations and transport/runtime changes prevent subsequent
  reads from joining requests started under the previous state.

Acceptance includes startup reuse, repeated and concurrent requests, isolation
between callers and runtimes, fixed expiry, revocation after expiry, failed
refresh without stale access, live catalog grant revocation, and Admin request
sharing with independent cancellation.

## Superseded behavior and preserved boundaries

This decision supersedes ADR 0001's pending-runtime configurator/existing-source
creator exclusivity, including the ownership admission of local database reset.
Those administrative actions now require the trusted platform admin fact.
It also supersedes independent application Team-membership authority and the
current permanent materialization of namespace grants.

It preserves ADR 0001's single runtime binding, explicit bootstrap, one database
for system and default user tables, shared local/hosted execution, and SDK-only
platform integration. No Organization or Environment model, index, or constraint
is reintroduced. Platform role evaluation stays with the platform; application
rules consuming that result stay with MetaTables.

Deployment control, platform Secret policy, and platform account/Team management
are outside this decision. It introduces no new authentication mechanism or
DataSource credential-retrieval endpoint.

## Consequences and implementation sequence

The model exposes only Reader, Writer, and the existing platform administrative
fact. Writers are trusted table co-owners: they can delete data, change schemas,
and delegate full control. There is no restricted ingestion-only Writer in this
version. Row-, column-, and time-coordinate grants, explicit denies, custom role
designers, and separate operator/curator roles are deferred.

Implementation must:

1. Supply trusted User, Team, and admin facts through supported SDK interfaces,
   including the pre-catalog bootstrap path, without duplicating platform policy.
2. Evolve direct/namespace grants, retire independent Team membership and copied
   namespace authority, and introduce durable grant-change audit history.
3. Apply the shared evaluator to every operation in both matrices, including SQL,
   migration targets, compound operations, and updater execution.
4. Provide public grant-management and effective-access APIs, then integrate
   table Access panels and application Settings/Security.
5. Update client support, capability documentation, examples, and behavior tests.

Reconciliation of existing grants must be explicit: direct view/edit grants map
to Reader/Writer, while copied namespace grants are replaced by their live source
where it still exists. Access surviving only through a retired copy is removed
and reported, not silently promoted to a permanent direct grant. The development
schema baseline/recreation policy remains governed by ADR 0001.

## Acceptance criteria

- A non-admin creates a table, receives Writer access, shares it, runs its updater,
  migrates it, and deletes it without administrative approval.
- A Reader can browse/query/export permitted data and cannot mutate the table,
  execution state, or grants. A caller without access cannot discover hidden
  resources through counts, search, lineage, or error details.
- A Writer can grant/revoke Reader and Writer access only on tables they control.
  Re-registering an existing table never grants the caller ownership.
- Team changes and namespace revocation/moves change effective access under the
  documented freshness rules; independent grants remain visible and effective.
- Non-admins cannot manage DataSources, runtime selection, system migrations,
  local database destruction, or global Security, even when the catalog is empty.
- Organization admins can administer the application and recover table grants
  without being the original runtime or resource creator.
- Compound queries, migrations, dependencies, and cascades cannot use permission
  on one table to access or change another unauthorized table or system record.
- Grant mutations are authorized atomically and produce durable audit history;
  the UI explains the same effective decisions enforced by the API.
- Both supported runtime adapters pass the same authorization scenarios. Existing
  lifecycle and physical ownership safeguards remain enforced.

## References

- [Architecture and glossary](../../concepts/architecture.md)
- [Current permissions, namespaces, and labels](../../concepts/permissions-namespaces-labels.md)
- [Table contracts and lifecycle](../../concepts/table-contracts-and-lifecycle.md)
- [Time-index tables and updates](../../concepts/time-index-tables-and-updates.md)
- [Supported capabilities](../../reference/capabilities.md)
