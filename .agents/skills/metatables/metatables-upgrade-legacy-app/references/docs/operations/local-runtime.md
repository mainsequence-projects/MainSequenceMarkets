# Local runtime

Local development uses the same API, client resources, contracts, migrations,
producers and readers as hosted execution. Its runtime DataSource is one persistent
SQLite file containing MetaTables' system tables, credentials and application rows.
All Git branches in the checkout use this same local runtime. Branches do not select
databases. MetaTables owns storage selection; the Main Sequence SDK is unchanged.

## Launch

From your application's Git checkout, using the Python environment containing
MetaTables and your application:

```bash
mainsequence login
metatables init --local
metatables serve --local --admin
```

The combined launcher starts the installed API on `18473` and Admin's existing
Vite development server on `19473`. Admin source and dependencies are prepared
only when missing; see [installation and reuse](../client/installation-and-connection.md).
`serve --local` runs only the API. `--admin-path /path/to/MetaTablesAdmin` selects
an existing checkout with dependencies installed. `--port` and `--admin-port`
select other ports. The local process launcher supports macOS and Linux.

The CLI and VS Code use the same supervisor. VS Code continues to select its
existing Admin checkout. Both `--sdk-session-source` values use the saved session
that `mainsequence login` and the Main Sequence VS Code extension share on this
machine: the API process receives only the backend and reads the session itself.
`vscode` takes the backend from the project's extension-managed `.env`, the
default `cli` from the CLI configuration. On a machine without a saved session,
`vscode` uses the tokens the extension exported into `.env` and `cli` uses
credentials already set in the environment. The launch prints which one it used
(`credentials: saved session` or `credentials: exported tokens`).

In another terminal, use `metatables --local runtime status`. Python applications
call `metatables.configure_local_client()` before client operations. The private
`.local/development-client.json` binds the project, token and live launcher process;
`init` adds `.local/` to `.gitignore`. Stop the launcher with Ctrl-C to stop its
owned services and remove its connection file. A second launcher for the same
project fails without replacing that connection.

The launcher validates a private loopback listener and uses the ordinary SDK login
for user identity and independent Git discovery. Browser writes require the configured
exact loopback origin. Native clients use the private token and their Git descriptor.
A client from another branch or checkout is rejected. The SDK provides developer identity. Local DataSource credentials use the API
CredentialStore without a hosted Secret requirement.

## Initialize explicitly

Open **Settings**, review the prefilled **SQLite file**, and click **Check DataSource**.
For a new workspace, click **Run MetaTables migrations**. The API creates the system
schema and then records this same file as its runtime DataSource. An existing compatible
file can instead be selected with **Use this DataSource**. Both modes follow
[the same bootstrap lifecycle](catalog-migrations.md).

Local launch does **not** run Alembic. Before initialization, Settings and Admin
Data Sources are available. Data Sources shows the configured SQLite file and its
initialization status from `/runtime-context/`; pending migrations do not mean the
connection is unconfigured. Credential-backed source registration requires these system migrations; ordinary
table and update routes also return 503 until initialization.
The same explicit action is available as `metatables --local runtime initialize`.
Apply application providers through the client with
`metatables --local migrations upgrade --provider ledger.migrations:migration`. See the
[write/read example](../examples/local_app/README.md).

## Switch modes in one Admin site

Register a hosted connection under **MetaTables → Data Sources**, then choose Hosted under
**Settings → Runtime mode** and select the registered DataSource. **Switch to Hosted**
stops the old worker before starting the selected mode; it never copies data. A fresh
Hosted runtime can start without a database, so Settings remains available.
Failed worker startup restores the previous worker. Mode selection is recorded in
`.local/runtime-selection.json`; successful DataSource selection is recorded separately
in `.local/runtime-data-sources.json` using public settings and Secret references only.

The API refuses switching or source reconfiguration while other requests, open
migration connections, reserved migrations, unfinished updates or unresolved physical
operations exist. Stale runtime-instance headers are rejected after a transition.
Migration connections use the selected runtime credentials and hold supervised
runtime switching until the client releases them.

`metatables serve --local` starts with Local selected and uses the shared supervisor.
Shared hosted deployments disable local mode. Switching affects the whole API instance.

## Workspace storage

The default file is:

```text
~/.local/share/metatables/<workspace-uid>/metatables.sqlite
```

`METATABLES_LOCAL_STORAGE_DIR` changes the root before workspace selection. Settings
can configure an absolute SQLite file. The default workspace identity uses the
checkout and repository, excluding Git branch, ref and commit. The selected file is
stored under the single `local` entry in `.local/runtime-data-sources.json`. Branch
changes and restarts reuse it, its credentials and its DataSource UID. Git context
still describes the running code; changing that context requires restarting the API.

