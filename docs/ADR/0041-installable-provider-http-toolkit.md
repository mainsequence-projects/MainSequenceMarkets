# 0041. Installable Provider HTTP Toolkit

## Status

Accepted.

## Context

The project FastAPI app already owned strict Command Center collection,
discovery, and bulk-action contracts, but those implementations lived under
the repository-only `apps/v1` tree. Alpaca, Binance, and future provider
CodeRepositories need the same infrastructure while retaining provider-owned
registration, account, holdings, and credential behavior.

Copying the app modules into every provider would make fixes and contract
upgrades diverge. Publishing the generic top-level `apps` package would also
create an unbranded import namespace and incorrectly make this repository's
complete API application the provider integration surface.

## Decision

Publish provider-neutral HTTP infrastructure under `msm.api.http`, which is
already included by the wheel's `src/msm` package boundary. This package owns:

- strict Command Center collection, discovery, bulk execution, and preflight
  models;
- reusable collection, discovery, and explicit-selection builders;
- sanitized structured HTTP error mapping; and
- generic owner-scoped observable-operation models and lifecycle storage.

Keep provider-specific discovery declarations, route composition, domain
services, permissions, credentials, and mutations in each provider project.
Keep the existing `apps/v1` import paths as compatibility shims for this
repository's deployed API.

The bundled `InMemoryOperationStore` is explicitly a one-process tool. Durable
or multi-worker deployments persist the same operation contract in a shared
provider-owned repository and preserve owner filtering.

## Consequences

Provider projects can depend on a tagged `ms-markets` release and share the
same validated API infrastructure without importing repository source files.
The existing FastAPI v1 wire contracts remain unchanged. Provider-specific API
behavior continues to evolve independently behind a consistent reusable
boundary.
