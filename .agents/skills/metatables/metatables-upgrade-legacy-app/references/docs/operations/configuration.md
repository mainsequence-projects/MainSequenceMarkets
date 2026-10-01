# Configuration

Configure platform identity through the Main Sequence SDK. MetaTables does not
implement a second platform HTTP client or token exchange.

| Setting | Consumer | Purpose |
| --- | --- | --- |
| `METATABLES_API_URL` | Python client / CLI | Local development only: loopback HTTP(S) base URL, set automatically by `--local` or `configure_local_client()`. Unset/empty resolves the packaged API deployment in the caller's SDK-owned Environment. Hosted URL overrides are rejected. |
| `local_mode_available` in `configuration.yaml` | API / launcher | Enables developer Local/Hosted selection; strict boolean, default false. |
| `METATABLES_LOCAL_TOKEN` | Local launcher and client | Private ASCII token of at least 40 characters. |
| `METATABLES_LOCAL_ALLOWED_ORIGINS` | Local API | Comma-separated exact loopback HTTP(S) origins with explicit ports; empty by default. |
| `METATABLES_LOCAL_STORAGE_DIR` | Local API | Root for the checkout's local runtime SQLite file, shared across Git branches; defaults to `~/.local/share/metatables`. |

Client discovery uses the name derived from the API automatic-deployment file
and the caller's resolved Organization Environment. Identical names in other
Environments do not require URL configuration or renaming. The cache is scoped
to the platform and Environment and retains only the resolved endpoint
and target identity; `/runtime-context/` continues to supply fresh DataSource
state. See [client connection](../client/installation-and-connection.md).

The supervisor passes runtime mode and listener/token parameters directly to each
worker through a private inherited descriptor. `METATABLES_LOCAL_RUNTIME` is
ignored. Deployment configuration is read from `configuration.yaml` in the working
directory, or the explicit `--configuration` path on the launcher/CLI; there is no
environment-variable override for that capability or configuration path.

A developer's selected mode is persisted separately in ignored
`.local/runtime-selection.json`, only after successful startup. Shared deployments
use `local_mode_available: false`; the developer checkout uses `true`.
See [mode switching](local-runtime.md#switch-modes-in-one-admin-site).

Configure the API’s SDK session for ordinary platform Secret access and supply
trusted caller-verifier settings. Use the SDK's own configuration contract;
MetaTables passes no user-supplied issuer, key URL, or target scope to verification.
The [SDK capability check](../client/installation-and-connection.md) establishes
interface availability, not deployment credentials or network readiness.

Settings configures the complete runtime DataSource. Its database contains the system
catalog and application tables. Local prefills SQLite; hosted accepts PostgreSQL or
TimescaleDB. Both require explicit initialization through [Settings](catalog-migrations.md).
Public source configuration and Secret references are persisted after activation in
`.local/runtime-data-sources.json`; proposed configuration stays in API memory until then.
Keep this directory private, writable by the API, and persistent across deployments.
Resolved passwords and TLS material remain in memory, never in selection files.

Separate catalog URLs, physical-file overrides and default-source UID overrides are
retired. Neither startup nor runtime-mode selection automatically runs Alembic.

Application providers run in their own Python process through the client. Use
`metatables migrations upgrade --provider ledger.migrations:migration` with the
application installed locally. The selected runtime supplies its database connection;
the environment operator configures the login's DDL privileges. Remove the retired
`application_migration_providers` key from existing configuration files. See
[application migrations](../client/define-and-migrate-tables.md).

## Transfer capacity

Transfer contract v1 uses API-owned defaults from `metatables.transfer_contract.DEFAULT_LIMITS`: 8 concurrent data requests per process, 1 second admission wait, 60 second request deadline, and an 8 MiB serialized response limit. Ingress must admit the documented 12,100,000-byte body limit or clients will encounter the lower proxy limit. More workers multiply admitted concurrency and memory usage. Client budgets can be smaller; they do not enlarge server limits. See [all units and defaults](../client/bounded-transfers.md#discover-limits).
