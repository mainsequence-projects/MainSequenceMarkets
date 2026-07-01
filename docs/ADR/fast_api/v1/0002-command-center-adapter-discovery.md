# FastAPI v1 Command Center Adapter Discovery

## Status

Implemented

## Success Condition

`apps/v1` remains backward compatible for all existing frontend routes while the
same API surface becomes discoverable by Main Sequence Command Center through
Adapter from API.

The implementation is successful only when:

- every existing `/api/v1/*` path, request model, response model, and
  `operationId` keeps its current behavior unless a separate ADR explicitly
  changes it;
- `GET /.well-known/command-center/connection-contract` exists and returns a
  strict adapter discovery document;
- `GET /health` exists and is the zero-argument health operation referenced by
  the adapter contract;
- `GET /openapi.json` remains available and is referenced by the adapter
  contract, but is not treated as the adapter source of truth;
- every current public `apps/v1` operation is listed in
  `availableOperations`;
- mutating endpoints are not exposed as query-capable operations;
- any endpoint that directly feeds generic tabular consumers returns the SDK
  `core.tabular_frame@v1` contract through `TabularFrameResponse`;
- provider-native responses stay provider-native, with optional
  `responseMappings` used only as metadata for frontend/editor context or a
  future explicit transform path.

Deployment, FastAPI ResourceRelease creation, Command Center connection
instance creation, and workspace wiring are intentionally out of scope for this
ADR.

## Context

The current `apps/v1` FastAPI surface already has documented Pydantic contracts
and stable route groups for assets, accounts, portfolios, virtual funds,
calendars, pricing curves, pricing market data, settings, and fixed income
pricing operations.

The current frontend consumes these routes directly. That behavior must remain
valid. Adapter from API support must therefore be additive metadata and
discovery over the same route set:

```text
existing direct frontend clients
  -> /api/v1/*

Command Center Adapter from API
  -> /.well-known/command-center/connection-contract
  -> /health
  -> /openapi.json
  -> existing /api/v1/* operations by operationId
```

The adapter skill defines the required provider-side contract:

- the well-known contract endpoint is the discovery source of truth;
- `/openapi.json` is supplementary documentation;
- health must be a trivial zero-argument operation;
- available operations must be explicitly allowlisted;
- operation IDs must be stable;
- public config and secret variables must be separated;
- provider-native JSON is not a canonical tabular frame just because a
  `responseMappings` entry exists;
- generic table, chart, statistic, curve, transform, and agent-facing
  consumers require an actual `core.tabular_frame@v1` payload at the consumption
  boundary.

The SDK public API tutorial also treats FastAPI as a project API surface and
shows the same project-resource deployment model. This ADR does not deploy the
API. It only plans the local API contract required before a release can be made.

## Decision

Make the existing `apps/v1` API adapter-ready without creating a shadow API.

The required adapter control surface consists only of:

```text
GET /health
GET /.well-known/command-center/connection-contract
```

These endpoints do not replace, wrap, or duplicate business routes. They only
let Command Center discover and call the existing `/api/v1/*` operations.

Implementation may keep the adapter control contract in dedicated files:

```text
apps/v1/routers/command_center.py
apps/v1/schemas/command_center_adapter.py
apps/v1/services/command_center_adapter.py
```

Those files are limited to adapter discovery and health. They must not define
business-route variants such as `/command-center/assets`, `/adapter/accounts`,
or any other duplicate route family.

The control router will be registered at the application root, not under
`/api/v1`, because the well-known path is a discovery endpoint for the deployed
API resource.

The adapter contract response will be strict Pydantic, with `extra="forbid"`.
Unknown fields should fail tests unless the contract version is intentionally
advanced.

## Required Adapter Control Endpoints

### Health

```text
GET /health
```

Purpose:

- provide a trivial health check for Adapter from API;
- avoid using a parameterized business route as health;
- avoid touching MetaTables or pricing runtime data paths.

Response model:

```json
{
  "status": "ok",
  "service": "apps/v1",
  "version": "0.0.49"
}
```

