# Administration, actions and roles

These matrices describe the implemented [security model](index.md)
([ADR 0024](../adr/api/0024-namespace-and-table-access-roles.md)). The API checks one
action for every operation; a role is a named set of actions. Application DDL runs in
the client with the configured environment login's database privileges.

## Application administration

These operations affect the application instance or its storage configuration.
Organization admin status comes from the platform through the SDK.

| Operation on this MetaTables | Any person (`member`) | Organization admin |
| --- | --- | --- |
| Enter the application and browse what you can see | Yes | Yes |
| Create a namespace whose name is free, and own it (`namespaces.create`) | Yes | Yes |
| Create or register a table outside any namespace, and own it (`tables.create`) | Yes | Yes |
| Configure, validate, disable, or remove DataSources | No | Yes |
| Select the runtime DataSource where supported | No | Yes |
| Initialize or upgrade MetaTables system tables in Local Settings (Hosted: the deployment's migration Job) | No | Yes |
| Run the database security check now (Hosted: it also runs daily) | No | Yes |
| Destroy a local runtime database through Settings | No | Yes |
| Discover and import external tables and views | No | Yes |
| Every action on every namespace and table, data included | No | Yes |

Workload Users are not `member`s: they never create tables outside a namespace and
never grant or revoke roles. A workload creates a namespace only by registering a table
into a free name, and then holds `editor` on it. They use the roles granted to them or
to their Teams.

In Local mode the operator, the SDK identity running the local API, is the admin of
that runtime for every row above, whatever their platform admin flag: the SQLite file,
its catalog and its local credentials are theirs. This includes setting up the
runtime and the `metatables credentials` commands.

Hosted runtime setup belongs to the deployment's migration Job; Settings and the API
check the platform admin fact. Configuring a pending database does not make the first
caller an admin.

## Namespace actions and roles

| Action | `metadata_viewer` | `data_viewer` | `data_writer` | `editor` | `owner` |
| --- | --- | --- | --- | --- | --- |
| `namespaces.get`: see it, its description and access map | Yes | Yes | Yes | Yes | Yes |
| `namespaces.update`: rename and describe it | No | No | No | Yes | Yes |
| `tables.create`: create or register a table in it, move a table into it | No | No | No | Yes | Yes |
| `namespaces.get_access`: see who holds which role | No | No | No | Yes | Yes |
| `namespaces.set_access`: grant and revoke roles | No | No | No | No | Yes |

A namespace role also gives the table role of the same name on every table currently
in the namespace, including tables created later.

The people who manage a namespace's creating workload hold `namespaces.get`,
`namespaces.get_access` and `namespaces.set_access` on it, with no role. They may grant
any role there, `owner` included, but they get no table actions and change no
table-level bindings.

## Table actions and roles

| Action | `metadata_viewer` | `data_viewer` | `data_writer` | `editor` | `owner` |
| --- | --- | --- | --- | --- | --- |
| `tables.get`: metadata, schema, contract, lineage, search, impact preview | Yes | Yes | Yes | Yes | Yes |
| `tables.get_data`: read, query, preview and export rows; statistics | No | Yes | Yes | Yes | Yes |
| `tables.update_data`: insert, update, upsert and delete rows; time-index delete-after-date | No | No | Yes | Yes | Yes |
| `tables.update`: descriptions, labels, configuration, compression and retention, moving it out of its namespace | No | No | No | Yes | Yes |
| `tables.migrate`: migration connection and contract finalization | No | No | No | Yes | Yes |
| `tables.operate_updaters`: register, configure and run its updaters | No | No | No | Yes | Yes |
| `tables.delete`: delete managed storage or unregister | No | No | No | Yes | Yes |
| `tables.get_access`: see who has access and its history | No | No | No | Yes | Yes |
| `tables.set_access`: grant and revoke roles | No | No | No | No | Yes |

Principals: every role can be granted to people, workload Users and Teams, except
`owner`, which goes to people and Teams only. A principal holds at most one role on an
object; its access is the strongest of its own, its Teams' and its namespace's roles.
Without any binding there is no access.

## Operations involving several resources

Permissions follow the resources actually affected:

- A query needs `tables.get_data` on every table it reads and `tables.update_data`
  on every table it changes. Supplying an authorized table UID does not authorize arbitrary
  SQL against other tables.
- A confirmed cascade delete needs `tables.delete` on every table it drops. A
  foreign-key action (`CASCADE`, `SET NULL`, `SET DEFAULT`) needs no access to the
  referencing tables: their own foreign keys authorize it (see
  [Foreign keys and cascades](#foreign-keys-and-cascades)). Migration connection
  admission checks all provider catalog tables, including their registry. The
  resulting direct connection is governed by database privileges, not roles.
- An updater needs `tables.operate_updaters` on its output and `tables.get_data` on
  its inputs. A read-only `TimeIndexTableRef` does not require control of the upstream
  producer. Running an upstream producer requires `tables.operate_updaters` on that
  producer's output.
- Moving a table between namespaces requires `tables.update` on the table and
  `tables.create` on the destination namespace. It changes inherited access, so the
  UI must show that impact.

Every role remains subject to lifecycle safeguards: a reserved table is not
ready for ordinary writes, active work can block destructive changes, and deletion
protections and dependency constraints still apply. Read-only or disabled sources
cannot be made writable by a role. Unsupported engine operations remain
unsupported.

For an external table, deletion removes its MetaTables registration; it does not
drop the externally owned physical relation. Application system tables and grant
records cannot be edited as ordinary API table data. Direct migration access uses
the environment login's privileges; its restrictions are the environment operator's responsibility.

## Foreign keys and cascades

**Write on a table depends only on that table's own roles.** Tables that
reference it, directly or through any chain of foreign keys, never add or remove
access to it.

A foreign key belongs to the referencing table. Whoever controls that table's
schema chooses its action, and so decides what happens to their own rows when a
referenced row is deleted or its key changes:

| Action on the referencing table | What happens to its rows |
| --- | --- |
| `CASCADE` | Deleted with the referenced row, or re-keyed with it |
| `SET NULL` / `SET DEFAULT` | Their reference is cleared or reset |
| `RESTRICT` / `NO ACTION` | The database refuses the change while they exist |

A caller who changes a referenced row therefore needs no access to the
referencing tables. The database applies each referencing table's action as part
of that write; MetaTables adds no check of its own. PostgreSQL runs these actions
as the referencing table's owner.

| Operation on a referenced table | Access required |
| --- | --- |
| Insert rows, or update columns no foreign key references | `tables.update_data` on the table |
| Delete rows, or update referenced key columns | `tables.update_data` on the table; each referencing table's action then applies |
| Drop the table with the confirmed cascade delete | `tables.delete` on the table and on every referencing table it drops |

For example, Alice owns `assets`. Carol's `details` table references `assets`
with `ON DELETE CASCADE`. Everyone with `data_writer` on `assets` can still insert, update and delete
assets without any access to `details`. When they delete an asset, the database
deletes Carol's rows for it, because Carol's foreign key says so. If Carol wants
her rows kept, she uses `RESTRICT` or `NO ACTION`, and the database then refuses
to delete assets her rows still reference. Dropping `assets` with the confirmed
cascade delete would drop `details` too, so it needs `tables.delete` on both.

Referencing another owner's table is a commitment: its writers' deletes and key
updates apply your foreign key's action to your rows.

**Seeing the effects first.** `table.get_impact(action=...)` (or
`GET /meta-tables/{uid}/impact/`) lists every table a row delete, key update or
table drop reaches and what happens to each. Cascade effects are information,
never a reason the action is blocked. Tables you cannot view appear as opaque
nodes. See [ADR 0016](../adr/api/0016-impact-preflight.md).

**SQLite limitation.** In a local SQLite runtime, MetaTables' authorizer is also
asked about the reads and writes that foreign-key actions make, and it cannot
tell them apart from the caller's own. A delete or key update on a referenced
table therefore fails unless the caller can access every referencing table.
PostgreSQL does not have this limitation; MySQL and SQL Server are pending
verification against their containers.

## Choosing the right page

The table page holds data, schema, updater, deletion and access actions, shown as
the caller's role allows. The namespace page holds its tables and its Access panel.
Nobody needs global Security for their own tables. An Organization admin uses
Settings for DataSources and runtime configuration, and Security for the security
check and catalog-wide inspection.

See [ownership, roles, and inheritance](ownership-and-sharing.md) for examples of
granting, inheritance and revocation.


## Imported tables and views

Discovery and creation of external registrations require an administrator.
Roles and namespace inheritance govern imported output. `editor` permits metadata
refresh and unregistration, and `owner` sharing; no role makes an imported view
writable. External reads use the stored connection account through the bounded
relation reader. They create no database roles, grants, helper objects or tables
in the external database, even with a privileged account configured as read-only.
Only the runtime catalog stores registrations and role bindings.

Runtime views use native permission checks and adapter dependency validation.
SQLite permits view-only output through the bounded reader; its arbitrary SQL
path still requires access to the underlying tables to prevent CTE origin spoofing.
