---
name: resource-release
description: Create, configure, deploy, inspect, and delete Main Sequence ResourceReleases through the canonical MCP operations, including FastAPI browser-origin preflight and the platform static-site wildcard default. Use for runtime, static-site, or fixed-profile widget-extension release discovery, creation, deployment, DeploymentRun observation, and explicit cleanup.
---

# Main Sequence Resource Release

Use this skill for the shared ResourceRelease lifecycle. Main Sequence MCP
projects the canonical DRF operations; it does not implement another release,
deployment, permission, or retry system.

Read `mainsequence://platform/ontology` before operating on CodeRepositoryBranch,
ResourceRelease, CodeRepositoryJobImage, PublicCatalogImage, or DeploymentRun
identities. Read the separate
`mainsequence://platform/skills/static-site` skill when the target release kind
is `static_site`.

This skill's runtime creation procedure describes the direct
`resource_release.create` MCP operation. When release intent is declared under
`.mainsequence/workflows`, read the `code-repository-workflows` skill instead; its
automatic-deployment image contract is intentionally different.

## Preserve Canonical Ownership

Pod Manager owns release persistence, validation, authorization, image and
source resolution, automatic promotion, deployment orchestration, and run
state. MCP owns only protocol adaptation and this operation guidance.

Every release owns immutable `ResourceReleaseRevision` identities plus
`active_revision`, `desired_revision`, and `revision_retention_count`.
Active/desired values returned by release list/detail are nullable revision
UIDs, not provider names or browser URLs. Only a ready active revision serves
the existing stable release URL; a failed desired revision leaves prior traffic
unchanged. DeploymentRuns remain separate attempts.

Set `revision_retention_count` through the existing release create/update
operation when a different rollback history is required. The value is a
positive integer, defaults to `3`, and belongs to the release, not
`automatic_redeployment_policy`. Existing widget, workspace, active, desired,
and live-run references remain protected. Revision candidate discovery is
report-only until the approved Command Center maintenance and static-policy
cutover exists; do not imply that editing the count synchronously deletes
provider artifacts.

For image-backed deployment, the parent `DeploymentRun` owns role-specific
`DeploymentRunImageDependency` relations and `CodeRepositoryImageBuildRun` owns the
complete provider attempt. Provider request/operation state and image
UID/URI/digest/readiness are never owned by generic run JSON or duplicated on
`CodeRepositoryJobImage`. Preparation commits before provider submission; database
due-action state recovers lost Celery wake-ups. An ambiguous submission is
reconciled on the same attempt and must not be retried through another create
call. Runtime admission requires the verified dependency's digest-pinned
output and never selects `latest`.

The persisted image model is ownership-typed. Public catalog inputs use
`PublicCatalogImage`; deployable code-repository outputs use the Organization-owned
`CodeRepositoryJobImage` descendant. There is no generic persisted `Image`, union
lookup, or ownership inference. The release operation accepts only the
canonical code-repository-image UID where documented; backend catalog selection never
asks the caller for a public-image UID.

The public release kinds are:

- `streamlit_dashboard`;
- `agent`, meaning a runtime ResourceRelease and not a CodeRepository Coding Agent;
- `fastapi`; and
- `static_site`; and
- `widget_extension`.

Every ResourceRelease belongs to one exact CodeRepositoryBranch. Use the public
CodeRepositoryBranch UID for branch-scoped discovery and never substitute a logical
CodeRepository UID.

`ResourceRelease.uid` is also the sole public runtime target. Release
responses do not expose a separate `subdomain`, and clients must not derive or
send numeric, product-specific, internal-service, or tenancy-qualified target
aliases. When a canonical operation returns a public or RPC URL, consume that
URL as opaque connection data instead of constructing a product hostname.

## Discover Existing Releases

Use `resource_release.list` with bounded `limit` and `offset`. Prefer exact
filters such as `code_repository_branch_uid`, `release_kind`, or `uid` before free-text
search. The response is the canonical paginated collection with `count`,
`next`, `previous`, `results`, `controls`, and `actions`.

Use `resource_release.get` with `resource_release_uid` before configuration or
deployment. Detail is discriminated by `release_kind`; do not assume runtime
fields exist on a static site or widget extension, or that static configuration
exists on a runtime release.

Collection `actions` describe authenticated DRF collection actions for user
interfaces. They do not create unregistered MCP tools. Never invoke an action's
raw endpoint through a generic HTTP or API proxy.

## Prepare Runtime Release Inputs

For the direct `resource_release.create` MCP operation, runtime release
creation requires two public references from the same intended CodeRepositoryBranch
and code revision:

1. Resolve an indexed source with `code_repository_resource.list`. Use
   `CodeRepositoryResource.uid` as `resource_uid`. This operation does not scan or
   synchronize the repository and does not return stored code.
