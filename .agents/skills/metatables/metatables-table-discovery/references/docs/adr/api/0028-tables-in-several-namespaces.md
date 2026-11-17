# ADR 0028: A table can be in several namespaces

Status: Accepted.

Implementation status: implemented on development, in the API, the Python client, the
migration handler and the Analyst's tools. System migration `0016_table_namespaces`
converts existing catalogs. Non-container tests pass on SQLite, including the migration
from a populated catalog and the database privileges following memberships. The
migration and the privilege refresh have not been run on PostgreSQL, TimescaleDB, MySQL
or SQL Server. The MetaTables Admin reads the `namespaces` list and adds or removes a table from a
namespace on the table's Access tab (its `development` branch); adding is browser-tested
against mocked routes, removing is not. Hosted deployment is pending.

Owner: MetaTables API, with client and Admin consumers.

Related decisions: [ADR 0024](0024-namespace-and-table-access-roles.md) (roles on
namespaces and tables, amended here), [ADR 0007](0007-database-enforced-table-access.md)
(database roles enforce table access), [ADR 0013](0013-application-owned-migrations.md)
(application migrations) and [ADR 0018](0018-table-search.md) (table search).

## Context

A namespace is an access group: a role on it gives the same role on every table in it,
including tables added later (ADR 0024). A table is in at most one namespace, through
one nullable column, `meta_table.namespace_uid`.

An application therefore cannot give access to part of its tables without naming them.
The Alpaca connectors application wants a Team to read its market-data tables but not
its account tables. Today it can:

- grant the Team a role on the whole namespace, which covers the account tables too;
- grant the Team a role on each market-data table, one request per table and per
  principal, and again for every table added later; or
- split the namespace in two. The two sets must then never overlap, every principal
  that had the whole namespace is granted again on each part, and each existing table
  is moved by hand, because a registration ignores a changed namespace.

Nothing else groups tables: labels never authorize, and Teams group principals.

The single namespace is not part of a table's identity. Identifiers are unique in the
whole catalog, storage names are generated, and a namespace is not a SQL schema. It is
one column and the checks that read it.

## Decision

### 1. The model

A table can be in any number of namespaces. A namespace role gives the table role of
the same name on every table in the namespace, as today. A caller's role on a table is
the strongest among their direct bindings, their Teams' bindings and the bindings on
**every** namespace the table is in.

```text
namespace alpaca-connectors          namespace alpaca-market-data
  bars  quotes  orders  positions      bars  quotes

Team alpaca-development: editor       Team research: data_viewer
```

Team research reads `bars` and `quotes` and nothing else. A market-data table added
later is readable as soon as it is registered in both namespaces. All namespaces of a
table are equal: none is its home.

There is still no explicit deny. A second namespace only adds access; it never hides a
table from someone who holds a role on another of its namespaces.

### 2. The catalog

A new system migration creates `meta_table_namespace` and removes
`meta_table.namespace_uid`:

| Column | Meaning |
| --- | --- |
| `meta_table_uid`, `namespace_uid` | The membership; together the primary key. Both cascade on delete |
| `source` | `declared` (set by a registration) or `manual` (set by a person) |
| `added_by_user_uid`, `created_at` | Who added it and when |

Every existing link becomes one `declared` row, so no access changes when the migration
runs.

### 3. Declaring namespaces in the application

A table declares its namespaces in code:

```python
class AlpacaBase(PlatformManagedMetaTable):
    __metatable_namespace__ = "alpaca-connectors"

class MarketData:
    __metatable_namespaces__ = ("alpaca-market-data",)

class Bars(MarketData, AlpacaBase): ...      # in both
class Orders(AlpacaBase): ...                # only alpaca-connectors
```

- `__metatable_namespace__` keeps its meaning: one name, and a class that sets it
  replaces what its base set.
