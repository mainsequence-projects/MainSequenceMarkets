---
name: mainsequence-markets-command-center-asset-monitor
description: Use this skill when creating, changing, reviewing, or documenting ms-markets Command Center Asset Monitor helpers, the getAssetMonitorFrame provider API operation, Adapter from API metadata, or connection-query bindings into the active main-sequence-markets__asset-screener widget.
---

# Main Sequence Markets Command Center Asset Monitor

Use this skill for the ms-markets Asset Monitor Command Center path:

```text
project API
  -> command_center.adapter_from_api connection
  -> connection-query source widget
  -> main-sequence-markets__asset-screener
```

## Source Of Truth

Before changing widget fields, props, bindings, or required frame metadata,
inspect the active widget registry:

```bash
mainsequence cc registered_widget_type detail main-sequence-markets__asset-screener --json
```

Use that registry detail over ADR text, old skills, previous runbooks, or
inferred field names.

Do not use the inactive legacy widget id:

```text
ms-markets-asset-screener
```

## Frame Rules

Provider operations for this widget must return:

```text
core.tabular_frame@v1
```

Use the SDK response model for provider APIs:

```python
from mainsequence.client.command_center.data_models import TabularFrameResponse
```

Do not add synthetic columns unless the active widget registry explicitly
requires them. In particular, do not add `Symbol` as a required or generated
field for this widget.

The ms-markets helper may emit domain fields such as:

```text
uid
unique_identifier
asset_type
ticker
```

These are ms-markets asset fields, not mandatory widget columns. The active
widget can resolve asset identity from metadata, explicit mappings, or
recognizable identity fields.

## Provider Operation

The standard operation id is:

```text
getAssetMonitorFrame
```

The reference `apps/v1` path is:

```text
GET /api/v1/asset/monitor/frame/
```

The operation should return `TabularFrameResponse` directly. Do not rely on a
provider-native response mapping for this frame operation.

Supported query parameters in this repository:

```text
search
limit
offset
asset_type
unique_identifiers
```

Use repeated `unique_identifiers` when the caller already knows the selected
asset identifiers and should not request the full monitor list.

## Workspace Binding

Use a source widget:

```text
connection-query
```

Bind its output to the screener:

```text
connection-query.dataset -> main-sequence-markets__asset-screener.seedData
```

Do not store endpoint URLs, credentials, or provider route fragments in widget
props. Those belong to the Adapter from API connection.

## Checks

Check the API contract:

```bash
curl -sS "$API_BASE_URL/.well-known/command-center/connection-contract"
```

Check that `getAssetMonitorFrame` is advertised with:

```text
responseContract: core.tabular_frame@v1
responseModel: TabularFrameResponse
```

Check widget registry and workspace detail before claiming the workspace is
ready:

```bash
mainsequence cc registered_widget_type detail main-sequence-markets__asset-screener --json
mainsequence cc workspace detail <workspace-uid> --json
```
