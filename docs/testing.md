# Testing

Tests live under the package they exercise, and a change runs only the tests it can
break. CI runs the whole suite on every pull request and on every push to `development`
and `main`; never run the whole suite locally.

## Where tests live

The packages depend on each other in one direction (ADR 0019):

- `msm` imports no other package. The one exception is `msm.migrations`, a
  compatibility alias that re-exports the `msm_migrations` provider.
- `msm_portfolios` and `msm_pricing` import `msm`, and not each other.
- `msm_migrations` imports all three: its registry collects every package's models.
- `msm_cli` imports `msm`.
- `apps` imports `msm`, `msm_portfolios` and `msm_pricing`.

Each test directory may import only what its package depends on:

| Directory | Tests | May import |
|---|---|---|
| `tests/msm` | core markets | `msm` |
| `tests/msm_portfolios` | portfolio construction and accounting | `msm`, `msm_portfolios` |
| `tests/msm_pricing` | pricing | `msm`, `msm_pricing` |
| `tests/msm_migrations` | the migrations and the provider's models | `msm`, `msm_portfolios`, `msm_pricing`, `msm_migrations` |
| `tests/msm_cli` | the `msm` command | `msm`, `msm_cli` |
| `tests/apps` | the FastAPI application and the client against it | `msm`, `msm_portfolios`, `msm_pricing`, `apps` |
| `tests/identity` | identities and renames across packages (ADR 0047, 0048) | every package but `apps` |
| `tests/packaging` | the distribution and the repository layout | anything |

A test that needs two packages lives under the one that depends on the other; a core
test that also checks a portfolio table lives in `tests/msm_portfolios`. A test that
needs both `msm_portfolios` and `msm_pricing` lives in `tests/apps`,
`tests/msm_migrations` or `tests/identity`, whichever it is about.
`tests/packaging/test_import_boundaries.py` enforces the table, and also that each
package's own code imports only what it depends on. Its imports include those of the
`tests.support` modules and `examples` a test uses.

Helpers that more than one test module uses live in `tests/support`; a test module
never imports another test module. Shared fixtures are in `tests/conftest.py`:

- `sqlite_markets`: a copy of a SQLite file migrated to head once per session, served
  by MetaTables' own server code. A module that needs triggers or tables first overrides
  `sqlite_markets_prepare`.
- `sqlite_revisions`: SQLite files migrated from empty to any revision, once per
  session; the migration tests start from them.
- `postgresql_markets`: the disposable PostgreSQL database in
  `MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`; tests that use it are skipped without it.

`tests/apps/conftest.py` holds what only the API needs: the stand-in for the platform
gateway that signs caller assertions, and the `caller_assertions` fixture. A run outside
`tests/apps` does not load the SDK's server modules.

## One test per behaviour

Each behaviour is checked once against a real database: SQLite, through MetaTables' own
server code. A PostgreSQL test checks only what SQLite cannot show: the SQL compiled
for PostgreSQL, its plans, its error text and its size limits. A route test patches the
service it calls and checks the status code, the detail and the arguments it passes; a
Job test does the same with the Job's service. Before adding a test, look for the one
that already checks the behaviour at another layer.

## What to run for a change

Run the tests of the package you changed, and the tests elsewhere that import what you
changed (`git grep -l <module> tests`). The packages that depend on yours are the only
other places to look.

| You changed | Run |
|---|---|
| `src/msm_pricing` | `tests/msm_pricing`, and the files in `tests/apps`, `tests/msm_migrations` and `tests/identity` that import the changed module |
| `src/msm_portfolios` | `tests/msm_portfolios`, and the files in `tests/apps`, `tests/msm_migrations` and `tests/identity` that import the changed module |
| `src/msm` | the files in `tests/msm` for the changed area, and every other test file that imports the changed module |
| `src/msm_migrations` | `tests/msm_migrations`, and the database tests of the tables the revision changes |
| `src/msm_cli` | `tests/msm_cli` |
| `apps` | the files in `tests/apps` for the changed routers and services |
| `jobs`, `examples` | the tests that load or import the changed file (`git grep -l <name> tests`) |
| `tests/support`, `tests/conftest.py` | the tests that use the changed helper or fixture |
| `pyproject.toml`, `uv.lock`, `requirements.txt` | `tests/packaging` |
| Documentation only | `mkdocs build --strict` |

For example:

```bash
uv run --frozen --all-extras pytest -q -n 4 tests/msm_pricing
```

## Parallel runs

Tests run in parallel with pytest-xdist. CI runs the suite with `-n auto --dist worksteal`:
one worker per CPU, and a worker that runs out of tests takes queued ones from a worker
held up by a long test. Locally, pass `-n 4` to a scoped run of more than a few files. A
single file or test runs faster without `-n`, which costs each worker its own start.

Each worker is a separate process, so every test must pass in any order and on any
worker:

- Write files only under `tmp_path` or `tmp_path_factory`; each worker has its own base
  directory. The session-scoped `sqlite_revisions` files are migrated once per worker.
- Change the environment, module attributes and `sys.modules` only through `monkeypatch`,
  so they are put back after the test.
- A module that reads the environment when imported is imported at collection, not first
  inside a test that changes that environment. A test that imports
  `msm_migrations` lives in `tests/msm_migrations`, whose modules import it at collection:
  first imported under another namespace, its migration provider would move every later
  database of that worker into that namespace.
- The PostgreSQL fixtures use a database per worker: `<database>_gw0`, `<database>_gw1`,
  ..., created next to the one their URL variable names
  (`tests/support/postgresql_databases.py`). The PostgreSQL user needs `CREATEDB`, which
  the throwaway container's `postgres` user has.

PostgreSQL-gated tests run only when the change touches PostgreSQL SQL, a migration, or
their fixtures. Run them against one throwaway TimescaleDB container with an empty
`markets_*` database per URL variable they read, and remove the container afterwards.

`tests/msm/repositories/test_postgresql_account_delete_volume.py` measures one account
delete with months of history in the tables (10 accounts of 1,000 holdings sets, their
allocations, targets, orders, trades and events). It prints the time of the read, of each
statement, of the transaction and of MetaTables' statistics rebuild of each table the
transaction locked, and fails when the read and the transaction take 10 s or more. Run it
with `-s` after changing the account delete, its keys or its indexes; seeding takes a
minute or two.
