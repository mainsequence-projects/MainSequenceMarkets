# 0034. Command Center Asset Monitor Helpers

## Status

Accepted - implementation not started

## Success Condition

`ms-markets` exposes a reusable Command Center helper layer for the Asset
Monitor workflow without forcing downstream projects to hand-roll widget
contracts, tabular-frame payloads, or workspace wiring.

The implementation is successful only when:

- a reusable package section exists for Command Center helpers;
- Asset Monitor data is published as an actual `core.tabular_frame@v1`
  response, not as provider-native paginated JSON with an implicit frontend
  transform;
- helper functions bind `AssetTable` identity to the Asset Screener field
  expectations;
- related asset detail fields, especially ticker and OpenFIGI-derived fields,
  can be included without replacing `AssetTable` identity;
- downstream projects can import the helpers and expose their own API operation
  without depending on this repository's `apps/v1` application;
- this repository's `apps/v1` API exposes a dedicated asset monitor frame
  operation as a reference implementation;
- Adapter from API discovery advertises the operation as a canonical tabular
  frame operation;
- workspace helpers can wire a `connection-query` source widget into
  `ms-markets-asset-screener`;
- documentation and skills describe the helper contract, CLI workflow, and
  verification checks.

This ADR does not implement the helpers. It defines the package boundary and
contract that the implementation must follow.

## Context

`ms-markets` already has a local `apps/v1` FastAPI surface that can be consumed
by Command Center through Adapter from API. That application is only one
consumer of the library. Other Main Sequence projects should be able to import
the Command Center helpers and expose their own API operation, using their own
route layout, deployment model, authentication, and data-loading policy.

The existing adapter discovery ADR requires generic tabular consumers to
receive a real `core.tabular_frame@v1` payload at the consumption boundary.

The current generic asset list operation is useful for direct API clients:

```text
GET /api/v1/asset/
operationId: listAssets
```

However, that operation is a provider-native paginated response. It is not the
right long-term source for an Asset Screener or Asset Monitor widget because the
widget consumes `core.tabular_frame@v1` through a source widget output and
expects asset-facing fields such as:

```text
unique_identifier
Symbol
```

Using `listAssets` plus a response mapping is acceptable as a temporary
workspace-wiring check, but it hides the real data contract in frontend glue.
Library extenders need a stable helper layer that builds the correct frame
shape from market-domain objects.

The first target workflow is:

```text
apps/v1 FastAPI API
  -> command_center.adapter_from_api connection
  -> connection-query source widget
  -> ms-markets-asset-screener visible widget
```

The package also needs a clearer home for Command Center-specific helpers and
skills. Workspace instructions currently live under a workspace-oriented skill
path. The Asset Monitor workflow should instead be nested under the
`ms-markets` Command Center area because it covers reusable contracts,
provider API shape, workspace wiring, and verification.

## Decision

Create a new reusable Command Center helper section for `ms-markets`.

The helper layer is library code. It is not an `apps/v1` implementation detail.
`apps/v1` is the first in-repository reference API that will consume the
helpers, but downstream projects must be able to build their own API surfaces on
top of the same helpers.

The target package root is:

```text
src/command_center/
```

This package owns `ms-markets` helper code for Command Center contracts,
market-widget payloads, and workspace document helpers. It must stay thin and
domain-specific. It must not become a generic replacement for the Main Sequence
SDK Command Center client.

If implementation discovers an import/package-name conflict with SDK or
platform packages, the fallback package name is:

```text
src/msm_command_center/
```

That fallback requires an amendment to this ADR before implementation continues.

## Package Layout

Use this initial layout:

```text
src/command_center/
  __init__.py
  contracts/
    __init__.py
    tabular.py
  widgets/
    __init__.py
    asset_monitor.py
  workspaces/
    __init__.py
    asset_monitor.py
```

The package boundaries are:

- `contracts.tabular`: generic helpers for constructing SDK-compatible
  `TabularFrameResponse` payloads.
