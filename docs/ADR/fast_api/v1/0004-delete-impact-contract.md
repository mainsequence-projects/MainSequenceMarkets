# FastAPI v1 Reusable Delete Impact Contract

## Status

Implemented

## Date

2026-06-30

## Success Condition

`apps/v1` has one reusable delete-impact request and response contract that can
be used before individual destructive delete routes. The first adopter is the
index delete preflight route, but the contract must be reusable by future asset,
portfolio, category, calendar, pricing, and group delete routes without copying
resource-specific Pydantic serializers.

The implementation is successful only when:

- destructive routes remain individual routes such as
  `DELETE /api/v1/index/{uid}/`;
- no bulk index delete route is introduced;
- every interactive destructive delete route can expose a read-only
  `GET .../delete-impact/` preflight route;
- the preflight serializer is shared under `apps/v1/schemas/`;
- resource-specific services still own the domain-specific relationship labels,
  counts, and effects;
- Command Center Adapter from API exposes delete-impact operations as read-only
  query operations, not mutations;
- OpenAPI documents one stable reusable response schema instead of one
  bespoke schema per resource.

## Context

The initial index delete preflight route used this FastAPI response boundary:

```python
response_model=IndexDeleteImpactResponse
```

That Pydantic model is the serializer. In `apps/v1`, the serializer is the
declared FastAPI `response_model`, usually implemented as a strict Pydantic
model under `apps/v1/schemas/`.

`IndexDeleteImpactResponse` was correct as a first narrow implementation, but it
should not become the pattern for every resource. Delete-impact is an API-wide
interaction contract:

```text
inspect the impact of deleting this one resource before the destructive delete
route is called
```

That interaction is reusable even though each resource has different
dependencies. For example, index deletion currently needs to explain:

- blocking direct references from `FutureAssetDetailsTable`;
- blocking fixing rows in `IndexFixingsStorage`;
- non-blocking `SET NULL` effects from `PortfolioTable.published_index_uid`;
- non-blocking cascade effects from `IndexConventionDetailsTable`;
- indirect restrictive curve references that can block the convention cascade.

A raw foreign-key graph is not enough for the public response. The API must
return curated dependency rows with user-facing labels and effects.

Delete-impact responses are provider-native business JSON. They are not
`core.tabular_frame@v1` payloads and should not use `TabularFrameResponse`.
Command Center may call them through Adapter from API as query operations, but
generic tabular widgets should not treat them as direct tabular data.

## Decision

Introduce a reusable delete-impact schema module:

```text
apps/v1/schemas/delete_impact.py
```

The shared serializer names are:

```python
DeleteImpactRequest
DeleteImpactRelationship
DeleteImpactResponse
```

`DeleteImpactRequest` is the reusable preflight request contract. For the
standard individual resource pattern, path parameters provide the resource UID
and the route does not need a request body. If a future route needs additional
preflight options, they should be bound as explicit query parameters or a
strict request model with these semantics:

```json
{
  "include_samples": false,
  "sample_limit": 0
}
```

Samples are intentionally opt-in and should default to disabled. Count-only
impact summaries are the default because they are safer and cheaper.

`DeleteImpactResponse` is the reusable response serializer:

```json
{
  "resource_type": "index",
  "uid": "resource-uid",
  "identifier": "MX-TIIE",
  "display_name": "TIIE",
  "can_delete": false,
  "blocking_count": 7,
  "affected_count": 11,
  "delete_endpoint": "/api/v1/index/resource-uid/",
  "relationships": [],
  "warnings": []
}
```

The response fields mean:

- `resource_type`: stable API resource key, for example `index` or
  `portfolio`;
- `uid`: UID of the resource being deleted;
- `identifier`: stable business identifier when available;
- `display_name`: user-facing label;
- `can_delete`: false when currently blocking relationships exist;
- `blocking_count`: total count across relationships that block deletion;
- `affected_count`: total count across all reported relationships;
- `delete_endpoint`: the individual destructive delete route;
- `relationships`: one row per relevant dependency or side effect;
- `warnings`: user-facing summary warnings derived from the relationship rows.

`DeleteImpactRelationship` is strict and reusable:

```json
{
  "key": "index_fixings",
  "label": "Index fixings",
  "model": "IndexFixingsStorage",
  "column": "index_identifier",
  "relationship_type": "direct",
  "on_delete": "RESTRICT",
  "count": 2,
  "effect": "blocks_delete",
  "severity": "blocking",
  "blocks_delete": true,
  "description": "Timestamped fixing rows reference this index by unique identifier."
}
```

Allowed relationship values:

- `relationship_type`: `direct`, `indirect`, or `derived`;
- `on_delete`: `RESTRICT`, `NO ACTION`, `CASCADE`, `SET NULL`,
  `APPLICATION`, or `UNKNOWN`;
