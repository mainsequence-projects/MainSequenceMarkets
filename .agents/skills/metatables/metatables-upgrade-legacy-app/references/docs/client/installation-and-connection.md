# Install and connect

MetaTables requires Python 3.13 or newer. Its PyPI distribution is named
`mainsequence-metatable`; Python imports and the CLI are named `metatables`.
The distribution installs both the
`metatables` Python client and the API's `api` package. Using a remote API does not
require running another service locally.

## Install and start locally

Install in your application's Python environment on macOS or Linux:

```bash
python -m pip install "mainsequence-metatable==0.1.8" "mainsequence[server]==9.0.4"
mainsequence login
metatables init --local
metatables serve --local --admin
```

Run from an application Git checkout with a commit and an `origin` remote. Python
3.13+ is required. Admin also needs Node.js 22.12+ (or 20.19+) and npm. The package
requires published `mainsequence[server]>=9.0.4,<10`; no SDK checkout is needed.
The next stable release is MetaTables 0.1.8, paired with published SDK 9.0.4.
The pinned command above applies after that stable release is published; before
then, install the exact `0.1.8.devN` artifact produced by the development publishing
workflow alongside `mainsequence[server]==9.0.4`. SDK 8 is outside this release's
dependency range.
`python -m metatables.sdk_compat` checks the required SDK interfaces without network
requests. Local SQLite uses the standard library driver.

The CLI starts the installed API on `127.0.0.1:18473`, runs Admin's existing Vite
development server on `127.0.0.1:19473`, and opens Admin after readiness. It installs
the pinned Admin source only if absent and reuses completed Node dependencies.
The source is shared across projects in the OS user-data directory. Source and npm
completion are recorded separately, so retrying failed npm installation does not
download the source again. Use `--no-open-browser` to keep the browser closed.

Admin's GitHub repository currently requires access. The installer tries anonymous
HTTPS first and can use an existing authenticated `gh` session. Alternatively,
prepare an existing checkout with `npm ci` and pass `--admin-path /path/to/MetaTablesAdmin`.
This option preserves its source and dependencies. The launcher does not change
repository visibility. `metatables admin repair` explicitly reinstalls the pinned
revision and refuses to replace an installation used by a running launcher.

For API-only development, omit `--admin`. Set alternate ports with `--port` and
`--admin-port`. `init` preserves existing configuration; startup never migrates a
database. In another terminal in the same project:

```bash
metatables --local runtime status
metatables --local runtime initialize
metatables --local meta-table list
```

Global `--local` selects the project's private, live connection. A missing or
stale connection fails locally. It never falls back to hosted discovery. The
launcher generates the token and removes its connection file on exit. Python
clients select it before using the public resources:

```python
from metatables import configure_local_client
configure_local_client()

from metatables import get_runtime_status
print(get_runtime_status())
```

The API uses your SDK login for identity. Native local requests use the private
launcher token and Git provenance; SDK platform credentials are not redirected to
the local API. See the [complete write/read example](../examples/local_app/README.md)
and [runtime guide](../operations/local-runtime.md) for explicit initialization,
application migrations, persistence and credentials.

## Copy client skills into an application

After installing MetaTables, explicitly copy its five client usage skills into a
consuming project:

```bash
metatables copy-metatables-skills --path /path/to/application
metatables copy-metatables-skills --path /path/to/application --dry-run
metatables --json copy-metatables-skills --path /path/to/application
```

`--path` defaults to the current directory. This command uses the SDK's
`copy_scaffold_skills` helper and needs no login or running API. Importing
`metatables` does not copy skills.

The destination is `<application>/.agents/skills/metatables/`. It contains the
local development, table, application migration, time-index updater and legacy
application upgrade skills, with matching
guide/example snapshots in each skill's `references/` folder. The installed client
version is recorded in `PINNED_FROM.txt`. Skills for API implementation or
MetaTables project development are outside this bundle.

Use `metatables-upgrade-legacy-app` when replacing older MainSequence/MetaTables
imports, declared SQL scopes or API-owned application migration setup. The
[legacy application upgrade guide](upgrade-legacy-app.md) explains the current
DataSource contract and includes before/after repository compiler examples.

