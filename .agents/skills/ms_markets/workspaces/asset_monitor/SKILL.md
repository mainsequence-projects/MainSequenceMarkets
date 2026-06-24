---
name: mainsequence-markets-asset-monitor-workspace
description: Use this skill when creating, updating, or verifying an ms-markets Command Center Asset Monitor workspace from the CLI. This skill owns the operational CLI workflow for the Adapter from API connection, the workspace payload, the main-sequence-markets__asset-screener widget, and verification of the live workspace wiring.
---

# Main Sequence Markets Asset Monitor Workspace

Use this skill to create an ms-markets Asset Monitor in Command Center from the CLI.

The target flow is:

```text
apps/v1 FastAPI
  -> command_center.adapter_from_api connection
  -> connection-query source widget
  -> main-sequence-markets__asset-screener seedData input
```

Do not use the inactive legacy widget id:

```text
ms-markets-asset-screener
```

Use the active widget id:

```text
main-sequence-markets__asset-screener
```

## Required Project Commands

Run commands from the project root.

Never run:

```bash
.venv/bin/msm copy-msm-skills --path .
```

Refresh authentication before live platform checks:

```bash
.venv/bin/mainsequence project refresh_token --path .
.venv/bin/mainsequence project current --debug
```

## 1. Verify The Widget Registry

Always inspect the active widget before building or changing bindings:

```bash
.venv/bin/mainsequence cc registered_widget_type detail main-sequence-markets__asset-screener --json
```

Expected facts:

- widget id is `main-sequence-markets__asset-screener`
- it consumes `core.tabular_frame@v1`
- the input used by this repository is `seedData`
- do not require or synthesize a `Symbol` column unless the registry explicitly changes

## 2. Verify The API Operation

The reference API operation is:

```text
GET /api/v1/asset/monitor/frame/
operationId: getAssetMonitorFrame
```

The operation must return a real `core.tabular_frame@v1` payload through
`TabularFrameResponse`.

Set the API base URL used by the connection:

```bash
export API_BASE_URL="http://127.0.0.1:8000"
```

Check the direct frame response:

```bash
curl -sS "$API_BASE_URL/api/v1/asset/monitor/frame/?search=BONO&limit=25&offset=0"
```

Check the repeated exact asset filter:

```bash
curl -sS "$API_BASE_URL/api/v1/asset/monitor/frame/?unique_identifiers=MXN-BONO-2031&unique_identifiers=MXN-CETE-28D&limit=25&offset=0"
```

Check Adapter from API discovery:

```bash
curl -sS "$API_BASE_URL/.well-known/command-center/connection-contract"
```

The discovery document must advertise `getAssetMonitorFrame` with:

```text
responseContract: core.tabular_frame@v1
responseModel: TabularFrameResponse
```

Supported operation query parameters:

```text
search
limit
offset
asset_type
unique_identifiers
```

Use repeated `unique_identifiers`; do not replace it with singular
`unique_identifier`.

## 3. Create Or Reuse The Adapter From API Connection

Search existing Adapter from API connections first:

```bash
.venv/bin/mainsequence cc connection list --filter type_id=command_center.adapter_from_api --json
```

Inspect a candidate:

```bash
.venv/bin/mainsequence cc connection detail "$CONNECTION_UID" --json
```

For a deployed or backend-reachable API, create the connection with:

```bash
.venv/bin/mainsequence cc connection create-adapter-from-api \
  --name "Main Sequence Market" \
  --api-base-url "$API_BASE_URL" \
  --default \
  --tag markets \
  --tag asset-monitor \
  --json
```

For local direct-mode development, expose the API first:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Then create the connection with the tunnel URL:

```bash
export DEBUG_API_BASE_URL="https://example.trycloudflare.com"

.venv/bin/mainsequence cc connection create-adapter-from-api \
  --name "Main Sequence Market" \
  --debug-api-base-url "$DEBUG_API_BASE_URL" \
  --default \
  --tag markets \
  --tag asset-monitor \
  --json
```

If the connection already exists, patch it instead:

