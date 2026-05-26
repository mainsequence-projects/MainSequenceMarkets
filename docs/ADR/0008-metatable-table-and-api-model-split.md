# 0008. MetaTable Table And API Model Split

## Status

Accepted

This decision is accepted as the general API direction for `ms-markets`.
Implementation is staged. Checked tasks below reflect the current repository
state; unchecked tasks are the remaining rollout backlog.

## Context

The markets package currently uses names such as `Asset`, `Portfolio`, and
`Order` for SQLAlchemy classes that author Main Sequence MetaTable contracts.
Those classes are correct as table declarations, but they are the wrong object
for most library consumers and FastAPI surfaces.

User-facing operations should deal in typed row objects:

```python
Asset.create_schemas(...)
asset = Asset.upsert(AssetUpsert(...))
```

The current names make that awkward because `Asset` already means the SQLAlchemy
MetaTable declaration. Returning SQLAlchemy instances from platform MetaTable
operations would also be misleading. The repository path executes governed
MetaTable operations and receives platform payloads; those objects are not
session-bound ORM rows.

The Main Sequence documentation separates platform data/table resources from
application/API surfaces. `ms-markets` needs the same package boundary:

- SQLAlchemy table declarations author MetaTable schemas, indexes, and foreign
  keys.
- Pydantic API models represent rows, create/update payloads, FastAPI request
  and response bodies, and typed service results.

## Decision

Rename every SQLAlchemy MetaTable declaration in `src/msm/models` to use the
`Table` suffix:

```text
Asset                      -> AssetTable
AssetCategory              -> AssetCategoryTable
AssetCategoryMembership    -> AssetCategoryMembershipTable
OpenFigiDetails            -> OpenFigiDetailsTable
Portfolio                  -> PortfolioTable
Order                      -> OrderTable
```

The exact migration must cover all markets MetaTables, not only assets.
The SQLAlchemy class names should change, but the existing
`__metatable_identifier__` values must remain stable unless a separate migration
explicitly changes platform logical identity.

Initial rename inventory:

```text
AccountModelPortfolio         -> AccountModelPortfolioTable
AccountGroup                  -> AccountGroupTable
Account                       -> AccountTable
AccountTargetPositionAssignment -> AccountTargetPositionAssignmentTable
Asset                         -> AssetTable
AssetMasterList               -> AssetMasterListTable
AssetCategory                 -> AssetCategoryTable
AssetCategoryMembership       -> AssetCategoryMembershipTable
Calendar                      -> CalendarTable
ExecutionError                -> ExecutionErrorTable
Fund                          -> FundTable
InstrumentsConfiguration      -> InstrumentsConfigurationTable
OpenFigiDetails               -> OpenFigiDetailsTable
OrderManager                  -> OrderManagerTable
OrderTargetQuantity           -> OrderTargetQuantityTable
Order                         -> OrderTable
OrderStatusEvent              -> OrderStatusEventTable
Trade                         -> TradeTable
Portfolio                     -> PortfolioTable
PortfolioAssetDetail          -> PortfolioAssetDetailTable
PortfolioMetadata             -> PortfolioMetadataTable
RebalanceStrategyMetadata     -> RebalanceStrategyMetadataTable
SignalMetadata                -> SignalMetadataTable
```

Create a new `src/msm/api` package for user-facing Pydantic contracts and typed
service helpers. This package is the public Python API contract layer for the
library. It is not the deployable FastAPI application package; project-level
FastAPI route surfaces still belong under the repository-level `api/` directory
when they are needed.

The package boundary is:

```text
src/msm/api
  library user-facing Pydantic models and typed helpers
  packaged with ms-markets
  imported as msm.api.assets.Asset
```

Use unsuffixed entity names for Pydantic row objects:

```python
from msm.api.assets import Asset, AssetCreate, AssetUpdate, AssetUpsert
from msm.models import AssetTable
```

Class-level row operations intended for application code should return Pydantic
row objects, not raw platform operation payloads:

```python
asset = Asset.upsert(AssetUpsert(unique_identifier="BTC", asset_type="crypto"))
crypto_assets = Asset.filter(asset_type="crypto")
```

Lower-level repository helpers may continue returning raw dictionaries because
they are the thin platform-operation layer. The typed API layer must own
normalization from platform payloads into Pydantic objects.

