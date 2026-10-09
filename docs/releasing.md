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

### MetaTables access in each Environment

!!! warning "Required in every Environment"
    An Organization admin must run `scripts/bootstrap_metatables_access.py` for an
    Environment before ms-markets can be deployed there. Without it:

    - the `migrate-markets` Job fails, for example with
      `422 MetaTable is not editable` or
      `Writer access to the destination namespace is required`;
    - the API rollout is blocked and no release becomes active.

    Run it before the first deployment to a new Environment, and again whenever
    the platform recreates the Job or the release.

The `migrate-markets` Job and the `markets-api` release run as their own workload
Users, which start with no grants. The workflow gives both `view` on the MetaTables
repository (`access.branches`), so they can find the Environment's MetaTables API.
A workflow cannot grant MetaTables table access, so an Organization admin runs
`scripts/bootstrap_metatables_access.py` once per Environment. Run it from a
checkout of the branch deployed there: `development` for the development
Environment, `main` for Production.

```bash
uv run --frozen --all-extras python -m scripts.bootstrap_metatables_access --dry-run
uv run --frozen --all-extras python -m scripts.bootstrap_metatables_access
```

The script names the Team after the checkout's Environment (`ms-markets-development`,
`ms-markets-production`). It:

- creates the Team if it doesn't exist;
- adds the workload Users of the Job and release declared in the workflow;
- creates the `mainsequence.markets` namespace if it is missing;
- grants the Team Writer on the namespace.

Tables in that namespace inherit the grant, including the ones the migration
registers later. Once `msm.alembic_version` is registered, the script checks each
workload User's effective access to it.

Re-running the script changes only what is missing. Run it again whenever the
platform recreates the Job or the release, because the new workload User is not
in the Team.

A workload User exists only after the workload's first deployment. In an
Environment where the Job has not run yet:

1. Run the script, then push. The Job's first run fails, because its workload User
   is not in the Team yet.
2. Run the script again.
3. Run the Job with `mainsequence code-repository jobs run <JOB_UID>`.

The API rolls out on the next push to the branch, because the CLI cannot retry a
blocked deployment.

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
