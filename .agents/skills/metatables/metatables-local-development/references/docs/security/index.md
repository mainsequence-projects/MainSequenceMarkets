# Security model

MetaTables separates **application administration** from **access to namespaces
and tables**. Organization admins configure the application and hold every action.
Everyone else gets access through **roles** granted on a namespace or a table:
`metadata_viewer`, `data_viewer`, `data_writer`, `editor` and `owner`. Any person can
create a namespace or a table and owns what they create. A deployed migration Job
creates its application's namespace on its first run, and the people who manage the
Job manage that namespace's access. Nobody needs to become an Organization admin to
deploy an application or maintain its tables.

The API enforces this model in both local and hosted runtimes. In Local mode the person
running the API administers their own SQLite runtime and holds every action, whatever
their platform admin flag. The Admin UI and
Python client use the same access endpoints. [ADR 0024](../adr/api/0024-namespace-and-table-access-roles.md)
records the role model; [ADR 0002](../adr/api/0002-application-administration-and-table-ownership.md)
records the separation from application administration.

**Applications run Alembic through the client using their environment database login.**
Direct database connections and general client-side Alembic execution remain blocked.
The local operator initializes and upgrades MetaTables system tables in Local Settings; a hosted
deployment's migration Job does so for its declared runtime database.

## Who owns each decision

| Responsibility | Owner |
| --- | --- |
| User identity, current Team membership, and Organization admin status | The platform, supplied through the Main Sequence SDK |
| Who holds which role on a namespace or table | MetaTables bindings in the selected runtime database |
| Application Settings and global Security admission | MetaTables, using the trusted platform admin fact |
| Sharing, lifecycle and schema admission | The MetaTables API |
| Data access during SQL execution | Database roles and privileges; SQLite engine authorizer locally |
| What happens to rows that reference a changed row | The referencing table's foreign key, chosen by whoever controls its schema |
| Showing permitted actions and access explanations | The Admin UI and Python client, using API decisions |

MetaTables does not maintain another Organization or Environment policy model.
It stores references to platform User and Team UIDs and the roles granted to
those principals. It does not administer Team membership. Both local and hosted
runtimes use the same application permission model and operation checks.

## The two layers

**Application administration** covers DataSource configuration, runtime selection,
system-table initialization and upgrades, global Settings, the security check, and
external table imports. It belongs to Organization admins (`metatables.administer`).

**Access to namespaces and tables** is a set of nested roles. Each includes the one
before it:

- **`metadata_viewer`:** see descriptions, schemas and lineage, not rows.
- **`data_viewer`:** read, query and export rows.
- **`data_writer`:** insert, update and delete rows.
- **`editor`:** change, migrate, operate updaters and delete; on a namespace, also
  create tables in it.
- **`owner`:** decide who has access.

A role on a namespace gives the table role of the same name on every table in it,
including tables created later. The [permission matrices](permissions.md) list every
action and role, and [ownership and sharing](ownership-and-sharing.md) explains how
roles are granted, inherited and revoked.

Organization admins hold every action on every namespace and table, reading and
writing data included. A call an application makes for a person, such as the
Analyst, carries only that person's access, never admin status.

## A table owner's workflow

Alice is an ordinary person. She creates namespace `prices` and becomes its owner.
She grants Team Research `editor` on it and Bob `data_viewer`. Research's members,
including the migration Job of the prices application, create and migrate tables in
`prices`; Bob can query them. A FastAPI that only writes rows gets `data_writer`: it
cannot migrate, delete or share. Alice can later grant or revoke any of these roles
without asking an Organization admin.

## Application interface and API

An admitted user can browse the application and see their permitted resources.
Table actions live on the table page, namespace actions on the namespace page. Their
**Access** panels let owners grant and revoke roles and show why each User or Team
has access. Global **Settings** and
**Security** belong to Organization admins.

Data Sources appears once in the MetaTables catalog menu. Its list and detail
pages at `/data-sources` and `/data-sources/{uid}` are available to authenticated
users, including before runtime initialization. Admins manage registrations in
these same pages. The hosted runtime DataSource is declared by the deployment;
Local selects its SQLite file in admin-only Settings.

The Admin menu is rendered only when the API reports `is_admin: true`. Its pages
are `/admin/settings` and `/admin/security`. Old `/settings` and `/security` links
redirect to their guarded destinations and preserve query parameters and
fragments. The old `/admin/data-sources/*` routes are removed without redirects. Settings is available to admins before database initialization;
other users are directed to an admin when configuration is needed.

These are browser routes. Resource API URLs remain unchanged and enforce their
own permissions: DataSource mutations and validation, runtime configuration and
selection, system migrations, local database destruction, external imports and
global Security operations require admin admission. Granting roles on a namespace or
table is available to its owners, and on a namespace also to the managers of the
workload that created it.

Every operation is enforced by the API, including requests from the Python client.
The UI shows the API's effective permissions. Hidden buttons are a presentation
choice, not an authorization mechanism.

## Deployment and revocation

