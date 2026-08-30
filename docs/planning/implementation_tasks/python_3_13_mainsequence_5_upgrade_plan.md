# Python 3.13 And MainSequence SDK Upgrade Record

## Status

The original Python 3.13 and MainSequence 5 runtime upgrade was implemented on
2026-07-25. Its dependency policy was superseded by the SDK 8 hard cut on
2026-08-30: `ms-markets` 1.x declares `mainsequence>=8.0.4` without an exact
patch pin, while the repository lock and exported runtime requirements select
MainSequence `8.0.4` as the validated build environment.

Compatibility was established before the original environment rebuild:

- Python `3.13.11` is installed locally;
- the existing dependency graph installed on Python 3.13, including a local
  source build of `psycopg2==2.9.12`;
- the full suite passed on Python 3.13 with MainSequence `4.4.32`:
  `1170 passed, 3 skipped`;
- the official MainSequence `v5.0.0` Git tag requires Python `>=3.13`;
- the full suite also passed on Python 3.13 with that exact SDK tag:
  `1170 passed, 3 skipped`.

The current project `.venv` reports Python `3.13.11` and MainSequence `8.0.4`.
The package metadata excludes SDK 6 and SDK 7 without exact-pinning an SDK
patch, and the lockfile resolves the published `mainsequence==8.0.4`
distribution. There is no machine-local `tool.uv.sources` override, so the same
dependency source is available to local and backend image builds.

Verification evidence from the rebuilt environment:

- `.venv/bin/pytest -q`: `1198 passed, 3 skipped`;
- `.venv/bin/ruff check apps src/cli src/msm src/migrations
  src/msm_portfolios src/msm_pricing examples tests`: passed;
- `.venv/bin/mkdocs build --strict`: passed;
- `uv build`: built the wheel and source distribution;
- locked full-environment audit: no changes required;
- wheel metadata: `Requires-Python: <3.14,>=3.13` and
  `Requires-Dist: mainsequence>=8.0.4`;
- package, native dependency, CLI, and FastAPI application import smoke tests:
  passed.

The current SDK and managed-skill pin both report `8.0.4`. This version uses the
canonical CodeRepository runtime context and retains the complete
time-index-table updater hard cut. The lockfile resolves the published
package-index distribution used by portable builds.

## Success Condition

The upgrade is complete when:

- `ms-markets` declares `>=3.13,<3.14`, with no Python 3.11 or 3.12
  compatibility contract;
- Ruff, CI documentation builds, and package publishing target Python 3.13;
- `mainsequence>=8.0.4` is enforced in the published package contract without
  an exact patch pin, while the lock and exported runtime requirements select
  the verified SDK patch version;
- `uv.lock` resolves only the Python 3.13 project contract;
- the local `.venv` reports Python 3.13 and the current selected MainSequence SDK;
- core, portfolio, pricing, public API, CLI, migration, and documentation
  imports work from the rebuilt environment;
- the complete test suite, scoped Ruff baseline, strict MkDocs build, and
  package build pass;
- built wheel metadata contains `Requires-Python: <3.14,>=3.13` and
  `Requires-Dist: mainsequence>=8.0.4`;
- a fresh locked sync can reproduce the environment from the package index.

No database schema change is required for this runtime upgrade. Applying
MetaTable migrations or deploying a platform release is outside this local
environment task.

## Implementation Phases

### 1. Runtime Contract

- Set `project.requires-python` to `>=3.13,<3.14`.
- Replace the Python 3.11 classifier with Python 3.13.
- Set Ruff's target to `py313`.
- Add `.python-version` with the `3.13` interpreter line.
- Update the README badge and package metadata summary.

Gate: repository search finds no active Python 3.11 or 3.12 runtime target.

### 2. MainSequence SDK And Dependency Lock

- Keep the publishable `mainsequence` dependency on the supported SDK 8 hard
  cut without exact-pinning a patch; select the verified SDK release in
  `uv.lock` and exported runtime requirements.
- Resolve MainSequence from the package index with no machine-local
  `tool.uv.sources` override.
- Regenerate `uv.lock` with Python 3.13.
- Validate the package-index distribution with a frozen full-environment sync.

Gate: uv resolves the selected current MainSequence SDK and all optional
dependency groups for Python 3.13.

### 3. Local Environment Rebuild

Recreate rather than mutate the old Python 3.11 environment:

```bash
uv venv --clear --python 3.13 .venv
uv sync --all-extras --all-groups --locked
```

Then compare `.venv/bin/mainsequence --version` with
`.agents/skills/mainsequence/PINNED_FROM.txt`. Refresh `AGENTS.md` and the
managed Main Sequence skills together when their recorded pin differs. If
authenticated platform-skill retrieval fails, do not retain only half of the
scaffold refresh.

Gate: `.venv/bin/python --version` reports 3.13 and
`.venv/bin/mainsequence --version` matches the managed-skill pin.

### 4. Repository And Distribution Verification

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check apps src/cli src/msm src/migrations src/msm_portfolios src/msm_pricing examples tests
.venv/bin/mkdocs build --strict
uv build
uv sync --all-extras --all-groups --locked --check
```

Also smoke-test:

- `msm`, `msm_portfolios`, and `msm_pricing` imports;
- FastAPI application imports;
- QuantLib, `psycopg2`, NumPy, pandas, SciPy, and scikit-learn imports;
- `mainsequence --version`, `mainsequence --help`, and `msm --help`;
- wheel metadata for the Python and MainSequence requirements.

Gate: all checks pass from the rebuilt `.venv`.

### 5. Release Follow-Up

- Confirm the intended MainSequence release is published to the configured
  package index.
- Remove the temporary local path source override and regenerate the lock from the
  registry.
- Authenticate the CLI and refresh the dual-source managed Main Sequence
  skills so `PINNED_FROM.txt` records the installed SDK version and platform
  resource hashes.
- Build a project image and run a canary job under the platform's Python 3.13
  runtime before a production release.
- Publish `ms-markets` only after registry-only resolution and canary
  verification pass.

## Rollback

This upgrade has no data migration. If a release check fails, restore the
previous package metadata and lockfile, recreate `.venv` from that lock, and do
not publish or deploy the Python 3.13 build. Do not introduce dual-runtime
compatibility branches into application code.