- `__metatable_namespaces__` is new and only adds: a table is also in every name that
  it or any of its base classes lists there. A table joins a subset by having its base;
  no table carries the full list.
- A SQLAlchemy Core table uses `info["namespace"]` and `info["namespaces"]` the same
  way.

The two attributes are separate because existing code relies on replacement. The base
class of every Alembic version table sets `mainsequence.migrations`, and each
application replaces it with its own namespace. If one attribute were collected from
base classes, every version table would also join `mainsequence.migrations`, a
namespace shared by all applications, and any table that replaces its base's namespace
today would silently stay in both.

A table declared this way is migration-managed: the client refuses to register it
outside its migration. Its namespaces reach the API in two requests:

- **New table.** The reservation request carries `namespaces`. The caller needs
  `tables.create` on each one, checked before a missing one is created. A reservation
  request holds up to 200 tables and is one transaction: a refusal rolls it back, so it
  reserves nothing and creates no namespace. A missing namespace is created as ADR 0024
  describes.
- **Existing table.** A migration does not reserve an existing table again; it
  finalizes it, at the end of every `upgrade` and `downgrade`, also when no revision is
  pending. The finalization request carries the declared list in `authored_metadata`,
  beside the description and labels, when it differs from the table's `declared`
  namespaces. The API adds the missing
  `declared` memberships and removes the `declared` ones no longer listed, under the
  rules of section 5, and leaves `manual` ones alone. It does so only when the request
  names the table's migration provider. Today a finalization that names no provider
  skips that check; for namespaces the provider is required. Today a changed namespace
  is silently ignored; that ends here.

### 4. Migrations and their folders

Nothing in a migration follows a table's namespaces, and that stays so:

- `metatables migrations scaffold --namespace ledger` uses the one value three times:
  as the provider's migration namespace, as the name of its revisions folder
  `versions/ledger/`, and as the catalog namespace of its Alembic version table. Only
  the third is a catalog namespace.
- A provider takes the models its registry returns, whatever namespaces they declare.
  Its revisions folder, its provider key and its version table do not change when a
  table declares another namespace.
- A namespace is not a schema change. Declaring or removing one needs no revision and
  no new folder: the next `upgrade head` applies it at finalization.

So an application that adds `alpaca-market-data` edits its models and deploys. It does
not scaffold a second provider. A table belongs to one provider; a model returned by
two registries is refused at reservation as belonging to another provider.

Two things in the client change:

- The Alembic version table is in the one namespace its application gives it. The
  client checks today that the catalog names exactly that namespace and stops the
  migration otherwise. It will check that the table is in it, so a version table that
  someone added to a further namespace still migrates.
- A table document returns each namespace with its `source`, so the client can compare
  the declared list with the `declared` memberships and send it only when they differ.

The migrations skill and the scaffold's help say that `--namespace` names the provider
and its folder, and that further namespaces are declared on the models.

### 5. Who may change a table's namespaces

| Change | Needs |
| --- | --- |
| Add table T to namespace N | `tables.update` on T and `tables.create` on N |
| Remove table T from namespace N | `tables.create` on N |

These are the actions a move needed, applied to one membership at a time. A removal
is checked on the namespace, not on the table, so a role that comes from one namespace
never removes a table from another. Each change is recorded in the table's access
history with the actor and, as the principal, the namespace (`principal_kind` `ns`,
reason `namespace_added` or `namespace_removed`).

A table's last namespace cannot be removed unless a person or Team holds a direct
`owner` binding on the table. Otherwise the table would be left with administrators
only.

### 6. Enforcement in the database

Unchanged in structure (ADR 0007). Each namespace keeps its reader and writer roles; a
table is granted to the roles of every namespace it is in.

The privileges are refreshed when a catalog row of a watched type changes: tables,
grants, namespaces and DataSources. The membership row is a new type and must be added
to that list. Without it, removing a table from a namespace would stop the API's access
and leave the database privilege in place.

### 7. API and clients