2. Resolve an execution image with `code_repository_image.list` or
   `code_repository_image.get`. Use `CodeRepositoryJobImage.uid` as
   `related_image_uid`.
3. If the required image does not exist, call `code_repository_image.create` once and
   inspect the returned image with `code_repository_image.get` until its canonical
   state establishes whether it is ready or failed.
4. Verify the source kind, image CodeRepositoryBranch, frozen commit, digest-pinned
   output, and read-only verified source provenance are compatible with the
   intended `streamlit_dashboard`, `agent`, or `fastapi` release.

The backend admits code-repository source only after proving that the full commit is
reachable from the exact CodeRepositoryBranch ref, then supplies every provider one
normalized checksummed archive. Do not accept an image whose provenance is
missing or unverified, infer provenance from its tag, or treat a matching
commit alone as sufficient when the image belongs to another CodeRepositoryBranch.

Python runtime releases execute the admitted checkout at `/workspace` under
non-root UID/GID `10000:10000`. This is a deployment-owned ABI; callers must
not supply legacy Jupyter/Jovyan paths, users, or compatibility environment.
The backend may reject Python image mutation and Knative materialization while
the ADR-047 destructive cutover lock is active. Preserve the requested release
identity and wait for the backend-owned cutover rather than selecting a retired
image or an alternate launcher.

Do not use numeric resource or image identifiers. Do not retry an ambiguous
image creation or release creation automatically; inspect the returned image
and canonical DeploymentRun until that same durable attempt is terminal.

## Prepare Static-Site Inputs

For `static_site`, read the separate static-site skill and call
`resource_release.static_site_capabilities` for the exact CodeRepositoryBranch before
creation or static configuration changes. That live DRF response owns supported
fields, defaults, choices, conditions, and constraints. The installed Command
Center SDK skills own frontend implementation.

## Prepare Widget-Extension Inputs

For `widget_extension`, supply only `code_repository_branch_uid`, `name`, and optional
repository-relative `root_directory`. Do not supply `extension_id`, a
CodeRepositoryResource or image UID, build/runtime settings, environment, secrets,
publication version, or an automatic-deployment policy. Automatic deployment
is forced on.

The release UID identifies the backend release. Manifest `id` and SemVer are
validated immutable build outputs, not release fields. Every build attempt uses
the existing `ResourceReleaseRun`; successful publications are historical
versions, not deployment attempts or a second deployment model.

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

- runtime kinds use `resource_uid` and `related_image_uid`;
- `static_site` uses `code_repository_branch_uid`, `name`, and only currently
  advertised static configuration; or
- `widget_extension` uses `code_repository_branch_uid`, `name`, and optional
  `root_directory`.

Creation uses the canonical authorization, credit, validation, persistence,
and asynchronous initial-deployment behavior. A successful create response
identifies the release; it is not proof that the first deployment is active.

### When An Image Is Needed

The operation path, release kind, and effective automatic-deployment setting
determine the image requirement:

| Operation path and target | Effective automatic deployment | Image requirement |
| --- | --- | --- |
| Direct `resource_release.create` for a runtime release | Either | `related_image_uid` is required for the initial deployment and must identify a ready verified image. Initial deployment uses `source=create`, `operation=deploy`. This includes a direct request with `automatic_deployment: true`. |
| Workflow declaration for a runtime release | Enabled | `related_image_uid` is not needed. If present for compatibility, the backend ignores it before UUID parsing or image lookup. Initial application owns one `source=create`, `operation=build_and_deploy` run and may wait for image verification. |
| Workflow declaration for a runtime release | Disabled | `related_image_uid` is required and selects the explicit verified code-repository image. |
| Static-site release | Either | No caller-supplied runtime image UID is needed. The backend owns the static-site build. |
| Widget-extension release | Forced enabled | No caller-supplied runtime image or CodeRepositoryResource UID is accepted. The fixed SDK workload adapter owns the build output. |

Runtime releases are `fastapi`, `streamlit_dashboard`, and runtime `agent`
ResourceReleases. For the workflow path, effective automatic deployment is
enabled by either `automatic_deployment: true` or
`automatic_redeployment.enabled: true`. Policy eligibility is decided before
the backend builds or reuses the exact-commit image.

Workflow APIs `2.0.0` and `2.1.0` also accept target-owned non-secret `env_vars` for these
runtime releases. The backend persists the normalized mapping on the release's
generated Job before deployment. Omission preserves, an empty list clears, and
a present list replaces the mapping. This workflow-only adapter does not add a
direct `resource_release.create` or `resource_release.update` field.

Static sites reject `env_vars` and continue to use `build_environment`.
Widget extensions reject both `env_vars` and `build_environment`.
Workflow environment values never create, resolve, or mutate platform Secrets,
Constants, CodeRepositorySecrets, or Organization Environments, and never enter the
code-repository-image build. Deployment context contains only names, count, and a keyed
HMAC digest; it never exposes values. Read the `code-repository-workflows` skill and
use the backend-provided API `2.1.0` template for the exact YAML shape.