Existing files retain their paths, storage markers and IDs. A single legacy saved
file is adopted intact and its selection is rewritten to `local`. When multiple
legacy files exist, choose the intended file in Settings; startup does not guess,
merge catalogs or create an empty replacement. Old unselected files are preserved.

The runtime source remains fixed while active. The Data Sources page displays it but
cannot retarget, disable or delete it. Source selection belongs to Settings, where the
complete runtime binding changes together. `METATABLES_CATALOG_DATABASE_URL`,
`METATABLES_LOCAL_TABLES_FILE` and `METATABLES_DATA_SOURCE_UID` cannot select independent
parts of the runtime. Remove these retired settings from launch environments.

Earlier development stores require [recreation from the current baseline](catalog-migrations.md#development-schema-baseline).
Use [Destroy local database](catalog-migrations.md#destroy-a-local-development-database)
in Settings to delete this workspace's current or older local store, then explicitly
run MetaTables migrations. Nothing is deleted automatically during startup or mode changes.
Back up the single database and its workspace marker
together, after stopping writers or using SQLite's backup API.

## SQLite capabilities

SQLite supports ordinary managed/external table workflows, contracts, incremental
updates and governed SQL within its dialect. PostgreSQL-specific SQL, database roles,
Timescale hypertables and policies are unavailable. Select expressions and writes must
use the API-advertised dialect; SQL is not translated between engines.

The SQLite adapter shares the request's transaction for catalog and physical work.
Physical savepoints preserve rollback semantics and avoid two writers competing for
the same file. Application migration connections are blocked; see the
[security boundary](../security/index.md).


## Local credentials

Encrypted credentials remain with their DataSource registrations in the same local
database across branch changes and schema migrations. Bootstrap does not copy
registration metadata from the saved candidate registry into a local catalog.
If an earlier version already created an orphaned credential reference, recover
that specific credential from its original catalog or re-enter it through **Edit
source**. Discovery and import report `credential_not_found` with recovery
instructions; a restart alone cannot repair an already missing record.

Catalog revision `0006_local_credentials` adds private credential tables. On an
existing checkout, restart the API and run the pending **MetaTables migrations**
in Settings. Explicit local setup initializes its encryption key. Startup never
migrates the catalog or replaces missing keys. Settings and the registration form
show credential-store readiness from `/runtime-context/`.

The default uses the API account's native keyring: macOS Keychain, Windows
Credential Locker, or Linux Secret Service/KWallet. The corresponding desktop
service must be available. No Null/plaintext keyring fallback is used.

For headless services, CI, or a protected secret volume, select the file provider:

```yaml
local_mode_available: true
local_credentials:
  provider: file
  key_directory: ~/.local/share/metatables/credential-keys
```

Choose a directory outside the checkout. Keys are named `<catalog-uuid>-<key-id>.key`
and contain one Base64-encoded 32-byte key. The API provisions a missing first key
only during explicit initialization. An injected existing key must match the
catalog's authenticated key check. Unix files require API-account ownership and
private permissions; Windows files require restricted ACLs. Symlinks and public
key files are rejected. Keep the directory accessible only to the service account.
Native services and Windows ACL integration must be verified on their host OS.

After migration, explicit admin maintenance uses:

```sh
metatables credentials initialize --database /absolute/path/metatables.sqlite
metatables credentials import-sdk --database /absolute/path/metatables.sqlite
metatables credentials rotate-key rotated-2026 --database /absolute/path/metatables.sqlite
metatables credentials remove-unused CREDENTIAL_UUID --database /absolute/path/metatables.sqlite
```

Pass `--configuration /absolute/path/configuration.yaml` for a different deployment
configuration. These commands require an authenticated platform admin. Import is
only for existing local references from the previous SDK-backed implementation;
it reads the supported SDK in its valid hosted context, preserves UUIDs, validates
affected enabled connections, and commits atomically. It never deletes SDK Secrets.
Entering replacement passwords is an alternative when old Secrets are inaccessible.
There is no automatic lookup fallback or import at startup.

Rotation commits resumable batches (`--batch-size`, default 100) and keeps credential
UUIDs stable. Keep old keys until no current records or retained backups need them.
Back up the encrypted catalog and its original key material separately. Restore
both to recover credentials. Missing/wrong keys are reported and never regenerated.
Plaintext values and key material are never returned by runtime-context or source
responses. Hosted mode continues to use managed Secrets without this local layer.
