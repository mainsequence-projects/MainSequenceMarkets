# Tutorial

This section will contain guided, end-to-end learning material for `ms-markets`.

Planned tutorial areas:

- setting up a markets project
- working with assets and asset categories
- building market data nodes
- constructing portfolios
- installing the optional pricing extra and using `msm_pricing` priceable instruments
- exposing markets workflows through Main Sequence applications with the
  optional `public_api` extra

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

## Installing MS Markets Agent Skills

Use the `msm` CLI when a host Main Sequence project should receive the
ms-markets agent skills:

```bash
msm copy-msm-skills --path .
```

The command copies the packaged bundle into `.agents/ms_markets/` and overwrites
only matching skill folders under that namespace. It does not touch
`.agents/skills/mainsequence`, project-state files, or `AGENTS.md`.

Do not rely on `import msm` for this setup. Imports are side-effect free and do
not copy skills into the current working tree.

## Asset Identity And Provider Rows

Use this workflow when ingesting external asset metadata:

1. Resolve or normalize provider data through a service module, for example
   `msm.services.assets.openfigi`.
2. Register the asset type through `msm.api.assets.AssetType` when the type is
   new to the project or namespace.
3. Persist canonical identity through the user-facing `msm.api.assets.Asset`
   row API. Row operations attach to registered MetaTables lazily.
4. Store timestamped asset facts through DataNode schemas in
   `msm.data_nodes.assets`.

The package boundary is deliberate: `msm.api` owns user row operations,
`msm.models.*Table` owns SQLAlchemy schema declarations, DataNodes own
time-indexed market facts, and services own external provider integration.

```python
from msm.data_nodes.assets import AssetSnapshot
from msm.services.assets.openfigi import (
    query_by_figi,
)
```

See `examples/assets/openfigi_asset_rows.py` for a small example that resolves a
FIGI through OpenFIGI and registers the resulting `Asset` and `OpenFigiDetails`
through `msm.api.assets`. The OpenFIGI helpers read the API key from the Main
Sequence secret `OPEN_FIGI_API_KEY`.

## Markets MetaTable Models

Use this workflow when adding or reviewing a market-domain relational table:

1. Define the SQLAlchemy model under `msm.models` with
   `MarketsMetaTableMixin` and `MarketsBase`.
2. Set `__metatable_identifier__` to the stable bare logical table name.
   The shared markets identifier rule prefixes it only for non-default runtime
   namespaces such as `mainsequence.examples`.
3. Put schema, table info, indexes, and constraints in `__table_args__`.
4. Do not set `__tablename__`; the SDK `PlatformManagedMetaTable` mixin derives
   the platform-managed physical table name from the resolved table contract.
5. Add the model to `markets_sqlalchemy_models()` in foreign-key dependency
   order.
6. Use `msm.create_schemas(...)` or `register_markets_meta_tables(...)` only
   when the workflow explicitly owns schema preflight.

Examples that should self-register platform-managed MetaTables must set
`MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples` before importing
MetaTable-backed `msm.api` or `msm.models` modules. The first row operation then
registers the row class's required tables and caches the runtime for the
process. A different namespace or registration configuration is rejected for
the already-initialized process.

Pass `models=[...]` to explicit preflight when a workflow only needs a subset of
tables, for example `msm.create_schemas(models=["Asset"])`. Normal examples and
application code should use typed row classes such as
`msm.api.assets.Asset.upsert(...)`. Use `runtime.table(...)` and
`runtime.context` only for lower-level repository or service internals.

See `examples/platform/inspect_markets_metatable_models.py` for a small offline
inspection example that prints the SDK-derived table names.