- `widgets.asset_monitor`: asset-domain frame, column, field, and metadata
  builders for `ms-markets` Asset Monitor workflows.
- `workspaces.asset_monitor`: JSON helper functions for Command Center
  workspace documents that wire a source widget into the Asset Screener widget.

FastAPI route handlers remain in `apps/v1`. They may call these helpers, but
the helper package must not depend on FastAPI request objects, route modules,
or application startup.

External projects may import the helper package from their own FastAPI,
Streamlit, job, or API-resource code. Those callers own data loading, request
identity, authorization, routing, pagination parameters, and deployment. The
helper package owns only the Command Center payload contract and ms-markets
widget-specific frame semantics.

## Tabular Frame Contract

Add a small helper layer around the SDK Command Center tabular models:

```python
build_tabular_frame(
    *,
    columns,
    rows,
    fields=None,
    meta=None,
    source=None,
)
```

The helper should return the SDK `TabularFrameResponse` model. It should not
return untyped dictionaries except at explicit serialization boundaries.

This layer exists so every ms-markets Command Center widget helper produces the
same canonical shape:

```text
status
columns
rows
fields
meta
source
```

The canonical frame helper must not silently convert provider-native responses
into frames without the caller explicitly choosing that behavior.

## Asset Monitor Frame Contract

Add Asset Monitor helpers such as:

```python
asset_monitor_columns(...)
asset_monitor_fields(...)
asset_monitor_meta(...)
build_asset_monitor_frame(...)
```

The minimum frame columns are:

```text
uid
unique_identifier
Symbol
asset_type
```

Recommended enrichment columns from related detail tables include:

```text
ticker
name
figi
composite_figi
exchange_code
security_type
security_market_sector
currency
```

The binding rules are:

- `unique_identifier` is the stable market asset key.
- `uid` is the backend row identifier.
- `Symbol` is the widget-facing display symbol. For the first implementation,
  it should resolve from ticker when available and otherwise fall back to
  `unique_identifier`.
- ticker and OpenFIGI fields enrich the monitor; they do not replace
  `AssetTable` identity.
- helper inputs should be already-loaded rows or row-like objects. The helper
  should not start `msm.start_engine(...)`, query MetaTables, or register
  schemas.

The frame metadata should identify the asset-role fields in a stable place
under `meta`, for example:

```text
marketAsset.assetKeyField = unique_identifier
marketAsset.uidField = uid
marketAsset.displayField = Symbol
```

The exact metadata object may evolve with the registered widget contract, but
the helper must keep the same intent: the frame declares which fields represent
asset identity and display.

## Provider API Operation

Any project exposing the Asset Monitor widget through Adapter from API should
provide a dedicated Asset Monitor frame operation. The recommended operation
shape is:

```text
GET /api/v1/asset/monitor/frame/
operationId: getAssetMonitorFrame
response contract: core.tabular_frame@v1
```

The path may differ in downstream projects, but the operation ID and response
contract should remain stable when the API is intended to be consumed by the
standard workspace helper.

This repository's `apps/v1` surface should add that operation as the reference
implementation. Other projects can expose the same operation from their own API
code by importing the helper package and passing already-loaded asset rows and
detail rows into the frame builder.

The operation should support the normal list controls:

```text
search
limit
offset
asset_type
```

Search behavior must align with the asset search service:

```text
AssetTable.unique_identifier contains search
related ticker contains search
```

The endpoint should return `TabularFrameResponse` directly. It should not
return a provider-native asset list response with a `responseMappingId`.

## Adapter Discovery

Update Adapter from API discovery for any provider API that exposes this helper
so the operation is available as a query-capable tabular operation:

```text
operationId: getAssetMonitorFrame
contract: core.tabular_frame@v1
query model: api-operation
```

For this operation, `responseMappings` should not be required because the
operation already returns the canonical frame consumed by `connection-query`.

