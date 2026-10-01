# Publishing MetaTables

The PyPI distribution is **`mainsequence-metatable`**. Python imports and the
command remain `metatables`. This repository uses the SDK's branch-based release
process: development pushes publish development builds; merges into `main`
publish stable builds. No manual upload or manually pushed release tag is needed.

## Branches and versions

| Branch | Purpose | Publication |
| --- | --- | --- |
| Feature branches | Reviewed implementation work | None |
| `development` | Integration and the next planned release | `X.Y.Z.devN` on each push |
| `main` | Stable releases, through pull requests | `X.Y.Z` on each merge |

`pyproject.toml` declares the next final version, initially `0.1.0`. The
development publisher appends `.devN`, using its GitHub workflow run number.
The edit is temporary and is never committed. PyPI is consulted to refuse used
versions, including yanked releases; it does not select the release number.
The first release works even when the project has no PyPI release history.

After publication, users install a stable release with:

```bash
python -m pip install mainsequence-metatable
```

Development releases are selected explicitly:

```bash
python -m pip install --pre mainsequence-metatable
```

## Release prerequisites

MetaTables and the Main Sequence SDK use the MIT License. Package metadata
declares `MIT`, and the license text is included in both the wheel and source
distribution.

CI installs dependencies from `uv.lock` and PyPI. An editable SDK checkout cannot
substitute for the published SDK in a release. The selected SDK artifact must
provide ordinary `Secret.get_by_uid`, independent Git source context, and
`CallerAssertionVerifier.from_environment` through its `server` extra.

The next MetaTables stable release is `0.1.5`; its supported SDK range is
`mainsequence[server]>=9.0.1,<10`. Development builds use `0.1.5.devN`.
The minimum and lockfile now select published SDK `9.0.1`, which supplies those
interfaces. Runtime compatibility is verified manually with the published artifact;
package/static CI does not establish runtime compatibility. When changing the SDK
minimum, update it in `pyproject.toml`, then run:

```bash
uv lock --upgrade-package mainsequence
uv sync --frozen --all-extras
uv run --frozen --all-extras python -m metatables.sdk_compat
```

SDK 9.0.1 upgrade verification used a fresh Python 3.13 environment resolving
the built MetaTables 0.1.4 wheel and the published SDK together with their declared
dependencies. The SDK capability check and installed-wheel tests passed, including
approved application migrations over loopback HTTP, tutorial updaters and readers,
SQLite persistence across API restart, and copied client skills. These checks
exercise local SQLite; they do not establish hosted deployment or other database
engine compatibility. Each later release still requires its package checks.

The reusable `checks.yml` runs on pull requests and is called by both publishing
workflows. It checks the lockfile, Ruff, the documentation build, distribution
metadata, sources and resources. Feature pushes do not launch a duplicate run.

The full test suite, SDK compatibility, disposable PostgreSQL, all-engine
database contracts and installed-wheel runtime tests run manually and locally,
as described in [Testing](testing.md). GitHub Actions does not start backend
services or run these tests, including during publication.

## GitHub and PyPI setup

The repository is `mainsequence-projects/MetaTables`. Configure these GitHub
environments and their allowed deployment branches:

| Environment | Allowed branch | Workflow |
| --- | --- | --- |
| `pypi` | `main` | `publish-to-pypi.yml` |
| `pypi-development` | `development` | `publish-dev-to-pypi.yml` |
| `github-pages` | `main` | `docs.yml` |

In the PyPI account's [Publishing settings](https://pypi.org/manage/account/publishing/),
both pending trusted publishers for `mainsequence-metatable` are registered
under `JoseMS`, with owner `mainsequence-projects` and repository `MetaTables`:

| Workflow | Environment |
| --- | --- |
| `publish-dev-to-pypi.yml` | `pypi-development` |
| `publish-to-pypi.yml` | `pypi` |

The first publisher used creates the project and becomes an active publisher.
The other pending publisher does **not** become active automatically: after the
first development upload, add `publish-to-pypi.yml` with environment `pypi` in
the project's Publishing settings before the first stable release. Remove its
obsolete pending entry afterward. The workflow filename and environment must
match exactly. Pending publishers do not reserve the package name. This follows
[PyPI's publisher conversion logic](https://github.com/pypi/warehouse/blob/main/warehouse/oidc/views.py).

Trusted publishing uses GitHub OIDC and the PyPA publishing action. No long-lived
PyPI API token is required. See [PyPI's setup documentation](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

Configure `main` to require pull requests and the `Package and static checks`
check. Backend tests are not required GitHub status checks.
Keep force pushes and deletion disabled. `development`
must share history with `main` and accept the release workflow's automatic push.
The `v*` tag rules restrict updates/deletion after creation. Enable GitHub Pages
with GitHub Actions as its deployment source.

The configured Pages site is private and uses
`https://potential-doodle-wn39mnm.pages.github.io/`. Repository visibility and
documentation access follow the existing GitHub organization settings.

## Publishing a stable release

1. Finish changes on `development` and confirm a development build passes CI
   and can be installed from PyPI in a fresh environment. Confirm that the
   project's Publishing settings contain the stable publisher described above.
2. Open a PR from `development` into `main` containing the intended final version
   and its matching lockfile.
3. Merge it with a **merge commit**. Squashing or rebasing breaks the shared
   branch history needed by the automatic merge back to `development`.

The stable workflow runs the shared checks, refuses duplicate versions or a tag
on another commit, builds/verifies the package, and uploads it. After the upload,
separate jobs create `vX.Y.Z` and the GitHub release, deploy the documentation,
and merge the released commit into `development`. If it still declares the
released version, the workflow bumps its patch number and updates `uv.lock`.
That automatic push uses the workflow token and does not trigger another
development publication.

For a minor or major release, declare that version deliberately on
`development` and regenerate its lockfile. Every merge into `main` is a release;
even a documentation-only change there needs an unpublished version.

## Failure recovery

Before upload, failed checks publish nothing. Correct the problem on
`development` and push again. The development publisher can also be dispatched
manually, selecting `development`; each new run gets a new serial. Dispatching
it from another branch publishes nothing.

PyPI accepts each distribution filename once. Do not rerun a complete stable
publication after its upload succeeded. If tagging, documentation, or the next
version job failed afterward, rerun the failed jobs in the same release run.
If upload only partially succeeded, inspect PyPI's uploaded files before
retrying; do not replace existing files or assume a new build is identical.

Resolve a merge-back conflict on `development` while preserving both branch
histories and the intended next version. Then regenerate the lockfile and run
the shared checks. The documentation workflow can be dispatched from `main`
to recover its deployment independently.
