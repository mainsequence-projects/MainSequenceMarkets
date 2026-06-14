---
name: mainsequence-markets-asset-monitor-workspace
description: Use this skill when creating, reviewing, or documenting a Main Sequence Command Center asset monitor workspace for ms-markets, including Adapter from API connections, local apps/v1 API endpoints, Connection Query source widgets, and the ms-markets Asset Screener widget.
---

# Main Sequence Markets Asset Monitor Workspace

Use this skill to create or review a Command Center workspace that monitors
ms-markets assets through the local `apps/v1` FastAPI surface.

The expected flow is:

```text
apps/v1 FastAPI API
  -> command_center.adapter_from_api connection
  -> connection-query source widget
  -> ms-markets-asset-screener visible widget
```

## Scope

This skill owns the Command Center workspace wiring for an asset monitor:

- Adapter from API connection selection or creation
- local API endpoint configuration
- widget registry verification
- workspace JSON shape
- `connection-query` to `ms-markets-asset-screener` binding
- validation commands after creation

This skill does not own:

- implementing or changing FastAPI routes
- creating a project API resource or release
- changing ms-markets asset models or DataNodes
- deploying the API
- generic workspace design outside this asset monitor pattern

Route those tasks to the relevant Main Sequence or ms-markets skills.

## Required Verified IDs

Do not invent these ids. Verify them before workspace creation.

```text
Connection type: command_center.adapter_from_api
Connection query model: api-operation
Source widget: connection-query
Visible asset widget: ms-markets-asset-screener
Primary asset API operation: listAssets
Primary list response mapping: results
```

`ms-markets-asset-screener` is titled `Asset Screener` in the registry. Treat
user wording such as "asset monitor" as this widget unless the registry exposes
a newer dedicated asset monitor widget.

## Success Condition

A successful asset monitor workspace has:

- a reachable local or tunnelled `apps/v1` API exposing the Command Center
  contract
- a `command_center.adapter_from_api` connection named `Main Sequence Market`
- a workspace containing:
  - one hidden `connection-query` source widget
  - one visible `ms-markets-asset-screener` widget
  - a binding from source `dataset` to screener `seedData`
- the workspace detail output shows both widget instances
- the connection detail output shows type `command_center.adapter_from_api`
- the selected operation is `listAssets`

Do not claim success if any of those facts is not verified.

## Before Creating Anything

Follow project startup rules first:

```bash
mainsequence project current --debug
mainsequence project refresh_token --path .
```

For local API development, confirm the API root. In this project the PyCharm
run configuration commonly uses:

```text
http://127.0.0.1:8021
```

Do not set or recommend `MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples` for
this workspace flow. The local launcher or caller may explicitly choose a
namespace, but this skill must not hardcode one.

Check the API contract:

```bash
export API_BASE_URL="http://127.0.0.1:8021"

curl -fsS "$API_BASE_URL/.well-known/command-center/connection-contract" | jq .
curl -fsS "$API_BASE_URL/openapi.json" | jq '.info.title'
```

If the API is not reachable from Command Center in direct local mode, expose it
with a tunnel and use the tunnel URL as `API_BASE_URL`:

```bash
cloudflared tunnel --url http://127.0.0.1:8021
export API_BASE_URL="https://<tunnel-host>.trycloudflare.com"
```

Use `--debug-api-base-url` for local or tunnel development. Use
`--api-base-url` only for a deployed stable backend URL.

## Registry Verification

Always verify the connection type and widget contracts before writing the
workspace JSON.

```bash
mainsequence cc connection_type detail command_center.adapter_from_api --json
mainsequence cc registered_widget_type list --json
mainsequence cc registered_widget_type detail connection-query --json
mainsequence cc registered_widget_type detail ms-markets-asset-screener --json
```

Required facts from the registry:

- `command_center.adapter_from_api` query model includes `api-operation`
- `connection-query` publishes `dataset` as `core.tabular_frame@v1`
- `ms-markets-asset-screener` accepts `seedData` as `core.tabular_frame@v1`
- `ms-markets-asset-screener` supports bound or managed connection source mode

Stop if a required widget or query model is missing.

## Command Chain

Create the workspace first when the connection should be workspace-scoped:

```bash
WORKSPACE_UID="$(
  mainsequence --json cc workspace create "Main Sequence Market Asset Monitor" \
    --description "Local Main Sequence Markets asset monitor workspace." \
    --category "Markets" \
    --source "user" \
    --layout-kind "custom" \
  | jq -r '.uid'
)"
```

Create the Adapter from API connection:

```bash
CONNECTION_UID="$(
  mainsequence --json cc connection create-adapter-from-api \
    --name "Main Sequence Market" \
    --debug-api-base-url "$API_BASE_URL" \
    --workspace-uid "$WORKSPACE_UID" \
    --default \
    --tag markets \
    --tag local \
  | jq -r '.uid'
)"
```

If the user explicitly wants the connection created before the workspace, omit
`--workspace-uid` and later select or reuse the returned `CONNECTION_UID` in the
workspace JSON.

Inspect the connection:

