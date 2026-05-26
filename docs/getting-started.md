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

Start by bootstrapping the markets runtime:

```python
import msm

runtime = msm.create_schemas()
context = runtime.context
```

This registers the markets SQLAlchemy models as MetaTables and returns the
repository context used by service helpers. Treat it as process startup work:
run it once during application initialization before importing MetaTable-backed
models, repositories, or services. Repeated calls with the same arguments return
the cached runtime; different arguments are rejected for that process. See
[MetaTable Registration](knowledge/platform/meta_table_registration.md) and
[Market Workflows](tutorial/market_workflows.md).
