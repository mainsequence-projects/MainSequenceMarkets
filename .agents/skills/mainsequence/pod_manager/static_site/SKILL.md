---
name: static-site
description: Create, deploy, and inspect a Main Sequence static-site ResourceRelease through the canonical platform operations. Use after a project frontend exists or when an agent must discover the current static-site release fields, create the release for a ProjectBranch, deploy its current commit, or inspect deployment state.
---

# Main Sequence Static-Site Release

Use Main Sequence MCP for the platform release workflow. Use the complete,
version-matched skill bundle shipped by the project's installed Command Center
SDK for frontend implementation.

The MCP server delivers this guidance and approved platform operations. The
calling coding agent owns local repository inspection, dependency management,
source edits, builds, and tests.

## Preserve The Ownership Boundary

This skill owns only:

- discovery of the canonical static-site creation contract;
- creation of a static `ResourceRelease` for an existing `ProjectBranch`;
- explicit deployment of the current ProjectBranch commit; and
- observation of release and deployment state.

This skill does not own:

- frontend architecture or source layout;
- framework-specific application scaffolding;
- resource views, actions, widgets, workspaces, themes, or embeds;
- Command Center SDK contracts or public entrypoints;
- package selection, dependency versions, or package-manager behavior;
- project API design or browser authentication; or
- local source edits, builds, tests, Git operations, or credentials.

A Project Blueprint may record why a static site exists and its deployment
intent, but a Blueprint is not a DRF or MCP precondition for creating a static
release.

## Use The Installed Command Center SDK Skill Bundle

Before implementing or changing the frontend:

1. Resolve the project's installed
   `@dev-mainsequence/command-center-sdk` package.
2. Read that installed package's version, `package.json`, README, public export
   map, and declarations relevant to the work.
3. Verify that its complete version-matched skill bundle is installed under
   `.agents/skills/command-center/` and that `PINNED_FROM.txt` identifies the
   installed package version.
4. If the dependency is installed but its skills are missing or stale, use the
   package's canonical installer rather than copying individual skills. The
   currently documented explicit command is:

   ```bash
   npx command-center-sdk skills install --path .
   ```

5. Start with the installed `use-command-center-sdk` skill and use the
   applicable installed skills for surface selection, resources, views,
   actions, widgets, workspaces, themes, embeds, SDK extension, contract
   evolution, and verification.

The installed SDK version is authoritative for frontend behavior. Do not use
this MCP skill as a substitute for those skills, summarize their contracts
here, or assume that every static site uses every SDK capability. The local
coding agent, not MCP, installs dependencies and refreshes project skills.

## Discover The Canonical Release Contract

Call `resource_release.static_site_capabilities` before creating a static
release. Pass `project_branch_uid` when the target ProjectBranch is known so
the canonical creation form can return that default.

Treat the returned DRF fields, requiredness, defaults, choices, conditions,
constraints, and help text as authoritative. Do not infer them from this skill,
an older project, framework documentation, or the installed Command Center
SDK.

The capability operation is read-only. It does not inspect the local
repository, test infrastructure readiness, or guarantee that a later create or
deployment will succeed.

## Prepare Only Canonical Release Inputs

Use the capability response to confirm that the repository implementation can
produce the advertised static output from the selected `root_directory`.

Do not impose a fixed application source tree, filenames, TypeScript policy,
test framework, or extra package scripts. The platform owns only the build and
output behavior advertised by the canonical capability response. Frontend
implementation choices belong to the installed Command Center SDK skills and
the project.

Build environment values are public browser build inputs, not secret storage.
Send only accepted keys and values. Do not submit platform-reserved keys, and
do not place credentials or secret values into the browser bundle.

## Create The Static Release

When the user requests creation:

1. Read `resource_release.static_site_capabilities` again.
2. Build `resource_release.create` input using only the currently advertised
   fields.
3. Set `release_kind` to `static_site`.
4. Set `project_branch_uid` to the public UID of the exact ProjectBranch that
   owns the source branch and current commit.
5. Set `name` to the requested human-facing release name.
6. Include optional configuration only when it is supported by the capability
   response and required by the accepted release intent.
7. Call `resource_release.create` once.

Creation uses the canonical DRF authorization, validation, configuration, and
asynchronous deployment behavior. Do not substitute the logical Project UID
for `project_branch_uid`. Do not automatically retry an ambiguous create
result.

## Deploy And Observe

Use `resource_release.get` to inspect the release. Use `deployment_run.list`
and `deployment_run.get` for canonical deployment-run state when the relevant
run identity or filters are available.

The initial deployment and later deployments are asynchronous. A queued or
accepted response is not proof that the site is ready or active. Report the
release state and deployment state separately.

Call `resource_release.deploy_current_version` only for an existing release
when deployment is requested. It deploys the ProjectBranch's persisted current
commit through the canonical DRF action. Do not automatically retry an
ambiguous deployment result.

## Stop Conditions

Stop and ask for direction when:

- the target ProjectBranch cannot be identified by public UID;
- the requested release field, framework, routing behavior, or build input is
  not advertised by `resource_release.static_site_capabilities`;
- the local frontend cannot produce the advertised output;
- a build input would expose a credential or secret in browser assets;
- creation or deployment has an ambiguous result that must be inspected before
  another mutation; or
- the requested work requires changing a Command Center SDK or DRF contract
  rather than consuming its current public surface.
