# Getting Started

Install the project in editable mode with development dependencies:

```bash
uv sync --extra dev
```

Or with pip:

```bash
python -m pip install -e ".[dev]"
```

Verify that the import package is available:

```python
import msm
```

## Documentation

Serve the documentation locally:

```bash
mkdocs serve
```

Build the static documentation site:

```bash
mkdocs build
```

## Architecture Decisions

Implementation decisions should be recorded under `docs/ADR`.

## First Market Setup

Start with the typed row API for simple workflows:

```python
from msm.api.assets import Asset, AssetCategory

asset = Asset.upsert(unique_identifier="example-asset-btc", asset_type="crypto")
assets = Asset.filter(asset_type="crypto")

category = AssetCategory.upsert(
    unique_identifier="example-crypto",
    display_name="Example Crypto",
)
```

This follows the library-wide convention: user code works with Pydantic row
objects, while schema code works with SQLAlchemy `*Table` declarations.
`Asset.upsert(...)` and `Asset.filter(...)` lazily attach to already-registered
MetaTables. They do not create schemas by default.

For application startup that wants a controlled schema preflight, bootstrap
directly:

```python
import msm

runtime = msm.create_schemas()
context = runtime.context
asset_table = runtime.table("Asset")
```

For development examples that should self-register missing tables, set
`MSM_AUTO_REGISTER_NAMESPACE` before importing `msm.api`. That namespace also
becomes the default namespace for markets DataNode identifiers and
`hash_namespace` values created in the same process.

Every markets MetaTable now has a user-facing row model under `msm.api.*`.
Legacy imports such as `from msm.models import Asset` have been removed; use
`from msm.api.assets import Asset` for row operations and
`from msm.models import AssetTable` for SQLAlchemy schema declarations.

Treat explicit schema creation as process startup work: run it once during
application initialization when the process owns that preflight. Repeated calls
with the same arguments return the cached runtime; different arguments are
rejected for that process. See
[MetaTable Registration](knowledge/platform/meta_table_registration.md) and
[Market Workflows](tutorial/market_workflows.md).