The preferred layering is:

```text
src/msm/models
  SQLAlchemy MetaTable declarations only.
  Names end in Table.

src/msm/repositories
  Governed MetaTable operation compilation/execution.
  Inputs and outputs may remain close to platform payloads.

src/msm/api
  Pydantic user-facing row and mutation contracts.
  Typed service helpers for library and FastAPI users.

src/msm/services
  Domain workflows and provider integrations.
  May call the typed API layer for row contracts when exposing public helpers.
```

This is the general spirit of the library:

- users work with typed domain row objects such as `Asset`, `Portfolio`, and
  `Order`;
- schema/bootstrap code works with SQLAlchemy table declarations such as
  `AssetTable`, `PortfolioTable`, and `OrderTable`;
- repository code remains the lower-level platform-operation layer and may keep
  raw operation payloads close to Main Sequence MetaTable execution;
- services compose workflows across providers, repositories, DataNodes, and
  row APIs when an operation is broader than one persisted row;
- row methods may be convenient, but they must stay explicit about bootstrap:
  `create_schemas(...)` can initialize required tables, while `upsert(...)`,
  `filter(...)`, and lookup methods use the active runtime and never silently
  create schemas.

Pydantic row models may own explicit class-level row operations:

```python
Asset.create_schemas(...)
Asset.upsert(...)
Asset.filter(...)
```

The method split matters. `Asset.create_schemas(...)` is allowed as a thin
convenience over `msm.create_schemas(models=[AssetTable], ...)`. It performs the
explicit schema/bootstrap lifecycle. `Asset.upsert(...)` and `Asset.filter(...)`
must use the already initialized runtime and must not create schemas silently.

The intended class shape is:

```python
class Asset:
    __table__ = AssetTable
    __required_tables__ = [AssetTable]

    @classmethod
    def create_schemas(cls, **kwargs): ...

    @classmethod
    def upsert(cls, ...): ...


class Portfolio:
    __table__ = PortfolioTable
    __required_tables__ = [PortfolioTable, AssetTable, PortfolioAssetDetailTable]

    @classmethod
    def upsert(cls, ...): ...
```

At scale, each row model can own the operations that make sense for that domain.
`Asset.upsert(...)` is a single-table operation. `Portfolio.upsert(...)` may be a
multi-table operation that touches portfolio identity, index-asset details, and
asset identity. The class declares its required tables and should raise a clear
bootstrap error if the active runtime was initialized without those tables.

The refactor should provide compatibility aliases for one release cycle where
the blast radius is high:

```python
Asset = AssetTable
```

Those aliases are only for old MetaTable imports. New documentation, examples,
and service signatures must use `Asset` for the Pydantic row object and
`AssetTable` for the MetaTable declaration.

## Non-Goals

This ADR does not require every MetaTable to receive a Pydantic row API in one
change. It defines the target architecture and the staged path.

This ADR does not move deployable FastAPI route modules into `src/msm/api`.
`src/msm/api` is the packaged library API contract layer. Repository-level
FastAPI apps still belong under the project-level `api/` directory when needed.

This ADR does not make row mutation methods silently bootstrap schemas.
`create_schemas(...)` is explicit. Mutation and lookup methods use the active
runtime and fail clearly when no compatible runtime has been initialized.

This ADR does not remove lower-level repository helpers. Repositories remain
useful for compiled operation construction, multi-table internals, and workflows
that need raw platform payloads.

## Migration Guidance

New code should use these imports:

```python
from msm.api.assets import Asset
from msm.models import AssetTable
```

Old schema-oriented imports should move as follows:

```python
# old compatibility import
from msm.models import Asset

# new schema import
from msm.models import AssetTable
```

If the caller wants a user-facing row object or FastAPI response model, use the
`msm.api` row object:

```python
from msm.api.assets import Asset
```

If the caller wants SQLAlchemy columns, foreign-key targets, MetaTable
registration, or compiled SQL construction, use the `*Table` declaration:

```python
from msm.models import AssetTable
```

Compatibility aliases such as `msm.models.Asset = AssetTable` may remain during
the transition, but they are not the preferred import path and must not be used
in new examples or docs.

## Implementation Tasks

