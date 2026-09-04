# FastAPI v1

The local `apps/v1` FastAPI app exposes the migrated public asset registry
surface for this repository.

## Scope

This API is intentionally thin:

- route declarations, validation, and OpenAPI metadata live under `apps/v1`
- reusable asset category workflows live under `src/msm/services`
- asset, category, and index frontend route composition is backed by
  `src/msm/services/asset_master_lists.py`
- pricing curve registry, market-data set, and binding workflows are backed by
  `msm_pricing.api`
- portfolio detail and latest-weight workflows are backed by
  `src/msm_portfolios/services`
- virtual-fund identity and holdings snapshot workflows are backed by
  `src/msm/services/accounts/virtual_funds_public_api.py`

## Route Reference

- [Settings Route](settings.md): read-only app settings and runtime
  assumptions for frontend clients.
- [Account Routes](accounts.md): route group for account identity, holdings
  snapshots, and target-position assignment.
- [Asset Routes](assets.md): route group for the asset registry and asset
  categories, including the Command Center monitor frame.
- [Index Routes](indexes.md): route group for index registry reads,
  delete-impact preflight, and index delete.
- [Calendar Routes](calendars.md): route group for calendar identity CRUD,
  summary, and date, session, and event maintenance.
- [Pricing Market Data Routes](pricing_market_data.md): route group for
  pricing market-data set and concept binding management.
- [Fixed Income Pricer Routes](fixed_income_pricer.md): route group for
  method-backed bond pricing operations over assets with current pricing
  details.
- [Pricing Curve Routes](pricing_curves.md): route group for pricing curve
  registry lists.
- [Portfolio Routes](portfolio.md): route group for portfolio identity,
  detail-page composition, latest weights, and delete operations.
- [Portfolio Group Routes](portfolio_groups.md): route group for many-to-many
  portfolio classification and membership lookups.
- [Portfolio Signal Metadata Routes](portfolio_signal_metadata.md): route
  group for signal metadata list/detail/write operations and signal-weight
  storage cleanup.
- [Virtual Fund Routes](virtualfund.md): route group for account-owned
  virtual-fund identity and holdings snapshots.
- [Command Center Bulk Actions](command_center_bulk_actions.md): SDK-contract
  discovery, preflight, and execution for destructive collection actions.
- [Command Center Resource Contracts](resource_contracts.md): the canonical
  collection, discovery, detail, summary, and action boundaries for all lists.

## Design Decisions (ADRs)

These FastAPI v1 decisions live in the single
[ADR tree](../../ADR/README.md):

- [Calendar CRUD And Summary Route](../../ADR/fast_api/v1/0001-calendar-crud-route.md):
  route group for calendar identity CRUD, summary, and bounded date, session,
  and event maintenance.
- [Command Center Adapter Discovery](../../ADR/fast_api/v1/0002-command-center-adapter-discovery.md):
  additive Adapter from API discovery contract for Command Center without
  breaking existing `/api/v1` clients.
- [Fixed Income Pricer API](../../ADR/fast_api/v1/0003-fixed-income-pricer-api.md):
  registry-driven pricing workbench API for price, analytics, duration, yield,
  z-spread, cashflows, carry/roll-down, curve preview, and fixings availability.
- [Reusable Delete Impact Contract](../../ADR/fast_api/v1/0004-delete-impact-contract.md):
  shared preflight serializer and route pattern for inspecting individual
  destructive delete effects before deletion.

## Runtime Bootstrap

`apps/v1` performs startup-time runtime attachment instead of waiting for the
first request to hit a row operation. `MSM_AUTO_REGISTER_NAMESPACE` may override
the namespace for local development; when it is not set, the runtime uses the
default markets namespace from `msm.settings.markets_namespace()`.

Current local-dev behavior:

- the app calls `msm_portfolios.start_engine(...)` during startup for the
  `apps/v1` table set because this surface includes portfolio-backed account
  target-position routes
- the startup table set includes portfolio-backed target-position tables, so
  target-position routes resolve against the existing shared markets runtime
  instead of starting a second portfolio runtime on first request
- the startup table set includes `PortfolioMetadata` and
  `PortfolioWeightsStorage` so portfolio detail and latest-weights routes use
  the same shared markets runtime
- the startup table set includes `VirtualFund`, `VirtualFundHoldingsSet`, and
  `VirtualFundHoldingsStorage` so virtual-fund routes attach to the shared
  markets runtime
- the app calls `msm_pricing.bootstrap.attach_pricing_schemas(...)` during
  startup for the pricing rows used by asset pricing details, curve registry
  lists, and pricing market-data management
- the pricing startup table set includes `AssetPricingDetailsStorage` because
  the current-pricing-details row API requires both the timestamped storage
  table and the current projection table to be attached before row operations
- index delete-impact preflight attaches `FutureAssetDetails` and
  `IndexFixingsStorage` so the API can report restrictive dependencies before
  an index delete is attempted
- schema mutation must already have been handled by
  `mainsequence migrations upgrade --provider migrations:migration head`
