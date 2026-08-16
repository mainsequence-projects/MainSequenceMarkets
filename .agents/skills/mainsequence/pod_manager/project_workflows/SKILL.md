---
name: project-workflows
description: Create and validate backend-managed deployment declarations under .mainsequence/workflows. Use when a project should deploy or schedule Jobs, ResourceReleases, or its Project Coding Agent from versioned repository files.
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

## File Contract

- Every file is independent and requires `api_version`, `name`, and
  `resources`.
- Version `1.0.0` supports `job` and `resource_release`; version `1.1.0` adds
  `project_coding_agent`.
- Each resource has a stable `key`, a supported `kind`, and a typed `spec`.
- `spec` fields follow the canonical backend create/update endpoint contract.
- The validation endpoint is read-only and uses the same validator as
  repository processing.
- Only direct `.yaml` and `.yml` children are processed; nested files and other
  extensions are ignored.

Do not maintain `scheduled_jobs.yaml`; it is not a supported input.

## When An Image Is Needed

The workflow target and its effective automatic-deployment setting determine
whether the declaration needs an image:

| Workflow target | Effective automatic deployment | Image requirement |
| --- | --- | --- |
| Static site | Either | No runtime image UID is needed. The backend owns the static-site build. |
| Project Coding Agent | Either | No project-image or Project Executor image UID is needed. The backend builds the verified image chain. |
| Runtime ResourceRelease (`fastapi`, `streamlit_dashboard`, or runtime `agent`) | Enabled | `related_image_uid` is not needed. If present for compatibility, the backend ignores it. |
| Runtime ResourceRelease (`fastapi`, `streamlit_dashboard`, or runtime `agent`) | Disabled | `related_image_uid` is required and selects the explicit verified project image. |

For a workflow runtime release, effective automatic deployment is enabled by
either `automatic_deployment: true` or `automatic_redeployment.enabled: true`.
The direct `resource_release.create` MCP operation has a different initial
deployment contract; read the `resource-release` skill before using it.

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
```

Prepare `.agents/agent_card.json`, project-owned skills, and project
instructions through the separate `project-to-agent` skill before declaring
deployment. Repository preparation and runtime deployment remain separate
validation steps.

A Project Coding Agent workflow declaration does not need a ProjectBranch
project-image UID, a Project Executor image UID, or a prebuilt image. The
deployment service builds the verified project-image and executor-image chain,
so `project_image.create` is not a prerequisite.

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
- workflow application creates or reconciles pending desired state without an
  image and without an initial deployment run; and
- the repository-event policy is evaluated before the backend builds or reuses
  an exact-commit image. An ineligible event performs no image work.

The workflow handler does not dispatch a runtime deployment for that automatic
target. The later generic ResourceRelease repository handler owns the policy
decision, image build or reuse, and deployment. A pending Job commit is desired
state, not proof of deployment; only an attached verified image establishes the
deployed commit.

When automatic deployment is disabled, use the existing explicit image-backed
runtime contract and provide `related_image_uid`.

## Stop Conditions

Stop and request direction when the target ProjectBranch is ambiguous, the
backend rejects the document version or resource kind, a requested field is
absent from the accepted template and canonical endpoint contract, or an apply
result is ambiguous. Do not work around validation by reproducing backend
defaults or deployment logic in the client.
