# Identity and scope

A table has several identities. Keep them separate when authoring, resolving,
migrating, or deleting a resource.

| Identity | Scope and purpose |
| --- | --- |
| `MetaTable.uid` | Public catalog UUID, used by HTTP resources and grants. |
| `identifier` | Optional logical name, unique in the connected catalog when non-empty. |
| Physical binding | DataSource UID + SQL schema + table name identify one physical relation in the catalog. |
| Update identity | Update hash + output table UID identify a configured producer record. |
| Contract fingerprint | Optional deterministic utility output; it is not a table UID or an automatic table name. |

The authenticated `/runtime-context/` descriptor supplies effective DataSource
metadata, dialect, parameter style, and default schema. Local responses also carry Git provenance
so a client cannot accidentally use an API started from another branch. Each
local workspace has one SQLite database for system and user tables, selected by
canonical repository, checkout, and Git branch. Hosted APIs use the PostgreSQL,
TimescaleDB, MySQL or MSSQL runtime DataSource their deployment declares, for both
roles; the deployment's migration Job initializes it. Local Settings initializes or
selects the SQLite file. Both use the same bootstrap operation.

The SDK supplies trusted User identity, active Team UIDs, Organization admin status,
and independent Git source facts. MetaTables owns workspace identity and
Reader/Writer table/namespace grants. It does not store an independent membership
registry or replicate platform Organization policy. See the implemented
[Security model](../security/index.md) for administration, sharing, and revocation.

## Namespaces are not schemas

A catalog **namespace** groups tables in the connected catalog. Its normalized
name is unique in the catalog. A **SQL schema** names a physical database
container. A **migration namespace** identifies a provider's Alembic stream.
An updater **hash namespace** isolates configured producer identities.

Use each independently. Setting a catalog namespace does not move a physical
table or change its database schema. Changing a producer's hash namespace does
not create a different output table.

## Author physical names explicitly

Use `schema_table_name("ledger", "account")` for an application/package-prefixed
name such as `ledger__account`. Declare identifiers, descriptions, namespace, and
column metadata alongside the SQLAlchemy model. Authored Alembic-managed physical
names are stable across contract changes; schema evolution uses revisions.

The low-level API creation path for `backend_managed` tables chooses its own
physical name. It is distinct from the ordinary provider-based authoring path.

Provider reconciliation resolves by DataSource UID, physical schema, and physical
table name, then validates provider and lifecycle state. Do not use an optional
identifier as a substitute for this binding. Readers can resolve an existing
time-index table by UID, identifier, or explicit physical identity, with the
connected catalog and resource visibility checks still applied.
