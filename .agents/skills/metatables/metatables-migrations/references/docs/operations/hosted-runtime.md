# Operate a hosted API

The repository's `.mainsequence/workflows/metatables-api.yaml` declares the
automatic FastAPI deployment at `api/metatables/main.py`. This file imports
`metatables.api.metatables.main:app`; the server and its deployment-specific
`configuration.yaml` are installed under `metatables.api`. That configuration
disables local controls. The workflow uses no release or
branch UIDs. Apply it through the platform's repository workflow lifecycle;
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

No database is required just to open Settings. Register a PostgreSQL, TimescaleDB, MySQL or MSSQL
DataSource with its connection settings and password under **MetaTables → Data Sources**.
The injected SDKCredentialStore saves the password as a managed platform Secret
and stores its UID. Hosted never provisions a local key or applies MetaTables AES
encryption to that Secret. Then select it
from the registered DataSources list in **Settings → Runtime → DataSource**. In the
developer launcher, this selection can be saved while Local mode remains active;
**Switch to Hosted** is a separate action.
If MetaTables is absent or outdated, explicitly click **Run MetaTables migrations**.
If its schema is already compatible, choose **Use this DataSource**. The selected
database stores both the system catalog and user tables; the source registration is
saved there only after migrations succeed. See [bootstrap and upgrades](catalog-migrations.md).

`GET /runtime-context/` reports `bootstrap.status`, candidate configuration, migration
revisions and activation state without querying catalog memberships. Pending bootstrap
returns HTTP 200 with a null active DataSource; application routes remain unavailable.
This lets the Vite site show Settings even on the first launch. Once active, the descriptor
supplies the source UID, dialect, parameter style and schema to both clients.

DataSources are registered through `/data-sources/` in either runtime mode. Private
pre-initialization persistence retains the legacy `.local/runtime-source-candidates.json`
filename for compatibility; it is not a second resource. Selection saves
public connection settings and Secret references to `.local/runtime-data-sources.json`.
Persist that directory across restarts. Startup verifies
the existing schema and reopens the selected source; it never upgrades. An incompatible
or unreachable database leaves Settings available and application operations blocked.

The active source cannot be replaced through `is_default` or independently redirected
through a catalog environment variable. Reconfigure it through Settings as one complete
runtime binding. Other registrations are candidates for Settings; operations execute
only against the selected source. The catalog and application tables stay in that
one database. Changing the selected source does not transfer tables or catalog state.

The verified hosted Environment remains display metadata supplied through ordinary SDK
interfaces. Selecting storage does not change SDK context or Environment requirements.

The ingress must provide signed caller assertions. Unsigned User UIDs and the
runtime's own workload token cannot identify the human requesting a table
operation. The SDK verifies caller proof; MetaTables applies local resource policy.

## Application grants

Platform Users, Teams and their membership are resolved through the SDK. MetaTables
stores Reader/Writer grants on tables and namespaces. Manage those grants through
Admin and the [security API](../security/permissions.md), and configure deletion
protection on individual tables. The [permission model](../concepts/permissions-namespaces-labels.md)
describes live inheritance and revocation.

## Source and physical operation readiness

Register the runtime DataSource under **MetaTables → Data Sources**, then select and initialize
it through Settings. Additional [DataSources](../concepts/data-sources.md) in an active
hosted catalog use the regular registry API. The runtime
descriptor supplies authoring defaults from the selected binding. Platform Secret access
retains its normal SDK Environment requirement.

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
