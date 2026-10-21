# Releasing ms-markets

The PyPI distribution is **`ms-markets`**. Releases follow the same branch-based
process as MetaTables: development pushes publish development builds; merges into
`main` publish stable builds. No manual upload or manually pushed release tag is
needed, and pushing a `v*` tag publishes nothing.

## Branches and versions

| Branch | Purpose | Publication |
| --- | --- | --- |
| Feature branches | Reviewed implementation work, merged into `development` | None |
| `development` | Integration and the next planned release | `X.Y.Z.devN` on each push |
| `main` | Stable releases, through pull requests from `development` | `X.Y.Z` on each merge |

`pyproject.toml` declares the next final version. The development publisher
appends `.devN`, using its GitHub workflow run number. The edit is temporary and
is never committed. PyPI is consulted to refuse used versions, including yanked
releases; it does not select the release number.

Users install a stable release with:

```bash
python -m pip install ms-markets
```

Development releases are selected explicitly:

```bash
python -m pip install --pre ms-markets
```

A development build still resolves the stable `mainsequence-metatable` range
declared in `pyproject.toml`. Pin a MetaTables development build explicitly when
a change depends on one.

## Checks

The reusable `checks.yml` workflow (check name `Package and static checks`)
runs on every pull request and is called by both publishing workflows. It:

- checks that `uv.lock` matches `pyproject.toml` and installs from it
- runs `ruff check` and `mkdocs build --strict`
- runs the full `pytest` suite, which needs no database or platform services
- builds the wheel and sdist, then runs `scripts/check_distribution_sources.py`
  and `twine check --strict`

The distribution check reads the hatch build configuration: the wheel must hold
exactly the files of the declared packages and the force-included
`.agents/skills/ms_markets` bundle, byte for byte, and the sdist must hold every
declared include path. Every top-level package under `src/` must be listed in
`[tool.hatch.build.targets.wheel] packages`.

Run the same checks locally before pushing:

```bash
uv lock --check
uv sync --frozen --all-extras
uv run --frozen --all-extras ruff check --no-fix .
uv run --frozen --all-extras mkdocs build --strict
uv run --frozen --all-extras pytest -q
rm -rf dist
uv run --frozen --all-extras python -m build
uv run --frozen --all-extras python -m scripts.check_distribution_sources
uv run --frozen --all-extras python -m twine check --strict dist/*
```

hatchling writes `Metadata-Version: 2.5`, which twine 6 rejects; the `dev` extra
therefore requires `twine>=7`.

## GitHub and PyPI setup

The repository is `mainsequence-projects/MainSequenceMarkets`. Its GitHub
environments and allowed deployment branches are:

| Environment | Allowed branch | Workflow |
| --- | --- | --- |
| `pypi` | `main` | `publish-to-pypi.yml` |
| `pypi-development` | `development` | `publish-dev-to-pypi.yml` |
| `github-pages` | `main` | `docs.yml` |

The `ms-markets` project on PyPI needs one trusted publisher per publishing
workflow, with owner `mainsequence-projects` and repository
`MainSequenceMarkets`:

| Workflow | Environment |
| --- | --- |
| `publish-to-pypi.yml` | `pypi` |
| `publish-dev-to-pypi.yml` | `pypi-development` |

Add them in the project's **Manage → Publishing** settings. The workflow
filename and environment must match exactly. Trusted publishing uses GitHub OIDC,
so no long-lived PyPI API token is required.

`main` requires pull requests and the `Package and static checks` check, applies
to administrators, and refuses force pushes and deletion. The repository allows
only merge commits. `development` is not protected: it must share history with
`main` and accept the release workflow's automatic push. A tag ruleset makes
`v*` tags immutable after creation.

## Publishing a stable release

1. Finish changes on `development` and confirm its development build passed and
   installs from PyPI in a fresh environment.
2. On `development`, rename the `## [Unreleased]` section of `CHANGELOG.md` to
   `## [X.Y.Z] - YYYY-MM-DD` for the declared version and start a new empty
   `## [Unreleased]` section above it.
3. Open a pull request from `development` into `main`.
4. Merge it with a **merge commit**. Squashing or rebasing breaks the shared
   branch history needed by the automatic merge back to `development`.

The stable workflow runs the shared checks, refuses an already released version
or a tag on another commit, builds and verifies the package, and uploads it.
After the upload, separate jobs create the `vX.Y.Z` tag and GitHub release,
deploy the documentation, and merge the released commit into `development`. If
`development` still declares the released version, the workflow bumps its patch
number and updates `uv.lock`. That automatic push uses the workflow token and
does not trigger another development publication.

