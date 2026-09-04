---
name: static-site
description: Apply the Static Site specialization of the canonical ResourceRelease workflow, including delegated FastAPI preflight and optional authenticated-repository-action-authorized Command Center navigation placement with an exact-commit repository icon.
---

# Main Sequence Static-Site Release

Read `mainsequence://platform/skills/resource-release` first. That skill owns
the shared release discovery, creation, configuration, deployment, and
DeploymentRun workflow. This skill adds only the static-site specialization.

Use the complete, version-matched skill bundle shipped by the CodeRepository's
installed Command Center SDK for frontend implementation.

The MCP server delivers this guidance and approved platform operations. The
calling coding agent owns local repository inspection, dependency management,
source edits, builds, and tests.

## Preserve The Ownership Boundary

This skill owns only:

- discovery of the canonical static-site creation contract;
- static-specific creation and configuration input preparation for an exact
  `CodeRepositoryBranch`; and
- the boundary between platform release behavior and frontend implementation.

The general `resource-release` skill owns the shared `resource_release.list`,
`resource_release.get`, `resource_release.create`, `resource_release.update`,
`resource_release.deploy_current_version`, and DeploymentRun sequence.

The static release UID is its sole public route target. The public location is
tenant-free and has the canonical UID site hostname returned by the backend;
there is no separate release subdomain or caller-selected tenancy route. The
server-owned product namespace is `site-dev` in development and `site`
in production; callers do not select or derive it. Treat `public_url` and
signed launch URLs as opaque values.

All site UIDs in one environment namespace use the same infrastructure-owned
wildcard DNS, TLS certificate, and static gateway. Creating, deploying, or
deleting a release does not create or remove a per-release edge resource. The
gateway resolves the UID through Django, so artifact tenancy remains storage
placement and is not encoded into edge lifecycle.

The gateway selects only the release's ready `active_revision` and that
revision's immutable static deployment. `desired_revision` may be pending or
failed without replacing the serving artifact. Static releases share the
positive release-owned `revision_retention_count` default of `3`; existing
deployment summary fields remain compatibility projections.

This skill does not own:

- frontend architecture or source layout;
- framework-specific application scaffolding;
- resource views, actions, widgets, workspaces, themes, or embeds;
- Command Center SDK contracts or public entrypoints;
- package selection, dependency versions, or package-manager behavior;
- CodeRepository API design or browser authentication; or
- local source edits, builds, tests, Git operations, or credentials.

## Optional Command Center Navigation Placement

When deployment intent includes a Command Center link, use workflow API
`2.2.0` and the backend template's nested `navigation_link` shape. Do not add a
top-level link resource or create a personal link. The exact declaration must
be triggered by an active human User resolved from authenticated repository
action provenance: exact signed provider identity for an ordinary push, or the
canonical default-tag action's short-lived exact branch/tag/commit correlation
for its matching tag webhook delivery; the request must predate delivery receipt
and a later delivery cannot reuse it. The User's current exact-branch and complete
affected-audience permissions must authorize the mutation.

There is no navigation-grant registry or `navigation_link_grant.*` MCP contract.
The Organization automation identity applies workflow state but is not the
authorization principal. The tag correlation is identity evidence, not a grant.
Commit authorship, email, username, uncorrelated bot or deploy-key identity, and
coding-agent identity are not accepted substitutes for authenticated causal evidence.
Placement does not grant target access.

The optional `navigation_link.icon_mask_path` points to the exact event-commit
checkout and never to a local absolute path, URL, branch tip, or runtime image.
It must be a safe forward-slash repository-relative path of at most 1024 UTF-8
bytes, with no empty, `.`, `..`, `.git`, backslash, NUL, or symlink component,
and must resolve to a regular file. Input is at most 512 KiB and must be either
a sanitized basic-geometry SVG with a finite positive square `viewBox`, at
most 256 elements, and at most 16 nesting levels; or a one-frame, static,
square transparent PNG/WebP from 32 x 32 through 512 x 512 pixels inclusive.
Raster input must contain transparent and visible pixels. Scripts, event
handlers, text, style, external references, embedded data, advanced SVG
elements, JPEG, opaque raster, and animation are rejected. Extensions and
media-type labels do not override byte validation.

