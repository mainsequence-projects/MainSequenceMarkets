---
name: project-workflows
description: Create and validate backend-managed API 2.1.0 deployment declarations under .mainsequence/workflows, including target-owned environment variables, FastAPI browser origins, and human-authorized Static Site navigation placement.
---

# Main Sequence Project Workflows

Project workflow files are repository-authored deployment configuration. The
backend owns parsing, validation, defaults, permissions, and application.
Clients must not implement a second parser or construct a separate interpreted
deployment payload.

## Procedure

1. Identify the exact `ProjectBranch` public UID.
2. GET `/api/v1/project-branches/{uid}/workflow-template/`.
3. Copy and edit the returned YAML using its advertised `api_version`.
4. POST the proposed `path` and `content` to
   `/api/v1/project-branches/{uid}/validate-workflow/`.
5. Fix every backend validation error before committing.
6. Save the file as a direct `.yaml` or `.yml` child of
   `.mainsequence/workflows/` and commit it.
7. Inspect the repository-event action result and any resulting deployment
   runs. A successful Git commit alone does not prove deployment succeeded.

Repository processing is branch-specific. The event repository, exact
`refs/heads/...` ref, matched ProjectBranch, and full pushed commit must agree.
Project-code images are admitted only after the backend proves that full commit
is reachable from the exact ProjectBranch ref and builds one normalized,
checksummed source archive. A provider build must consume that archive; it does
not clone the repository or choose a branch tip. Any Job or runtime release
deployed from the workflow may attach only a digest-pinned verified image for
the same ProjectBranch and commit. For an automatically managed runtime release,
the backend—not the workflow author—resolves that image after policy eligibility.

Always retrieve a fresh template when the backend's current or supported
versions differ from the document version.

The template also carries the active platform FastAPI browser-origin default.
Development returns `https://*.site-dev.main-sequence.app`; production returns
`https://*.site.main-sequence.app`. Copy the backend-provided value instead of
hard-coding development. This platform deployment environment is not an
`OrganizationEnvironment`.

## Backend-Owned Image Orchestration

The persisted image model is ownership-typed. Platform bases, build tools, and
executor bundles are `PublicCatalogImage` inputs. Project build outputs are
Organization-owned `ProjectJobImage` rows. There is no generic persisted
`Image` resource, manager, UID resolver, or cross-root search. Jobs and
JobRuns use exclusive public/Organization relations while preserving their
documented read-only response projections.

Workflow authors never create build attempts, choose provider operations,
select transient tags, or retry ambiguous submissions. For every image-backed
target, the backend attaches a typed `DeploymentRunImageDependency` to the
parent run and prepares one complete `ProjectImageBuildRun` before contacting
the provider. The database row is the durable queue; Celery only wakes
submission or reconciliation. Concurrent Jobs, ResourceReleases, and Project
Coding Agent stages requesting the same exact build converge on one canonical
attempt while retaining independent parent dependencies.

Active build, deployment, and JobRun relations block image deletion. Terminal
history retains immutable typed image snapshots and may detach its live
relation, so historical evidence never forces an image row to exist forever.

An image UID, URI, digest, provider handle, or readiness value in generic run
JSON is never authoritative. A build uses an attempt-specific transient tag,
not `latest`, and becomes executable only after its relational dependency is
verified with a digest-pinned output. If submission is ambiguous, inspect the
same DeploymentRun; do not call image creation again.

## File Contract

- Every file is independent and requires `api_version`, `name`, and
  `resources`.
- Version `2.1.0` is current and `2.0.0` remains supported. Both support `job`,
  `resource_release`, including `widget_extension`, and
  `project_coding_agent`. Runtime targets may use target-owned `env_vars`.
  Version `2.1.0` additionally accepts approved Static Site
  `navigation_link` placement. Pre-`2.0.0` versions are rejected.