The exact version value comes from the installed `ms-markets` package version.

### Adapter Discovery

```text
GET /.well-known/command-center/connection-contract
```

Response model:

```json
{
  "contractVersion": 1,
  "adapter": {
    "type": "adapter-from-api",
    "id": "ms-markets.apps-v1",
    "title": "MainSequence Markets API",
    "description": "Adapter contract for the apps/v1 markets FastAPI surface."
  },
  "openapi": {
    "url": "/openapi.json",
    "version": "3.1.0",
    "checksum": null
  },
  "configVariables": [],
  "secretVariables": [],
  "availableOperations": [],
  "health": {
    "operationId": "getApiHealth",
    "expectedStatus": 200,
    "timeoutMs": 5000
  }
}
```

Implementation details:

- `openapi.url` should be resolved from the incoming request when possible, so
  deployed API resources can return an absolute URL.
- `openapi.checksum` should be a deterministic SHA-256 checksum of the
  canonical OpenAPI JSON if it can be computed without side effects; otherwise
  it remains `null`.
- `configVariables` is initially empty because this API does not require public
  adapter configuration to call its own deployed routes.
- `secretVariables` is initially empty. Do not invent API token variables until
  the deployment/auth model requires backend secret injection.
- request identity, access tokens, refresh tokens, and platform credentials must
  never be returned by the contract.

## Explicit Operation Registry

The adapter contract must expose every current public API operation, but it must
not discover or publish routes by blindly dumping every FastAPI route at runtime.

Add an explicit operation registry with stable operation IDs. The registry is an
allowlist in the sense that every exposed operation is intentionally described,
classified, and tested. It is not a partial rollout.

Read/query operations must be marked as query-capable. Mutating operations must
also be included, but they must never be marked as query-capable.

### System Operations

- `getApiHealth`

The well-known contract endpoint itself is the discovery document and does not
need to be treated as a normal business operation.

### Query And Read Operations

Settings:

- `getApiSettings`

Asset read operations:

- `listAssets`
- `getAsset`
- `getAssetSummary`
- `getAssetPricingDetails`

Asset category read operations:

- `listAssetCategories`
- `getAssetCategoryDetail`

Account read operations:

- `listAccounts`
- `getAccountSummary`
- `searchAccountTargetAllocationTargets`
- `getAccountHoldings`
- `getAccountHoldingsByFund`
- `getAccountTargetPositions`

Index read operations:

- `listIndexes`
- `getIndex`

Portfolio read operations:

- `listPortfolios`
- `getPortfolio`
- `getPortfolioSummary`
- `getPortfolioWeights`

Virtual fund read operations:

- `listVirtualFunds`
- `getVirtualFund`
- `getVirtualFundSummary`
- `getVirtualFundHoldings`

Calendar read operations:

- `listCalendars`
- `getCalendar`
- `getCalendarSummary`
- `listCalendarDates`
- `getCalendarDate`
- `listCalendarSessions`
- `getCalendarSession`
- `listCalendarEvents`
- `getCalendarEvent`

Pricing curve read operations:

- `listPricingCurves`
- `getPricingCurveSummary`
- `listPricingCurveSelections`
- `getPricingDiscountCurve`

Pricing market-data read operations:

- `getPricingMarketDataCard`
- `listPricingMarketDataSets`
- `getPricingMarketDataSetByKey`
- `getPricingMarketDataSet`
- `listPricingMarketDataBindings`
- `listPricingMarketDataSetBindings`
- `resolvePricingMarketDataBinding`
- `getPricingMarketDataBinding`

Fixed income pricing operations:

- `priceFixedIncomeAsset`
- `getFixedIncomeAssetAnalytics`
- `getFixedIncomeAssetDuration`
- `getFixedIncomeAssetYield`
- `getFixedIncomeAssetZSpread`
- `getFixedIncomeAssetCashflows`
- `getFixedIncomeAssetCashflowsFrame`
- `getFixedIncomeAssetNetCashflows`
- `getFixedIncomeAssetNetCashflowsFrame`
- `getFixedIncomeAssetCarryRollDown`
- `previewFixedIncomeAssetCurve`
- `checkFixedIncomeAssetFixingsAvailability`