Use `metatables-local-development` to guide application work from local setup
through verification and an explicit return to the intended environment. It
checks actual runtime mode and DataSource before test writes, keeps fixtures in
local SQLite, and distinguishes passing local tests from verification of an
engine-specific feature. Switching runtimes never promotes local data.

Rerunning the command replaces matching skill folders, including local edits to
those folders, and preserves unrelated skill folders and namespaces. Use
`--dry-run` to inspect the selected folders without writing to the application.
Run this command against a consuming project outside the MetaTables source
checkout. After upgrading the client, rerun it to refresh the copied bundle.

## Connect to an API

Authenticate through the SDK. Hosted connections require no API URL. The client
reads the API deployment name from the workflow bundled with MetaTables and
selects exactly one release in the caller's resolved Organization Environment.
The SDK obtains that Environment from the registered consuming branch or the
authenticated runtime credential. This also applies when running on a developer
machine and connecting to a hosted API. The endpoint is cached per platform and
Environment in this process:

```bash
mainsequence login
unset METATABLES_API_URL
metatables --json meta-table detail TABLE_UID
```

`METATABLES_API_URL` is only for a local development API on `localhost` or a
loopback IP address. `--local` and `configure_local_client()` set it automatically
from the launcher's private connection file. A manual local URL overrides
discovery, including an already cached deployment, and can include a path prefix:

```bash
export METATABLES_API_URL=http://127.0.0.1:18473
```

The name comes from `.mainsequence/workflows/metatables-api.yaml` in the
MetaTables repository, packaged unchanged with installed clients. No deployment
UID or name variable is needed in consuming projects. Missing or ambiguous
deployments **within the selected Environment** fail clearly. The same name in
other Environments is expected and requires no configuration. A lone deployment
in another Environment is never used as a fallback. Apply the workflow in the
intended Environment before using hosted discovery;
having the Python package installed does not create a deployment.

Remove existing hosted `METATABLES_API_URL` values; non-loopback overrides are
rejected. If the SDK cannot resolve the caller's Environment, fix the consuming
branch registration or runtime context. If no deployment matches, apply the API
workflow in that Environment; if several match within it, remove the duplicates.
Discovery also requires authorized SDK reads of the candidate releases' owning
branch metadata to verify their Environments.

Call `metatables.endpoint.reset_api_endpoint()` or restart the process to resolve
again. This rereads the workflow in editable installs; a wheel uses its packaged
snapshot. Renamed deployment declarations require the matching package build.
See [client ADR 0003](../adr/client/0003-api-endpoint-resolution.md).

The client uses SDK-issued release access for automatically discovered deployments,
separate from the platform session. SDK request handling renews rejected release
credentials for the same target without repeating name discovery. Local URLs
retain the existing SDK session behavior. The
platform ingress supplies the caller proof consumed by the API. Direct callers
cannot replace that proof with an unsigned user UID.

For a local API, use `metatables --local …` or `configure_local_client()` as shown
above. The private token is sent only to the selected loopback HTTP target.
Git source facts remain required; platform branch registration is unnecessary.

## Keep the scopes explicit

Use SDK configuration for platform authentication and repository identity. Use
Environment-scoped discovery for hosted table operations and the local development
connection for a local API. The API selects the effective DataSource. The client discovers its storage capabilities and
dialect through `/runtime-context/`. Never point the SDK session
at the MetaTables URL to make table requests work.

## Response and DataSource compatibility

MetaTables responses contain resource and DataSource identity without platform
Environment or generic scope fields. Local runtime context carries Git provenance
for workspace validation. Update response consumers
together with the API and client.

`metatables.DataSource` registers and manages sources through this API and provides
table operations. Connection configuration references ordinary platform Secrets
by UID; the API resolves their values through the SDK. See [DataSources](../concepts/data-sources.md).
Earlier development databases require [recreation from the current baseline](../operations/catalog-migrations.md#development-schema-baseline).

## Transfer contract upgrades

Deploy catalog migration `0008_upload_receipts` and the matching API before updating writers. Receipt support is negotiated through transfer contract version 1; the development package version alone does not establish server support. See [compatibility and changed failure behavior](bounded-transfers.md#retries-and-compatibility).