The existing `listAssets` operation should remain available for direct API
clients and provider-native workflows. It should not be reclassified as a
tabular-frame operation unless its response model changes in a separate ADR.

## Workspace Helper

Add a helper for the standard Asset Monitor workspace chain:

```python
build_asset_monitor_workspace_document(
    *,
    connection_id,
    operation_id="getAssetMonitorFrame",
    title="Main Sequence Market Asset Monitor",
    max_rows=500,
)
```

The helper should produce a workspace document with:

```text
connection-query source widget
  queryModelId: api-operation
  operationId: getAssetMonitorFrame
  output: dataset

ms-markets-asset-screener visible widget
  binding seedData <- source dataset
```

The helper must not hardcode local URLs, tokens, or secrets. Endpoint
configuration belongs to the `command_center.adapter_from_api` connection, not
to widget props.

## Documentation And Skill Layout

Add a Command Center documentation section before or during implementation:

```text
docs/command_center/index.md
docs/command_center/asset_monitor.md
```

The documentation must explain:

- the Asset Monitor tabular-frame contract;
- required and optional columns;
- how `AssetTable` identity maps to widget-facing fields;
- how ticker and OpenFIGI details enrich the frame;
- the `getAssetMonitorFrame` operation;
- Adapter from API discovery expectations;
- CLI creation and verification commands for the connection and workspace.

Move the existing Asset Monitor skill under the ms-markets Command Center skill
area:

```text
.agents/skills/ms_markets/command_center/asset_monitor/SKILL.md
```

The skill should cover:

- helper development;
- API contract verification;
- Adapter from API connection setup;
- workspace JSON creation;
- `connection-query` to `ms-markets-asset-screener` binding;
- post-creation verification.

The old workspace-oriented skill path should either be removed or replaced with
a short redirect note so future agents use the Command Center location.

## Validation Requirements

Implementation should include focused tests for:

- `build_tabular_frame(...)` returns the SDK `TabularFrameResponse` shape;
- `build_asset_monitor_frame(...)` includes `unique_identifier` and `Symbol`;
- ticker/OpenFIGI enrichment works when detail rows are available;
- missing detail rows do not break frame generation;
- Adapter from API discovery advertises `getAssetMonitorFrame` as
  `core.tabular_frame@v1`;
- workspace helper output binds `connection-query.dataset` to
  `ms-markets-asset-screener.seedData`.

Manual verification should include:

```bash
curl -sS "http://127.0.0.1:8000/api/v1/asset/monitor/frame/?search=BONO&limit=25&offset=0"
curl -sS "http://127.0.0.1:8000/.well-known/command-center/connection-contract"
```

Platform verification should still use the Command Center CLI to inspect:

```text
connection type command_center.adapter_from_api
connection instance Main Sequence Market
registered widget type connection-query
registered widget type ms-markets-asset-screener
workspace detail widget bindings
```

## Consequences

Positive consequences:

- downstream projects get a reusable, tested helper path for Asset Monitor
  widgets;
- Asset Monitor data has an explicit backend contract instead of relying on
  implicit frontend transforms;
- the API can continue serving provider-native asset lists without weakening
  Command Center tabular consumers;
- future ms-markets Command Center widgets can reuse the same contract helper
  pattern.

Tradeoffs:

- this adds a new package area that must stay aligned with SDK Command Center
  model changes;
- the first implementation must maintain both `listAssets` and
  `getAssetMonitorFrame`;
- widget-specific metadata may need adjustment if the Asset Screener registry
  contract evolves.

Rejected alternatives:

- Use `listAssets` plus `responseMappingId=results` as the final Asset Monitor
  source. This keeps the workspace easy to mount, but it does not publish the
  widget-ready `core.tabular_frame@v1` contract.
- Put all transformation logic inside `apps/v1` route handlers. This would work
  for the local API but would not give library extenders reusable helpers.
- Store endpoint URLs or API details in widget props. Connection configuration
  owns endpoint binding; widgets should consume connection outputs.
