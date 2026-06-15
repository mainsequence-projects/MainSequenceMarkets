# Asset Monitor

The Asset Monitor helper builds the tabular frame consumed by the
`main-sequence-markets__asset-screener` Command Center widget.

## Data Flow

```text
project API
  -> command_center.adapter_from_api connection
  -> connection-query source widget
  -> main-sequence-markets__asset-screener seedData input
```

Generic Command Center tabular consumers require a real
`core.tabular_frame@v1` payload. Do not treat a provider-native paginated JSON
response as widget-ready only because a response mapping exists.

## Library Helpers

Use the library helpers when building a project-specific API:

```python
from command_center.widgets.asset_monitor import build_asset_monitor_frame

frame = build_asset_monitor_frame(asset_rows)
```

The caller owns data loading. The helper accepts already-loaded asset rows and
optional related details. It does not start `msm.start_engine(...)`, query
MetaTables, resolve request identity, or register schemas.

## Frame Identity Fields

The active widget registry does not require an exact `Symbol` column. It
resolves asset identity from source metadata, explicit field mappings, or
recognizable identity fields such as `unique_identifier`, `assetKey`,
`asset_identifier`, `symbol`, or `ticker`.

The ms-markets helper emits:

```text
uid
unique_identifier
asset_type
ticker
```

`unique_identifier` is the stable market asset key from `AssetTable`. It is a
domain field emitted by this helper, not an exact widget-required column.

## Optional Enrichment Columns

The helper can include related detail metadata when supplied by the caller:

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

These fields enrich the monitor. They do not replace `AssetTable.uid` or
`AssetTable.unique_identifier`.

## Reference API Operation

The local `apps/v1` reference app exposes:

```text
GET /api/v1/asset/monitor/frame/
operationId: getAssetMonitorFrame
```

Supported query parameters:

```text
search
limit
offset
asset_type
unique_identifiers
```

Search follows the asset-list service behavior: it checks
`AssetTable.unique_identifier` by contains search and related ticker details
when available.

Use `unique_identifiers` as a repeated query parameter when the widget or a
caller already knows the exact asset identifiers and should not request the full
monitor list:

```text
GET /api/v1/asset/monitor/frame/?unique_identifiers=MXN-BONO-2031&unique_identifiers=MXN-CETE-28D
```

## Workspace Helper

Use the workspace helper to build the standard workspace payload:

```python
from command_center.workspaces.asset_monitor import (
    build_asset_monitor_workspace_document,
)

workspace = build_asset_monitor_workspace_document(connection_id=connection_uid)
```

To pre-scope the workspace source query to known assets, pass the repeated
filter values as a list:

```python
workspace = build_asset_monitor_workspace_document(
    connection_id=connection_uid,
    unique_identifiers=["MXN-BONO-2031", "MXN-CETE-28D"],
)
```

The helper wires:

```text
connection-query.dataset -> main-sequence-markets__asset-screener.seedData
```

It intentionally does not store endpoint URLs or credentials in widget props.
Those belong to the `command_center.adapter_from_api` connection instance.

## Verification

Check the API frame:

```bash
curl -sS "http://127.0.0.1:8000/api/v1/asset/monitor/frame/?search=BONO&limit=25&offset=0"
```

Check Adapter from API discovery:

```bash
curl -sS "http://127.0.0.1:8000/.well-known/command-center/connection-contract"
```

The discovery document should advertise `getAssetMonitorFrame` with:

```text
responseContract: core.tabular_frame@v1
responseModel: TabularFrameResponse
```