Use the compatible published SDK prerequisite described in
[installation](../client/installation-and-connection.md). In hosted mode the SDK
request identity verifies the existing signed caller assertion. Admission takes the
caller and its admin flag from `User.get_logged_user()`, as the platform signed
them, and looks up no User
([ADR 0017](../adr/api/0017-hosted-request-identity.md)). Workload Users are
admitted like people. The assertion carries no Teams: admission asks the platform,
with `in_teams()`, which of the Teams that MetaTables grants name the caller belongs
to. Each pod reuses an answer for 24 hours, so a person removed from a Team can
keep reading through that Team's grants for up to a day. Writes act on an answer
at most a minute old. Migration credentials, table deletion, finalization and
permission changes always ask the platform at once, and a login's database role
memberships change only on such a fresh answer. A failed check fails the request;
it never counts as "not a member". Local admission resolves facts for the running SDK user,
whose platform User response must supply `is_organization_admin` and
`active_team_uids`.

The API caches the developer's successful User facts for one hour. Startup
seeds that entry; cache hits do not contact the platform, and concurrent
refreshes share one SDK request. Reads do not extend expiry. The developer's
platform membership, admin and User-deactivation changes take effect at the next
admission after expiry or an API restart; a hosted caller's take effect with its
next caller assertion. Already admitted work may finish. Expired facts are never used
if refresh fails; missing facts, an inactive User, or an unavailable platform then
fails closed with 503. MetaTables stores no independent Team membership.

Role bindings remain live catalog decisions: revoking one does not wait for cache
expiry. Access changes recheck current bindings under the catalog mutation lock and
reject a stale access revision with 409. Restart the
API after changing its SDK account or endpoint.

## SQL and schema boundary

SQL runs unchanged as a restricted database identity for the caller. `data_viewer`
means `SELECT`; `data_writer`, `editor` and `owner` add `INSERT`, `UPDATE` and
`DELETE`; `metadata_viewer` gives no database privilege. Organization admins' login
roles are members of an admin role with write privileges on every managed table.
Separate read and write identities ensure that a read request cannot write.
The API owns sharing, schema and lifecycle actions and never executes caller SQL
as its privileged schema-management login. SQLite enforces the same grants with
its engine authorizer callback.

Queries select only the runtime DataSource. There is no declared table scope,
statement classification or function allowlist. The database enforces access in
joins, CTEs, subqueries and permitted invoker routines. Database permissions are
established during setup and schema changes. Catalog tables remain inaccessible,
views cannot be registered, elevated routines cannot confer owner access, and
triggered writes are restricted by the engine's policy. Cascading foreign keys are
allowed: a referencing table's own foreign key decides what happens to its rows, so
tables that reference a table never change who may write it. See
[foreign keys and cascades](permissions.md#foreign-keys-and-cascades).

PostgreSQL stores the catalog in `metatables` and owns managed tables through a
non-login owner role. User, Team and namespace bindings become database privileges
and role memberships. The cached Team membership projection follows the platform
facts used at admission; it does not become a second membership authority.
PostgreSQL and SQL Server mirror permission changes transactionally with catalog
grants. MySQL records durable pending work because its permission statements commit
independently; it admits queries only after reconciliation succeeds.

The Admin Security page reads `GET /security/database-permissions/` to show caller
SQL admission, pending synchronization, policy coverage for active tables, and the
last security check.
This admin-only read does not repair permissions or resolve credential Secrets.
It reports durable catalog state; it does not audit native grants changed outside
MetaTables. SQLite uses a connection authorizer rather than database roles.

A security check compares everything MetaTables secures in the database with the
catalog's grants and repairs what differs, including grants changed directly in the
database. It runs daily at 03:00 UTC as the `check-security` Job of a hosted API's
workflow ([ADR 0023](../adr/api/0023-daily-security-check.md)). **Run security check
now** on the Admin Security page runs it at any time; the admin-only endpoint is
`POST /security/checks/`. Hosted starts the Job, Local runs the check in the request.
Queries keep running during a check, and a failed check changes nothing. The page
shows the last check: what started it, when, and whether it passed, repaired
something or failed with an error code.

Grants changed outside MetaTables are repaired within a day. A release that changes
how MetaTables computes access reaches the database at the next check; its release
notes say to run the check after deploying.
Client migration finalization refreshes the affected catalog contracts and SQL policies. Grant editing never requires a platform authentication change.

The API cancels work at its deadline and bounds fetched rows. PostgreSQL, MySQL
and SQLite reject multiple statements; SQL Server accepts a restricted batch.
Explicit commits in a SQL Server write batch can persist permitted writes before
another statement fails. See [ADR 0007](../adr/api/0007-database-enforced-table-access.md)
for the complete contract.

Application-table Alembic code runs in the application's Python process. The API
checks `tables.migrate` on provider catalog entries before returning the selected
runtime connection. No provider allowlist or API installation is required.

Direct database DDL uses the configured login's privileges, outside governed SQL.
Environment operators own those permissions and credential distribution. Catalog
grants do not sandbox migrations or revoke credentials already received. Finalization
reconciles catalog metadata and governed-SQL policies after schema changes. See
[ADR 0013](../adr/api/0013-application-owned-migrations.md).

## Development database setup

Declare a fresh hosted development runtime database in the API's `configuration.yaml`
and its Environment Secret, then deploy; the migration Job initializes it
([hosted setup](../operations/hosted-runtime.md#set-up-a-hosted-runtime-database)).
Existing development data is not migrated into the new PostgreSQL catalog schema.
Setup must also establish database permissions before caller SQL is enabled. The
login password in the URI Secret also seeds the derived caller-login passwords; each
deployment reapplies them, so a rotated password reaches them. Credentials are exposed only through the authenticated migration connection workflow;
ordinary data/query clients do not receive them.