## Configure FastAPI Browser Origins

When FastAPI creation omits `cors_allowed_origins`, the backend persists the
active platform static-site wildcard already selected by its deployment
environment. Development resolves to:

```yaml
cors_allowed_origins:
  - "https://*.site-dev.main-sequence.app"
```

Production resolves to `https://*.site.main-sequence.app`. This platform
deployment environment is not an Organization Environment, and callers must
not derive the value from a CodeRepositoryBranch or
`OrganizationEnvironment`. Retrieve the backend workflow template when
authoring a workflow; do not copy the development value into production.

Pass the canonical field on create, partial update, or an API `2.1.0`
code-repository workflow declaration only when an explicit override is intended.
Creation omission uses the platform default. Update or workflow-reconciliation
omission preserves the stored policy. An explicitly submitted `[]` denies all
browser origins, while a non-empty list replaces the policy.

The list accepts at most 32 exact HTTP(S) origins or a wildcard only as the
complete leftmost hostname label. The backend normalizes and deduplicates the
effective list, persists it on that FastAPI release, and supplies the platform-owned,
comma-separated `FASTAPI_CORS_ALLOW_ORIGINS` setting on the next deployment.
Do not put that reserved setting in workflow `env_vars`.

```text
FASTAPI_CORS_ALLOW_ORIGINS=https://*.site-dev.main-sequence.app
```

Starlette's `allow_origins` accepts exact origins and does not interpret that
glob by itself. The launcher validates the glob and compiles it to an anchored
`allow_origin_regex` equivalent to:

```yaml
cors_allowed_origin_regex: '^https://[^.]+\.site-dev\.main-sequence\.app$'
```

The public release contract intentionally does not accept an arbitrary regex.
For understanding or testing the stricter platform UID-host policy, the
preferred equivalent regex is:

```yaml
cors_allowed_origin_regex: '^https://[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.site-dev\.main-sequence\.app$'
```

The `*` policy authorizes browser JavaScript from every matching
`<site-uid>.site-dev.main-sequence.app` static-site deployment origin to make
and read CORS-enabled requests to that FastAPI release. It does not match the
parent domain, nested subdomains, or Streamlit dashboard origins under
`*.dash-dev.main-sequence.app`. CORS is not API authentication: the caller must
still present the FastAPI release's valid Bearer token and target the exact
release UID.

The public gateway delegates unauthenticated `OPTIONS` preflight to the exact
release runtime and preserves its CORS headers. Normal requests remain
Bearer-authenticated, and the gateway preserves the runtime's CORS response.

## Compose A Static Site With One FastAPI Release

Before implementing the composition, call `resource_release.get` for the exact
target FastAPI release and inspect its returned `cors_allowed_origins`. Compare
that policy with the source release's backend-returned `public_url`; do not
construct either hostname. An empty or non-matching target policy makes the
delegated exchange return `403` with `code=origin_not_allowed`.

If the accepted policy must change, call `resource_release.update`, retrieve
the target again to verify the persisted value, and then call
`resource_release.deploy_current_version`. The update changes Django's current
delegation admission but does not update an already-running FastAPI launcher.
Observe the DeploymentRun to terminal success before testing browser preflight
or application requests.

The existing authenticated ResourceRelease action supports a narrow delegated
FastAPI exchange without adding another credential endpoint:

```text
GET /api/v1/resource-releases/<fastapi_release_uid>/exchange-launch/
    ?static_site_release_uid=<static_site_release_uid>
```

Use the exact source StaticSiteRelease UID and exact target FastAPI
ResourceRelease UID. The backend derives the source origin; never submit or
infer an origin, user, Organization, branch, environment, target URL, or token
claim. The target FastAPI release must explicitly admit that source through its
current `cors_allowed_origins` policy.

Issuance and every delegated validation require an active user with current
view access to both releases, servable/routable release state, same-Organization
ownership, an exact Origin match, exact target identity, and current CORS
admission. The releases do not need to share a CodeRepositoryBranch or
OrganizationEnvironment. CORS remains browser admission and never
replaces the delegated credential or code-repository route authorization.

The successful no-store response supplies an opaque `rpc_url`, the exact
target `resource_release_uid`, expiration, and a maximum-five-minute token
bound to the source release, source origin, user, target, and FastAPI RPC
purpose. This flow never transfers the user's general platform JWT to code-repository
code. Frontend acquisition and transport belong to the installed Command
Center SDK skill bundle; do not duplicate its message protocol or TypeScript
API here.

## Read The Authenticated FastAPI Request User

