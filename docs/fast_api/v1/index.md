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

## API Discoverability

- `GET /openapi.json`
  - includes Redocly-compatible `info.x-logo` metadata for Main Sequence
    Markets branding
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

## Compatibility Notes

The `response_format=frontend_list` and `response_format=frontend_detail`
query parameters are still accepted on migrated legacy routes, but list and
direct detail rows now prefer core library API models over frontend projections.

The nested category asset table should use `GET /api/v1/asset/` with
`categories__uid`. The dedicated `POST /api/v1/asset/query/` route is still
future work for this local API.

## Validation

The focused FastAPI coverage for this surface lives under:

- `tests/msm/fastapi/v1/`

Use `/openapi.json`, `/docs`, and `/redoc` from the local app for contract
inspection.
