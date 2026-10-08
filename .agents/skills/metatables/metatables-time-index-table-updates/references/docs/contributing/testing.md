# Testing

API, SDK compatibility, database and installed-wheel runtime tests are manual
local checks. CI runs only package validation, lint and the documentation build.

Container database tests run only on an explicit request for the current task.
Routine implementation, fixes, verification, commits and merges do not trigger
Docker builds or the database matrix. Use focused checks without containers by
default; the commands below are available checks, not a checklist to run after
every change.

Install the [compatible published SDK](../client/installation-and-connection.md)
first, then install this project with development and documentation dependencies:

```bash
python -m pip install -e '.[dev,docs]'
python -m metatables.sdk_compat
python -m pytest -q
python -m scripts.check_boundaries
python -m scripts.check_client_api_coverage
python -m scripts.check_docs
python -m scripts.build_reference --check
ruff check --no-fix .
mkdocs build --strict
```

The suite includes contract/domain tests, SQLite catalog tests, API admission and
SDK-adapter tests, client-to-API wire tests, real loopback HTTP tests, provider
scaffold/TLS tests, and executable example tests. Loopback tests need permission
to bind local sockets. Tests inject identity and SDK responses where appropriate;
they do not claim a hosted SDK deployment has been verified.

## Hosted request identity

The `platform_caller_assertions` fixture simulates a hosted deployment's trust
configuration and signs genuine EdDSA caller assertions that the SDK verifies.
`tests/auth/test_request_identity.py` also runs PodDeploymentOrchestrator's
`require_request_identity` and `serve_fastapi` against the deployed entrypoint when
that launcher is importable; otherwise those two tests are skipped:

```bash
PYTHONPATH=/path/to/PodDeploymentOrchestrator/src python -m pytest -q tests/auth/test_request_identity.py
```

The suite removes platform caller-authentication variables inherited from the
shell. These checks do not establish a hosted rollout
([ADR 0017](../adr/api/0017-hosted-request-identity.md)).

## Local CLI workflow

Focused manual checks for ADR 0011:

```bash
python -m pytest -q tests/e2e/test_admin_installation.py tests/e2e/test_local_client_selection.py
METATABLES_TEST_ADMIN_PATH=/path/to/prepared/MetaTablesAdmin python -m pytest -q tests/e2e/test_local_cli_workflow.py
```

The second command starts temporary loopback services with a synthetic SDK identity
and temporary SQLite. It checks API-only and Vite launches, explicit initialization,
approved migrations, writes, reads, restarts, duplicate launch rejection and cleanup.
Without the Admin path, the Vite case is skipped. These checks remain outside CI.
The same test can run in the installed-wheel environment below to exclude checkout
imports and validate the published SDK.

## All database backends

Run `python -m scripts.test_databases` for the local SQLite, PostgreSQL,
TimescaleDB, MySQL and MSSQL suite. The [database matrix guide](database-backends.md)
describes Docker prerequisites, engine subsets, reports and cleanup. This common
API/client contract runs manually in isolated local Compose services, one engine
at a time; skipped contract tests fail the matrix.

## Disposable PostgreSQL

The normal run skips physical PostgreSQL tests unless explicit test URLs are set.
Install PostgreSQL server tools (`initdb`, `pg_ctl`, `createdb`) on `PATH`, then run:

```bash
python -m scripts.test_postgresql -q
```

The runner first checks the installed SDK interfaces, then initializes a new
temporary cluster, binds loopback on an available
port, creates separate `metatables_test_catalog` and `metatables_test_physical`
databases, applies packaged catalog migrations, and runs the full suite. It stops
and removes only that cluster afterward. A startup collision fails the run.
No existing cluster or database is reused.

If supplying your own disposable instance, tests require loopback URLs with those
exact database names in `METATABLES_TEST_CATALOG_URL` and
`METATABLES_TEST_PHYSICAL_URL`. Apply catalog migrations first. Physical tests use
random schemas or explicitly checked example tables and clean up their own
objects. Ordinary PostgreSQL tests do not establish Timescale extension behavior.

## Evidence and examples

The capability inventory lives in `tests/contracts/capabilities.json`. Its checks
compare actual resource methods, exports, CLI visibility, mounted routes, and
referenced behavior tests. A route listing is not a substitute for executing the
test. Signature and database-operation contracts live beside it; documentation is
not used as a test fixture store.

`tests/examples` executes the assets in `src/metatables/examples/`. Contract construction,
bound SQL, incremental frame shape, and SQLite persistence run without an API.
A PostgreSQL example test also creates the authored relations, persists producer
rows, and executes the compiled bound query in the disposable database. Network
workflows still require identity, visible resources, and a matching
physical source; guide prerequisites describe these conditions explicitly.

## Distribution

Build into an empty output directory, then check package contents:

```bash
python -m build
python -m scripts.check_distribution_sources
```

The distribution check requires exactly one wheel and one sdist in `dist/` and
compares packaged Python modules with current source. Also test importing the
wheel in a fresh environment with the compatible published SDK installed, and verify
both catalog migrations and application revision templates are packaged.
The package requires published SDK 9.0.19 or newer within its declared major version.

Run the installed-wheel smoke tests manually from outside the checkout, using a
fresh virtual environment with the compatible SDK and built MetaTables wheel:

```bash
METATABLES_SOURCE_CHECKOUT=/absolute/path/to/MetaTables \
  /absolute/path/to/wheel-venv/bin/python -I -m pytest \
  --rootdir /tmp -c /dev/null -o pythonpath= -q \
  /absolute/path/to/MetaTables/tests/packaging/test_installed_distribution.py
```

The [publishing workflows](releasing.md) run the same package and static checks
as pull requests. Runtime tests, SDK compatibility checks and database services
are excluded from GitHub Actions and required merge checks.

## Shared storage behavior

`tests/e2e/test_sqlite_runtime.py` runs the real client over loopback HTTP against
SQLite, an explicit SQLite file override, and PostgreSQL. Its one tutorial path
covers migrations, producers, reads, API restarts, unique grain, foreign keys, and
tail deletion. Local tests forbid platform DataSource/credential lookup and
PostgreSQL connections. SDK identity and hosted ingress are stubbed at their
boundaries; this does not verify a live platform login or Timescale extensions.

Run `python scripts/test_postgresql.py -q` for the complete suite, including a
disposable local PostgreSQL cluster. SQLite transaction, concurrent-write, type,
and rollback checks live in `tests/integrations/test_sqlite_operations.py`. The
normal suite can run without PostgreSQL, skipping its explicitly provisioned
cases. Real HTTP tests need permission to bind loopback sockets.