FastAPI releases served by `pod-orchestrator serve_fastapi` always receive the
platform-authenticated human caller through request state. Pod Deployment
Orchestrator owns and installs the middleware; code-repository code must not import or
install `mainsequence.client.fastapi.LoggedUserContextMiddleware` or any other
request-identity middleware.

```python
from fastapi import FastAPI, Request


app = FastAPI()


@app.get("/me")
def get_me(request: Request) -> dict[str, str | None]:
    return {
        "uid": request.state.user_uid,
        "username": request.state.user.username,
    }
```

- `request.state.user` has canonical `uid` and optional `username`.
- `request.state.user_uid` is the same public UUID string.
- `request.state.user_id` does not exist.
- FastAPI code passes request state explicitly to shared services; it does not
  use `User.get_logged_user()` as the handler entry point.

The public FastAPI gateway removes caller-supplied identity headers, validates
the release Bearer token through Django, installs Django's trusted UID headers,
and removes the Bearer credential before code-repository code runs. Direct local
launcher requests validate a Bearer token through `/api/v1/users/me/`. Every
non-`OPTIONS` route is authenticated; CORS preflight remains outside identity
resolution.

Request identity names the human making the call. It is not the release owner,
CodeRepositoryBranch, Organization Environment, runtime workload principal, or an
authorization grant. Each route must still apply its own object and operation
authorization using the canonical request UID.

## Update Configuration

Call `resource_release.update` with `resource_release_uid` and only fields that
belong to that release kind.

Runtime releases accept only:

- `automatic_deployment`;
- `automatic_redeployment_policy`;
- positive release-owned `revision_retention_count`; and
- for FastAPI only, `cors_allowed_origins`.

Static sites additionally accept the canonical static configuration fields
advertised by `resource_release.static_site_capabilities`, including the
complete write-only `build_environment` map.

Widget-extension source, rename, root directory, automatic-deployment switch,
and manifest identity remain immutable through ordinary update. Its shared
`revision_retention_count` is the one editable release lifecycle policy.

An update replaces the submitted configuration values and returns the canonical
release detail. It does not deploy the release. Re-read the release after an
ambiguous result before deciding whether another update is necessary.

Browser build-environment values are not secret storage. Never place a token,
credential, private key, or secret value in `build_environment`. Submitted
values are write-only and responses expose only their keys.

## Deploy The Current Version

When explicit deployment is requested, call
`resource_release.deploy_current_version` with only
`resource_release_uid`. The operation deploys the CodeRepositoryBranch's persisted
current commit; it does not accept an arbitrary commit, tag, policy override,
or MCP idempotency key.

The operation requires canonical edit access, may perform build or provider
work, is non-idempotent, and returns the unified DeploymentRun projection. Do
not automatically retry an ambiguous response.

For `widget_extension`, this action queues the same fixed SDK build/publication
pipeline used by automatic repository events. If the deployment does not have
that adapter installed, the canonical run becomes blocked; it is never routed
to the runtime/Knative deployer.

A runtime ResourceRelease receives a backend-derived public CodeRepositoryBranch
context during runtime-credential exchange. The deployed SDK uses that
authenticated context for branch-owned operations without requiring a Git
checkout. The container cannot select another CodeRepositoryBranch or Organization
Environment through branch text, environment values, request data, or image
metadata.

The exchanged credential also authenticates its persisted responsible User.
Runtime token scope neither grants nor removes API actions: canonical DRF,
product-role, service-identity, object, and operation policy applies exactly as
it would for another token belonging to that User. CodeRepositoryBranch and
Organization Environment context still narrow resource discovery and routing;
they are not a second action principal.

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

Call `code_repository_image.delete` with only `code_repository_image_uid` when an exact image is
no longer required. It dispatches the canonical CodeRepositoryJobImage destroy action,
including live-resource protection, typed detachment of terminal build,
deployment, and JobRun history, and registry-artifact cleanup. Active runs or
live Jobs return the canonical structured conflict; terminal records retain
their immutable typed image snapshots without retaining the image row. Success
returns `{}` after the canonical HTTP 204 response.

Delete dependent ResourceReleases before deleting an image they use. Neither
delete tool is a bulk operation or a generic API proxy. Do not automatically
retry an ambiguous destructive response: use `resource_release.get` or
`code_repository_image.get` first to determine whether the object still exists.

## Stop Conditions

Stop and ask for direction when:

- the CodeRepository and exact CodeRepositoryBranch cannot be distinguished;
- a runtime source or image does not belong to the intended CodeRepositoryBranch or
  commit;
- a static field is not advertised by the live capability response;
- a requested update field is not valid for the target release kind;
- a delegated static-site origin is not admitted by the target FastAPI policy
  and the intended exact or wildcard override is not known;
- a build environment value would expose secret material;
- a create, update, or deployment response is ambiguous; or
- the requested bulk action, log read, arbitrary-commit deployment, or other
  operation has no registered MCP tool.
