# 0023. Deterministic Alembic Schema And Identifier Naming

## Status

Proposed

## Context

ADR 0022 moved `ms-markets` to the SDK-managed Alembic migration workflow. The
first generated revision files exposed a bad autogenerate shape:

```python
op.drop_constraint(
    op.f("ms_markets__assetcurrentpricingdetails__mainsequ_asset_uid_fkey"),
    "ms_markets__assetcurrentpricingdetails__mainsequence_examples",
    type_="foreignkey",
)
op.create_foreign_key(
    None,
    "ms_markets__assetcurrentpricingdetails__mainsequence_examples",
    "ms_markets__asset__mainsequence_examples",
    ["asset_uid"],
    ["uid"],
    source_schema="public",
    referent_schema="public",
    ondelete="CASCADE",
)
```

The database already has the reflected foreign-key name. The churn is not
caused by a missing backend constraint. It is caused by Alembic comparing
schema-qualified SQLAlchemy metadata against reflected default-schema database
objects and by unstable Python-side constraint names.

Alembic foreign-key comparison includes source schema, source table, source
columns, target schema, target table, target columns, and FK options.
PostgreSQL's `public` schema is the default schema. In autogenerate,
default-schema reflected objects are represented as `schema=None`. Therefore
authoring package metadata with explicit `schema="public"` makes Alembic see a
false difference:

```text
reflected FK: schema=None
metadata FK:  schema="public"
```

That false `None` versus `public` difference is enough for Alembic to emit FK
drop/create churn even when the FK names and options are identical.

The current metadata also lacks deterministic FK naming:

```python
class MarketsBase(DeclarativeBase):
    metadata = MetaData()
```

Model declarations use natural SQLAlchemy `ForeignKey(...)` declarations
without `name=...`, so model-side FK names are `None`. Once Alembic decides a
foreign key differs, it renders `op.create_foreign_key(None, ...)` and can
produce invalid downgrade operations such as
`op.drop_constraint(None, ..., type_="foreignkey")`.

Indexes have a separate naming problem. Many models declare `Index(None, ...)`.
SQLAlchemy's default index naming is based on the first indexed column. That
creates duplicate generated names when a table has both a single-column index
and a composite index that starts with the same column. The namespace suffix can
also push generated index names over PostgreSQL's identifier limit. PostgreSQL
visible identifiers are limited to `POSTGRES_IDENTIFIER_MAX_LENGTH` characters
in the SDK, currently 63. Names longer than that are reflected back as truncated
database names, which causes more Alembic drop/create noise.

Nothing is deployed yet for this migration stream, so bad generated revisions
can be discarded after the comparison contract is fixed.

## Decision

`ms-markets` will make Alembic metadata deterministic before accepting any
source revision files.

The fix has two parts:

1. Make Alembic schema reflection match the authored metadata.
2. Centralize all physical table, foreign-key, primary-key, unique-constraint,
   check-constraint, and index naming in one package-owned naming module.

### Default Schema Normalization

`ms-markets` must treat PostgreSQL `public` as the default schema in authored
SQLAlchemy metadata. Default-schema package tables and the package Alembic
version table are authored as `schema=None`, not `schema="public"`.

This means:

- `MARKETS_SCHEMA` is `None`;
- `MARKETS_DEFAULT_SCHEMA` records the database default name `public`;
- `markets_table_args(...)` omits the SQLAlchemy `schema` table option when
  the requested schema is `None`, empty, or `public`;
- `MarketsAlembicVersion.__alembic_version_schema__` is `None`;
- the SDK `PlatformManagedMetaTable.__table_cls__` default-schema behavior is
  overridden in the `ms-markets` mixins so it cannot force `public` into the
  SQLAlchemy `Table` metadata;
- explicit named schemas remain supported, but only non-default schemas are
  authored as schema-qualified metadata.

`src/msm/migrations/env.py` must not force schema-aware comparison for default
schema metadata. It should enable `include_schemas` only when the provider
metadata or version table actually uses a non-default named schema.

The Alembic environment shape is:

```python
from msm.base import MARKETS_DEFAULT_SCHEMA, MARKETS_SCHEMA


def _included_schema(name: str | None) -> bool:
    if MARKETS_SCHEMA is None:
        return name in (None, MARKETS_DEFAULT_SCHEMA)
    return name == MARKETS_SCHEMA


def _uses_named_schemas() -> bool:
    migration = _migration_provider()
    if migration.version_table_schema is not None:
        return True
    return any(table.schema is not None for table in migration.target_metadata.tables.values())


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return _included_schema(name)

    schema_name = parent_names.get("schema_name") if parent_names else None
    if not _included_schema(schema_name):
        return False

    return _migration_provider().include_name(name, type_, parent_names)


def include_object(object_, name, type_, reflected, compare_to):
    object_schema = getattr(object_, "schema", None)
    if not _included_schema(object_schema):
        return False

    return _migration_provider().include_object(
        object_,
        name,
        type_,
        reflected,
        compare_to,
    )


def _configure_kwargs():
    migration = _migration_provider()
    return {
        "target_metadata": migration.target_metadata,
        "version_table": migration.version_table,
        "version_table_schema": migration.version_table_schema,
        "include_schemas": _uses_named_schemas(),
        "include_name": include_name,
        "include_object": include_object,
        "compare_type": True,
        "compare_server_default": True,
    }
```

The important behavior is that default-schema metadata and default-schema
reflection both compare as `None`. The provider still owns table scope.

### Naming Module

Add one independent naming module under `src/msm/`, for example:

```text
src/msm/schema_names.py
```

This module owns all deterministic physical names used by SQLAlchemy metadata.
It should not import model classes. It should operate on strings and normalized
name parts only, so it can be used safely by `msm.base`, tests, and migration
configuration without creating model import cycles.

The module must stay domain-neutral. It is intended to be portable to
`mainsequence-sdk`, so it must not expose markets-specific helper names or know
about `ms-markets` models. Package-specific code such as `msm.base` supplies
the app prefix, namespace suffix, and any compatibility aliases.

The module should provide helpers with this intent:

```python
normalize_identifier_part(value: str, *, field_name: str = "identifier part") -> str
bounded_identifier(*parts: str, max_length: int = POSTGRES_IDENTIFIER_MAX_LENGTH) -> str
schema_table_name(app: str, concept: str, suffix: str | None = None) -> str
parse_schema_table_name(table_name: str) -> SchemaTableNameParts
schema_index_name(table_name: str, columns: Sequence[str], *, unique: bool = False) -> str
schema_foreign_key_name(
    table_name: str,
    columns: Sequence[str],
    target_table: str,
    target_columns: Sequence[str] = (),
) -> str
schema_primary_key_name(table_name: str) -> str
schema_unique_constraint_name(table_name: str, columns: Sequence[str]) -> str
schema_check_constraint_name(table_name: str, constraint_name: str | None = None) -> str
sqlalchemy_naming_convention() -> dict[str, Any]
```

The exact function names can change during implementation, but the behavior
must be fixed:

- normalize dots, dashes, whitespace, uppercase letters, and other separators
  the same way for tables, indexes, and constraints;
- support an `app__concept` table convention where the package supplies the
  app name, for example `ms_markets`;
- append optional package namespace suffixes only through the table-name helper;
- keep every returned identifier within `POSTGRES_IDENTIFIER_MAX_LENGTH`;
- include a short deterministic digest when a name must be shortened;
- compute the digest from the full untruncated semantic payload;
- include all indexed or constrained columns in index/constraint identity, not
  only the first column;
- keep generated names stable across processes and Python versions;
- avoid handwritten per-model FK/index names unless a model has a genuine
  exceptional requirement.

### SQLAlchemy Naming Convention

`MarketsBase.metadata` must use a SQLAlchemy naming convention that delegates to
the naming module through custom naming tokens. The convention should cover at
least:

```text
pk
fk
ix
uq
ck
```

Model code should continue to use natural SQLAlchemy declarations:

```python
ForeignKey(f"{AssetTable.__table__.fullname}.uid", ondelete="CASCADE")
Index(None, "account_uid", "time_index", unique=True)
```

The metadata naming convention, not each model declaration, should assign the
physical FK/index names. This keeps models readable while giving Alembic stable
constraint identity.

### Revision Policy

Generated revision files under:

```text
src/msm/migrations/versions/
```

must not be accepted when they contain unrelated FK/index churn. This ADR fixes
the metadata and Alembic comparison contract so future SDK CLI revision output
can be reviewed against a deterministic baseline. It does not require creating
migration revisions as part of this implementation.

A follow-up revision for a single model change must not drop and recreate
unrelated FKs or indexes.

### Generated Revision Review

The first generated file:

```text
src/msm/migrations/versions/0001_migration.py
```

fixed deterministic constraint and index naming, but it was still generated
from explicit `schema="public"` metadata. The second no-op autogenerate check
proved that explicit default-schema metadata is still wrong: Alembic generated
FK drop/create churn where every FK name matched but the reflected side was
`schema=None` and the metadata side was `schema="public"`.

Observed shape from the initial/base revision:

- `44` `op.create_table(...)` operations and matching `44`
  `op.drop_table(...)` operations;
- `75` `op.create_index(...)` operations and matching `75`
  `op.drop_index(...)` operations;
- `40` embedded `sa.ForeignKeyConstraint(...)` declarations;
- no standalone `op.drop_constraint(...)` calls;
- no standalone `op.create_foreign_key(None, ...)` calls;
- no `op.drop_constraint(None, ...)` downgrade operations;
- PK, FK, CK, and index names are deterministic `op.f(...)` names;
- generated `op.f(...)` names stay within the PostgreSQL identifier length
  limit.

Observed shape from the no-op revision attempt:

- `40` FK `drop_constraint(...)` operations;
- `40` FK `create_foreign_key(...)` operations;
- no index churn;
- the FK name sets were identical between drop and create;
- the drop side had no schema argument;
- the create side had `source_schema="public"` and `referent_schema="public"`.

That proves the remaining issue was default-schema normalization, not FK
naming.

This review does not close the no-op autogenerate task. A separate check must
still apply the baseline to a database and run autogenerate again without model
changes after default-schema normalization. That no-op check is the evidence
that unchanged FKs and indexes do not produce churn.

The reviewed revision includes the `mainsequence_examples` namespace suffix in
physical table names. That is valid only when the intended migration target is
the `mainsequence.examples` namespace. Future generated revisions must be
reviewed for accidental namespace suffix changes before they are accepted.

## Implementation Tasks

- [ ] Add regression tests that reproduce the current bad autogenerate inputs:
      explicit `public` metadata, reflected/default-schema comparison, unnamed
      FKs, and duplicate/overlong index names.
- [x] Add `src/msm/schema_names.py` or an equivalent independent naming module
      for table, FK, PK, UQ, CK, and index names.
- [x] Move the current table-name normalization/truncation logic out of
      `src/msm/base.py` into the naming module, leaving compatibility imports
      in `msm.base` if public callers already import `markets_table_name`.
- [x] Implement bounded-name generation that always stays within
      `POSTGRES_IDENTIFIER_MAX_LENGTH` and uses a deterministic digest from the
      full semantic payload.
- [x] Add unit tests for naming normalization, suffix handling, truncation,
      digest stability, collision resistance for same-first-column indexes, and
      the PostgreSQL length boundary.
- [x] Configure `MarketsBase.metadata` with a SQLAlchemy naming convention for
      PKs, FKs, indexes, unique constraints, and check constraints.
- [x] Verify loaded provider metadata has no unnamed FK constraints and no
      unnamed or over-limit indexes.
- [x] Normalize the PostgreSQL default schema so `public` is authored as
      `schema=None` in SQLAlchemy metadata and the Alembic version table schema.
- [x] Override the SDK default table-construction path in the `ms-markets`
      mixins so default-schema tables are not forced back to `schema="public"`.
- [x] Update `src/msm/migrations/env.py` so `include_schemas` is enabled only
      when provider metadata actually uses non-default named schemas.
- [x] Review the generated `src/msm/migrations/versions/0001_migration.py`
      baseline for deterministic PK/FK/CK/index names and absence of standalone
      FK drop/create churn.
- [ ] Verify Alembic autogenerate no longer emits FK drop/create pairs for
      unchanged FKs in `public`.
- [ ] Verify Alembic autogenerate no longer emits index churn for unchanged
      single-column/composite index pairs.
- [ ] Add a focused test or scripted check that upgrades to head, runs
      autogenerate again without model changes, and confirms no schema
      operations are produced.
- [ ] Resolve the git/index state for
      `src/msm/migrations/versions/0001_migration.py` so the reviewed generated
      file is tracked normally instead of appearing as a staged delete plus an
      untracked replacement.
- [x] Update MetaTable migration docs to state that default PostgreSQL `public`
      schema is authored as `schema=None`, named schemas are opt-in, deterministic
      naming is required, and generated revisions with unrelated FK/index churn
      must be rejected.

## Consequences

Alembic revision review becomes stricter: generated files with unrelated
FK/index churn are considered invalid input, not something to manually clean up
and commit.

`ms-markets` keeps natural SQLAlchemy FK/index declarations in model files, but
the package owns the physical naming contract through one naming module and
`MarketsBase.metadata`.

The naming module becomes a long-lived compatibility boundary. Once a migration
has been released, changing name-generation rules is itself a migration concern
because it can cause Alembic to see rename/drop/create operations.

If a future provider uses a real non-default schema, `include_schemas` must be
enabled and provider filters must be tested so Alembic does not scan unrelated
tables in the same database.