For a minor or major release, declare that version deliberately on `development`
and regenerate the lockfile with `uv lock`. Every merge into `main` is a release:
even a documentation-only change there needs an unpublished version.

## Platform deployment

`.mainsequence/workflows/ms-markets-api.yaml` sets `automatic_deployment: true`
with `tag_regex: null`, so every push to a branch that has a platform release
rebuilds the image, runs the `migrate-markets` Job and redeploys the API. Pushes to
`main` happen only through release merges, so the `main` deployment follows
stable releases.

### Legacy 0017 compatibility

Release 2.2.7 bridges populated PostgreSQL databases at `0017` to `0020` in
place. `0018` and `0019` remain unchanged, and development at either revision
also reaches `0020`. Never reset, downgrade, or stamp a production database to
recover from the retired-history error. See
[the migration guide](knowledge/msm/migrations/index.md) and
[ADR 0046](ADR/0046-legacy-0017-schema-bridge.md).

In addition to the service-free checks, run the original-history regression
against an empty disposable PostgreSQL database on localhost:

```bash
MS_MARKETS_LEGACY_TEST_POSTGRES_URL=postgresql+psycopg2://localhost/markets_migration_test \
  uv run --frozen --all-extras pytest -q tests/msm/maintenance/test_legacy_schema_migration.py
```

Confirm the development migration succeeds and its API remains healthy before
merging into `main`. After the Production workflow, verify the Job's preserved
row counts/checksums and successful catalog finalization, the active API revision,
and delegated requests from both static sites to their own environment APIs.
A failed guard blocks rollout; investigate the drift or overlong values instead
of bypassing the check. The bridge's new revisions are forward-only.


Legacy TimescaleDB finalization also requires the shared **MetaTables API
0.1.34** ownership-before-conversion repair. On TimescaleDB 2.10.2, converting
a populated ordinary table and then reassigning it fails when the API login
lacks `CREATE` on `_timescaledb_internal`. The API now transfers the ordinary
table first, then converts it with `migrate_data`, in one transaction. This
requires no new grant or application revision. If `0020` committed but
finalization failed, deploy the repaired shared API and rerun the hosted Job at
head; keep all existing application data and applied revisions. An already
current development hypertable keeps its owner and rows. This is a server
requirement; the Markets migration client requirement is separate (currently 0.1.51).

FastAPI startup also uses `api_endpoint_scope(discovery_timeout=300)` for its
canonical and pricing runtime attachments. Discovery during shared-API wake or
rollout previously exhausted the ordinary 30-second budget. Attachment errors
still fail startup; the scope ends before normal request serving.

Startup retries the gateway’s explicit `503 authentication_unavailable` response
and temporary MetaTables deployment unavailability within one 300-second budget.
Each attempt performs read-only attachment with a fresh endpoint scope. Authentication
`401`, permission `403`, schema errors, and other server failures propagate immediately;
persistent temporary failures also stop startup. Normal requests do not use this retry.

### Upgrading the migration client

The project requires `mainsequence>=9.0.29,<10` and
`mainsequence-metatable>=0.1.51,<0.2`; `uv.lock` and `requirements.txt` select
`mainsequence` 9.0.30 and `mainsequence-metatable` 0.1.51. Move the SDK and the
client together: MetaTables clients before 0.1.51 fail on SDK 9.0.30, and 0.1.51
itself requires SDK 9.0.29 or later. The SDK floor also excludes 9.0.25 and 9.0.26,
which raise on the request identity's Teams. After changing the dependency, run
`mainsequence code-repository sync --path .`, refresh the MetaTables-owned guidance
with `metatables copy-metatables-skills --path .`, and run the checks above. Keep the
provider identity, version table, and applied revisions unchanged.

The candidate image uses the shared `upgrade_application()` runner and batched
inspections. The Job explicitly wraps the runner in
`api_endpoint_scope(discovery_timeout=300)` for a waking MetaTables API; ordinary
client discovery defaults to 30 seconds. Check that the Environment's MetaTables
deployment is ready before restarting a workflow that failed during discovery.
The updated runner also sends changed, non-empty authored table and column
metadata during finalization, even without a new Alembic revision. That payload
requires the matching MetaTables API; the updated API also fixes SQLite
multi-batch downgrade finalization. The Job enables INFO phase timings and must run even when Alembic is
already at head: catalog reconciliation is not optional. The workflow remains
image → migration Job → API deployment, all from the same candidate image.

