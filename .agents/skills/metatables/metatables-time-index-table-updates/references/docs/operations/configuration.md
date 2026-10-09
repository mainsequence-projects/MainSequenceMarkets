# Configuration

Configure platform identity through the Main Sequence SDK. MetaTables does not
implement a second platform HTTP client or token exchange.

| Setting | Consumer | Purpose |
| --- | --- | --- |
| `METATABLES_API_URL` | Python client / CLI | Local development only: loopback HTTP(S) base URL, set automatically by `--local` or `configure_local_client()`. Unset/empty resolves the packaged API deployment in the caller's SDK-owned Environment. Hosted URL overrides are rejected. |
| `local_mode_available` in `configuration.yaml` | API / launcher | Enables developer Local/Hosted selection; strict boolean, default false. |
| `runtime_database` in the API's `configuration.yaml` | Hosted API, migration Job, launcher in Hosted mode | Declares the hosted runtime database: engine, the Environment Secret holding its URI, schema and TLS. See [hosted runtime](hosted-runtime.md#declare-the-runtime-database). |
| `serving.concurrency` in `configuration.yaml` | API | T, a strict positive integer, default 20: route threads per process, catalog connections, and connections per database server for caller sessions and table operations. See [pods and connections](hosted-runtime.md#size-pods-and-database-connections). |
| `METATABLES_LOCAL_TOKEN` | Local launcher and client | Private ASCII token of at least 40 characters. |
| `METATABLES_LOCAL_ALLOWED_ORIGINS` | Local API | Comma-separated exact loopback HTTP(S) origins with explicit ports; empty by default. |
| `METATABLES_LOCAL_STORAGE_DIR` | Local API | Directory of the laptop's single local runtime SQLite file, shared by every checkout and branch; defaults to `~/.local/share/metatables`. |

Client discovery uses the name derived from the API automatic-deployment file
and the caller's resolved Organization Environment. Identical names in other
Environments do not require URL configuration or renaming. The cache is scoped
to the platform and Environment and retains only the resolved endpoint
and target identity; `/runtime-context/` continues to supply fresh DataSource
state. See [client connection](../client/installation-and-connection.md).

The supervisor passes listener/token parameters directly to its Local worker
through a private inherited descriptor. `METATABLES_LOCAL_RUNTIME` is
ignored. Deployment configuration is read from `configuration.yaml` in the working
directory, or the explicit `--configuration` path on the launcher/CLI; there is no
environment-variable override for that capability or configuration path. The
migration Job reads `runtime_database` from the API's packaged `configuration.yaml`
instead.

Shared deployments use `local_mode_available: false`; the developer checkout uses
`true`. The launcher always runs Local; see [Local only](local-runtime.md#local-only).

Configure the API’s SDK session for ordinary platform Secret access and supply
the platform's caller-assertion trust configuration, which the SDK request identity
reads ([ADR 0017](../adr/api/0017-hosted-request-identity.md)). Use the SDK's own configuration contract;
MetaTables passes no user-supplied issuer, key URL, or target scope to verification.
The [SDK capability check](../client/installation-and-connection.md) establishes
interface availability, not deployment credentials or network readiness.

The runtime DataSource's database contains the system catalog and application tables.
A hosted deployment declares a PostgreSQL, TimescaleDB, MySQL or SQL Server database
under `runtime_database`, and its migration Job initializes it before each rollout
([hosted runtime](hosted-runtime.md)). Local prefills SQLite and requires explicit
initialization through [Settings](catalog-migrations.md). Local persists the selected
file after activation under `local` in `.local/runtime-data-sources.json`; proposed
configuration stays in API memory until then. Keep this directory private, writable
by the API, and persistent across restarts. Hosted writes no selection file.
Resolved passwords and TLS material remain in memory, never in files.

Separate catalog URLs, physical-file overrides and default-source UID overrides are
retired. Startup never automatically runs Alembic.

Application providers run in their own Python process through the client. Use
`metatables migrations upgrade --provider ledger.migrations:migration` with the
application installed locally. The selected runtime supplies its database connection;
the environment operator configures the login's DDL privileges. Remove the retired
`application_migration_providers` key from existing configuration files. See
[application migrations](../client/define-and-migrate-tables.md).

## Transfer capacity

Transfer contract v1 uses API-owned defaults from `metatables.transfer_contract.DEFAULT_LIMITS`: `serving.concurrency` (T) concurrent data requests per process, each waiting for a slot within its 60 second request deadline, and an 8 MiB serialized response limit. Ingress must admit the documented 12,100,000-byte body limit or clients will encounter the lower proxy limit. More workers multiply admitted concurrency and memory usage. Client budgets can be smaller; they do not enlarge server limits. See [all units and defaults](../client/bounded-transfers.md#discover-limits).

Admitted data requests also share the process's `serving.concurrency` route threads
and database connections with every other request. A request that finds every
connection to its database server busy until its deadline answers 503 with
`database_connections_busy` and `Retry-After: 1`; no statement ran, so it is safe to retry.