```bash
.venv/bin/mainsequence cc connection patch-adapter-from-api "$CONNECTION_UID" \
  --api-base-url "$API_BASE_URL" \
  --default \
  --json
```

For direct mode patching:

```bash
.venv/bin/mainsequence cc connection patch-adapter-from-api "$CONNECTION_UID" \
  --debug-api-base-url "$DEBUG_API_BASE_URL" \
  --default \
  --json
```

Record the returned connection `uid`:

```bash
export CONNECTION_UID="<connection-uid>"
```

## 4. Generate The Asset Monitor Workspace File

Use the project helper so the workspace payload matches the repository contract.

Default monitor:

```bash
.venv/bin/python - <<'PY' > /tmp/ms-markets-asset-monitor-workspace.json
import json
import os

from command_center.workspaces.asset_monitor import build_asset_monitor_workspace_document

payload = build_asset_monitor_workspace_document(
    connection_id=os.environ["CONNECTION_UID"],
    search="",
    limit=500,
    offset=0,
)

print(json.dumps(payload, indent=2))
PY
```

Pre-scoped monitor using repeated `unique_identifiers`:

```bash
.venv/bin/python - <<'PY' > /tmp/ms-markets-asset-monitor-workspace.json
import json
import os

from command_center.workspaces.asset_monitor import build_asset_monitor_workspace_document

payload = build_asset_monitor_workspace_document(
    connection_id=os.environ["CONNECTION_UID"],
    unique_identifiers=["MXN-BONO-2031", "MXN-CETE-28D"],
    limit=500,
    offset=0,
)

print(json.dumps(payload, indent=2))
PY
```

The generated workspace must contain:

- a `connection-query` source widget
- `operationId: getAssetMonitorFrame`
- query parameters under `parameters.query`
- `main-sequence-markets__asset-screener`
- binding `seedData.sourceWidgetId` pointing to the connection-query widget
- binding `seedData.sourceOutputId: dataset`

## 5. Create The Workspace

Create the workspace from the generated JSON file:

```bash
.venv/bin/mainsequence cc workspace create --file /tmp/ms-markets-asset-monitor-workspace.json --json
```

Record the returned workspace `uid`:

```bash
export WORKSPACE_UID="<workspace-uid>"
```

Search existing workspaces instead of opening them one by one:

```bash
.venv/bin/mainsequence cc workspace list --show-filters
.venv/bin/mainsequence cc workspace list --filter title__contains="Asset Monitor" --json
```

If `title__contains` is not listed by `--show-filters`, use the exact supported
title/name filter printed by the CLI.

## 6. Verify The Workspace

Inspect the workspace document:

```bash
.venv/bin/mainsequence cc workspace detail "$WORKSPACE_UID" --json
```

Check for:

- the connection-query widget exists
- the connection reference points to `$CONNECTION_UID`
- the query uses `operationId: getAssetMonitorFrame`
- the query contains `unique_identifiers` when pre-scoping was requested
- the screener widget id is `main-sequence-markets__asset-screener`
- the screener `seedData` binding points to the connection-query `dataset`

Capture a browser-backed snapshot when runtime behavior matters:

```bash
.venv/bin/mainsequence cc workspace snapshot "$WORKSPACE_UID" \
  --output-path /tmp/ms-markets-asset-monitor-snapshot
```

Use the snapshot output to confirm the widget ran and rendered the expected
asset rows. If the widget reports that the selected operation does not declare
`core.tabular_frame@v1`, fix the API discovery contract before changing the
workspace.

## Failure Rules

Stop and report the exact failing command if:

- widget registry does not declare `core.tabular_frame@v1`
- `getAssetMonitorFrame` is missing from the discovery contract
- `getAssetMonitorFrame` does not declare `responseContract: core.tabular_frame@v1`
- the connection detail does not show `command_center.adapter_from_api`
- the workspace detail does not contain the connection-query source widget
- the screener widget is the legacy `ms-markets-asset-screener`
- the API route returns provider-native JSON instead of `TabularFrameResponse`

Do not hide these by changing widget props.



