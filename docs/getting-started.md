# Getting Started

Install the project in editable mode with development dependencies:

```bash
uv sync --extra dev
```

Or with pip:

```bash
python -m pip install -e ".[dev]"
```

The project-level FastAPI surface is optional. Install it only for public API
work:

```bash
uv sync --extra public_api
```

Verify that the import package is available:

```python
import msm
```

Install ms-markets agent skills into a host project only through the explicit
CLI command:

```bash
msm copy-msm-skills --path .
```

This copies the packaged skill bundle into `.agents/skills/ms_markets/`.
Importing `msm` does not write files, create `.agents/`, or auto-install
skills.

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

```bash
mainsequence migrations upgrade --provider msm.migrations:migration --to head
```

```python
import msm

from msm.api.assets import Asset, AssetCategory, AssetType

msm.start_engine(models=["AssetType", "Asset", "AssetCategory"])

AssetType.upsert(asset_type="crypto", display_name="Crypto")

asset = Asset.upsert(unique_identifier="example-asset-btc", asset_type="crypto")
assets = Asset.filter(asset_type="crypto")

category = AssetCategory.upsert(
    unique_identifier="example-crypto",
    display_name="Example Crypto",
)
```

This follows the library-wide convention: user code works with Pydantic row
objects, while schema code works with SQLAlchemy `*Table` declarations.
`Asset.upsert(...)` and `Asset.filter(...)` use the active markets runtime.
They do not attach to MetaTables or create schemas on first use.

For application startup that wants a controlled runtime preflight, attach
directly:

```python
import msm

runtime = msm.start_engine()
context = runtime.context
asset_table = runtime.table("Asset")
```

That startup preflight uses the internal maintenance catalog. Cataloged tables
are attached by platform
`MetaTable.uid`; missing or stale catalog rows fail startup and should be fixed
through the SDK migration upgrade flow.

For development examples that should use an example namespace, set
`MSM_AUTO_REGISTER_NAMESPACE` before importing `msm.api`, then call
`msm.start_engine(...)` during startup. That namespace also becomes the default
namespace for markets DataNode identifiers and `hash_namespace` values created
in the same process.

Every markets MetaTable now has a user-facing row model under `msm.api.*`.
Legacy imports such as `from msm.models import Asset` have been removed; use
`from msm.api.assets import Asset` for row operations and
`from msm.models import AssetTable` for SQLAlchemy schema declarations.

Treat explicit runtime attachment as process startup work: run it once during
application initialization after admin migrations are current. Repeated calls
with the same arguments return the cached runtime; different arguments are
rejected for that process. See
[MetaTable Registration](knowledge/msm/platform/meta_table_registration.md),
[Migrations](knowledge/msm/migrations/index.md), and
[Market Workflows](tutorial/market_workflows.md).
