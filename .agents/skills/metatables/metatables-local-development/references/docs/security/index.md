# Security model

MetaTables separates **application administration** from **ownership of a table**.
Organization admins configure the application. Table Writers control their own
tables, including their data, schema, updaters, deletion, and sharing. A user does
not need to become an Organization admin to maintain a table they created.

The API enforces this model in both local and hosted runtimes. The Admin UI and
Python client use the same sharing endpoints. [ADR 0002](../adr/api/0002-application-administration-and-table-ownership.md)
records the decision and the migration boundary.

**Applications run Alembic through the client using their environment database login.**
Direct database connections and general client-side Alembic execution remain blocked.
Admins initialize and upgrade MetaTables system tables in Local Settings; a hosted
deployment's migration Job does so for its declared runtime database.

## Who owns each decision

| Responsibility | Owner |
| --- | --- |
| User identity, current Team membership, and Organization admin status | The platform, supplied through the Main Sequence SDK |
| Who can read or control a particular table | MetaTables grants in the selected runtime database |
| Application Settings and global Security admission | MetaTables, using the trusted platform admin fact |
| Sharing, lifecycle and schema admission | The MetaTables API |
| Data access during SQL execution | Database roles and privileges; SQLite engine authorizer locally |
| Showing permitted actions and access explanations | The Admin UI and Python client, using API decisions |

MetaTables does not maintain another Organization or Environment policy model.
It stores references to platform User and Team UIDs and the permissions assigned
to those principals. It does not administer Team membership. Both local and hosted
runtimes use the same application permission model and operation checks.

## The two layers

**Application administration** covers DataSource configuration, runtime selection,
system-table initialization and upgrades, global Settings, and Security management.
Organization admins can inspect and repair access across the application.

**Table access** has only two levels:

- **Reader:** inspect the table and read, query, or export its data.
- **Writer:** all Reader operations plus full table lifecycle and sharing control.
  Writer is ownership; there is no separate Owner role.

The [permission matrices](permissions.md) specify both layers. A table Writer
cannot change application Settings or a DataSource connection just because their
table uses that source. Conversely, table maintenance does not require access to
global Settings or Security.

Organization admins can grant or restore table access. Ordinary table operations
still use table permissions, so an admin can explicitly grant themselves Writer
access with an audit record. Security administration does not promise data
confidentiality against someone allowed to change all grants.

## A table owner's workflow

Alice is an ordinary application user. She creates a `prices` table in an available
DataSource and receives Writer access as part of its creation. She gives Bob Reader
access and Team Research Writer access. Bob can query prices; current members of
Research can update data, run producers and share the table. Writers can request the environment connection for client-owned migrations; its database privileges govern DDL.
Alice can eventually delete the managed table without asking an Organization admin.

The [ownership and sharing guide](ownership-and-sharing.md) explains how these
grants are recorded, how namespace inheritance works, and what revocation removes.

## Application interface and API

An admitted user can browse the application and see their permitted resources.
Table actions live on the table page. Its **Access** panel lets Writers
manage grants and see why each User or Team has access. Global **Settings** and
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
selection, system migrations, local database destruction, namespace grants, and
global Security operations require admin admission. Table sharing remains
available to the table's Writers.

Every operation is enforced by the API, including requests from the Python client.
The UI shows the API's effective permissions. Hidden buttons are a presentation
choice, not an authorization mechanism.

## Deployment and revocation

The platform User response must supply `is_organization_admin` and
`active_team_uids`; use the compatible published SDK prerequisite described in
[installation](../client/installation-and-connection.md). Hosted admission verifies
the existing signed caller assertion, then obtains that User's facts through the
SDK User detail operation. Local admission resolves facts for the running SDK user.
The deployment's existing User-directory access must permit that lookup.

The API caches successful User facts for one hour per caller and runtime. Startup
seeds the developer's entry; cache hits do not contact the platform, and concurrent
refreshes share one SDK request. Reads do not extend expiry. Platform membership,
admin and User-deactivation changes take effect at the next admission after expiry
or an API restart. Already admitted work may finish. Expired facts are never used
if refresh fails; missing facts, an inactive User, or an unavailable platform then
fails closed with 503. MetaTables stores no independent Team membership.

Table and namespace grants remain live catalog decisions: revoking them does not
wait for cache expiry. Grant mutations recheck current catalog grants under the
catalog mutation lock and reject stale sharing revisions with 409. Restart the
API after changing its SDK account or endpoint.

## SQL and schema boundary

SQL runs unchanged as a restricted database identity for the caller. Reader means
`SELECT`; Writer additionally means `INSERT`, `UPDATE` and `DELETE`. Separate read
and write identities ensure that a read request cannot write even for a Writer.
The API owns sharing, schema and lifecycle actions and never executes caller SQL
as its privileged schema-management login. SQLite enforces the same grants with
its engine authorizer callback.

Queries select only the runtime DataSource. There is no declared table scope,
statement classification or function allowlist. The database enforces access in
joins, CTEs, subqueries and permitted invoker routines. Database permissions are
established during setup and schema changes. Catalog tables remain inaccessible,
views cannot be registered, elevated routines cannot confer owner access, and
triggered writes and cascading foreign keys are restricted by the engine's policy.

PostgreSQL stores the catalog in `metatables` and owns managed tables through a
non-login owner role. User, Team and namespace grants become database privileges
and role memberships. The cached Team membership projection follows the platform
facts used at admission; it does not become a second membership authority.
PostgreSQL and SQL Server mirror permission changes transactionally with catalog
grants. MySQL records durable pending work because its permission statements commit
independently; it admits queries only after reconciliation succeeds.

The Admin Security page reads `GET /security/database-permissions/` to show caller
SQL admission, pending synchronization, and policy coverage for active tables.
This admin-only read does not repair permissions or resolve credential Secrets.
It reports durable catalog state; it does not audit native grants changed outside
MetaTables. SQLite uses a connection authorizer rather than database roles.

**Repair database permissions** on the Admin Security page re-establishes native
permissions from catalog grants and rechecks physical safeguards. The corresponding
admin-only endpoint is `POST /security/reconcile/`. Queries pause during repair.
If permission repair fails, caller SQL stays disabled until repair succeeds.
Client migration finalization refreshes the affected catalog contracts and SQL policies. Grant editing never requires a platform authentication change.

The API cancels work at its deadline and bounds fetched rows. PostgreSQL, MySQL
and SQLite reject multiple statements; SQL Server accepts a restricted batch.
Explicit commits in a SQL Server write batch can persist permitted writes before
another statement fails. See [ADR 0007](../adr/api/0007-database-enforced-table-access.md)
for the complete contract.

Application-table Alembic code runs in the application's Python process. The API
checks Writer access to provider catalog entries before returning the selected
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
