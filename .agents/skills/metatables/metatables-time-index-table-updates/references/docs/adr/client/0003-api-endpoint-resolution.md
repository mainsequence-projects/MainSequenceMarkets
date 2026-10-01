# ADR 0003: Automatic API endpoint resolution

Date: 2026-09-29

Status: Accepted and implemented. Verified with the local SDK and isolated
platform responses; live hosted deployment verification remains separate.

Owner: MetaTables Python client, including the CLI.

Related decision: [API ADR 0001: One API execution path with SQLite for local development](../api/0001-unified-api-storage-and-local-sqlite.md).

The client implements this decision using the SDK's exact-name release filter
and existing release-access operation.

Amended 2026-09-29: obtain the target name from the MetaTables automatic
deployment. Remove the proposed conventional name and manually configured
deployment-name variable.

Implementation clarification 2026-09-29: the authoritative metadata is the API
workflow in this repository, not a new SDK metadata endpoint. Package that file
with the client and use the SDK for the subsequent release lookup and access.

## Context

Previously, the client constructed resource URLs from a model's `ROOT_URL` or
`METATABLES_API_URL`, and failed when neither was configured. The CLI separately
required the environment variable. This decision replaces that duplicated
selection with automatic discovery and an explicit URL override.

A client connecting to a hosted MetaTables deployment obtains the correct name
from the automatic deployment's authoritative metadata. Users should not copy
release names, UIDs or deployment URLs into each consuming project. Discovery
should happen once per client process, with subsequent operations reusing the
resolved address. A developer must also be able to point the same client at a
local API through an environment variable.

The SDK supplies generic platform release operations. Ordinary release collection
queries currently infer the consuming repository's branch, whereas the MetaTables
deployment can belong to another repository. A name filter alone does not solve
that distinction. Release names are also not currently guaranteed to be unique;
text search or selecting the first result cannot establish the intended target.

Endpoint selection is a client transport concern. The API's runtime mode,
bootstrap and DataSource binding remain governed by API ADR 0001. Connecting to
a loopback URL does not imply SQLite: a developer API can select either supported
runtime mode through Settings.

## Decision

### 1. One resolver with an explicit URL override

All Python resource models, runtime-context requests, readers, updaters and CLI
commands use one client endpoint resolver. Migration commands use the same
resolved API for their reservation, connection and finalization requests.

The resolver uses the following precedence:

| Configuration | Behavior |
| --- | --- |
| Nonempty `METATABLES_API_URL` | Use that explicit base URL and skip all deployment discovery. |
| URL unset or empty | Obtain the MetaTables API's name from its automatic-deployment metadata, then resolve that named deployment through the SDK. |

The deployment name is derived data, owned by the automatic deployment. There is
no hardcoded default such as `metatables`, and no manually maintained
`METATABLES_API_DEPLOYMENT_NAME` setting. The client must consume the actual name
produced by that deployment, so changing it does not require editing consuming
projects. `METATABLES_API_URL` remains the explicit client override; there is no
additional automatic/manual mode variable.

An explicit URL may target a local or hosted API. Preserve any deployment path
prefix when joining resource routes. A nonempty invalid URL produces a
configuration error; it must not fall through to automatic discovery. Model-level
`ROOT_URL` assignments must no longer independently override the environment or
split different resources across different API targets.

For example, the existing local override remains:

```bash
export METATABLES_API_URL=http://127.0.0.1:18473
```

This selects the API address only. Existing local transport requirements still
apply; it neither starts the API nor changes its storage mode.

### 2. Obtain the automatic deployment's name and resolve it through the SDK

The authoritative source is `.mainsequence/workflows/metatables-api.yaml` in
this repository. Its single `kind: fastapi` target selects
`spec.source_path`. Under workflow API `2.3.0`, the release name is the containing
API directory's name. Neither the workflow's top-level `name` nor its resource
`key` is the release name. The checked-in target is `api/metatables/main.py`.

Editable installations read this package's source workflow, regardless of the
consumer's working directory. Builds copy the same file into the wheel as
`metatables/_api_workflow.yaml`; consumers need no checkout or deployment file.
Renaming the deployed API directory requires installing the matching package
build, not changing constants or configuration in each consuming project.

MetaTables reads its own deployment declaration and uses public SDK interfaces
for exact-name lookup and stable endpoint retrieval. It does not call platform
routes directly, inspect platform persistence models, derive hostnames from UIDs,
or maintain a second platform client.

Discovery must operate in the platform's permitted release scope without
implicitly restricting the result to the consuming application's repository
branch. The SDK owns the generic lookup capability and its platform contract.
This decision does not relax branch or Environment requirements on ordinary SDK
resource operations, and does not make local development require a registered
branch.

The client calls `ResourceRelease.filter_admin(name=..., release_kind="fastapi")`
using the existing explicit SDK collection interface, which does not infer the
consumer's branch. This is an exact bounded query, not enumeration of all releases.
Backend visibility and runtime scope still apply. The client requires one match
and calls that release's `resolve_runtime_access()` for the backend-issued URL.
No SDK context reset, branch override or new platform metadata endpoint is needed.

Exactly one matching release is required. Missing or ambiguous target metadata,
no matching release, multiple matches, the wrong release kind, or a missing
usable endpoint produces a specific resolution error.
Ambiguous deployments must be given distinct names or use the explicit URL
override. There is no first-result selection or fallback to another release.