```bash
mainsequence cc connection detail "$CONNECTION_UID"
```

## Workspace JSON Template

The CLI `workspace update --file` expects raw writable workspace fields at the
top level. Do not wrap the payload in `{ "workspace": ... }`.

Create a temporary JSON file:

```bash
cat > /tmp/main-sequence-market-asset-monitor.json <<EOF
{
  "title": "Main Sequence Market Asset Monitor",
  "description": "Local Main Sequence Markets asset monitor workspace.",
  "labels": ["markets", "asset-monitor", "local-api"],
  "category": "Markets",
  "source": "user",
  "schemaVersion": 1,
  "layoutKind": "custom",
  "grid": { "columns": 48, "rowHeight": 15, "gap": 8 },
  "controls": {
    "enabled": true,
    "refresh": {
      "enabled": true,
      "defaultIntervalMs": 300000,
      "intervals": [null, 30000, 60000, 300000]
    }
  },
  "widgets": [
    {
      "id": "asset-monitor-source",
      "widgetId": "connection-query",
      "title": "Asset source",
      "props": {
        "connectionRef": {
          "id": "$CONNECTION_UID",
          "typeId": "command_center.adapter_from_api"
        },
        "queryModelId": "api-operation",
        "query": {
          "kind": "api-operation",
          "operationId": "listAssets",
          "parameters": {
            "path": {},
            "query": {
              "response_format": "frontend_list",
              "limit": 500,
              "offset": 0
            },
            "headers": {}
          },
          "body": null,
          "responseMappingId": "results"
        },
        "timeRangeMode": "none",
        "maxRows": 500
      },
      "managedBy": {
        "ownerInstanceId": "asset-monitor",
        "role": "embedded-connection-source"
      },
      "presentation": {
        "placementMode": "sidebar",
        "railVisibility": "hidden"
      }
    },
    {
      "id": "asset-monitor",
      "widgetId": "ms-markets-asset-screener",
      "title": "Asset Monitor",
      "props": {
        "assetScreenerSourceMode": "bound",
        "columnConfigMode": "source",
        "density": "compact",
        "maxRenderedRows": 500,
        "showDiagnostics": true
      },
      "bindings": {
        "seedData": {
          "sourceWidgetId": "asset-monitor-source",
          "sourceOutputId": "dataset"
        }
      },
      "layout": { "cols": 48, "rows": 20 },
      "position": { "x": 0, "y": 0 }
    }
  ]
}
EOF
```

Update the workspace:

```bash
mainsequence cc workspace update "$WORKSPACE_UID" \
  --file /tmp/main-sequence-market-asset-monitor.json
```

## Validation

Validate platform objects after the update:

```bash
mainsequence cc connection detail "$CONNECTION_UID" --json
mainsequence cc workspace detail "$WORKSPACE_UID" --json
```

Check the workspace detail includes:

- widget `asset-monitor-source`
- widget type `connection-query`
- widget `asset-monitor`
- widget type `ms-markets-asset-screener`
- binding `asset-monitor.bindings.seedData.sourceWidgetId == "asset-monitor-source"`
- binding `asset-monitor.bindings.seedData.sourceOutputId == "dataset"`

Check the connection detail includes:

- name `Main Sequence Market`
- type id `command_center.adapter_from_api`
- public config for the selected API root
- direct/debug mode when using `--debug-api-base-url`

Check the API contract includes `listAssets`:

```bash
curl -fsS "$API_BASE_URL/.well-known/command-center/connection-contract" \
  | jq '.availableOperations[] | select(.operationId == "listAssets")'
```

## Asset Screener Data Requirements

`ms-markets-asset-screener` consumes `core.tabular_frame@v1` through
`seedData`. Its registry detail requires asset identity fields including:

```text
unique_identifier
Symbol
```

The local `listAssets` operation returns provider-native paginated JSON, and the
Adapter from API contract exposes the `results` response mapping. If the
workspace mounts correctly but the screener does not render, do not blame the
workspace wiring first. Verify whether the connection query publishes a
screener-ready canonical frame.

Acceptable fixes are outside this skill:

- add a direct `TabularFrameResponse` operation for asset monitoring
- add a transform that maps `unique_identifier` to `Symbol`
- adjust the API Command Center contract so the selected operation publishes a
  full `core.tabular_frame@v1` with Asset Screener field roles

Route API changes to the `apps-v1-public-api` skill.

## Review Checklist

When reviewing an asset monitor workspace, flag these issues:

- workspace created before verifying widget registry details
- hardcoded endpoint URLs in widget props instead of connection config
- credentials or tokens in workspace JSON
- `connection-query` missing `connectionRef`
- `queryModelId` not equal to query `kind`
- `query.operationId` not declared in the API contract
- visible screener querying the connection directly instead of consuming a
  source widget output
- `seedData` bound to anything other than `connection-query.dataset`
- direct local API configured with `--api-base-url` instead of
  `--debug-api-base-url`
- wrapped workspace payload passed to `workspace update --file`
- claimed success without `connection detail` and `workspace detail`
  verification