- Each resource has a stable `key`, a supported `kind`, and a typed `spec`.
- `spec` fields follow the canonical backend create/update endpoint contract.
- Every runtime, static-site, or widget-extension `resource_release` spec may
  set positive `revision_retention_count`; omission defaults to `3`. Keep it
  beside `automatic_redeployment`, never inside the tag-promotion policy.
- The validation endpoint is read-only and uses the same validator as
  repository processing.
- Only direct `.yaml` and `.yml` children are processed; nested files and other
  extensions are ignored.

Do not maintain `scheduled_jobs.yaml`; it is not a supported input.

For example:

```yaml
spec:
  release_kind: static_site
  name: Markets
  automatic_redeployment:
    enabled: true
    tag_regex: null
  revision_retention_count: 3
```

The static frontend accesses an API through its stable release URL and the
target's backend-selected `active_revision`; do not add API binding syntax,
revision-selection values, or browser-build release-identity configuration.
An API promotion does not rebuild a consuming static site.

## Runtime Environment Variables

The current API `2.1.0` template returned by
`/api/v1/project-branches/{uid}/workflow-template/` includes `env_vars`
examples. Always preserve that list-of-items shape:

```yaml
env_vars:
  - name: LOG_LEVEL
    value: INFO
  - name: POLL_INTERVAL_SECONDS
    value: "30"
```

`env_vars` is accepted for `job`, runtime `resource_release` kinds, and
`project_coding_agent`. Omission preserves an existing target mapping, an
empty list clears it, and a present non-empty list replaces it. Static sites
reject this field because `build_environment` is their separate build-time
contract. Widget extensions reject both fields because their SDK build profile
is fixed.

These are non-secret literals committed to Git. Never place passwords, API
keys, access tokens, private keys, provider credentials, or signing material
in `env_vars`. The backend rejects reserved runtime identity/authentication
names and warns about suspicious names without echoing values.

The mapping belongs only to the declared Job or to the ResourceRelease/Project
Coding Agent backing Job. Workflow application does not create, resolve,
shadow, update, or delete platform Secrets, Constants, ProjectSecrets, or
Organization Environments, and it does not write ProjectBranch-wide
configuration. Runtime values never become project-image build inputs.

## Static Site Navigation Placement

A `2.1.0` Static Site declaration may propose a managed Command Center link:

```yaml
navigation_link:
  label: Markets
  icon_key: line-chart
  is_enabled: true
  audiences:
    organization_wide: false
    team_uids:
      - "11111111-1111-4111-8111-111111111111"
    user_uids: []
```

The repository and Organization automation identity may propose and apply this
state but cannot authorize its audience. Before committing, inspect the exact
grant with `navigation_link_grant.list` or `navigation_link_grant.get`. If no
active grant covers the requested audience, stop and ask the authenticated
human to authorize it through `navigation_link_grant.create` or expand it
through `navigation_link_grant.update`. Never infer approval from Git author,
Project edit authority, an existing manual link, or the automation identity.

Grant identity is the exact ProjectBranch, workflow path, and resource key.
Humans must select an Organization Environment for list discovery; the grant's
environment is backend-derived from its ProjectBranch. Placement never grants
Static Site access.

Omission preserves the existing workflow-owned link. Explicit
`navigation_link: null` removes it. Missing, insufficient, revoked, or
conflicting authorization blocks only link reconciliation; inspect the
resource result and correlated DeploymentRun for a sanitized
`blocks_deployment=false` warning. Malformed fields are blocking workflow
validation errors.

## When An Image Is Needed

The workflow target and its effective automatic-deployment setting determine
whether the declaration needs an image:

