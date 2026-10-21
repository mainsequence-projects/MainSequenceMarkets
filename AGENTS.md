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
- Main Sequence SDK guidance is in `.agents/skills/mainsequence/` (start with
  `sdk_code_repository_execution/SKILL.md`) and MetaTables client guidance in
  `.agents/skills/metatables/`; both are copies of the installed packages' skills.
  `.agents/skills/ms_markets/` is this package's own guidance, shipped in the wheel.