### Mutation Operations

Asset operations:

- `deleteAsset`

Asset category operations:

- `createAssetCategory`
- `bulkDeleteAssetCategories`
- `updateAssetCategory`
- `deleteAssetCategory`

Account operations:

- `addAccountHoldings`
- `addAccountTargetPositions`

Index operations:

- `deleteIndex`

Portfolio operations:

- `bulkDeletePortfolios`
- `deletePortfolio`
- `deletePortfolioWeights`

Calendar operations:

- `createCalendar`
- `updateCalendar`
- `deleteCalendar`
- `createCalendarDate`
- `bulkUpsertCalendarDates`
- `updateCalendarDate`
- `deleteCalendarDate`
- `createCalendarSession`
- `bulkUpsertCalendarSessions`
- `updateCalendarSession`
- `deleteCalendarSession`
- `createCalendarEvent`
- `bulkUpsertCalendarEvents`
- `updateCalendarEvent`
- `deleteCalendarEvent`

Pricing market-data operations:

- `createPricingMarketDataSet`
- `upsertPricingMarketDataSet`
- `updatePricingMarketDataSet`
- `deletePricingMarketDataSet`
- `createPricingMarketDataBinding`
- `upsertPricingMarketDataBinding`
- `updatePricingMarketDataBinding`
- `deletePricingMarketDataBinding`

Rules for mutation exposure:

- `kind` must be `mutation` or another explicit non-query kind supported by the
  adapter runtime.
- `capabilities` must not include `query`.
- `requestBody` must be explicit for POST/PATCH/DELETE operations that require
  body data.
- `cache.enabled` must be `false`.
- destructive operations must remain discoverable as operations, but clients
  should decide how to render confirmation and permission UI from the operation
  metadata and response contract.

## Operation Metadata Shape

Every operation in `availableOperations` must include:

```json
{
  "operationId": "listAssets",
  "label": "List assets",
  "description": "List assets from the apps/v1 public API.",
  "method": "GET",
  "path": "/api/v1/asset/",
  "kind": "query",
  "capabilities": ["query"],
  "requiresTimeRange": false,
  "supportsVariables": true,
  "supportsMaxRows": true,
  "parameters": [],
  "requestBody": null,
  "responseMappings": [],
  "cache": {
    "enabled": true,
    "ttlSeconds": 30
  }
}
```

Rules:

- `path` is relative to the deployed API root and must include `/api/v1` for
  existing business routes.
- `operationId` must match the FastAPI route `operation_id` exactly.
- `supportsMaxRows` should be true only for operations that expose `limit` or a
  bounded equivalent.
- mutating endpoints must be included but must not be marked with `query`
  capability.
- POST pricing operations can be query operations because they are read-only
  calculations, but their request body metadata must be explicit.
- cache TTLs must be conservative and operation-specific. Use `enabled=false`
  for routes where results depend on live runtime state and no cache behavior is
  safe yet.

Mutation example:

```json
{
  "operationId": "deleteAsset",
  "label": "Delete asset",
  "description": "Delete one asset by uid.",
  "method": "DELETE",
  "path": "/api/v1/asset/{uid}/",
  "kind": "mutation",
  "capabilities": ["mutation"],
  "requiresTimeRange": false,
  "supportsVariables": true,
  "supportsMaxRows": false,
  "parameters": [
    {
      "name": "uid",
      "in": "path",
      "required": true,
      "type": "string"
    }
  ],
  "requestBody": null,
  "responseMappings": [],
  "cache": {
    "enabled": false,
    "ttlSeconds": null
  }
}
```

## Response Mapping Policy

Provider-native responses remain provider-native.

Mappings may be provided for editor/frontend metadata, but must not claim
runtime conversion into `core.tabular_frame@v1`.