- the app uses the real project/session data source already configured for the
  Main Sequence client session
- if the session cannot resolve a valid DynamicTable data source, startup
  should fail instead of redirecting writes into an ad hoc local store

### Local full-stack debugging

The sibling `mainsequencemarketssite` repository owns the VS Code compound launcher for local
frontend/API debugging. Its **Markets: Full Stack** configuration runs
`apps.v1.dev_cors:app` with the project `.venv` under `debugpy` on
`http://127.0.0.1:8001`, and runs the Vite frontend on `http://127.0.0.1:3010` with that exact API
origin. The development wrapper admits ports 3010 and 5173 for both `localhost` and `127.0.0.1`;
the deployed `api.main:app` surface is not mutated. The launcher leaves
`MSM_AUTO_REGISTER_NAMESPACE` unset in accordance with the local runtime bootstrap contract.

## Platform Deployment

The application implementation remains under `apps/v1`. The thin
`api/main.py` module re-exports the same FastAPI `app` object because Main
Sequence discovers deployable FastAPI resources from `api/**/main.py` paths.
It contains no route, schema, service, or runtime logic.

The release is managed by
`.mainsequence/workflows/fastapi.yaml`. The declaration uses workflow API
`2.1.0`, retains three release revisions for rollback, and its
automatic-redeployment policy follows every synchronized
`main` commit (`tag_regex: null`). The backend resolves the verified image for
the exact eligible commit, so the workflow must not contain a
`related_image_uid`. It requests the standard API capacity of `0.25` vCPU and
`0.5` GiB on non-spot infrastructure. The release admits the supported
`https://*.site-dev.main-sequence.app` origin so the Main Sequence Markets
static-site release can use the Command Center SDK delegated FastAPI transport.
The frontend identifies this release by its stable ResourceRelease UID; the SDK
resolves the current opaque RPC endpoint at request time after every automatic
API redeployment.

Use `mainsequence code-repository sync --path . -m "<message>"` to publish
repository changes. A successful sync triggers the backend-owned image build
and release rotation; use the deployment-run interfaces to verify the terminal
state and logs instead of treating the Git push alone as deployment success.

Runtime dependencies must be resolvable from the backend build environment.
The published `ms-markets` 1.x package therefore declares
`mainsequence>=8.0.7` without an exact SDK patch pin. The lower bound enforces
the SDK 8 CodeRepository hard cut, while the project lock and exported runtime
requirements select the exact SDK release validated for this repository. Do
not replace the published dependency with a machine-local `[tool.uv.sources]`
path override.

## API Discoverability

- `GET /openapi.json`
  - includes Redocly-compatible `info.x-logo` metadata for Main Sequence
    Markets branding
  - declares every operation summary and description, all used tags, stable tag groups, and the
    [API source repository](https://github.com/mainsequence-projects/MainSequenceMarkets)
  - derives canonical row and field descriptions from the backing MetaTable metadata instead of
    maintaining a second description inventory in the FastAPI layer
  - uses the local emblem served by this FastAPI app at
    `/static/main-sequence-markets/main_sequence_markets_icon_emblem_transparent.png`
- `GET /docs`
  - serves the Swagger UI for interactive inspection
- `GET /redoc`
  - serves the ReDoc view; consumers that support `info.x-logo` can render the
    configured logo
- `GET /health`
  - returns a zero-argument health payload for API discovery
  - response is `{ status, service, version }`
  - does not touch MetaTables, pricing runtime data paths, or request identity
- `GET /.well-known/command-center/connection-contract`
  - returns the Adapter from API discovery contract for the existing
    `apps/v1` FastAPI operations
  - references `/openapi.json`
  - lists every public `/api/v1/*` operation by its existing `operationId`
  - classifies read/calculation operations as `query`
  - classifies create/update/delete/write operations as `mutation`
  - disables cache metadata for mutation operations and non-GET calculations
  - keeps provider-native responses provider-native and exposes optional
    `responseMappings` only as metadata
  - advertises `getAssetMonitorFrame` as a direct
    `core.tabular_frame@v1` query operation for Command Center Asset Monitor
    workspaces

## Resource contract cutover

All list operations return `command-center.resource_collection@v1`, and each
has an authoritative sibling `/discovery/` operation. The retired
`response_format` selectors, DRF-style pagination envelopes, and standalone
`/bulk-actions/` discovery endpoints are not part of the API.

The nested category asset table should use `GET /api/v1/asset/` with
`categories__uid`. The dedicated `POST /api/v1/asset/query/` route is still
future work for this local API.

## Validation

The focused FastAPI coverage for this surface lives under:

- `tests/msm/fastapi/v1/`

Use `/openapi.json`, `/docs`, and `/redoc` from the local app for contract
inspection.

Export a deterministic reviewed snapshot for downstream documentation or client generation with:

```bash
.venv/bin/python -m scripts.export_apps_v1_openapi --output /absolute/path/to/openapi.json
```

The downstream repository owns its pinned snapshot. Its production documentation build must not
fetch a live API release or import this repository at runtime.
