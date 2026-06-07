# 0025. Direct MetaTable Runtime Binding

## Status

Accepted

This ADR replaces the earlier secondary-registry runtime binding design. The
internal markets MetaTable registry was removed entirely; runtime attachment
uses direct backend lookup by SQLAlchemy table name.

[ADR 0026](0026-explicit-pricing-market-data-sets.md) proposes a future
replacement for pricing market-data bindings. That proposal is not implemented;
the current implementation still stores attached storage identifiers in
`PricingMarketDataBindingTable`.

## Context

`ms-markets` previously started runtime by reading an internal markets registry
table, resolving registry rows to backend MetaTables by UID, and binding each
SQLAlchemy model from those rows.

That was useful before the SDK/runtime had a stable client-side table identity.
The current model graph already has a canonical table identifier through the
SQLAlchemy table name:

```text
AssetTable.__table__.name
  -> ms_markets__asset__mainsequence_examples

DiscountCurvesStorage.__table__.name
  -> ms_markets__discountcurvests__mainsequence_examples
```

The backend MetaTable and TimeIndexMetaTable rows are registered under that same
identifier. The SDK can resolve them directly by that identifier, so keeping a
separate internal registry row duplicated state and created drift risk.

The pricing failure exposed the issue:

```text
PricingMarketDataBinding.data_node_identifier
  -> mainsequence.examples.DiscountCurvesTS
APIDataNode.build_from_identifier(...)
  -> MetaTable.get(identifier="mainsequence.examples.DiscountCurvesTS")
  -> no backend MetaTable found
```

That string came from rebuilding an identifier from
`DiscountCurvesTS` instead of asking the attached storage MetaTable for the
identifier that the SDK can resolve.

Python class names are not globally unique, and a local extension can reuse the
same class name as a built-in or another package. Runtime identity must come
from the SQLAlchemy table name and the backend registered table object, not from
a secondary inventory row.

## Decision

Runtime attachment will resolve registered MetaTables directly from each
model's canonical table identifier.

The runtime binding flow becomes:

```text
resolved model graph
  -> model.__table__.name
  -> MetaTable / TimeIndexMetaTable backend lookup
  -> model._bind_meta_table(...)
  -> model.get_identifier()
```

No internal registry table is retained. Runtime binding works from the model's
table identity and the backend MetaTable/TimeIndexMetaTable APIs.

### Canonical Identifier

There is one public identifier access path on a mapped markets model:

```python
Model.get_identifier()
```

That method returns the attached backend MetaTable identifier:

```python
Model.get_meta_table().identifier
```

It must fail clearly when the model has not been attached to a backend table.
It must not rebuild a fallback string from namespace helpers, authored model
names, or `__metatable_identifier__`.

Internal mutation of `__metatable_identifier__`, if retained, is not public
runtime truth. User code, pricing code, DataNode code, and repository code
should use the attached backend identifier through `get_identifier()`.

### Runtime Lookup

Runtime attachment must query the backend directly in bulk. It must not issue
one lookup per model. The resolver partitions requested models into normal
`MetaTable` models and `PlatformTimeIndexMetaTable` storage models, then performs
one body-filter query per backend resource type.

```text
normal MetaTable models:
  MetaTable.filter_by_body(
    physical_table_name__in=[model.__table__.name, ...],
    management_mode=...
  )

time-index storage models:
  TimeIndexMetaTable.filter_by_body(
    physical_table_name__in=[model.__table__.name, ...]
  )
```

The result set is then matched back to the requested models by canonical table
name:

```text
model.__table__.name -> backend physical_table_name -> backend object
```

Missing matches, duplicate matches, or mismatched backend physical table names
must fail startup before any row API is exposed.

### Pricing DataNode Identifiers

Pricing market-data bindings must store SDK-resolvable identifiers from attached
storage classes:

```python
DiscountCurvesStorage.get_identifier()
IndexFixingsStorage.get_identifier()
```

They must not store:

```text
mainsequence.examples.DiscountCurvesTS
mainsequence.examples.IndexFixingsTS
```

