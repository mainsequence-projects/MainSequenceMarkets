# ADR 0039: SDK 8 Hard Cut And 1.0 Package Contract

## Status

Accepted and implemented for `ms-markets` 1.0.1.

## Context

Main Sequence SDK 8 completed two incompatible platform transitions. The data
surface uses the time-index-table updater API, configuration schema version 2,
canonical dependency actions, and read-only table references. The source and
deployment surface replaces the legacy Project and ProjectBranch ontology with
CodeRepository, CodeRepositoryBranch, and GitHubRepositoryBinding.

SDK 8 and earlier SDK/backend contracts cannot safely share one runtime. Local
aliases, mixed configuration formats, or legacy repository fields would hide an
invalid deployment. At the same time, an exact SDK patch pin would block later
compatible fixes from reaching library consumers and deployment builds.

## Decision

- `ms-markets` 1.x requires `mainsequence>=8.0.4` without an exact SDK patch
  pin.
- SDK 6 and SDK 7 are unsupported. The library provides no fallback imports,
  aliases, runtime converters, dual configuration formats, or legacy CLI
  behavior.
- `8.0.4` is the minimum because it includes the canonical
  `code_repository_context` runtime documentation and the backend response
  alignment from the initial SDK 8 patches.
- The repository lock and exported deployment requirements select the exact SDK
  patch validated for project builds, while published wheel metadata permits
  later compatible SDK fixes.
- The hard cut is released as `ms-markets` 1.0.1 because it is a breaking public
  dependency and runtime contract.

## Consequences

- Installers reject SDK 6 and SDK 7 before importing or running project code.
- SDK patch and later releases can be adopted without a new `ms-markets`
  release unless this library itself needs changes.
- Active documentation and automation use `code-repository` CLI commands and
  canonical CodeRepository terminology.
- Existing SDK 6 or SDK 7 projects must remain on an older `ms-markets` release
  or migrate their backend and project code before installing 1.x.
- No database schema migration is introduced by this package-version decision;
  updater hashes already rotated under configuration schema version 2.