Omitting `icon_mask_path` preserves the current stored mask, explicit null
removes it, and content-identical sanitized bytes are a digest-aware no-op. Invalid path
syntax blocks workflow validation. A missing, unsafe, unreadable, oversized,
or invalid repository file preserves the prior navigation link and mask and
emits a non-blocking navigation warning while the Static Site deployment
continues. `icon_key` remains required as the loading/error fallback. After the
hard cut clears legacy images, a valid push or redeployment re-resolves and
restores the exact-commit mask.

A navigation authorization failure does not mean the Static Site deployment
failed. Read the workflow result and correlated DeploymentRun warning. A
malformed `navigation_link` block still invalidates the workflow file.

A CodeRepository Blueprint may record why a static site exists and its deployment
intent, but a Blueprint is not a DRF or MCP precondition for creating a static
release.

## Use The Installed Command Center SDK Skill Bundle

Before implementing or changing the frontend:

1. Use the GitHub repository binding root as the canonical Vite application root. Keep
   `package.json`, `package-lock.json`, `.agents/`, `src/`, and `dist/` under
   that root; do not create or discover a nested `frontend/` repository.
2. Resolve the CodeRepository's installed
   `@dev-mainsequence/command-center-sdk` package.
3. Read that installed package's version, `package.json`, README, public export
   map, and declarations relevant to the work.
4. Verify that its complete version-matched skill bundle is installed under
   `.agents/skills/command-center/` and that `PINNED_FROM.txt` identifies the
   installed package version.
5. If the dependency is installed but its skills are missing or stale, use the
   package's canonical installer rather than copying individual skills. The
   currently documented explicit command is:

   ```bash
   npx command-center-sdk skills install --path .
   ```

6. Start with the installed `use-command-center-sdk` skill and use the
   applicable installed skills for surface selection, resources, views,
   actions, widgets, workspaces, themes, embeds, SDK extension, contract
   evolution, and verification.

The installed SDK version is authoritative for frontend behavior. Do not use
this MCP skill as a substitute for those skills, summarize their contracts
here, or assume that every static site uses every SDK capability. The local
coding agent, not MCP, installs dependencies and refreshes CodeRepository skills.

## Use Narrow FastAPI Delegation When The Site Calls An API

When a static site must call a platform FastAPI ResourceRelease, use the
supported integration documented by the installed Command Center SDK skill
bundle. That integration may consume Django's existing delegated exchange:

```text
GET /api/v1/resource-releases/<fastapi_release_uid>/exchange-launch/
    ?static_site_release_uid=<static_site_release_uid>
```

The backend response supplies the exact `rpc_url` and a maximum-five-minute
credential bound to this source StaticSiteRelease, its backend-derived origin,
the authenticated user, and the exact FastAPI target. application code must not
receive, store, or forward the user's general platform JWT. Treat the delegated
credential and `rpc_url` as opaque, short-lived values; do not decode them or
derive a target host.

The returned `rpc_url` is the existing stable target-release URL. The backend
requires and routes through the FastAPI release's ready `active_revision`; the
frontend never chooses a revision, deployment attempt, provider endpoint,
logical binding key, or browser-build release-identity variable. A new API
deployment changes serving state behind the same URL without rebuilding the
static site.

The target FastAPI release must allow the site's exact origin, or a supported
one-label wildcard that covers it, through `cors_allowed_origins`. CORS alone
does not grant access. Django also rechecks the current user, both releases,
same-Organization ownership, release serving state, exact request Origin,
target identity, permissions, and target CORS policy on every delegated
request. A source and target may belong to different CodeRepositories, CodeRepositoryBranches,
or OrganizationEnvironments; do not infer co-location. Both releases
must belong to the same Organization.

Preflight this before frontend work: retrieve the exact target with
`resource_release.get`, read its persisted `cors_allowed_origins`, and compare
it with the source release's backend-returned `public_url`. FastAPI creation
normally persists the active platform static-site wildcard (`site-dev` in
development and `site` in production). Do not infer that platform deployment
environment from an Organization Environment.

If exchange returns `403` with `code=origin_not_allowed`, treat it as target
FastAPI policy mismatch. Correct the target through `resource_release.update`,
verify it with another get, redeploy it through
`resource_release.deploy_current_version`, and observe the DeploymentRun before
retrying browser preflight. application code never submits an origin to Django and
never writes the reserved `FASTAPI_CORS_ALLOW_ORIGINS` runtime setting.

