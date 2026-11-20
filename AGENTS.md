# AGENTS.md

**never run .venv/bin/msm copy-msm-skills --path . in this project **

## Project-Specific Instructions

- This project does not use `.agents/brief.md`, `.agents/status.md`, `.agents/tasks.md`, or
  `.agents/record.md`.
- Do not expect, create, update, or report missing project-state files under `.agents/`.
- Use repository documentation, tests, git state, task context, and verified platform evidence for
  status and handoff information. The `.agents/` directory is reserved for managed skills and
  explicitly documented tooling configuration.
- Work on `development` or on feature branches merged into it. `main` is protected and changes
  only through a merge-commit pull request from `development`; every merge into `main` publishes
  the declared version to PyPI. Never push to `main` or push `v*` tags. See `docs/releasing.md`.
- Tests live under the package they exercise: `tests/msm`, `tests/msm_portfolios`,
  `tests/msm_pricing`, `tests/msm_migrations`, `tests/msm_cli`, `tests/apps`, and
  `tests/identity` for identities and renames across packages. A package's tests import only
  the packages it depends on (`tests/packaging/test_import_boundaries.py`); shared helpers live
  in `tests/support`, and no test module imports another. Run only the tests for what you
  changed, as `docs/testing.md` lists; never the whole suite locally. CI runs it on every pull
  request and push.
- Main Sequence SDK guidance is in `.agents/skills/mainsequence/` (start with
  `sdk_code_repository_execution/SKILL.md`) and MetaTables client guidance in
  `.agents/skills/metatables/`; both are copies of the installed packages' skills.
  `.agents/skills/ms_markets/` is this package's own guidance, shipped in the wheel.
