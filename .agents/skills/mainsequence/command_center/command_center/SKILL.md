---
name: command-center
description: Discover and use the Main Sequence Command Center backend resources exposed through MCP. Use as the top-level operation map for Workspaces, immutable widget revisions, Connections, and human-authorized Project workflow navigation placement.
---

# Main Sequence Command Center

Use the Command Center backend through the exact MCP tools advertised by the
connected server. Treat DRF as canonical for persisted behavior,
authorization, validation, and responses.

## Preserve The Boundary

This skill owns the language-neutral backend resource and operation map for:

- `Workspace`;
- `RegisteredWidgetType`;
- `ConnectionType`; and
- `ConnectionInstance`, exposed by MCP as `connection.*`; and
- `ProjectWorkflowNavigationLinkGrant`, exposed by MCP as
  `navigation_link_grant.*`.

It does not own frontend architecture, React components, resource views,
actions, widgets, workspaces, themes, embeds, or Command Center SDK extension
contracts. Use the complete version-matched skill bundle installed from the
project's `@dev-mainsequence/command-center-sdk` package for frontend work.

Do not use the Python SDK model hierarchy as proof that an operation exists.
Generic inherited methods such as `create`, `patch_by_uid`,
`update_or_create`, or `destroy_by_uid` are client conveniences, not an
authoritative backend or MCP capability declaration.

## Use The Current MCP Catalog

The approved discovery surface includes these read operations:

| Resource | List | Detail |
| --- | --- | --- |
| Workspace | `workspace.list` | `workspace.get` |
| RegisteredWidgetType | `registered_widget_type.list` | `registered_widget_type.get` |
| ConnectionType | `connection_type.list` | `connection_type.get` |
| ConnectionInstance | `connection.list` | `connection.get` |
| Workflow navigation grant | `navigation_link_grant.list` | `navigation_link_grant.get` |

Always inspect the live `tools/list` result before relying on an operation.
Do not invent an aggregate `command_center.get_context`, a generic API proxy,
or an unadvertised mutation tool.

ConnectionInstance lifecycle and adapter execution are additionally available
through `connection.create`, `connection.update`, `connection.delete`,
`connection.test`, `connection.query`, and `connection.resource`. Read the
`mainsequence://platform/skills/command-center-connections` skill before using
those operations.

### Workspace reads

Use `workspace.list` to enumerate visible Workspaces. Supported filters are:

- `uid`, `uid__in`, and `exclude_uids`;
- `title` and `title__contains`;
- `type` and `type__in`;
- `source` and `source__in`;
- `labels`, `labels__contains`, and `labels__in`;
- `search`; and
- `limit` and `offset`.

Use `workspace.get` with `workspace_uid` for one visible Workspace. The result
is the canonical composable Workspace read representation reconstructed from
normalized instance rows. Its executable identity is
`widgets[*].widgetRevisionUid`; `widgetId` and `widgetVersion` are read-only
projections. Only the requesting user's transient runtime state may be merged
into that response; it is never shared workspace content.

### Registered widget type reads

Use `registered_widget_type.list` with only `widget_id`, `limit`, and `offset`.
Use `registered_widget_type.get` with the stable `widget_id` natural key.

RegisteredWidgetType is stable `(widget-extension release, widget_id)` identity,
not a mutable metadata mirror. Each catalog response selects an immutable
`RegisteredWidgetRevision` and returns its `widgetRevisionUid`, version,
release UID, publication UID, and manifest-projected metadata. The mutable
registry synchronization service no longer exists. Successful
WidgetExtensionRelease publication is the only registration path, including
for first-party widgets.

### Connection type reads

Use `connection_type.list` with the supported `type_id`, `category`, `source`,
`access_mode`, `isActive`, `includeInactive`, `limit`, and `offset` fields. Use
`connection_type.get` with the stable `type_id` natural key; detail resolves
the latest matching registered version.

ConnectionType is a registered catalog definition. Creation, update, deletion,
and registry synchronization are not exposed through MCP.

### Connection instance reads

Use `connection.list` with the supported `workspace_uid`, `type_id`, `status`,
`is_active`, `is_default`, `limit`, and `offset` fields. Use `connection.get`
with the public `connection_uid`.

The safe read representation may describe public configuration and which
secure fields are present. It never returns secure configuration values.

Connection creation, partial update, hard delete, health test, query, and
allowlisted resource reads use their dedicated `connection.*` tools. Streaming
and ConnectionType registry synchronization remain outside MCP.

### Workflow navigation placement grants

Use `navigation_link_grant.list` with the required
`organization_environment_uid` to discover grants the authenticated
human may manage. Use `navigation_link_grant.get` for one exact grant UID.

`navigation_link_grant.create` authorizes a maximum audience for one exact
`projectBranchUid + workflowPath + resourceKey`. `update` changes, contracts,
or reactivates it. `revoke` immediately removes its workflow-owned link while
retaining the audit row. These tools dispatch to canonical DRF operations;
MCP owns no separate permission model.

Project edit authority is required in addition to audience authority. A
Project editor may authorize only their own exact User. Other selected Users
and Organization-wide placement require Organization administrator authority.
Team audiences require edit authority for every selected Team or Organization
administrator authority. Repository automation, Git authors, and coding agents
cannot create human authorization on their own. Placement never grants access
to the target Static Site.

## Understand Workspace Mutation Availability

The canonical Workspace DRF surface and the current Python compatibility
client support substantial mutations, including:

- create, partial update, and delete;
- add and remove labels;
- user and team view/edit sharing changes; and
- widget patch, delete, and move operations.

Those capabilities do not become MCP operations merely because this skill
describes them. The current MCP catalog exposes only `workspace.list` and
`workspace.get`. An MCP-only agent must stop when a requested Workspace
mutation has no advertised tool instead of attempting a generic request or
claiming success.

Workspace mutation parity still requires separately approved MCP tools with
exact DRF-aligned schemas and permission-parity tests. This skill does not
provide that parity by itself.

## Authorization And Safety

- Authenticate with the normal tracked platform JWT.
- Let each canonical DRF operation resolve visible objects and permissions.
- Treat an empty or not-found result as non-disclosure when the canonical
  operation does so.
- Never infer mutation authority from successful list or detail access.
- Never return, log, or place connection secure configuration values into read
  results. Accept them only as intentional write-only `secureConfig` input to
  connection create or update.
- Do not automatically retry an ambiguous mutation if future mutation tools
  are added; inspect canonical state first.

## Report Results Truthfully

Name the exact MCP tool used and distinguish:

1. catalog discovery;
2. visible persisted state;
3. an operation that is supported by the backend but absent from MCP; and
4. frontend implementation work owned by the installed Command Center SDK
   skills.

Never describe a backend or Python-client method as completed through MCP when
the corresponding MCP tool is not present.