Deploy the shared MetaTables API as well to receive its server-side inspection,
unchanged-contract, and startup improvements. A client-only upgrade cannot
change an older deployed API. Verify image preparation, successful migration
finalization, and API rollout separately; a push or an `already current` Alembic
revision alone is not proof of deployment success. See
[Migration diagnostics](knowledge/msm/migrations/index.md#migration-diagnostics-and-repeated-runs).

### MetaTables access in each Environment

The `migrate-markets` Job and the `markets-api` release run as their own workload
Users. The workflow gives both the `reader` policy on the MetaTables branch
(`access.branches`), so they can find the Environment's MetaTables API. Their access
to the ms-markets tables is a MetaTables role on the `mainsequence.markets` namespace
(MetaTables ADR 0024). A role on the namespace covers every table in it, including
tables registered later. Workflow entries don't grant MetaTables roles and workloads
never grant them: the namespace's owners do, in the namespace's **Access** panel of
that Environment's MetaTables Admin or with `grant_role`.

| Principal | Role on `mainsequence.markets` | Why |
| --- | --- | --- |
| `migrate-markets` workload User | `editor` | registers and migrates the ms-markets tables |
| `markets-api` workload User | `data_writer` | reads and writes rows; never migrates, deletes or shares tables |
| a person, or a Team of people only | `owner` | decides who has access; a workload is never an owner |

Without `editor`, the Job's registration fails with `403` `namespace_access_required`
(`table_not_editable` for an existing table), naming its workload User as
`caller_user_uid`; the API rollout is blocked and the previous release keeps serving.
Without a role on the namespace, the API can't attach its tables at startup, so its
rollout fails and only the next push deploys it. A running API whose role is missing
has its MetaTables requests refused; they succeed from the next request after the
grant, with no redeployment.

**Where the namespace exists.** `mainsequence.markets` predates roles in the
development and Production Environments, so no migration creates it there. When
roles arrived, an Organization admin granted it a first owner, and the old Team
Writer binding became `editor` for every member of that Team, `markets-api`
included. The owner keeps the Job's `editor` and lowers the API: grant the API's
workload User `data_writer`, then take it out of the Team that holds `editor`.

**In a new Environment.** Nobody creates the namespace before the push. The first
`migrate-markets` run registers the tables, which creates `mainsequence.markets` and
grants the Job `editor`. The people who manage the Job then manage the namespace's
access: they grant `markets-api` `data_writer`, and `owner` to themselves or to a
Team they belong to, so the namespace keeps an owner when the Job is recreated. The
API's first rollout there fails at startup because it has no role yet; push again
after the grant.

**When the platform recreates the Job or the release**, its new workload User has no
role. With direct bindings, an owner grants the role again; with a Team that holds
the role, add the new workload User to the Team. The Job can then be run again, but a
blocked API rollout resumes only with the next push to the branch.

**Consumers.** An application that uses the ms-markets tables gets its roles in each
Environment from an owner of `mainsequence.markets`:

| Consumer workload | Role |
| --- | --- |
| Migration Job that registers tables in `mainsequence.markets` | `editor` on the namespace |
| Updater producer that writes an ms-markets table | table `editor` on each output table, plus `data_viewer` on the namespace |
| Row writer (assets, OpenFIGI details, categories, calendars, Index rows) | `data_writer` on the namespace |
| Reader | `data_viewer` on the namespace |

Prefer table `editor` for producers: namespace `editor` would also let them delete
every table in the namespace. Grant before the consumer's push when its workload
already exists. A workload the push creates gets its role right after it; if it
attaches ms-markets tables at startup (`msm.start_engine`), its first rollout fails
until then and the next push deploys it. A consumer keeps its own tables in its own
namespace, which its first migration creates.

## Failure recovery

Before upload, failed checks publish nothing. Correct the problem on
`development` and push again. The development publisher can also be dispatched
manually from `development`; each new run gets a new serial. Dispatching it from
another branch publishes nothing.

PyPI accepts each distribution filename once. Do not rerun a complete stable
publication after its upload succeeded. If tagging, documentation, or the
next-version job failed afterward, rerun only the failed jobs in the same run.
If an upload only partially succeeded, inspect PyPI's uploaded files before
retrying; do not replace existing files or assume a new build is identical.

Resolve a merge-back conflict on `development` while preserving both branch
histories and the intended next version, then regenerate the lockfile and run the
checks. The documentation workflow can be dispatched from `main` to recover its
deployment independently.
