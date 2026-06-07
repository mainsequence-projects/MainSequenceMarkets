---
name: library_maintenance
description: Use this skill when making relevant implementation, API, packaging, documentation, example, or tutorial changes in the MainSequence Markets `ms-markets` library. This skill enforces the maintenance workflow that every meaningful change must keep docs, examples, tutorials, changelog, and validation aligned.
---

# Library Maintenance

## Overview

Use this skill to keep `ms-markets` maintainable as the library evolves.

This skill is for:

- implementation changes
- public API changes
- package metadata changes
- documentation changes that affect how users understand the library
- examples and tutorials
- release notes and changelog maintenance
- validation before handing work back

## Core Rule

Do not treat an implementation as complete until the surrounding library assets
are updated:

1. Documentation is updated.
2. An example is added or updated.
3. The tutorial is updated.
4. The changelog is updated when behavior, package surface, docs, examples, or
   user-facing workflows change.
5. Validation has been run and reported.

If one of these items is not appropriate for a specific change, state the reason
explicitly in the final response.

## Maintenance Workflow

### 1. Classify The Change

Before editing, identify the affected concept area:

- `accounts`
- `assets`
- `client`
- `execution`
- `models`
- `platform`
- `portfolios`
- `pricing`
- `repositories`
- `services`
- packaging, docs, examples, skills, or CI

Use the matching package-owned page as the primary documentation anchor:
`docs/knowledge/msm/<concept>/index.md`,
`docs/knowledge/msm_portfolios/<concept>/index.md`, or
`docs/knowledge/msm_pricing/index.md`.

### Asset Extension Naming Standard

When a change extends `AssetTable` through a one-to-one asset detail table, use
the same naming split everywhere:

- Public Pydantic API rows use the domain name users think in:
  `Bond`, `Future`, `CurrencySpot`, `OpenFigiDetails`.
- SQLAlchemy/MetaTable declarations use
  `<Domain>AssetDetailsTable`: `BondAssetDetailsTable`,
  `FutureAssetDetailsTable`, `CurrencySpotAssetDetailsTable`,
  `OpenFigiAssetDetailsTable`.
- MetaTable logical identifiers use the same name without the `Table` suffix:
  `BondAssetDetails`, `FutureAssetDetails`, `CurrencySpotAssetDetails`,
  `OpenFigiAssetDetails`.
- One-to-one asset detail tables use `asset_uid` as the only primary key and as
  the foreign key to `AssetTable.uid`. Do not add a separate detail `uid`.
- Built-in asset type constants use `ASSET_TYPE_<DOMAIN>` in `msm.constants`,
  for example `ASSET_TYPE_BOND` and `ASSET_TYPE_FUTURE`.
- Tests, docs, ADRs, examples, and skills must use the same split: user
  workflows talk about `Bond.upsert(...)` or `Future.upsert(...)`; schema and
  registration text talks about `BondAssetDetailsTable` or
  `FutureAssetDetailsTable`.
- Do not keep legacy aliases or compatibility shims for renamed asset detail
  table classes unless the user explicitly asks for backward compatibility.

If an asset extension does not fit this naming shape, stop and write or update
an ADR before implementation.

### 2. Update Documentation Continuously

For every relevant implementation change, update the closest documentation:

- Concept docs under the owning package namespace, for example
  `docs/knowledge/msm/assets/index.md`,
  `docs/knowledge/msm_portfolios/portfolios/index.md`, or
  `docs/knowledge/msm_pricing/index.md`
- Tutorial docs: `docs/tutorial/index.md` or a new tutorial page wired into
  `mkdocs.yml`
- Public overview: `README.md` when installation, usage, package surface,
  project status, license, or docs map changes
- ADRs: `docs/ADR/` when package boundaries, architecture, migration decisions,
  or long-lived tradeoffs change
- Changelog: `CHANGELOG.md` for user-facing or maintainer-relevant changes

Documentation should explain the new contract or workflow, not just list files.

### 3. Add Or Update An Example

For implementation changes, add or update an example under the owning package
namespace:

- `examples/msm/` for core markets workflows
- `examples/msm/` for account virtual-fund allocation workflows
- `examples/msm_portfolios/` for portfolio construction workflows
- `examples/msm_pricing/` for pricing workflows

Examples should:

- import through public package paths such as `msm`, `msm_portfolios`, or
  `msm_pricing`
- demonstrate the intended workflow end to end where practical
- avoid private internals unless the implementation itself is internal-only
- be small enough to run or inspect quickly

If the change is packaging-only, docs-only, or otherwise has no meaningful code
example, record that exception in the final response.

### 4. Update The Tutorial Critically

The tutorial is not optional for implementation changes. Update
`docs/tutorial/index.md` or add a dedicated tutorial page when the change creates
or changes a user workflow.

Tutorial updates should:

- show the order a user should follow
- use public imports and stable APIs
- connect the feature to the relevant concept docs
- include the example path when an example was added

Do not replace tutorial work with API reference text.

### 5. Keep Navigation Wired

When adding a new doc page, wire it into `mkdocs.yml`. Also update `docs/index.md`
or `README.md` if the page is a new user-facing entry point.

When adding a new package concept, add or update:

- `docs/knowledge/index.md`
- the package-owned concept page under `docs/knowledge/msm/`,
  `docs/knowledge/msm_portfolios/`, or `docs/knowledge/msm_pricing/`
- `mkdocs.yml`

### 6. Validate Before Finishing

Run validation scaled to the change:

- Always run `git diff --check`.
- Run focused Python syntax/import checks for touched Python modules.
- Run focused tests for touched behavior.
- Run `mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site` when docs
  or MkDocs navigation changed.
- Run or at least smoke-check the example when practical.

If a broader test suite fails because of an unrelated dependency or known
environment issue, report the exact failure and the focused checks that passed.

## Final Response Checklist

Include:

- implementation summary
- docs updated
- example added or updated
- tutorial updated
- validation run
- skipped maintenance items with concrete reasons

Keep the response concise, but do not omit skipped items.