- A table document returns `namespaces`, a list of `{uid, name, source}`, instead of
  `namespace` and `namespace_uid`.
- `POST /meta-tables/{uid}/namespaces/changes/` takes `add` and `remove`, two lists of
  names of existing namespaces, applies them in one request and returns the table's
  `namespaces`. Memberships added here are `manual`. `PATCH` no longer accepts
  `namespace`.
- A registration, a reservation and an import carry `namespaces`, a list, instead of
  `namespace`. `register` answers with `registration.namespaces_not_applied`.
- The `namespace` filters match a table that is in the namespace. `namespace__isnull`
  matches a table in none.
- `access/` and `explain` name each namespace a role comes from.
- A table's search document lists every namespace it is in.
- The Analyst's `list_tables` shows a table under each of its namespaces and counts it
  once.
- Every other document that names a table's namespace returns the list: the access
  map, the impact pre-flight, the cascade delete result, run graphs, the schema graph
  and the update pipeline. The updaters' `output_table__namespace` filters match as the
  table filters do.
- The Python client gets `MetaTable.add_to_namespace()` and
  `remove_from_namespace()`. The Admin shows a table's namespaces and lets an editor of
  a namespace add an existing table to it.

## Edge cases

**An editor can widen who owns a table.** Adding a table to a namespace gives that
namespace's owners `owner` on the table. A person with `editor` on `bars` and `owner`
of their own namespace can add `bars` to it and become its owner. The same is possible
today through a move, and worse: the move also removes everyone else's inherited
access. Here nobody loses access, and the change is recorded. This is accepted; see
[Decisions taken](#decisions-taken).

**A workload's managers gain access management.** A migration Job with `editor` on
tables it did not create can declare them in a new namespace. The Job creates that
namespace, so the people who manage the Job manage its access and can grant themselves
`owner` on it, and so on those tables. They could already read, migrate and delete
those tables through the Job; what they gain is deciding who else has access. This is
accepted for the same reason.

**A subset cannot restrict.** Roles are the strongest of all sources. If Team research
also holds `data_viewer` on `alpaca-connectors`, it reads the account tables whatever
`alpaca-market-data` says. A subset works only for principals with no role on the
larger namespace.

**Narrowing in code.** Removing a name from a table's declaration removes that
`declared` membership at the next registration, and its principals lose access to the
table without anyone revoking a binding. This is intended: a deployment must be able to
narrow a subset. A `manual` membership is never removed by a registration.

**A declared and a manual membership of the same pair.** There is one row. A person
adding a table to a namespace it is already declared in changes nothing; a registration
declaring a namespace the table was added to by hand turns the row into `declared`, so
code owns it from then on.

**Two applications declaring the same table.** Cannot change memberships. The client
refuses to reserve a table that belongs to another provider, and the API refuses to
finalize it with `provider_mismatch` (ADR 0013). The provider key is a name the code
declares, but it is not taken on trust: a finalization must also hold `tables.migrate`
on the provider's own version table.

**Tables with no migration.** Three kinds exist: a table created through the low-level
API, a table imported from an external database, and an external table declared in
code as a SQLAlchemy model and registered with `register_external_sqlalchemy_model`.
None has a provider. Each gets its namespaces in the request that creates it. A later
registration with a different list changes no membership and says so in its answer.

**Refused in the middle.** A reservation refused on one namespace reserves none of its
tables and answers `namespace_access_required` for that namespace, naming the table.
The Alembic version table is reserved by an earlier request, so it and its namespace
already exist when a later namespace is refused, as today when a name is taken.

**A table in no namespace.** Still allowed for a person, who owns it directly. Still
refused for a workload. The last-namespace rule keeps a table from reaching this state
without an owner.

**Deleting a namespace.** No route deletes a namespace today. When one does, it must
refuse while the namespace is the only one of a table that has no direct owner.

**Renaming a namespace.** Memberships hold the namespace's UID, so a rename keeps them.
An application that still declares the old name creates a namespace with that name at
its next registration and its tables join it. This happens today as well and is not
changed here.

**Counts.** A namespace's table count stays the tables in it. The counts of all
namespaces no longer add up to the number of tables.

**The contract fingerprint.** `compute_metatable_contract_hash` includes the namespace.
It is used only in diagnostics and identifies nothing. It will use the sorted list, so
adding a namespace changes the fingerprint and nothing else.

**Imported external tables.** An import still places a table in the one namespace
given, or in `external-<source>`. It can then be added to others like any table.

**Cost.** The database holds two grants for each membership instead of two for each
table in a namespace. Access checks read memberships through an index on
`(namespace_uid, meta_table_uid)`.

## Decisions taken

1. **Adding an existing table to a namespace** needs `tables.update` on the table and
   `tables.create` on the namespace, as a move needs today. Requiring
   `tables.set_access` was rejected: a workload never holds it, so a migration Job
   could not declare a new subset for its existing tables and a person would add each
   one by hand. The cost is accepted: an editor, or the managers of a Job that is an
   editor, can make themselves owners of a table.
2. **A registration removes the `declared` memberships its code no longer declares**
   and never a `manual` one. A registration that only adds was rejected: the code and
   the catalog would disagree silently, and narrowing a subset would always need a
   person.
3. **Two attributes declare namespaces.** `__metatable_namespace__` is unchanged: one
   name, replaced by a subclass. `__metatable_namespaces__` only adds and is collected
   from base classes. One attribute collected from base classes was rejected: every
   Alembic version table would join `mainsequence.migrations`, and a table that
   replaces its base's namespace today would stay in both.
4. **A table's last namespace is removed only when the table has a direct owner.**
   Leaving it to administrators, as a move out does today, was rejected.

5. **Registering a table with no migration again changes no membership.** The answer
   names the declared namespaces it did not apply, and these tables change only
   through `namespaces/changes/`. Applying the list was rejected: two applications can
   register the same external table and nothing tells them apart, so each would undo
   the other, and an import run again with no namespace given would move tables into
   `external-<source>`.

## Consequences

- An application shares part of its tables by declaring a second namespace and granting
  on it once. Later tables are covered by their declaration.
- Subsets can overlap. One namespace per application stays the recommended layout, with
  further namespaces for the parts shared differently.
- A table no longer has one namespace to name. Every document, filter and message that
  says "its namespace" changes, in the API, the client, the Analyst and the Admin.
- Removing all of someone's access to a table can mean revoking bindings on several
  namespaces. `explain` lists them.
- There is no compatibility layer. A client older than this change sends `namespace`
  and is refused by the API, and reads a field the API no longer returns. Applications
  upgrade the MetaTables client together with the API, and the Admin is updated to read
  `namespaces`.
- This amends ADR 0024: "moving" a table becomes adding and removing memberships, and
  `tables.update` no longer covers leaving a namespace. The security guides, the client
  skills and the refusal messages change with it.

## Verification

- A caller with a role on only one of a table's namespaces gets that role, in the API
  and in the database; removing the membership removes it.
- The Alpaca layout end to end as a non-admin: one Job registers tables in two
  namespaces, a Team granted on the second reads only its tables, and a table added
  later is covered.
- A registration adds and removes `declared` memberships and leaves `manual` ones.
- A second provider is refused and changes no membership, and so is a finalization
  that names no provider.
- Adding and removing a membership changes the database privilege in the same request.
- An Alembic version table stays only in its application's namespace.
- A namespace declared on an existing table is applied by `upgrade head` with no
  revision pending and no new folder; a version table added to a further namespace
  still migrates.
- An editor of one namespace cannot remove a table from another.
- The last-namespace rule, and a registration refused on one of several namespaces.
- The migration on a catalog with tables in a namespace and in none.