Existing SDK release-access operations may report a starting or unavailable
runtime. Such a result is not a successful endpoint resolution. Respect the
SDK's existing retry contract within a bounded timeout and report failure when
the target cannot be resolved. This decision introduces no new authentication
mechanism, credential type, account-binding policy or Organization policy.

### 3. Cache the endpoint once per process

Resolve lazily on the first operation that needs an API address. Cache a
successful result in process memory for the selected platform endpoint and
automatic-deployment target, including its derived name. The discovery sequence
obtains target metadata, resolves the exact name and retrieves the endpoint;
subsequent operations reuse its result without repeating any of those steps.

Concurrent first callers share one resolution attempt. Do not cache failed,
ambiguous, starting or unavailable results as successful entries. Later calls
can retry after a failed attempt. Forked or new processes start with their own
cache; no discovered address is persisted to disk.

The explicit URL is checked before consulting the discovery cache, so setting
`METATABLES_API_URL` takes effect even after automatic resolution. Configuration
changes invalidate the previous target's cache; an explicit client reset or
process restart also permits a fresh lookup, including reacquiring the name from
the packaged workflow. Editable installs observe workflow changes on that fresh
lookup; installed wheels use their immutable workflow snapshot. Stable configuration
has no periodic discovery or per-request platform identity preflight.

Keep the selected endpoint fixed for an in-flight operation, including a migration
lifecycle. Changing configuration between operations must not leave individual
models pinned to the previous target. An ordinary request failure does not
silently select another deployment or replay a mutation against a different API.

### 4. Keep endpoint discovery separate from runtime state

Cache only the stable endpoint and the release identity needed to describe that
selection. Do not cache temporary release-access tokens, admission/readiness
decisions, permission facts or the API's effective DataSource with it. SDK session
and credential refresh remain governed by existing SDK behavior.

The release-access response supplies the existing release Bearer credential.
Keep it in a separate, memory-only SDK `SessionJWTAuthProvider`, outside the
endpoint cache and shared platform session. The SDK request helper retries a
401 once: reacquire access for the same release UID and reject a changed URL
instead of retargeting the request. This does not repeat name discovery or add an
authentication contract. Local and explicit-URL transports retain their existing
SDK session behavior.

The API's `/runtime-context/` response remains fresh under API ADR 0001. Resetting
local storage, selecting another DataSource or restarting the API can change
runtime state without changing its address. The endpoint cache must not hide
those changes or introduce client database access.

## Ownership and consequences

| Owner | Responsibility |
| --- | --- |
| MetaTables client | Read the packaged workflow, configuration precedence, shared endpoint resolver, process cache and resolution errors. |
| Main Sequence SDK/platform | Generic exact-name release discovery, accessible release scope, endpoint and release-access retrieval. |
| MetaTables API | Own the automatic deployment declaration, runtime descriptor, admission, Settings, bootstrap and its enforced DataSource binding. |

This is a separate client ADR because API runtime selection and storage ownership
do not change. API ADR 0001's prohibition on caching effective runtime context
remains in force. The Vite Admin site's connection configuration is outside this
Python-client decision.

Existing explicit URL configurations continue to work. Automatic mode adds a
platform discovery dependency only when no URL is provided. A deleted or replaced
deployment can require an explicit reset or process restart to discover a new
address; normal requests do not repeatedly search for one.

## Implementation and acceptance criteria

Implemented in `metatables.endpoint` and `metatables.transport`. Resource methods,
CLI commands and migrations share the resolver; operation scopes prevent a
configuration change from retargeting active work. Endpoint reset is available as
`metatables.endpoint.reset_api_endpoint()`.

The two VS Code example launches select the local launcher's private connection
or automatic hosted discovery. Their read step requires the tutorial tables and
data to exist; `connect` verifies selection without table access. Packaging tests
verify that installed clients carry the same workflow used by the API deployment.
The workflow must be applied on the platform before the hosted launch can find it.

- The client obtains the actual MetaTables deployment name from automatic
  deployment metadata and resolves it through the SDK without a user-supplied
  name or UID, including outside the consuming repository's branch.
- Tests use distinct deployment-generated names and verify that a fresh lookup
  after an editable-workflow rename uses updated metadata without edits to
  consuming projects. Wheels retain their packaged deployment declaration.
  Missing or ambiguous metadata/names fail clearly without a constant fallback.
- Repeated and concurrent operations across resource classes and CLI consumers
  perform one successful discovery sequence per process and configuration.
- An explicit URL bypasses all discovery, including automatic-deployment metadata
  retrieval and a populated cache, and preserves route prefixes. Invalid explicit
  URLs do not trigger discovery.
- Failed resolution remains retryable; reset, configuration changes and process
  forks do not reuse a stale target.
- Local explicit-URL operations still work on an unregistered branch without
  introducing a platform release or Environment requirement.
- Changing runtime state at an unchanged URL remains visible to the client.
  Endpoint caching does not retain DataSource state or temporary credentials.
- Resource calls and migration lifecycles consistently use their selected API;
  the resolver never redirects ordinary SDK platform requests to that API.
- Update connection guides, configuration reference and executable examples with
  automatic and explicit modes once behavior is verified. Keep dependency and
  authentication boundaries covered by the existing checks.

## References

- [Current client connection guide](../../client/installation-and-connection.md)
- [Current configuration reference](../../operations/configuration.md)
- [API runtime and storage decision](../api/0001-unified-api-storage-and-local-sqlite.md)
- [Architecture decisions by owner](../index.md)