| Workflow target | Effective automatic deployment | Image requirement |
| --- | --- | --- |
| Job | Either | The workflow never accepts an image or commit selector. The backend creates or reuses the exact image identity for the immutable repository-event commit and keeps the Job non-runnable until it is verified and digest-pinned. |
| Static site | Either | No runtime image UID is needed. The backend owns the static-site build. |
| Widget extension | Always enabled | No runtime image or ProjectResource UID is accepted. The backend invokes the fixed SDK widget build through the existing ResourceReleaseRun pipeline. |
| Project Coding Agent | Either | No project-image or Project Executor image UID is needed. The backend builds the verified image chain. |
| Runtime ResourceRelease (`fastapi`, `streamlit_dashboard`, or runtime `agent`) | Enabled | `related_image_uid` is not needed. If present for compatibility, the backend ignores it. |
| Runtime ResourceRelease (`fastapi`, `streamlit_dashboard`, or runtime `agent`) | Disabled | `related_image_uid` is required and selects the explicit verified project image. |

For a workflow runtime release, effective automatic deployment is enabled by
either `automatic_deployment: true` or `automatic_redeployment.enabled: true`.
The direct `resource_release.create` MCP operation has a different initial
deployment contract; read the `resource-release` skill before using it.

## Jobs

Every workflow Job declaration must include explicit future-promotion intent:

```yaml
- key: daily-prices
  kind: job
  spec:
    name: Daily Prices
    execution_path: jobs/daily_prices.py
    cpu_request: "1"
    memory_request: "2"
    max_runtime_seconds: 3600
    automatic_redeployment:
      enabled: true
      tag_regex: null
```

Do not add `related_image_uid`, `project_repo_hash`, or
`project_branch_uid`. The backend owns the exact ProjectBranch and immutable
repository-event commit. On first application it creates or reuses the exact
`ProjectJobImage`, persists the Job pointing to that identity, disables any
schedule until the artifact is ready, and activates only after verified
digest-pinned readiness. This exact initial image is required whether future
automatic redeployment is enabled or disabled.

`automatic_redeployment.enabled` controls only later qualifying immutable
repository events. `tag_regex: null` admits every otherwise-valid event while
enabled; a non-null regex full-matches an exact tag snapshot. It never means
branch HEAD, a registry `latest` tag, an omitted image, or client-side Git
selection. Each JobRun freezes the selected image UID, digest, and commit
before launch and is unaffected by later promotions.

## Project Coding Agent

Use one `project_coding_agent` declaration when the current ProjectBranch
itself must be deployed as a Project Executor coding agent. The backend derives
the ProjectBranch and `agent_type=project-executor`; do not put either selector
in the spec. A ProjectBranch can have only one such declaration across all
workflow files.

The spec accepts the canonical Project Executor LLM, compute,
`automatic_deployment`, and `automatic_redeployment_policy` fields. Never add
`harness`. Harness is registered by the selected backend deployment and exposed
later as read-only service metadata; it is not user-selectable deployment
input.

```yaml
- key: project-agent
  kind: project_coding_agent
  spec:
    llm_provider: openai
    llm_model: gpt-5.4
    llm_thinking: medium
    cpu_request: 250m
    cpu_limit: "1"
    memory_request: 512Mi
    memory_limit: 2Gi
    automatic_deployment: true
    automatic_redeployment_policy:
      tag_regex: null
    env_vars:
      - name: PROJECT_OPERATING_MODE
        value: review
```

Prepare `.agents/agent_card.json`, project-owned skills, and project
instructions through the separate `project-to-agent` skill before declaring
deployment. Repository preparation and runtime deployment remain separate
validation steps.

A Project Coding Agent workflow declaration does not need a ProjectBranch
project-image UID, a Project Executor image UID, or a prebuilt image. The
deployment service builds the verified project-image and executor-image chain,
so `project_image.create` is not a prerequisite.

## Widget Extensions

Declare every Command Center widget implementation, including first-party
widgets, through the ordinary `resource_release` workflow kind:

```yaml
- key: command-center-widgets
  kind: resource_release
  spec:
    release_kind: widget_extension
    name: command-center-widgets
    root_directory: command-center
```

This spec accepts exactly `release_kind`, `name`, and optional
`root_directory`. Do not add `extension_id`, `resource_uid`,
`related_image_uid`, build commands, output paths, environment, secrets,
`automatic_deployment`, or `automatic_redeployment`. Automatic deployment is
forced on and first application queues the canonical exact-commit
`ResourceReleaseRun`; later repository events reuse the same resource-release
policy, idempotency, queue, and run history.