Static pricing defaults that rebuild names from authored storage identifiers are
invalid for persisted market-data bindings because they rebuild a logical string
instead of reading the backend identifier.

## Consequences

This removes a duplicated runtime source of truth. Runtime startup depends on
the SDK's registered MetaTable/TimeIndexMetaTable lookup by canonical table
identifier, not on a secondary pointer. Runtime failures should point to missing
backend MetaTables or TimeIndexMetaTable rows for the table identifier the model
declares.

Pricing defaults become runtime-dependent. They can only be seeded after the
pricing storage tables are attached, because `get_identifier()` must read the
actual backend MetaTable identifier.

## Implementation Tasks

### Stage 1: Model Identifier API

- [x] Add `get_identifier()` to the markets MetaTable mixins.
- [x] Make `get_identifier()` return `get_meta_table().identifier`.
- [x] Make `get_identifier()` fail clearly when the model is not attached.
- [x] Add tests proving `get_identifier()` returns the same identifier as the
      bound backend MetaTable object.

### Stage 2: Direct Runtime Attachment

- [x] Add a direct runtime resolver that partitions requested models into
      normal MetaTable models and `PlatformTimeIndexMetaTable` storage models.
- [x] Resolve normal MetaTables in one SDK
      `MetaTable.filter_by_body(physical_table_name__in=...)` call keyed by
      `model.__table__.name`.
- [x] Resolve time-index storage tables in one SDK
      `TimeIndexMetaTable.filter_by_body(physical_table_name__in=...)` call
      keyed by `model.__table__.name`.
- [x] Reject missing matches, duplicate matches, or backend objects whose
      returned physical table name does not match the requested
      `model.__table__.name`.
- [x] Bind each resolved backend object to its model with `_bind_meta_table`.
- [x] Return `MarketsMetaTableRegistrationResult` keyed by canonical table
      identifier.
- [x] Update `msm.start_engine(...)` to use direct runtime attachment instead
      of the previous secondary-registry attach path.
- [x] Update `msm.attach_schemas(...)` to use the same direct runtime
      attachment.
- [x] Keep process-idempotence and missing-model runtime checks unchanged.

### Stage 3: Secondary Registry Removal

- [x] Remove the internal markets MetaTable registry model.
- [x] Remove secondary-registry refresh hooks from migration providers.
- [x] Remove secondary-registry reads from normal runtime startup.
- [x] Remove generic registry API routes and services.
- [x] Update documentation so direct backend lookup is the only runtime binding
      mechanism.

### Stage 4: DataNode Identifier Resolution

- [x] Update `storage_data_node_identifier(storage_table)` to call
      `storage_table.get_identifier()`.
- [x] Remove fallback DataNode identifier construction from storage class
      authored names.
- [x] Add tests proving DataNode default identifiers equal the attached backend
      MetaTable/TimeIndexMetaTable identifiers.

### Stage 5: Pricing Binding Defaults

- [x] Remove static pricing binding defaults based on namespace-rebuilt
      authored storage identifiers.
- [x] Seed default pricing market-data bindings from
      `DiscountCurvesStorage.get_identifier()` and
      `IndexFixingsStorage.get_identifier()`.
- [x] Ensure pricing bootstrap attaches the required pricing storage models
      before seeding default bindings.
- [x] Update the bond pricing example to store identifiers returned from the
      attached storage classes.
- [x] Add regression tests proving no pricing binding persists
      `mainsequence.examples.DiscountCurvesTS` or
      `mainsequence.examples.IndexFixingsTS`.
- [x] Add a pricing resolver test proving `APIDataNode.build_from_identifier`
      receives the same identifier returned by `DiscountCurvesStorage.get_identifier()`.

### Stage 6: Documentation And Validation

- [x] Update bootstrap documentation to describe direct runtime attachment.
- [x] Update pricing documentation to explain that market-data bindings store
      SDK-resolvable DataNode/MetaTable identifiers from attached storage
      classes.
- [x] Remove obsolete secondary-registry documentation.
- [x] Run focused runtime attachment tests.
- [x] Run pricing bootstrap tests.
- [ ] Run the live bond pricing example against a configured platform session.
- [x] Run `mkdocs build --strict`.