- `effect`: `blocks_delete`, `blocks_cascade`, `cascade_delete`, `set_null`,
  `delete_cleanup`, `manual_cleanup_required`, or `informational`;
- `severity`: `blocking`, `destructive`, `mutating`, `warning`, or `info`.

Resource-specific aliases may be used only when they add fields that the shared
contract cannot represent. A resource-specific alias must still be a subclass
or compatible projection of `DeleteImpactResponse`, not a copy-pasted sibling.
The index preflight route now returns the shared `DeleteImpactResponse`.

## Route Pattern

The standard route pattern is:

```text
GET    /api/v1/{resource}/{uid}/delete-impact/
DELETE /api/v1/{resource}/{uid}/
```

Rules:

- `GET .../delete-impact/` is read-only and must not delete or mutate rows.
- `DELETE .../{uid}/` remains the only destructive route.
- The preflight route should be called by interactive clients before the
  destructive delete route.
- The preflight route does not grant delete permission or reserve state. It is a
  current-impact snapshot only.
- A fresh preflight should be fetched again if the user waits, changes filters,
  or another actor may have changed dependencies.

Bulk delete-impact is not part of this ADR. If a future bulk maintenance
workflow is needed, it requires a separate ADR because the user interaction,
partial failure semantics, and safety controls are different.

## Service Boundary

The reusable serializer does not imply a single generic delete-impact service.

Each resource should implement a small resource-specific resolver that returns
the shared serializer. That resolver owns:

- which relationships matter for this resource;
- how to count dependencies through governed MetaTable operations;
- which indirect dependencies must be surfaced;
- user-facing labels and descriptions;
- whether a relationship blocks deletion or only reports a side effect.

The resolver should not expose raw SQLAlchemy foreign-key metadata directly to
clients. FK metadata can help implementation and tests, but the public API
contract must remain curated and stable.

For index deletion, the resolver should continue to report:

- `FutureAssetDetailsTable.underlying_index_uid` as blocking;
- `IndexFixingsStorage.index_identifier` as blocking;
- `PortfolioTable.published_index_uid` as `SET NULL`;
- `IndexConventionDetailsTable.index_uid` as cascade;
- `PricingMarketDataSetCurveBindingTable.selector_type="index"` and
  `selector_key=<index_uid>` as application-owned curve selections that must be
  removed or repointed before delete.

## Command Center Adapter Contract

Delete-impact routes are read-only query operations in the Adapter from API
contract.

For a route such as:

```text
GET /api/v1/index/{uid}/delete-impact/
```

the operation remains:

```text
operationId: getIndexDeleteImpact
kind: query
```

It must not be classified as a mutation because it does not perform deletion.
It also must not be exposed as `core.tabular_frame@v1`; the response is
provider-native JSON with a strict Pydantic schema.

Cache metadata should be conservative because dependency counts can change.
The implementation should either disable caching for delete-impact operations
or use a very short TTL if the adapter contract requires cache metadata.

## Implementation Notes

The implemented contract:

1. Adds `apps/v1/schemas/delete_impact.py` with strict Pydantic models:
   `DeleteImpactRequest`, `DeleteImpactRelationship`, and
   `DeleteImpactResponse`.
2. Migrates `GET /api/v1/index/{uid}/delete-impact/` to return
   `DeleteImpactResponse`.
3. Updates index service code to build the shared response shape, including
   `resource_type="index"` and `identifier` instead of index-only field names.
4. Keeps resource-specific dependency counting in the index service for now.
   Extract shared helper utilities only after a second resource adopts the
   contract and real duplication exists.
5. Updates OpenAPI tests to assert the shared schema reference.
6. Keeps Command Center adapter tests asserting `getIndexDeleteImpact` as a
   query operation.
7. Updates `docs/fast_api/v1/index.md` to describe the reusable delete-impact
   contract and the index route as the first adopter.
8. Adds focused route and service tests proving that blocking, cascade, SET NULL,
   and indirect dependency rows serialize through the shared model.

## Consequences

Positive consequences:

- new delete preflight routes can reuse one OpenAPI response model;
- clients can render one delete-impact UI across resource types;
- the API keeps destructive delete routes individual and explicit;
- future delete-impact routes can be added without copying index-specific
  serializers;
- Command Center can discover the preflight operations without treating them as
  mutating actions.

Tradeoffs:

- each resource still needs a curated resolver;
- the response shape must be generic enough for several resources, so resource
  details belong in relationship rows rather than top-level fields;
- automatic FK graph traversal remains an implementation aid, not the public
  response contract.

## Non-Goals

This ADR does not introduce:

- bulk delete for indexes;
- bulk delete-impact preview;
- stateful delete confirmation tokens;
- automatic deletion when `can_delete=true`;
- a generic SQLAlchemy introspection endpoint;
- a Command Center tabular frame response for delete impact.
