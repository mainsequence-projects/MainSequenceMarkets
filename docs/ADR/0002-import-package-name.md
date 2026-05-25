# 0002. Import Package Name

## Status

Accepted

## Context

The project distribution name is `ms-markets`, but Python imports cannot contain
hyphens. The library also needs a short import path because market-domain code is
expected to be used heavily in notebooks, scripts, services, and agent tools.

## Decision

Use `msm` as the Python import package:

```python
import msm
```

The source layout is:

```text
src/msm/  Main package
```

## Consequences

Users install the distribution with:

```bash
pip install ms-markets
```

Application code should prefer:

```python
import msm
```
