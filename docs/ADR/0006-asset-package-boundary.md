# 0006. Asset Package Boundary

## Status

Accepted

## Context

The extracted SDK code temporarily used an `msm.assets` package for both asset
DataNode schemas and OpenFIGI provider helpers. That boundary made asset identity
look like a standalone package when the implementation actually spans three
different concepts:

- MetaTable models and repositories own persistent asset identity.
- DataNodes own timestamped asset facts.
- Services own provider lookup and normalization workflows.

Keeping `msm.assets` would make future changes ambiguous, especially as provider
integrations and DataNode schemas grow independently.

## Decision

Remove the `msm.assets` package boundary.

Use these public paths instead:

```text
msm.models.assets
msm.repositories.assets
msm.services.assets
msm.services.assets.openfigi
msm.data_nodes.assets
```

The `Asset` model remains the MetaTable-backed model at:

```python
from msm.models import Asset
```

Asset snapshot and pricing-detail DataNode schemas move to:

```python
from msm.data_nodes.assets import AssetSnapshot, AssetPricingDetail
```

OpenFIGI helpers move to:

```python
from msm.services.assets.openfigi import query_figi
```

## Consequences

Imports through `msm.assets` are not supported. Code should choose the package
that matches the concept it is using: `models` for identity, `data_nodes` for
timestamped frames, and `services` for provider workflows.

OpenFIGI packaged definition lists live next to the service implementation under
`msm.services.assets.open_figi_lists`.
