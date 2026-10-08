# ADR 0003: Automatic API endpoint resolution

Date: 2026-09-29

Status: Accepted and implemented. Verified with the local SDK and isolated
platform responses; live hosted deployment verification remains separate.

Owner: MetaTables Python client, including the CLI.

Related decision: [API ADR 0001: One API execution path with SQLite for local development](../api/0001-unified-api-storage-and-local-sqlite.md).

The client implements this decision using the SDK's Environment context,
exact-name release filter, owning-branch metadata and release-access operation.

Amended 2026-10-01 ([MetaTables #11](https://github.com/mainsequence-projects/MetaTables/issues/11)):
hosted discovery must select the caller's resolved Organization Environment.
The previous visibility-only lookup and hosted URL workaround violated that
contract. `METATABLES_API_URL` is reserved for loopback development APIs. Identical
deployment names in different Environments are expected and must work without
user configuration. Connection and configuration documentation must describe
this distinction and the Environment-specific failure cases.

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
selection with automatic hosted discovery and a local development URL override.

A client connecting to a hosted MetaTables deployment obtains the correct name
from the automatic deployment's authoritative metadata. Users should not copy
release names, UIDs or deployment URLs into each consuming project. Discovery
should happen once per client process, with subsequent operations reusing the
resolved address. A developer must also be able to point the same client at a
local API through an environment variable.

The SDK supplies generic platform release operations. Ordinary release collection
queries currently infer the consuming repository's branch, whereas the MetaTables
deployment can belong to another repository. A name filter alone does not solve
that distinction. The caller's Environment, obtained from the SDK's resolved
repository context or authenticated runtime credential, selects the intended
deployment across repositories. Release names can repeat across Environments;
visibility alone, text search or selecting the first result cannot establish the
intended target. Selecting the wrong API also selects the wrong runtime DataSource.

Endpoint selection is a client transport concern. The API's runtime mode,
bootstrap and DataSource binding remain governed by API ADR 0001. Connecting to
a loopback URL does not imply SQLite: a developer API can select either supported
runtime mode through Settings.

## Decision

### 1. One resolver with a local development URL override

All Python resource models, runtime-context requests, readers, updaters and CLI
commands use one client endpoint resolver. Migration commands use the same
resolved API for their reservation, connection and finalization requests.

The resolver uses the following precedence:

| Configuration | Behavior |
| --- | --- |
| Nonempty `METATABLES_API_URL` | Require a loopback HTTP(S) development URL, use it and skip platform Environment/deployment discovery. |
| URL unset or empty | Obtain the MetaTables API's name from its automatic-deployment metadata and resolve that deployment in the caller's SDK-owned Environment. |

The deployment name is derived data, owned by the automatic deployment. There is
no hardcoded default such as `metatables`, and no manually maintained
`METATABLES_API_DEPLOYMENT_NAME` setting. The client must consume the actual name
produced by that deployment, so changing it does not require editing consuming
projects. `METATABLES_API_URL` remains the local development override; there is no
additional automatic/manual mode variable.

An explicit URL must target `localhost` or a loopback IP address. Hosted URLs
are rejected with an instruction to unset the variable and use Environment
discovery. Preserve any local path prefix when joining resource routes. A nonempty
invalid URL produces a configuration error; it must not fall through to automatic
discovery. Model-level
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

Resolve the caller's Environment with the public SDK
`resolve_organization_environment_uid()` helper. The SDK owns Git registration,
authenticated runtime context and authorization. A developer's signed-in process
connecting to a hosted API follows the same Environment selection rule. Local
development URL selection does not require a registered branch or Environment.

The installed SDK does not expose an Environment filter on `ResourceRelease`.
Use `ResourceRelease.filter_admin(name=..., release_kind="fastapi")` only to
obtain exact-name candidates, without restricting them to the consuming
application's repository branch. Each candidate supplies its owning
`code_repository_branch_uid`. Read those public `CodeRepositoryBranch` records
through the SDK using `filter(uid__in=...)`, in batches of at most 100 unique UIDs,
and compare their `organization_environment_uid` with the caller's Environment.
The client must verify ownership before requesting runtime access, even if only
one release is visible. Missing or inconsistent ownership metadata fails closed.
An owning branch with no Environment cannot match an Environment-bound caller.

Require exactly one match **within that Environment**, then call the selected
release's `resolve_runtime_access()` for its backend-issued URL. The same name in
other Environments is neither an error nor a fallback. Zero matches report a
missing deployment in the selected Environment; multiple matches report duplicate
deployments within it. Neither error recommends a URL override or globally unique
deployment names. No first-result selection, SDK context reset, consumer branch
override, direct platform request or new platform endpoint is needed.

Existing SDK release-access operations may report a starting or unavailable
runtime. Such a result is not a successful endpoint resolution. Respect the
SDK's existing retry contract within a bounded timeout and report failure when
the target cannot be resolved. This decision introduces no new authentication
mechanism, credential type, account-binding policy or Organization policy.

### 3. Cache the endpoint once per process

Resolve lazily on the first operation that needs an API address. Cache a
successful result in process memory for the selected platform endpoint and
resolved Organization Environment. The entry holds the release UID and derived
deployment name. The discovery sequence obtains target metadata, verifies the
candidate owners' Environments and retrieves the endpoint; subsequent operations
reuse its result without repeating those platform lookups. Read the SDK-owned
process context when selecting the cache key; do not maintain a separate
Environment cache or reuse an endpoint after that context changes.

Concurrent first callers share one resolution attempt. Do not cache failed,
ambiguous, starting or unavailable results as successful entries. Later calls
can retry after a failed attempt. Forked or new processes start with their own
cache; no discovered address is persisted to disk.

The local URL is checked before consulting the discovery cache, so setting
`METATABLES_API_URL` takes effect even after automatic resolution. Configuration
and Environment changes invalidate the previous target's cache; an explicit client reset or
process restart also permits a fresh lookup, including reacquiring the name from
the packaged workflow. Editable installs observe workflow changes on that fresh
lookup; installed wheels use their immutable workflow snapshot. Stable configuration
has no periodic discovery or per-request platform identity preflight.

Keep the selected endpoint fixed for an in-flight operation, including a migration
lifecycle. Changing configuration between operations must not leave individual
models pinned to the previous target. An ordinary request failure does not
silently select another deployment or replay a mutation against a different API.

### 4. Keep endpoint discovery separate from runtime state

Amended 2026-10-01 ([MetaTables #9](https://github.com/mainsequence-projects/MetaTables/issues/9)):
the compiler's default is Environment → API deployment → fresh `/runtime-context/`
→ selected DataSource UID and SQL dialect. Consuming applications configure none
of these values. Runtime bootstrap and Settings remain operator responsibilities.
The client preserves the runtime descriptor's public `data_source` dictionary
and uses a shared validated UID accessor. Missing, unavailable or malformed source
metadata raises `DataSourceResolutionError`, including when the compiler is given
an isolated runtime descriptor. UID, dialect and parameter style must describe
the same source. Never combine an explicit different source UID with the runtime
source's inferred dialect. Supplying both a UID and dialect retains offline
compilation; execution still applies API source binding and grants.

Optional reads from another registered source use the imported MetaTable's source
through ADR 0010's bounded reader. They do not change the resolved API, runtime
default or write destination. General SQL on another source needs a separate
database-permission design; the client must not imply that an explicit UID grants
that capability. Document default compilation, offline compilation, source-specific
errors and the distinction between bounded external reads and runtime SQL.

Cache only the stable endpoint and the release identity needed to describe that
selection. Do not cache temporary release-access tokens, admission/readiness
decisions, permission facts or the API's effective DataSource with it. SDK session
and credential refresh remain governed by existing SDK behavior.

The release-access response supplies the existing release Bearer credential.
Keep it in a separate, memory-only SDK `SessionJWTAuthProvider`, outside the
endpoint cache and shared platform session. The SDK request helper retries a
401 once: reacquire access for the same release UID and reject a changed URL
instead of retargeting the request. This does not repeat name discovery or add an
authentication contract. Local development transports retain their existing
SDK session behavior.

The API's `/runtime-context/` response remains fresh under API ADR 0001. Resetting
local storage, selecting another DataSource or restarting the API can change
runtime state without changing its address. The endpoint cache must not hide
those changes or introduce client database access.

## Ownership and consequences

| Owner | Responsibility |
| --- | --- |
| MetaTables client | Read the packaged workflow, select the release in the SDK-owned Environment, enforce the local URL override, share and cache endpoints, and report resolution errors. |
| Main Sequence SDK/platform | Resolve the caller's Environment and provide authorized release discovery, owning-branch metadata and release access. |
| MetaTables API | Own the automatic deployment declaration, runtime descriptor, admission, Settings, bootstrap and its enforced DataSource binding. |

This is a separate client ADR because API runtime selection and storage ownership
do not change. API ADR 0001's prohibition on caching effective runtime context
remains in force. The Vite Admin site's connection configuration is outside this
Python-client decision.

Local explicit URL configurations continue to work. Existing hosted URL overrides
must be removed; Environment discovery replaces them. Hosted selection requires
SDK Environment context and authorized reads of candidate branch metadata. A
deleted or replaced deployment can require an explicit reset or process restart to discover a new
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
  name, UID or URL, including outside the consuming repository's branch but
  always within its resolved Environment.
- Identically named deployments in other Environments are ignored; a lone release
  in the wrong Environment cannot be selected. Missing Environment context,
  unverifiable ownership or duplicate releases within the selected Environment
  fail before runtime access. Test both signed-in and authenticated runtime context.
- Tests use distinct deployment-generated names and verify that a fresh lookup
  after an editable-workflow rename uses updated metadata without edits to
  consuming projects. Wheels retain their packaged deployment declaration.
  Missing or ambiguous metadata/names fail clearly without a constant fallback.
- Repeated and concurrent operations across resource classes and CLI consumers
  perform one successful discovery sequence per process and configuration.
- A local loopback URL bypasses all discovery, including Environment and
  automatic-deployment metadata retrieval and a populated cache, and preserves
  route prefixes. Invalid URLs and hosted URL overrides fail without discovery.
- Failed resolution remains retryable; reset, Environment/configuration changes and process
  forks do not reuse a stale target.
- Local explicit-URL operations still work on an unregistered branch without
  introducing a platform release or Environment requirement.
- Changing runtime state at an unchanged URL remains visible to the client.
  Endpoint caching does not retain DataSource state or temporary credentials.
- Resource calls and migration lifecycles consistently use their selected API;
  the resolver never redirects ordinary SDK platform requests to that API.
- Update connection guides, configuration reference and executable examples with
  automatic hosted discovery and local development selection once behavior is verified.
  Document removal of hosted URL overrides and Environment-specific deployment
  errors without suggesting URL or name workarounds. Keep dependency and
  authentication boundaries covered by the existing checks.

## References

- [Current client connection guide](../../client/installation-and-connection.md)
- [Current configuration reference](../../operations/configuration.md)
- [API runtime and storage decision](../api/0001-unified-api-storage-and-local-sqlite.md)
- [Architecture decisions by owner](../index.md)