Initial mapping rules:

- paginated list endpoints can advertise `rowsPath: "$.results"`;
- holdings endpoints can advertise rows under `$.holdings`;
- target-position endpoints can advertise rows under `$.positions`;
- by-fund holdings can advertise fund rows under `$.funds` and residual rows
  under `$.residuals` as separate mappings;
- fixed income cashflow provider-native endpoints can advertise their existing
  metadata mappings;
- existing endpoints whose response model is `TabularFrameResponse` can be
  advertised as direct canonical frame operations.

If a generic Command Center consumer needs direct tabular data, it should use an
operation whose response model is `TabularFrameResponse`, or an explicit
adapter/transform path. It should not bind raw provider-native JSON directly.

This ADR does not introduce new business endpoints just to create additional
canonical frames. Any future direct frame route is a separate business/API
design decision.

## Implementation Tasks

- [x] Add strict adapter contract schemas in
  `apps/v1/schemas/command_center_adapter.py`.
- [x] Add `apps/v1/services/command_center_adapter.py` with the curated
  operation registry and OpenAPI checksum helper.
- [x] Add `apps/v1/routers/command_center.py` with:
  - [x] `GET /health`;
  - [x] `GET /.well-known/command-center/connection-contract`.
- [x] Register the command-center router in `apps/v1/main.py` without a
  `/api/v1` prefix.
- [x] Ensure the contract references the current OpenAPI URL and uses the
  deployed request base URL when available.
- [x] Add tests in `tests/msm/fastapi/v1/` for:
  - [x] health response shape;
  - [x] well-known contract required fields;
  - [x] `adapter.type == "adapter-from-api"`;
  - [x] `health.operationId` exists in `availableOperations`;
  - [x] every allowlisted `operationId` exists in `/openapi.json`;
  - [x] every current public `operationId` is present in `availableOperations`;
  - [x] mutating operations are present with non-query `kind` and without the
    `query` capability;
  - [x] mutating operations have `cache.enabled=false`;
  - [x] direct frame operations use `TabularFrameResponse`;
  - [x] provider-native mappings do not mark the operation as a direct frame.
- [x] Update `docs/fast_api/v1/index.md` with the new discovery and health
  endpoints.
- [x] Update any frontend handoff docs that refer to Command Center discovery.

## Compatibility Rules

- Do not move existing routes.
- Do not rename existing `operationId` values.
- Do not alter existing response payloads for direct frontend clients.
- Do not replace provider-native endpoints with `TabularFrameResponse`.
- Do not add duplicate business endpoints as part of adapter-readiness.
- Expose mutation endpoints in the adapter contract with explicit non-query
  semantics, request body metadata, and disabled cache.

## Consequences

Positive:

- Command Center can discover the API through a single well-known contract.
- Existing frontend clients continue using the same routes.
- Operation exposure becomes explicit and reviewable.
- Generic tabular consumers can identify which existing operations already
  return canonical frame contracts and which provider-native operations require
  a transform path.
- Provider-native response mappings remain useful metadata without pretending to
  be runtime transformations.

Tradeoffs:

- The operation registry must stay aligned with route `operationId` values.
- Some provider-native endpoints will still require an adapter/transform path
  before they can feed generic tabular widgets.
- Mutating workflows become discoverable through Adapter from API, which means
  their operation metadata must stay accurate enough for clients to render
  confirmation, permission, and request-body UI correctly.

## Validation

Run after implementation:

```text
.venv/bin/python -m pytest tests/msm/fastapi/v1
.venv/bin/python -m ruff check apps/v1 tests/msm/fastapi/v1
.venv/bin/python -m ruff format --check apps/v1 tests/msm/fastapi/v1
.venv/bin/python -c "import apps.v1.main; print(apps.v1.main.API_TITLE)"
.venv/bin/python -m mkdocs build --strict
git diff --check
```

If platform state is being verified, separately check the FastAPI project
resource and ResourceRelease through the Main Sequence platform workflow. That
is outside this ADR's implementation scope.
