# Operate a hosted API

A hosted API's runtime database is declared by its deployment, not selected in
Settings. The API's `configuration.yaml` names the engine, the Environment Secret
holding the connection URI, and the public schema and TLS settings. Before every
rollout, the deployment workflow's migration Job prepares that database from the
new image, and a failure stops the rollout. API pods only open it. See
[ADR 0001](../adr/api/0001-unified-api-storage-and-local-sqlite.md) and
[ADR 0014](../adr/api/0014-main-sequence-release-jobs-and-production-migrations.md).

The repository's `.mainsequence/workflows/metatables-api.yaml` declares the
automatic FastAPI deployment at `api/metatables/main.py`. This file imports
`metatables.api.metatables.main:app`; the server and its deployment-specific
`configuration.yaml` are installed under `metatables.api`. That configuration
disables local controls and declares the runtime database. The workflow uses no
release or branch UIDs. Apply it through the platform's repository workflow lifecycle;
installing or debugging the Python client does not deploy the API.

The FastAPI target declares `min_scale: 1`, requesting at least one runtime
replica. The platform applies this setting on the next successful deployment.

The Python package bundles this same workflow for [client discovery](../client/installation-and-connection.md).
Workflow API `2.3.0` derives a FastAPI release name from the directory containing
`source_path`, so the declared directory is also the client's exact lookup name.
Do not maintain a separate name constant in consuming projects. After changing
that source path, publish/install a matching package build. Clients select the
release in their SDK-owned Organization Environment, including when the API and
the consuming application belong to different repositories. Identical names in
other Environments are expected. Each Environment must have one matching visible
deployment; resolve duplicates within it. Hosted clients leave
`METATABLES_API_URL` unset; that variable accepts only loopback development URLs.

Serve `metatables.api.app.main:app` with hosted execution and one runtime DataSource. Start one
worker per runtime instance, configure the ordinary SDK session and caller verifier,
and set `local_mode_available: false` in `configuration.yaml` on shared deployments.

```bash
uvicorn metatables.api.app.main:app --host 0.0.0.0 --port 18473
```

The ingress must provide signed caller assertions. Unsigned User UIDs and the
runtime's own workload token cannot identify the human requesting a table
operation. The SDK verifies caller proof; MetaTables applies local resource policy.

## Declare the runtime database

The deployment configuration is `src/metatables/api/metatables/configuration.yaml`,
packaged as `metatables/api/metatables/configuration.yaml`. It holds Secret names
and public settings, never secret values:

```yaml
local_mode_available: false
runtime_database:
  engine: timescale_db                      # postgresql | timescale_db | mysql | mssql
  uri_secret: METATABLES_RUNTIME_DATABASE   # Environment Secret holding the connection URI
  default_schema: public                    # optional; the engine default when omitted
  tls:
    mode: require                           # disable | require | verify-ca | verify-full
    ca_secret: null                         # optional Environment Secret names
    client_certificate_secret: null
    client_key_secret: null                 # set together with the certificate
```

The Secret named by `uri_secret` holds a URI such as
`postgresql://metatables:password@host:5432/database`. The login is always
`metatables`; the Job and the API refuse any other. Use `postgresql://` or
`postgres://` for `postgresql` and `timescale_db`, `mysql://` for MySQL and
`mssql://` for SQL Server, and percent-encode special characters in the password.
Host, port, database, login and password come only from the URI. It takes no
query options: TLS and the schema come from `configuration.yaml`.

The certificate Secrets apply to PostgreSQL, TimescaleDB and MySQL. SQL Server
rejects them and maps `tls.mode` to its driver: `disable` turns encryption off,
`require` encrypts and trusts the server certificate without validating it, and
`verify-ca` or `verify-full` encrypt and validate it.

## Set up a hosted runtime database

