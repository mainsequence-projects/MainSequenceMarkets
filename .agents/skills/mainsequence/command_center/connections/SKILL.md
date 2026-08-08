---
name: command-center-connections
description: Design and operate Main Sequence Command Center connections by selecting a registered ConnectionType, configuring a ConnectionInstance, validating it, and using its declared query models and resources through canonical MCP operations.
---

# Command Center Connections

Use this skill when work requires connecting Command Center to a platform or
external data source. Treat DRF as canonical for persisted behavior,
validation, authorization, adapter dispatch, and responses. MCP is the
language-neutral operation surface; it does not reimplement connection logic.

## Understand The Two Objects

`ConnectionType` is the registered adapter contract. It describes:

- the stable `id` and registered `version`;
- public and secure configuration schemas;
- technical `capabilities` such as query, resource, health check, or stream;
- `queryModels` and their standard output contracts;
- `usageGuidance` and examples; and
- physical-data-source eligibility owned by the backend.

`ConnectionInstance`, exposed by MCP as `connection.*`, is an
organization-owned configured use of one ConnectionType. It has a public UID,
public configuration, write-only secure configuration, health state, optional
Workspace association, and sharing permissions.

Type capabilities describe what the adapter implementation supports. They do
not prove that the current caller can execute an operation. The canonical DRF
action performs the caller and object authorization check at call time.

## Follow The Connection-First Workflow

1. Use `connection_type.list` to discover active types.
2. Use `connection_type.get` and read `publicConfigSchema`,
   `secureConfigSchema`, `capabilities`, `queryModels`, `usageGuidance`, and
   `examples` before composing configuration or a request.
3. Use `connection.list` to find a suitable existing instance. Use
   `connection.get` before changing or executing it.
4. If no suitable instance exists, ask for missing configuration and create it
   with `connection.create`. Do not guess credentials or secret values.
5. Use `connection.update` for an intentional partial configuration change.
6. Use `connection.test` when the caller wants to validate connectivity. A
   test contacts the configured backend and records connection health state.
7. Select an advertised `queryModels` entry or documented resource. Use
   `connection.query` or `connection.resource` with the exact payload required
   by that ConnectionType.
8. Check the returned warnings, trace identifier, frame contracts, and updated
   connection state before reporting success.

Do not substitute a widget type, Workspace, physical DataSource, or Python SDK
model for either connection object.

## Use The Exact MCP Operations

Catalog and instance discovery:

- `connection_type.list`
- `connection_type.get`
- `connection.list`
- `connection.get`

Connection lifecycle:

- `connection.create`
- `connection.update`
- `connection.delete`
- `connection.test`

Adapter execution:

- `connection.query`
- `connection.resource`

Always inspect the connected server's live tool catalog. Do not invent a
generic API proxy, type synchronization call, caller-action discovery call, or
streaming MCP tool.

## Configure Instances Safely

For create and update, derive `publicConfig` and `secureConfig` from the live
ConnectionType schemas. `secureConfig` is a write-only input. Successful
responses expose only `secureFields`, which records whether named secure values
are present; they never return encrypted or decrypted values.

On update, sending a secure field as `null` requests the existing canonical
clear behavior. Do not resend unchanged credentials merely because
`secureFields` reports that they exist. Never place secrets in public config,
skill files, source control, logs, or result summaries.

MCP does not expose `openForEveryone`, internal status mutation,
`statusMessage`, `lastHealthCheckAt`, `isSystem`, or direct `secureFields`
mutation. Do not infer or manufacture those inputs.

`connection.delete` performs the existing hard-delete operation. Inspect the
instance and its consumers first, obtain clear user intent, and do not retry an
ambiguous delete. Backend dependency protection remains authoritative.

## Query By Declared Model

Choose the query model from `ConnectionType.queryModels`; do not infer payload
fields from the connection name. Preserve the query model's query kind,
parameters, time range, variables, limits, cache controls, and requested output
contract exactly as documented by the type.

Widget-bound queries return a normalized `ConnectionQueryResponse`. Frames use
only the standard contracts advertised by the query model:

- `core.tabular_frame@v1`; or
- `core.chart_data@v1`.

If `requestedOutputContract` is supplied, every returned frame must use that
contract. A resource/detail JSON response is not a widget frame.

Do not assume `connection.query` is read-only. The selected query model remains
authoritative, and the Main Sequence MetaTable connection can execute governed
insert, update, delete, or upsert operations. Obtain explicit intent before a
mutating query and do not retry it automatically after an ambiguous failure.

## Read Allowlisted Resources

Use `connection.resource` only for a resource documented by the selected
ConnectionType. Pass its canonical adapter payload inside the tool's `payload`
object. Resources may return adapter-specific JSON because they are discovery
or detail operations rather than widget-bound queries.

Resource capability does not mean every resource name is accepted. The
backend adapter allowlist and canonical object permissions decide the result.

## Keep Streaming On Its Existing Transport

The backend may advertise streaming for a ConnectionType, but stateless MCP
does not proxy SSE or WebSocket streams. A streaming consumer must use the
existing Command Center streaming transport and its documented authentication
contract. Do not emulate a stream by repeatedly calling `connection.query`.

## Delegate Frontend Implementation

This skill owns platform connection meaning and MCP operation selection. It
does not own React controls, entity summaries, resource-list normalization,
bulk selection/preflight UX, widgets, themes, or iframe integration. For those
tasks, use the complete version-matched skill bundle installed from the
project's `@dev-mainsequence/command-center-sdk` package.

The frontend may derive configuration controls from the ConnectionType schemas
and normalize canonical DRF pagination. Do not create duplicate backend DTOs
inside this skill.

## Report Truthfully

Distinguish:

1. a discovered ConnectionType contract;
2. a visible configured ConnectionInstance;
3. a successful canonical connection mutation;
4. an adapter test, query, or resource result; and
5. frontend composition performed with Command Center SDK skills.

Report validation, permission, capability, provider, and dependency failures
as returned by the platform. Never convert a failed adapter operation into a
successful connection claim.
