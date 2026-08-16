---
name: resource-release
description: Create, configure, deploy, inspect, and delete Main Sequence ResourceReleases through the canonical MCP operations. Use for runtime or static release discovery, source and image selection, automatic redeployment configuration, explicit deployment, DeploymentRun observation, and explicit release cleanup.
---

# Main Sequence Resource Release

Use this skill for the shared ResourceRelease lifecycle. Main Sequence MCP
projects the canonical DRF operations; it does not implement another release,
deployment, permission, or retry system.

Read `mainsequence://platform/ontology` before operating on ProjectBranch,
ResourceRelease, Image, or DeploymentRun identities. Read the separate
`mainsequence://platform/skills/static-site` skill when the target release kind
is `static_site`.

This skill's runtime creation procedure describes the direct
`resource_release.create` MCP operation. When release intent is declared under
`.mainsequence/workflows`, read the `project-workflows` skill instead; its
automatic-deployment image contract is intentionally different.

## Preserve Canonical Ownership

Pod Manager owns release persistence, validation, authorization, image and
source resolution, automatic promotion, deployment orchestration, and run
state. MCP owns only protocol adaptation and this operation guidance.

The public release kinds are:

- `streamlit_dashboard`;
- `agent`, meaning a runtime ResourceRelease and not a Project Coding Agent;
- `fastapi`; and
- `static_site`.

Every ResourceRelease belongs to one exact ProjectBranch. Use the public
ProjectBranch UID for branch-scoped discovery and never substitute a logical
Project UID.

`ResourceRelease.uid` is also the sole public runtime target. Release
responses do not expose a separate `subdomain`, and clients must not derive or
send numeric, product-specific, internal-service, or tenancy-qualified target
aliases. When a canonical operation returns a public or RPC URL, consume that
URL as opaque connection data instead of constructing a product hostname.

## Discover Existing Releases

Use `resource_release.list` with bounded `limit` and `offset`. Prefer exact
filters such as `project_branch_uid`, `release_kind`, or `uid` before free-text
search. The response is the canonical paginated collection with `count`,
`next`, `previous`, `results`, `controls`, and `actions`.

Use `resource_release.get` with `resource_release_uid` before configuration or
deployment. Detail is discriminated by `release_kind`; do not assume runtime
fields exist on a static site or static configuration exists on a runtime
release.

Collection `actions` describe authenticated DRF collection actions for user
interfaces. They do not create unregistered MCP tools. Never invoke an action's
raw endpoint through a generic HTTP or API proxy.

## Prepare Runtime Release Inputs

For the direct `resource_release.create` MCP operation, runtime release
creation requires two public references from the same intended ProjectBranch
and code revision:

1. Resolve an indexed source with `project_resource.list`. Use
   `ProjectResource.uid` as `resource_uid`. This operation does not scan or
   synchronize the repository and does not return stored code.
2. Resolve an execution image with `project_image.list` or
   `project_image.get`. Use `ProjectImage.uid` as `related_image_uid`.
3. If the required image does not exist, call `project_image.create` once and
   inspect the returned image with `project_image.get` until its canonical
   state establishes whether it is ready or failed.
4. Verify the source kind, image ProjectBranch, frozen commit, digest-pinned
   output, and read-only verified source provenance are compatible with the
   intended `streamlit_dashboard`, `agent`, or `fastapi` release.

The backend admits project source only after proving that the full commit is
reachable from the exact ProjectBranch ref, then supplies every provider one
normalized checksummed archive. Do not accept an image whose provenance is
missing or unverified, infer provenance from its tag, or treat a matching
commit alone as sufficient when the image belongs to another ProjectBranch.

Do not use numeric resource or image identifiers. Do not retry an ambiguous
image creation or release creation automatically.

## Prepare Static-Site Inputs

For `static_site`, read the separate static-site skill and call
`resource_release.static_site_capabilities` for the exact ProjectBranch before
creation or static configuration changes. That live DRF response owns supported
fields, defaults, choices, conditions, and constraints. The installed Command
Center SDK skills own frontend implementation.

## Configure Automatic Redeployment

`automatic_deployment` is the master switch for repository-triggered
redeployment. The only promotion rule is the nested target-owned policy:

```json
{
  "automatic_deployment": true,
  "automatic_redeployment_policy": {
    "tag_regex": null
  }
}
```

- Omit `automatic_redeployment_policy` during creation to persist stable SemVer
  on `main` or branch-qualified SemVer on another branch.
- Send `{"tag_regex": null}` to allow every synchronized commit when the
  master switch is enabled.
- Send a bounded non-empty regex to require a full match against a valid short
  Git tag pointing to the exact synchronized commit.
- Never send `policy_revision`; it is read-only.
- Never send a flat `tag_regex`, `trigger_mode`, `rule_type`, or a client-side
  Git evaluation result.

Explicit manual deployment is independent of this promotion rule and does not
change it.

## Create A Release

Call `resource_release.create` once with the exact discriminated request:

- runtime kinds use `resource_uid` and `related_image_uid`; or
- `static_site` uses `project_branch_uid`, `name`, and only currently
  advertised static configuration.

Creation uses the canonical authorization, credit, validation, persistence,
and asynchronous initial-deployment behavior. A successful create response
identifies the release; it is not proof that the first deployment is active.

### When An Image Is Needed

The operation path, release kind, and effective automatic-deployment setting
determine the image requirement:

| Operation path and target | Effective automatic deployment | Image requirement |
| --- | --- | --- |
| Direct `resource_release.create` for a runtime release | Either | `related_image_uid` is required for the initial deployment. This includes a direct request with `automatic_deployment: true`. |
| Workflow declaration for a runtime release | Enabled | `related_image_uid` is not needed. If present for compatibility, the backend ignores it before UUID parsing or image lookup. |
| Workflow declaration for a runtime release | Disabled | `related_image_uid` is required and selects the explicit verified project image. |
| Static-site release | Either | No caller-supplied runtime image UID is needed. The backend owns the static-site build. |

Runtime releases are `fastapi`, `streamlit_dashboard`, and runtime `agent`
ResourceReleases. For the workflow path, effective automatic deployment is
enabled by either `automatic_deployment: true` or
`automatic_redeployment.enabled: true`. Policy eligibility is decided before
the backend builds or reuses the exact-commit image.

## Update Configuration

Call `resource_release.update` with `resource_release_uid` and only fields that
belong to that release kind.

Runtime releases accept only:

- `automatic_deployment`; and
- `automatic_redeployment_policy`.

Static sites additionally accept the canonical static configuration fields
advertised by `resource_release.static_site_capabilities`, including the
complete write-only `build_environment` map.

An update replaces the submitted configuration values and returns the canonical
release detail. It does not deploy the release. Re-read the release after an
ambiguous result before deciding whether another update is necessary.

Browser build-environment values are not secret storage. Never place a token,
credential, private key, or secret value in `build_environment`. Submitted
values are write-only and responses expose only their keys.

## Deploy The Current Version

When explicit deployment is requested, call
`resource_release.deploy_current_version` with only
`resource_release_uid`. The operation deploys the ProjectBranch's persisted
current commit; it does not accept an arbitrary commit, tag, policy override,
or MCP idempotency key.

The operation requires canonical edit access, may perform build or provider
work, is non-idempotent, and returns the unified DeploymentRun projection. Do
not automatically retry an ambiguous response.

A runtime ResourceRelease receives a backend-derived public ProjectBranch
context during runtime-credential exchange. The deployed SDK uses that
authenticated context for branch-owned operations without requiring a Git
checkout. The container cannot select another ProjectBranch or Organization
Environment through branch text, environment values, request data, or image
metadata.

## Observe Deployment State

Use `deployment_run.get` for the returned run UID. Use
`deployment_run.list` for bounded history, normally filtering by
`target_uid=resource_release_uid` and the correct target discriminator:

- runtime releases use `target_type=resource_release`;
- static sites use `target_type=static_site`.

Treat `queued` or `running` as accepted work, not successful deployment. A
release detail and a DeploymentRun describe different state: the release is
the durable target configuration; the run is one deployment attempt.

Read whole-attempt status from root `state`. Read progress only from
`pipeline.current_step_key` and the complete ordered `pipeline.steps` list,
which is present in both list and detail. Do not infer stages from `target_kind`
or expect a separate phase. `pending` means a declared future step has not
started; waiting for image/provider work leaves the build step `running`; after
a failure, later prevented steps are `skipped` with
`outcome=run_terminated`. Inspect the failed step's `error` before the root
error when explaining where execution stopped.

The current MCP catalog exposes run list and detail but no log-read tool. A
logs URL in the run projection does not authorize a generic endpoint call.

## Delete Releases And Images

Delete only after the user has explicitly selected the exact public UID and
requested the destructive action. Re-read the target immediately before the
delete when its identity or current use is uncertain.

Call `resource_release.delete` with only `resource_release_uid`. The tool
dispatches the canonical ResourceRelease destroy action and preserves its
operation authorization, scoped lookup, edit checks, dependency protection,
target-specific cleanup, and errors.

- Runtime release deletion removes the release and its generated Job, schedules
  the existing UID-named Knative cleanup, and returns `{}` after the canonical
  HTTP 204 success. It never mutates DNS, TLS, a Front Door custom domain, or
  an edge route; those shared wildcard resources are infrastructure-owned.
- Static-site deletion starts the existing durable asynchronous deletion flow
  and returns the canonical release representation with HTTP 202. Static sites
  share the same infrastructure-owned environment edge, so deletion does not
  mutate DNS, TLS, or a Front Door domain. Treat a `deleting` lifecycle as
  accepted cleanup, not completed deletion.
- A conflict or target-cleanup failure is a failed delete. Preserve the
  canonical error and do not claim that the target was removed.

Call `project_image.delete` with only `project_image_uid` when an exact image is
no longer required. It dispatches the canonical ProjectImage destroy action,
including existing dependency protection and registry-artifact cleanup, and
returns `{}` after the canonical HTTP 204 success.

Delete dependent ResourceReleases before deleting an image they use. Neither
delete tool is a bulk operation or a generic API proxy. Do not automatically
retry an ambiguous destructive response: use `resource_release.get` or
`project_image.get` first to determine whether the object still exists.

## Stop Conditions

Stop and ask for direction when:

- the logical Project and exact ProjectBranch cannot be distinguished;
- a runtime source or image does not belong to the intended ProjectBranch or
  commit;
- a static field is not advertised by the live capability response;
- a requested update field is not valid for the target release kind;
- a build environment value would expose secret material;
- a create, update, or deployment response is ambiguous; or
- the requested bulk action, log read, arbitrary-commit deployment, or other
  operation has no registered MCP tool.