The manifest `id` and SemVer are validated outputs of the fixed SDK workload
build and are retained in immutable publications. They are not workflow or
release fields. A run with no installed fixed workload adapter blocks
explicitly; it never falls through to a Knative runtime deployment.

## Application Semantics

A valid file creates or updates only the resources it declares. Removing a
resource declaration or deleting a file does not delete an existing backend
resource. Use that resource's explicit delete operation when deletion is
intended. There is no prune or strict-delete mode.

Files are processed independently. An invalid file is not applied and does not
block another valid file. Git commit SHA, file path, and blob hash identify the
document version; repository-event action results record processing status.
A successful workflow parse or source commit is not build or deployment
success. Inspect the project-image provenance/build state and resulting
DeploymentRun independently.

Workflow files never declare build-context storage or provider source
locations. For every backend-derived project or executor image, the platform
freezes the exact compressed context as a checksum-verified relational artifact
before it commits the build attempt. GCP and Azure derive their request source
from that artifact; a retry never re-reads branch HEAD or asks the workflow
author for a bucket, URI, credential, or image selector.

## ResourceRelease Automatic Redeployment

Use the file-only `automatic_redeployment` block when future repository events
should redeploy a ResourceRelease:

```yaml
automatic_redeployment:
  enabled: true
  tag_regex: null
```

`enabled` maps to the canonical automatic-deployment switch. `tag_regex`
configures the automatic-redeployment target policy; `null` accepts every
commit while enabled. Omitting the block preserves the existing configuration.

For a runtime `resource_release` with effective automatic deployment enabled,
`related_image_uid` is not needed:

- provide `resource_uid` without waiting for an image;
- if a legacy file supplies `related_image_uid`, the backend ignores it before
  UUID parsing or image lookup, so even a stale or invalid value has no effect;
- workflow application creates or reuses the exact event image identity and
  never materializes an image-less executable backing Job; and
- initial application creates one canonical `source=create`,
  `operation=build_and_deploy` run and waits for that image when necessary.

The later generic ResourceRelease repository handler evaluates policy and
deploys only for later immutable repository events.
An ineligible event performs no image work.
The exact image already attached during initial creation makes the same event
commit idempotent rather than creating a second run. An exact pending image
identity is desired state, not proof of deployment;
only an attached verified digest-pinned image establishes the deployed commit.

When automatic deployment is disabled, use the existing explicit image-backed
runtime contract and provide `related_image_uid`.

A runtime release may also carry target-owned process configuration:

```yaml
- key: orders-api
  kind: resource_release
  spec:
    release_kind: fastapi
    resource_uid: "00000000-0000-4000-8000-000000000002"
    automatic_redeployment:
      enabled: true
      tag_regex: null
    cors_allowed_origins:
      - "https://*.site-dev.main-sequence.app"
    env_vars:
      - name: PUBLIC_MARKET
        value: XNYS
```

Deployment history records only sorted variable names, count, and a keyed
HMAC digest. Repository-event action results do not retain normalized content
or environment values.

For a newly created FastAPI release, omitting `cors_allowed_origins` persists
the active platform default. For an existing workflow-owned release, omission
preserves its policy. An explicit `[]` denies all browser origins, and a
non-empty list replaces the policy. A changed policy is persisted during
reconciliation but requires a subsequent deployment before the running
FastAPI launcher emits matching CORS headers. The workflow never sets the
reserved `FASTAPI_CORS_ALLOW_ORIGINS` environment variable.

## Stop Conditions

Stop and request direction when the target ProjectBranch is ambiguous, the
backend rejects the document version or resource kind, a requested field is
absent from the accepted template and canonical endpoint contract, or an apply
result is ambiguous. Do not work around validation by reproducing backend
defaults or deployment logic in the client.
