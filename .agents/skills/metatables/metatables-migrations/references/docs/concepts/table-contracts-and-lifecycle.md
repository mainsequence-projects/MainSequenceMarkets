# Table contracts and lifecycle

The relational contract version is `relational-table.v1`. SQLAlchemy authoring
helpers derive it from the user's table metadata. The API normalizes it, checks
catalog invariants and foreign-key visibility, and verifies physical state when
the operation requires it.

A normalized API contract contains `physical` binding, ordered `columns`,
`indexes`, and `foreign_keys`. Column definitions carry type, nullability, key
information, and human descriptions. The Python SQLAlchemy helper emits the
physical and column contract plus authoring metadata. Alembic owns index and
foreign-key DDL; finalization/introspection populates their catalog projections.
Keep foreign keys on SQLAlchemy models and include both ends in the selected
provider. Do not author catalog foreign-key UID links in application migrations.

Time-index tables add `time_index_name`, ordered `index_names`, cadence, and a
storage layout. A time-index grain has one unique coordinate per observation.
`PlatformTimeIndexMetaTable` adds its full-grain SQLAlchemy unique index before
Alembic autogeneration. Add only additional workload-specific indexes yourself.

## Three lifecycle axes

| Catalog management | Physical schema management | Provisioning | Behavior |
| --- | --- | --- | --- |
| `platform_managed` | `backend_managed` | `reserved` → `active` | The MetaTables API creates and manages the physical relation. |
| `platform_managed` | `alembic_managed` | `reserved` → `active` | A selected migration provider applies DDL and finalizes the catalog. |
| `external_registered` | `external_registered` | `active` | A pre-existing relation is verified and registered. |

`backend_managed` names a schema-management mode of the MetaTables API.
Direct API-managed creation currently requires PostgreSQL; local SQLite uses
the same Alembic provider workflow as hosted application authoring.
Management describes catalog ownership, schema management describes who applies
DDL, and provisioning describes readiness. Treat them as independent fields.

For ordinary managed authoring, use the migration provider workflow. The provider
reserves its Alembic registry and application tables, obtains a scoped migration
connection, runs Alembic, then finalizes and binds the physical tables. Its
registry is an Alembic-managed, platform-managed root with no parent registry UID.

A reserved table is not ready for routine storage operations. Finalization
introspects actual storage and returns per-table outcomes. A batch can contain
both successes and failures; inspect every result before declaring it complete.

## Validation and evolution

Pure contract validation checks payload shape and supported values; it does not
prove a relation exists, grant access, or apply DDL. Introspection reads physical
state and refreshes catalog metadata. Provider finalization reconciles reserved
bindings with that state.

Evolve managed schemas with a new Alembic revision. Keep applied revisions
immutable. Registering a changed model repeatedly is not a migration strategy.
External schema changes remain the external owner's responsibility.

Ordinary deletion unregisters external catalog metadata without dropping its
physical relation. Managed deletion can remove physical storage and is subject
to grants, protections, references, and operation-journal state. See
[recovery and deletion](../operations/recovery-and-observability.md).