This skill records only the platform boundary. Read the installed Command
Center SDK skills for the actual frontend API and transport; do not reproduce
that SDK's message protocol here.

## Discover The Canonical Release Contract

Call `resource_release.static_site_capabilities` before creating a static
release. Pass `code_repository_branch_uid` when the target CodeRepositoryBranch is known so
the canonical creation form can return that default.

Treat the returned DRF fields, requiredness, defaults, choices, conditions,
constraints, and help text as authoritative. Do not infer them from this skill,
an older CodeRepository, framework documentation, or the installed Command Center
SDK.

The advertised nested `automatic_redeployment_policy.tag_regex` is the only
promotion rule. Omit the policy to persist stable SemVer on `main` or
branch-qualified SemVer on another branch, or send explicit null for every
synchronized commit. Do not send a flat regex, `trigger_mode`, `rule_type`, or
another legacy policy shape, and do not evaluate Git refs in the client.

The capability operation is read-only. It does not inspect the local
repository, test infrastructure readiness, or guarantee that a later create or
deployment will succeed.

The release create/update operation accepts `revision_retention_count` even
though the frozen static capability field catalog cannot yet advertise its
integer discriminator without separately approved contract evolution.

## Prepare Only Canonical Release Inputs

Use the capability response to confirm that the repository implementation can
produce the advertised static output from the selected `root_directory`.

Do not impose a fixed application source tree, filenames, TypeScript policy,
test framework, or extra package scripts. The platform owns only the build and
output behavior advertised by the canonical capability response. Frontend
implementation choices belong to the installed Command Center SDK skills and
the repository.

Build environment values are public browser build inputs, not secret storage.
Send only accepted keys and values. Do not submit platform-reserved keys, and
do not place credentials or secret values into the browser bundle.

## Prepare Static Release Creation

When the user requests creation:

1. Read `resource_release.static_site_capabilities` again.
2. Build `resource_release.create` input using only the currently advertised
   fields.
3. Set `release_kind` to `static_site`.
4. Set `code_repository_branch_uid` to the public UID of the exact CodeRepositoryBranch that
   owns the source branch and current commit.
5. Set `name` to the requested human-facing release name.
6. Include optional configuration only when it is supported by the capability
   response and required by the accepted release intent.
7. Hand the exact request to the general Resource Release workflow and call
   `resource_release.create` once.

Creation uses the canonical DRF authorization, validation, configuration, and
asynchronous deployment behavior. Do not substitute the CodeRepository UID
for `code_repository_branch_uid`. Do not automatically retry an ambiguous create
result.

## Configure, Deploy, And Observe

Use `resource_release.update` only with fields advertised by the live
capability response. The update changes static configuration and does not
deploy it. Treat `build_environment` as a complete write-only browser-build
map and never put secret material in it.

Follow the general Resource Release skill for explicit deployment, ambiguous
result handling, and `deployment_run.list/get` observation. Static deployment
history uses `target_type=static_site`.

Static build attempts expose the complete declared build pipeline under
`pipeline.steps`; explicit activation/rollback attempts use the shorter
`static_site.deploy` pipeline. Determine which workflow ran from
`pipeline.key`, not from a phase string or the presence of only observed
steps.

Call `resource_release.deploy_current_version` only for an existing release
when deployment is requested. It deploys the CodeRepositoryBranch's persisted current
commit through the canonical DRF action. Before materializing site source, the
backend proves that full commit is reachable from the exact CodeRepositoryBranch ref
and produces a normalized checksummed archive; it does not accept a commit
merely because that object exists elsewhere in the repository. Do not
automatically retry an ambiguous deployment result.

## Stop Conditions

Stop and ask for direction when:

- the target CodeRepositoryBranch cannot be identified by public UID;
- the requested release field, framework, routing behavior, or build input is
  not advertised by `resource_release.static_site_capabilities`;
- the local frontend cannot produce the advertised output;
- a build input would expose a credential or secret in browser assets;
- creation or deployment has an ambiguous result that must be inspected before
  another mutation; or
- the requested work requires changing a Command Center SDK or DRF contract
  rather than consuming its current public surface.
