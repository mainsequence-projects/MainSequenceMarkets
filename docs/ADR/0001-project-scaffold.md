# 0001. Project Scaffold

## Status

Accepted

## Context

The project needs to start as a standalone Python package that depends on
MainSequence libraries and QuantLib while keeping the import name short.

## Decision

The Python distribution is named `ms-markets`.

The import package is named `msm`:

```python
import msm
```

The initial runtime dependencies are:

- `mainsequence`
- `QuantLib`
- `SQLAlchemy`

The source tree uses the `src/` layout to avoid accidental imports from the
repository root during development. The canonical package lives at
`src/msm`.

## Consequences

Packaging metadata lives in `pyproject.toml`.

Future architecture decisions should be added under `docs/ADR`.
