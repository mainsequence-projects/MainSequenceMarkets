# Command Center

`ms-markets` exposes reusable Command Center helper code for projects that want
to build their own API surfaces and workspaces around markets data.

The helpers live in the library package, not in the local `apps/v1` FastAPI
application:

```text
src/command_center/
```

Downstream projects can import these helpers from their own FastAPI app,
Streamlit surface, job, or API resource. The caller owns route layout,
authentication, data loading, pagination, deployment, and access control. The
helper package owns the Command Center payload contract and ms-markets
widget-specific frame semantics.

## Available Helpers

- [Asset Monitor](asset_monitor.md): build `core.tabular_frame@v1` payloads and
  workspace documents for the `main-sequence-markets__asset-screener` widget.

## Reference API

This repository's `apps/v1` app is a reference consumer of the helpers. It
exposes:

```text
GET /api/v1/asset/monitor/frame/
operationId: getAssetMonitorFrame
response contract: core.tabular_frame@v1
```

Other projects may expose the same operation from a different path, but the
standard workspace helper expects the `getAssetMonitorFrame` operation ID.
