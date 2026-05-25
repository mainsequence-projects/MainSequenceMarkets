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

Start by registering the markets SQLAlchemy models as MetaTables. See
[MetaTable Registration](knowledge/platform/meta_table_registration.md) and
[Market Workflows](tutorial/market_workflows.md).