Every Environment's runtime database is opened by the same login, `metatables`.
Database roles are server-wide, so each database server has one `metatables`
login, shared by every Environment's database on it. Its role names are the
same everywhere: the login and `mt_owner`, which setup creates. The database,
the login and its privileges are the database administrator's responsibility.
[DataSource database privileges](../api/data-sources.md#database-privileges-and-sql-behavior)
lists what MetaTables requires.

1. Once per database server, create the login. On PostgreSQL and TimescaleDB:

   ```sql
   CREATE ROLE metatables LOGIN CREATEROLE PASSWORD '...';
   ```

2. For each Environment's database, let the login create the `metatables` schema:

   ```sql
   GRANT CREATE ON DATABASE production TO metatables;
   ```

   It also needs `CREATE` on the default schema.
3. Create the Environment Secret named by `uri_secret` in that Environment, holding
   `postgresql://metatables:password@host:5432/<database>`.
4. Set `runtime_database` in the API's `configuration.yaml`: engine, Secret name,
   schema and TLS.
5. Deploy the API. The migration Job initializes the database before the API rolls out.
6. Open **Settings** and check the declaration, the resolved connection, the
   `ready` status and the applied migration revisions.

## Deployment gate

In `.mainsequence/workflows/metatables-api.yaml`, the `migrate-system` Job
(`jobs/migrate_system.py`, exactly `metatables runtime upgrade`) runs from the
candidate image before the API rolls out, on every deployment. It reads
`configuration.yaml` and the Secret itself; it does not call the running API. It:

1. checks that the login can secure the database: `CREATEROLE`, `CREATE` on the
   database or ownership of the `metatables` schema, and `CREATE` on the default schema;
2. applies the system migrations;
3. registers the runtime DataSource, or updates its connection if the declaration changed;
4. reapplies database access setup. Per-User role passwords derive from the login
   password, so a rotated password reaches them.

Any failure blocks the rollout. The Job prints `status` (`initialized`, `upgraded`
or `up_to_date`), `previous_revisions`, `revisions` and `data_source_uid`. A new
runtime DataSource is recorded as created by the Job's SDK user.

A failed run names its cause. The error line gives the exception type, plus the
database server's SQLSTATE and message when the server answered. The
`metatables.bootstrap` logger writes the full error with its traceback to the Job
log, with passwords, tokens and connection-string credentials redacted. Settings
and API errors never carry driver text, which can include hosts and connection strings.

## API pods and Settings

API pods read the same declaration and Secret at startup and never run DDL. They
write no pointer to the pod's filesystem, so restarts and additional pods agree.
If the database is not migrated or registered, they report `migration_required` or
`registration_required` and serve no application operations until a deployment's
Job has run and the API has rolled out.

A Secret change takes effect on the next deployment. Pointing the Secret at a
different database follows the same procedure. Each database keeps its own
catalog, including registered tables and grants; nothing is transferred.

Settings is read-only in Hosted mode. It shows the declaration, the resolved
connection, the status and the migration revisions. `POST /runtime-bootstrap/configure/`,
`/migrate/` and `/activate/` answer 409: "The deployment manages the hosted runtime
database. Change runtime_database in the API's configuration.yaml or its Environment
Secret, then deploy the API." `metatables runtime initialize` uses `/migrate/`, so
it is Local only.

`GET /runtime-context/` reports the `bootstrap` descriptor without querying catalog
memberships. Pending bootstrap returns HTTP 200 with a null active DataSource, and
application routes remain unavailable. `managed_by` is `deployment` in Hosted and
`settings` in Local, and `can_configure` is false in Hosted. For admins,
`declaration` is the `runtime_database` section and `candidate` the resolved public
configuration, whose `password_secret_uid` is the URI Secret's UID.
`selected_source_uid` is the runtime DataSource UID once registered. Once active,
the descriptor supplies the source UID, dialect, parameter style and schema to
both clients.

Before the runtime is active, `/data-sources/` lists nothing and creating a
DataSource answers 409: registrations live only in the runtime catalog. The active
source cannot be replaced through `is_default` or redirected through a catalog
environment variable; change the declaration and deploy. The catalog and
application tables stay in that one database.

The verified hosted Environment remains display metadata supplied through ordinary SDK
interfaces. The declared database does not change SDK context or Environment requirements.

## Developer launcher in Hosted mode

After `metatables serve --local --admin` is switched to Hosted, the launcher reads
the API's packaged deployment configuration and the same Secret, resolved in the
developer's SDK Environment, so it uses the same database as the deployed API.
It never migrates. If the local branch has newer migrations than the deployed API,
it reports `migration_required` until that code is deployed.

## Application grants

Platform Users, Teams and their membership are resolved through the SDK. MetaTables
stores Reader/Writer grants on tables and namespaces. Manage those grants through
Admin and the [security API](../security/permissions.md), and configure deletion
protection on individual tables. The [permission model](../concepts/permissions-namespaces-labels.md)
describes live inheritance and revocation.

## Source and physical operation readiness

The deployment registers the runtime DataSource. Once it is active, additional
[DataSources](../concepts/data-sources.md) are registered under **MetaTables → Data
Sources** through the regular registry API. The injected SDKCredentialStore saves
each entered password as a managed platform Secret and stores its UID; Hosted never
provisions a local key or applies MetaTables AES encryption to that Secret. The
runtime descriptor supplies authoring defaults from the runtime binding. Platform
Secret access retains its normal SDK Environment requirement.

DataSources are resolved from the application catalog. Platform Secret values are fetched
for each physical operation after resource authorization; it is not cached across
operations by MetaTables. TLS settings and keys are passed to the physical adapter,
with temporary files restricted to the operation's lifetime.

Test connectivity and table operations with a disposable source before admitting
production writes. Migration-role provisioning needs additional database privileges.
Read-only or disabled source modes must remain enforced even when a catalog actor
has edit rights. A catalog row staying visible after source revocation does not
mean a physical operation remains authorized.

Back up the runtime database as a unit. System migrations and application-provider migrations have independent histories. A root HTTP response is not proof those dependencies are
ready. Hosted platform integration must be verified in its actual environment;
isolated tests do not establish deployment readiness.

## Bounded transfer rollout

Apply catalog revision `0008_upload_receipts` before updating writers. Keep all traffic through Main Sequence; Artifacts and temporary URLs are not dependencies. Concurrent PostgreSQL/MySQL/SQL Server admission uses transaction-held shared catalog guards, while permission publication uses exclusive guards. Run the targeted engine matrix before production rollout: the current change has local SQLite and focused contract evidence, not hosted buffering/cancellation/RSS benchmarks. See [transfer compatibility](../client/bounded-transfers.md#retries-and-compatibility).
