# Backend contract schemas

This directory is the language-neutral contract bundle shipped with
`@dev-mainsequence/command-center-sdk`. Backend teams can design, validate, and fixture payloads
without reading TypeScript implementation files.

## Start with the manifest

[`manifest.json`](./manifest.json) is the machine-readable index. Each entry contains:

- a stable contract identifier and JSON Schema `$id`;
- the schema file and public npm subpath;
- whether the payload is a backend request, backend response, shared value, or normalized adapter
  result;
- the matching public TypeScript type; and
- valid and invalid fixtures.

All schemas use JSON Schema draft 2020-12. The `$id` URNs are identifiers, not network locations;
resolve files through the manifest or the documented npm exports.

This manifest is the canonical machine-readable contract documentation. The schemas it references
are the wire definitions, and its fixture indexes identify the conformance examples. Human guides
and agent skills must link here rather than copying contract catalogs or field definitions.

## Published paths

```text
@dev-mainsequence/command-center-sdk/contracts/manifest.json
@dev-mainsequence/command-center-sdk/contracts/schemas/*
@dev-mainsequence/command-center-sdk/contracts/fixtures/valid/*
@dev-mainsequence/command-center-sdk/contracts/fixtures/invalid/*
```

Resolve exact schema and fixture paths from the manifest. Do not maintain a second filename list in
documentation or skills.

## Which contract should a backend implement?

Read the manifest's `schemas` array and select an entry by its exact `contract` and `role`. That
entry supplies the schema, TypeScript mapping, and positive and negative fixtures. The human guide
in [`docs/backend-contracts.md`](../docs/backend-contracts.md) explains how the contract families
fit into application workflows without redefining their JSON shapes.

The collection schema intentionally describes `ResourceListResult<T>`, not every product's raw
pagination envelope. A backend using `{count, results}` or another established envelope remains
valid when the consumer adapter performs the documented normalization.

The `command-center.static_site_iframe@v1` manifest entry has role `iframe-protocol`. It describes
the language-neutral `mainsequence.*` ready, initialize, delegated FastAPI credential request,
response, and sanitized-error messages. It is not a backend endpoint schema: host applications map
their authenticated backend response into the SDK resolver result, and the SDK alone owns these
wire bytes across the iframe boundary.

## Validate in a backend repository

Pin the SDK version, read `contracts/manifest.json`, register every schema by `$id`, then validate
the payload against the selected contract. Registering all entries is important because the
resource-collection schema references the bulk-action definition by its stable URN.

Backends that do not use npm may unpack the pinned npm tarball or vendor `contracts/` from an exact
repository release tag. Do not fetch schemas from a moving `main` branch in validation or release
pipelines.

Python example using `jsonschema`:

```py
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

contracts = Path("node_modules/@dev-mainsequence/command-center-sdk/contracts")
manifest = json.loads((contracts / "manifest.json").read_text())
schemas = {
    item["id"]: json.loads((contracts / item["file"]).read_text())
    for item in manifest["schemas"]
}
registry = Registry().with_resources(
    (schema_id, Resource.from_contents(schema))
    for schema_id, schema in schemas.items()
)

selected = next(item for item in manifest["schemas"] if item["contract"] == requested_contract)
validator = Draft202012Validator(schemas[selected["id"]], registry=registry)
validator.validate(response_payload)
```

Use the equivalent draft-2020-12 validator in other languages. Invalid fixtures must fail; they
are not examples of tolerated legacy data.

The Adapter From API v1 schemas do not define compatibility aliases. Alternate operation IDs,
unknown query or discovery properties, and missing required transport modes are invalid rather
than silently normalized.

## Semantic rules beyond portable JSON Schema

Portable JSON Schema cannot express uniqueness by one property inside an object array. Runtime
parsers additionally require unique action IDs, option keys, filter keys, ordering values,
resource identity paths, and discovery column IDs. Resource discovery also verifies that column
sort/filter references occur in its controls and that generic columns supply both `value_path` and
`data_type`.
Tabular normalization likewise canonicalizes duplicate field keys. Schemas mark these cases with
`$comment` where applicable, and SDK tests run both schema validation and the public runtime
parsers where applicable.
The static-site iframe runtime additionally pins the source window, exact origin, established
channel, target UID, correlation ID, and future expiry; the portable schema validates message bytes
but cannot establish browser-window identity or the client-only transport lifecycle. The additive
`runtime_starting` error code lets a host expose a backend-confirmed cold-start condition without
forwarding an internal response body. `authorizing`, `ready`, `expired`, `forbidden`,
`missing-route`, and `transient` remain runtime client states rather than wire messages.

`fixtures/valid/tabular-frame-v1.table-visuals.json` is the backend example for labels, numeric
formatting, widths, ranges, data bars, and threshold rules. Table visuals change rendering only;
they do not change canonical rows or the Table widget's `dataset` output.

Adapter From API implementations must also enforce rules that span payload locations:

- `configVariables[].key`, `secretVariables[].key`, and `availableOperations[].operationId` are
  unique; public and secret variable keys do not overlap;
- `health.operationId` and query `operationId` resolve to one declared operation;
- the health operation is a safe GET operation whose method/path come from `availableOperations`;
  `health` contains only the operation reference, expected status, and timeout;
- every executable query operation declares `responseContract`, and the provider response body
  validates against that exact contract;
- query parameters occur only in their declared path/query/header location, and credential headers
  cannot be supplied by a query; and
- secret values never appear in public config, responses, traces, logs, or cache keys.

`command-center.resource_discovery@v1` is the language-neutral backend response for a resource
list's identity, visible controls, ordered columns, and authorized bulk actions. It is separate from
the paginated collection response. Backends must not accept pagination or presentation state on
the discovery endpoint, and must use `extensions` for explicitly namespaced future hints. Local
rich-column IDs omit generic binding metadata; a backend-added generic column includes both a safe
dot-delimited `value_path` and one supported `data_type`.

## Versioning and backend impact

Schema filenames and contract IDs are immutable once released. Additive compatible fields require
fixtures and documentation. Breaking semantics require a new `vN` schema, a new contract ID, a
transition plan, mixed-version tests, and coordinated frontend/backend rollout and rollback.

The Table authoring schema documents the existing `core__table` and `core__pro-table` IDs and prop
meaning. It introduces no required persisted field and needs no backend migration. A backend that
authors or validates widgets can opt into the envelope and its fixtures.

The AppComponent, Tabular Transform, and workspace-document schemas likewise describe existing
persisted v1 shapes. They add no field to stored widget props or workspace JSON. A backend may pin
the SDK bundle and introduce validation in shadow mode before enforcing it; rollback consists of
disabling that validation because payload bytes and version axes are unchanged. Older clients can
continue reading the same documents, and unknown workspace/widget fields remain preserved.

The Adapter From API v1 bundle is still part of the current unreleased change. Its obsolete mapping
fields were removed before publication and are covered by invalid fixtures; no migration aliases or
runtime compatibility behavior are shipped.

Adding the bundle itself does not change stored workspace/widget data or require a backend
migration. Adapter From API providers must opt into the new strict IDs and return declared response
contracts exactly; existing endpoints are not silently reinterpreted or accepted through
compatibility aliases.
