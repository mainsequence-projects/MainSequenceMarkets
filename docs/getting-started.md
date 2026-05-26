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
from msm.api.assets import Asset

Asset.create_schemas()
asset = Asset.upsert(unique_identifier="example-asset-btc", asset_type="crypto")
assets = Asset.filter(asset_type="crypto")
```

This follows the library-wide convention: user code works with Pydantic row
objects, while schema code works with SQLAlchemy `*Table` declarations.
`Asset.create_schemas()` is explicit bootstrap for the tables required by asset
row operations. `Asset.upsert(...)` and `Asset.filter(...)` use the active
runtime and do not silently create schemas.

For application startup or multi-table workflows, bootstrap directly:

```python
import msm

runtime = msm.create_schemas()
context = runtime.context
asset_table = runtime.table("Asset")
```

Treat schema creation as process startup work: run it once during application
initialization before row operations, repositories, or services depend on the
registered tables. Repeated calls with the same arguments return the cached
runtime; different arguments are rejected for that process. See
[MetaTable Registration](knowledge/platform/meta_table_registration.md) and
[Market Workflows](tutorial/market_workflows.md).