The implementation should move in dependency-aware stages. Each stage must keep
the `Table` declarations registerable, add Pydantic row contracts only for the
public operations being exposed, update examples/docs for that stage, and add
focused tests before moving to the next group.

### Stage 1: Shared Infrastructure

- [x] Add `src/msm/api/__init__.py` and domain modules such as
  `src/msm/api/assets.py`.
- [x] Add a runtime accessor that row APIs can use after explicit bootstrap.
- [x] Make `msm.create_schemas(...)` accept selected table models.
- [x] Add `MarketsRuntime.table(...)` so lower-level repository/service code can
  still obtain a registered table handle when needed.
- [x] Rename current SQLAlchemy MetaTable declarations to `*Table` class names.
- [x] Add temporary import aliases where needed to avoid breaking all existing
  callers in one release.

### Stage 2: Asset Identity API

This is the first user-facing slice because asset identity is the root of most
market workflows.

- [x] Define `msm.api.assets.Asset`, `AssetCreate`, `AssetUpdate`, and
  `AssetUpsert`.
- [x] Add `Asset.__table__ = AssetTable`.
- [x] Add `Asset.__required_tables__ = [AssetTable]`.
- [x] Add `Asset.create_schemas(...)`.
- [x] Add `Asset.upsert(...) -> Asset`.
- [x] Add `Asset.get_by_uid(...) -> Asset | None`.
- [x] Add `Asset.get_by_unique_identifier(...) -> Asset | None`.
- [x] Add `Asset.filter(...) -> list[Asset]`.
- [x] Move the focused asset example and tutorial excerpts to the new API
  vocabulary: user-facing code imports `Asset`, schema/bootstrap code imports
  `AssetTable`.

### Stage 3: Asset Reference Data API

This stage should complete the asset catalog surface after the core `Asset`
row is stable.

- [ ] Add Pydantic row and mutation contracts for:
  `AssetMasterList`, `AssetCategory`, `AssetCategoryMembership`, and
  `OpenFigiDetails`.
- [ ] Add class-level `create_schemas(...)` for each row model with explicit
  `__required_tables__`.
- [ ] Add `AssetCategory.upsert(...)` and category lookup/filter helpers.
- [ ] Add `AssetCategory.replace_memberships(...)` as the category-owned
  multi-table operation requiring `[AssetCategoryTable,
  AssetCategoryMembershipTable, AssetTable]`.
- [ ] Add `OpenFigiDetails.upsert(...)` or provider-specific registration helper
  requiring `[OpenFigiDetailsTable, AssetTable]`.
- [ ] Update OpenFIGI examples so provider row-building uses API rows when the
  result is intended for user-facing code and `*Table` declarations only when
  authoring MetaTable contracts.

### Stage 4: Accounts And Calendars API

This stage covers the operational identity tables needed before funds,
portfolios, and execution workflows can expose typed APIs.

- [ ] Add Pydantic row and mutation contracts for:
  `Calendar`, `AccountModelPortfolio`, `AccountGroup`, `Account`, and
  `AccountTargetPositionAssignment`.
- [ ] Add `Calendar.create_schemas(...)`, `Calendar.upsert(...)`, and
  lookup/filter helpers.
- [ ] Add `Account.create_schemas(...)`, `Account.upsert(...)`, and
  lookup/filter helpers.
- [ ] Add account-group helpers after account-model-portfolio contracts are in
  place.
- [ ] Keep account target-position assignment as an explicit relationship API;
  do not hide it inside `Account.upsert(...)` unless a workflow clearly owns
  that mutation.

### Stage 5: Portfolio And Fund API

This is the first larger multi-table API stage. It should prove that
class-owned operations scale beyond single-table assets.

- [ ] Add Pydantic row and mutation contracts for:
  `Portfolio`, `PortfolioAssetDetail`, `PortfolioMetadata`, and `Fund`.
- [ ] Add `Portfolio.__required_tables__ = [PortfolioTable, AssetTable,
  PortfolioAssetDetailTable]` for workflows that maintain index asset details.
- [ ] Add `Portfolio.create_schemas(...)`.
- [ ] Add `Portfolio.upsert(...)` as a domain-specific operation, not a generic
  table upsert. It may resolve or validate asset identity and write
  `PortfolioAssetDetail` when required by the payload.
- [ ] Add `Portfolio.filter(...)`, `Portfolio.get_by_unique_identifier(...)`,
  and typed portfolio asset detail helpers.
