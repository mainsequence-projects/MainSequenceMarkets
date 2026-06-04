# 0025. Direct MetaTable Runtime Binding

## Status

Proposed

This ADR supersedes the runtime-control part of
[ADR 0015](0015-catalog-based-metatable-bootstrap.md). ADR 0015 remains valid
for catalog inventory and post-migration catalog refresh, but the catalog must
not be the source of truth for runtime attachment.

## Context

`ms-markets` currently starts runtime by reading
`MarketsMetaTableCatalogTable`, resolving catalog rows to backend MetaTables by
UID, and binding each SQLAlchemy model from those rows.

That was useful before the SDK/runtime had a stable client-side table identity.
The current model graph already has a canonical table identifier through the
SQLAlchemy table name:

```text
AssetTable.__table__.name
  -> ms_markets__asset__mainsequence_examples

DiscountCurvesStorage.__table__.name
  -> ms_markets__discountcurvests__mainsequence_examples
```

The backend MetaTable and TimeIndexMetaData rows are registered under that same
identifier. The SDK can resolve them directly by that identifier, so using a
separate catalog row as runtime control duplicates state and creates drift risk.

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

`model_name` in the catalog is not a safe runtime key. Python class names are
not globally unique, and a local extension can reuse the same class name as a
built-in or another package. If the catalog remains, its stable key is the
canonical table identifier, not `model_name`.

## Decision

Runtime attachment will resolve registered MetaTables directly from each
model's canonical table identifier.

The runtime binding flow becomes:

```text
resolved model graph
  -> model.__table__.name
  -> MetaTable / TimeIndexMetaData backend lookup
  -> model._bind_meta_table(...)
  -> model.get_identifier()
```

The catalog is retained only as a maintenance and inspection table:

```text
SDK migration provider registers/refreshes tables
  -> refresh catalog rows for inventory
  -> user/services can list app-owned tables
```

The catalog must not decide whether application runtime can attach a model.
Runtime binding must work from the model's table identity and the backend
MetaTable/TimeIndexMetaData APIs.

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
`MetaTable` models and `PlatformTimeIndexMetaData` storage models, then performs
one filter query per backend resource type.

```text
normal MetaTable models:
  MetaTable.filter(identifier__in=[model.__table__.name, ...], management_mode=...)

time-index storage models:
  TimeIndexMetaData.filter(identifier__in=[model.__table__.name, ...])
```

The result set is then matched back to the requested models by canonical table
identifier:

```text
model.__table__.name -> backend object
```

Missing matches, duplicate matches, or mismatched backend identifiers must fail
startup before any row API is exposed.

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

Static pricing defaults such as `markets_data_node_identifier("DiscountCurvesTS")`
are invalid for persisted market-data bindings because they rebuild a logical
string instead of reading the backend identifier.

### Catalog Role

The catalog remains useful as an inventory:

- list app-owned registered tables;
- record table descriptions, model names, SDK version, and backend UID;
- support user-facing catalog services;
- provide migration refresh evidence after SDK registration.

It is not runtime control:

- `start_engine(...)` does not require catalog rows;
- `attach_schemas(...)` does not require catalog rows;
- row APIs do not require catalog rows;
- pricing does not use catalog rows to discover DataNode storage.

## Consequences

This removes a duplicated runtime source of truth. Runtime startup depends on
the SDK's registered MetaTable/TimeIndexMetaData lookup by canonical table
identifier, not on a secondary catalog pointer.

The catalog can become stale without breaking runtime. Stale catalog rows affect
inventory views and maintenance diagnostics only. Runtime failures should point
to missing backend MetaTables or TimeIndexMetaData rows for the table identifier
the model declares.

Pricing defaults become runtime-dependent. They can only be seeded after the
pricing storage tables are attached, because `get_identifier()` must read the
actual backend MetaTable identifier.

## Implementation Tasks

### Stage 1: Model Identifier API

- [ ] Add `get_identifier()` to the markets MetaTable mixins.
- [ ] Make `get_identifier()` return `get_meta_table().identifier`.
- [ ] Make `get_identifier()` fail clearly when the model is not attached.
- [ ] Add tests proving `get_identifier()` returns the same identifier as the
      bound backend MetaTable object.

### Stage 2: Direct Runtime Attachment

- [ ] Add a direct runtime resolver that partitions requested models into
      normal MetaTable models and `PlatformTimeIndexMetaData` storage models.
- [ ] Resolve normal MetaTables in one SDK `MetaTable.filter(identifier__in=...)`
      call keyed by `model.__table__.name`.
- [ ] Resolve time-index storage tables in one SDK
      `TimeIndexMetaData.filter(identifier__in=...)` call keyed by
      `model.__table__.name`.
- [ ] Reject missing matches, duplicate matches, or backend objects whose
      returned identifier does not match the requested `model.__table__.name`.
- [ ] Bind each resolved backend object to its model with `_bind_meta_table`.
- [ ] Return `MarketsMetaTableRegistrationResult` keyed by canonical table
      identifier.
- [ ] Update `msm.start_engine(...)` to use direct runtime attachment instead
      of `attach_markets_meta_tables_from_catalog(...)`.
- [ ] Update `msm.attach_schemas(...)` to use the same direct runtime
      attachment.
- [ ] Keep process-idempotence and missing-model runtime checks unchanged.

### Stage 3: Catalog Demotion

- [ ] Keep `MarketsMetaTableCatalogTable` and post-migration catalog refresh.
- [ ] Remove catalog reads from normal runtime startup.
- [ ] Rename or document catalog attachment helpers as maintenance-only if they
      remain for diagnostics.
- [ ] Update catalog docs to state that `model_name` is descriptive and not a
      binding key.
- [ ] Update ADR 0015 status text to say runtime control is superseded by this
      ADR while catalog inventory remains.

### Stage 4: DataNode Identifier Resolution

- [ ] Update `storage_data_node_identifier(storage_table)` to call
      `storage_table.get_identifier()`.
- [ ] Remove fallback DataNode identifier construction from storage class
      authored names.
- [ ] Add tests proving DataNode default identifiers equal the attached backend
      MetaTable/TimeIndexMetaData identifiers.

### Stage 5: Pricing Binding Defaults

- [ ] Remove static pricing binding defaults based on
      `markets_data_node_identifier("DiscountCurvesTS")` and
      `markets_data_node_identifier("IndexFixingsTS")`.
- [ ] Seed default pricing market-data bindings from
      `DiscountCurvesStorage.get_identifier()` and
      `IndexFixingsStorage.get_identifier()`.
- [ ] Ensure pricing bootstrap attaches the required pricing storage models
      before seeding default bindings.
- [ ] Update the bond pricing example to store identifiers returned from the
      attached storage classes.
- [ ] Add regression tests proving no pricing binding persists
      `mainsequence.examples.DiscountCurvesTS` or
      `mainsequence.examples.IndexFixingsTS`.
- [ ] Add a pricing resolver test proving `APIDataNode.build_from_identifier`
      receives the same identifier returned by `DiscountCurvesStorage.get_identifier()`.

### Stage 6: Documentation And Validation

- [ ] Update bootstrap documentation to describe direct runtime attachment.
- [ ] Update pricing documentation to explain that market-data bindings store
      SDK-resolvable DataNode/MetaTable identifiers from attached storage
      classes.
- [ ] Update catalog documentation to describe inventory-only semantics.
- [ ] Run focused runtime attachment tests.
- [ ] Run pricing bootstrap and bond example tests.
- [ ] Run `mkdocs build --strict`.
