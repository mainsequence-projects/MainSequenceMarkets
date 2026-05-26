# Tutorial

This section will contain guided, end-to-end learning material for `ms-markets`.

Planned tutorial areas:

- setting up a markets project
- working with assets and asset categories
- building market data nodes
- constructing portfolios
- using pricing workflows and priceable instruments
- exposing markets workflows through Main Sequence applications

## Library Maintenance Workflow

When changing this library, use the local Open Agent skill at
`.agents/skills/library_maintenance/SKILL.md`.

The maintenance loop for any meaningful implementation change is:

1. Classify the affected `msm` concept area.
2. Update the closest knowledge documentation under `docs/knowledge/`.
3. Add or update an example under `examples/`.
4. Update this tutorial section or add a focused tutorial page.
5. Update `CHANGELOG.md` for maintainer- or user-facing changes.
6. Run focused validation and report any skipped maintenance item explicitly.

This tutorial requirement is intentional: examples show isolated usage, while
tutorials show the order a user should follow.

## Asset Identity And Provider Rows

Use this workflow when ingesting external asset metadata:

1. Resolve or normalize provider data through a service module, for example
   `msm.services.assets.openfigi`.
2. Persist canonical identity through the `Asset` MetaTable model in
   `msm.models.assets` and repository/service helpers in
   `msm.repositories.assets` or `msm.services.assets`.
3. Store timestamped asset facts through DataNode schemas in
   `msm.data_nodes.assets`.

The package boundary is deliberate: asset models own identity, DataNodes own
time-indexed market facts, and services own external provider integration.

```python
from msm.services import build_asset_snapshot_node
from msm.services.assets.openfigi import (
    build_asset_rows_from_openfigi_result,
    normalize_openfigi_result,
)
```

See `examples/assets/openfigi_asset_rows.py` for a small offline example that
normalizes an OpenFIGI-style row and builds the corresponding library objects.

## Markets MetaTable Models

Use this workflow when adding or reviewing a market-domain relational table:

1. Define the SQLAlchemy model under `msm.models` with
   `MarketsMetaTableMixin` and `MarketsBase`.
2. Set `__metatable_identifier__` to the stable logical table name.
3. Put schema, table info, indexes, and constraints in `__table_args__`.
4. Do not set `__tablename__`; the SDK `PlatformManagedMetaTable` mixin derives
   the platform-managed physical table name from the resolved table contract.
5. Add the model to `markets_sqlalchemy_models()` in foreign-key dependency
   order.
6. Register through `msm.create_schemas(...)` or `register_markets_meta_tables(...)`
   before constructing repository/service workflows.

Examples that create platform-managed MetaTables must set the logical namespace
to `mainsequence.examples` before importing `msm.models`. `msm.create_schemas(...)`
is the process initialization preflight for that: call it once at startup with
`namespace="mainsequence.examples"` or with the
`examples.platform.bootstrap.EXAMPLE_METATABLE_NAMESPACE` constant. A repeated
call with the same startup arguments returns the cached runtime; a different
namespace or registration configuration is rejected for the already-initialized
process.

Pass `models=[...]` when a workflow only needs a subset of tables, for example
`msm.create_schemas(models=["Asset"])`. Use `runtime.table("Asset")` for
single-table asset service calls and `runtime.context` for operations that touch
multiple MetaTables.

See `examples/platform/inspect_markets_metatable_models.py` for a small offline
inspection example that prints the SDK-derived table names.