- [ ] Add `Fund.__required_tables__ = [FundTable, AccountTable,
  PortfolioTable]`.
- [ ] Add `Fund.upsert(...)` and lookup helpers after account and portfolio APIs
  are stable.

### Stage 6: Signals, Rebalance, And Instrument Configuration API

These are metadata/configuration surfaces. They should remain thin unless a
larger service workflow exists.

- [ ] Add Pydantic row and mutation contracts for:
  `SignalMetadata`, `RebalanceStrategyMetadata`, and
  `InstrumentsConfiguration`.
- [ ] Add class-level `create_schemas(...)`, upsert, lookup, and filter helpers
  for each table.
- [ ] Keep pricing-runtime and strategy construction outside these row models;
  row APIs should only own persisted metadata/configuration mutations.

### Stage 7: Execution API

Execution tables have stronger workflow semantics and should not be treated as
generic CRUD only.

- [ ] Add Pydantic row and mutation contracts for:
  `OrderManager`, `OrderTargetQuantity`, `Order`, `OrderStatusEvent`, `Trade`,
  and `ExecutionError`.
- [ ] Add `OrderManager.create_schemas(...)` with required tables for account,
  asset, fund, and order dependencies.
- [ ] Add workflow-specific class methods such as `OrderManager.create_batch(...)`
  or `Order.record_status(...)` only where the lifecycle is clear.
- [ ] Avoid hiding execution side effects behind generic `upsert(...)` when the
  domain operation is append-only or event-oriented.

### Stage 8: Compatibility Removal

- [ ] Mark legacy `msm.models.Asset`-style aliases as deprecated in docs and
  release notes.
- [ ] Audit all examples and docs so new code imports row objects from
  `msm.api.*` and table declarations from `msm.models.*Table`.
- [ ] Remove compatibility aliases on a planned breaking release boundary.
- [ ] Run full package tests, docs build, and example smoke checks after alias
  removal.

## Stage Exit Criteria

Each stage is complete only when:

- Pydantic row models exist for the rows exposed in that stage.
- Row classes declare `__table__` and `__required_tables__`.
- Row operations return Pydantic objects or lists of Pydantic objects, not raw
  platform operation payloads.
- `create_schemas(...)` is explicit and includes every required table for the
  class-owned operations in that stage.
- Mutation and lookup methods fail clearly if the active runtime has not been
  initialized or was initialized without the required tables.
- Repository helpers still compile against `*Table` declarations.
- Docs and examples for that stage use `msm.api.*` row objects for user-facing
  code and `msm.models.*Table` declarations for schema code.
- Focused tests cover schema declaration names, runtime bootstrap behavior,
  operation compilation, and Pydantic result normalization.

## Current Implementation State

The repository currently implements the shared infrastructure and the first
asset identity slice:

- SQLAlchemy MetaTable declarations have `*Table` names.
- Compatibility aliases remain in `msm.models`.
- `msm.api.assets.Asset` is the user-facing Pydantic row object.
- `Asset.create_schemas(...)`, `Asset.upsert(...)`,
  `Asset.get_by_uid(...)`, `Asset.get_by_unique_identifier(...)`, and
  `Asset.filter(...)` are implemented.
- Focused asset examples and tutorial excerpts use the new typed row API.

The remaining stages are future implementation work. They should proceed in the
order listed above unless a specific user workflow requires a narrower slice.

## Consequences

The public API becomes clearer: users manipulate `Asset` objects, while schema
registration code manipulates `AssetTable`.

FastAPI integration becomes straightforward because Pydantic models can be used
directly as request and response models. The typed service layer becomes the
stable boundary between platform MetaTable payloads and application code.

The refactor is broad. It touches MetaTable registration order, SQLAlchemy
foreign-key references, repository helpers, services, examples, docs, and tests.
It should be implemented in focused slices, starting with assets, then expanding
across the remaining MetaTables.

This ADR supersedes the naming assumption in ADR 0006 that `Asset` is the
MetaTable-backed model. ADR 0006 still applies to the package-boundary decision
that asset identity, DataNodes, and provider services are separate concepts.

Compatibility aliases reduce immediate breakage but also create ambiguity while
they exist. They should be documented as deprecated and removed on a planned
breaking release boundary.
