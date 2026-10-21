# ADR 0024: Access roles for namespaces and tables

Status: Accepted.

Implementation status: implemented on development, in the API and in the MetaTables
Admin's Access panels. Namespaces created by a workload's registration (sections 3 and 5)
are implemented in the API; the Admin does not yet label the `manager` source. Non-container tests pass. The container matrix passes on SQLite;
on PostgreSQL, TimescaleDB, SQL Server and MySQL one runtime-bootstrap test fails, as it
did before this change. Hosted deployment is pending. The user guides are
[Ownership, roles, and inheritance](../../security/ownership-and-sharing.md) and the
[actions and roles](../../security/permissions.md).

Owner: MetaTables API, with client and Admin consumers.

Related decisions: [ADR 0002](0002-application-administration-and-table-ownership.md)
(administration and table ownership, amended here),
[ADR 0007](0007-database-enforced-table-access.md) (database roles enforce table access),
[ADR 0013](0013-application-owned-migrations.md) (application migrations) and
[ADR 0020](../agent/0020-analyst-reads-as-its-requester.md) (the Analyst reads as its
requester).

## Context

Access to a table or namespace is one of two levels, Reader or Writer. Writer is full
control: it reads and writes rows, changes the schema, runs migrations, operates
updaters, deletes the table and shares it. Neither level says this when it is granted,
and nothing narrower exists. A FastAPI that only writes rows becomes a co-owner of the
tables it writes.

Namespaces have no owner. Only an Organization admin can create a namespace or grant
access to one. Since an application's tables belong to whoever holds Writer on their
namespace ([MetaTables #43](https://github.com/mainsequence-projects/MetaTables/issues/43)),
an ordinary user cannot deploy a new application that uses MetaTables without an admin,
in every Environment.

## Decision

### 1. The model

Access follows role-based access control over a hierarchy of objects: this MetaTables
instance contains namespaces, and a namespace contains tables.

- Every kind of object has **actions**, named `<object type>.<verb>`. Creating an object
  is the action of its type, checked on the parent it is created in: `namespaces.create`
  on the instance, `tables.create` on the namespace (or on the instance for a table
  outside any namespace).
- A **role** is a named set of actions, granted on one object. A role on a namespace
  also covers the tables in it. Each role carries three texts that say what it allows,
  what it can cause and what it does not include.
- A **binding** grants one role to one principal (a person, a workload User or a Team)
  on one object. It records who granted it, when, and its source: `explicit`, `creator`
  or `converted`. The source is shown; it grants nothing by itself.
- A principal holds at most one binding per object; granting another role replaces
  it. Because roles are nested, its access is the strongest role among its own, its
  Teams' and its namespace's bindings. There is no explicit deny.
- Organization admins, Team membership, namespace inheritance and the managers of a
  namespace's creating workload are **computed**, never stored.
- The API checks actions, never role names. One evaluator answers both single checks
  and list filters, so a list never shows what a check would refuse.
- Each action has a level: `read` (see metadata), `use` (read data), `write` (change
  data, the object or its lifecycle) or `permissions` (see or decide access).
- Lifecycle safeguards still apply whatever the role: reserved tables, active work,
  deletion protection, dependency checks and read-only DataSources.

### 2. Objects, actions and roles

These are all the roles that exist. Texts are given as Summary / Impact / Not included.

#### This MetaTables instance

| Action | Level | Covers |
| --- | --- | --- |
| `namespaces.create` | write | create a namespace whose name is free |
| `tables.create` | write | create or register a table outside any namespace |
| `metatables.administer` | write | DataSources, runtime selection, Settings, local system migrations, the security check, local database reset, discovery and import of external tables |

**`member`** (implicit; `namespaces.create`, `tables.create`). Holder: every person the
platform admits to this MetaTables. Not workload Users.

- Summary: "Create namespaces and tables in this MetaTables."
- Impact: "You become the owner of what you create and decide who can use it."
- Not included: "Access to namespaces and tables other people created; administration."

**`administrator`** (implicit; every action on every object). Holder: Organization
admins, as the platform reports them on each request.

- Summary: "Do everything in this MetaTables."
- Impact: "Includes reading and changing every table's data, deleting any table and
  changing anyone's access."
- Not included: "Nothing. A call an application makes on an admin's behalf does not
  carry it."

#### Namespaces

| Action | Level | Covers |
| --- | --- | --- |
| `namespaces.get` | read | see the namespace, its description and its access map |
| `namespaces.update` | write | rename it and change its description |
| `tables.create` | write | create or register a table in it, and move a table into it |
| `namespaces.get_access` | permissions | see who holds which role on it |
| `namespaces.set_access` | permissions | grant and revoke roles on it |

A namespace role also gives the table role of the same name on every table in the
namespace, including tables registered later. Moving a table out removes it.

**`metadata_viewer`** (`namespaces.get`; tables: `metadata_viewer`). Principals: people,
workload Users, Teams.

- Summary: "See this namespace and the descriptions and schemas of its tables."
- Impact: "Shows table and column names and descriptions, which can reveal what data
  exists."
- Not included: "Reading rows; changing anything."

**`data_viewer`** (`namespaces.get`; tables: `data_viewer`). Principals: people,
workload Users, Teams.

- Summary: "Read the data of every table in this namespace."
- Impact: "Covers tables added later. Rows read can be copied out and kept after access
  is removed."
- Not included: "Changing rows, tables or access."

**`data_writer`** (`namespaces.get`; tables: `data_writer`). Principals: people,
workload Users, Teams.

- Summary: "Insert, update and delete rows in every table in this namespace."
- Impact: "Covers tables added later. Deleted or overwritten rows can't be restored by
  MetaTables."
- Not included: "Creating tables, changing schemas, deleting tables, deciding access."

**`editor`** (`namespaces.get`, `namespaces.update`, `tables.create`,
`namespaces.get_access`; tables: `editor`). Principals: people, workload Users, Teams.

- Summary: "Create tables in this namespace, and change, migrate, operate and delete
  every table in it."
- Impact: "Covers tables added later. A migration or a delete can remove columns, rows
  or whole tables for everyone who uses them."
- Not included: "Deciding who has access."

**`owner`** (every namespace action; tables: `owner`). Principals: people and Teams.

- Summary: "Everything on this namespace and its tables, including deciding who has
  access."
- Impact: "Anyone you give access to reaches every current and future table in the
  namespace, at the level you choose."
- Not included: "Nothing in this namespace."

#### Tables: MetaTables and TimeIndexMetaTables

| Action | Level | Covers |
| --- | --- | --- |
| `tables.get` | read | metadata, schema, contract, lineage, search results, impact preview |
| `tables.get_data` | use | read rows, SQL that reads it, preview, export, statistics |
| `tables.update_data` | write | insert, update, upsert and delete rows, SQL that changes them, time-index delete-after-date |
| `tables.update` | write | descriptions, labels, column metadata, configuration, compression and retention, moving it out of its namespace |
| `tables.migrate` | write | the migration connection and finalizing its managed contract |
| `tables.operate_updaters` | write | register, configure and run its updaters, and its dependencies |
| `tables.delete` | write | delete its managed storage or unregister it, and the confirmed cascade delete |
| `tables.get_access` | permissions | see who has access and the access history |
| `tables.set_access` | permissions | grant and revoke roles |

An operation on several tables needs the action on each: a query needs `tables.get_data`
on every table it reads and `tables.update_data` on every table it changes; a cascade
delete needs `tables.delete` on every table it drops; an updater needs
`tables.operate_updaters` on its output and `tables.get_data` on its inputs.

**`metadata_viewer`** (`tables.get`). Principals: people, workload Users, Teams.

- Summary: "See this table's description, schema and lineage."
- Impact: "Shows its column names and descriptions."
- Not included: "Reading rows; changing anything."

**`data_viewer`** (`tables.get`, `tables.get_data`). Principals: people, workload Users,
Teams.

- Summary: "Read and query this table's rows."
- Impact: "Rows read can be copied out and kept after access is removed."
- Not included: "Changing rows or the table."

**`data_writer`** (`data_viewer` + `tables.update_data`). Principals: people, workload
Users, Teams.

- Summary: "Insert, update and delete this table's rows."
- Impact: "Deletes and overwrites can't be undone by MetaTables. Foreign-key actions of
  tables that reference it apply to their rows."
- Not included: "Changing the schema or configuration, deleting the table, deciding
  access."

**`editor`** (`data_writer` + `tables.update`, `tables.migrate`,
`tables.operate_updaters`, `tables.delete`, `tables.get_access`). Principals: people,
workload Users, Teams.

- Summary: "Change, migrate, operate and delete this table, and see who has access."
- Impact: "A migration can drop columns and their data; deleting removes the table for
  everyone who uses it."
- Not included: "Deciding who has access."

**`owner`** (`editor` + `tables.set_access`). Principals: people and Teams.

- Summary: "Everything on this table, including deciding who has access."
- Impact: "The owner decides who can read, change and delete it."
- Not included: "Nothing on this table."

### 3. Creation, computed access and constraints

**Creation.**

- A person who creates a namespace is granted `owner` on it (source `creator`). A taken
  name is refused and never adopted; the refusal names its owners when the caller may
  see them.
- Registering a table into a namespace that does not exist creates it. A person who
  does so is granted `owner`. A workload User is granted `editor`, and the namespace
  records it as its **creating workload**: the people who manage that workload manage
  the namespace's access. An existing namespace needs `tables.create`, whoever created it.
- A person who creates a table outside any namespace is granted `owner` on it.
- A table created in a namespace gets no binding: the namespace's roles cover it.

**Computed access.**

| Access | Comes from | Shown as |
| --- | --- | --- |
| Every action on every object | Organization admin, from the platform on each request | `admin` |
| The roles granted to a Team | the caller's current Team membership, from the platform | `team`, with the Team |
| The table role of the same name | a role on the table's current namespace | `namespace`, with the namespace |
| `namespaces.get`, `namespaces.get_access`, `namespaces.set_access` on a namespace | managing its creating workload, from the platform on each request | `manager`, with the workload |

Managing the creating workload is access management only. It gives no role: no access
to the namespace's tables, no `namespaces.update` and no table-level bindings.

**Constraints** that no role overrides:

- A workload User is never granted `owner`, never grants or revokes a role and never
  creates a table outside a namespace. It creates a namespace only by registering a
  table into a free name, and then holds `editor`. A Team holding `owner` gives its
  workload members no access management.
- A non-admin grants roles only to Teams they belong to, checked with the platform at
  that moment, and to people and workload Users they can find in their own platform
  directory.
- A call an application makes for a person carries only that person's access, never
  admin, and stays read-only (ADR 0020).
- The MetaTables Analyst's workload User is granted no roles.

**Granting.** To grant a role on an object, the caller must:

1. hold `set_access` on the object and every action of the role on it (owners and
   admins always do); or
2. manage the target workload User and hold every action of the role on the object; or
3. manage the namespace's creating workload: any role, `owner` included, on that
   namespace.

Revoking your own binding, and lowering or revoking a binding of a workload you manage,
are always allowed. Revoking the last owner leaves the admins. Every grant and revoke is
recorded with the actor, the principal, the old and new role and the time; the history
survives the object's deletion.

### 4. Enforcement in the database

The database keeps the two privilege sets of ADR 0007:

| Role | Database privileges |
| --- | --- |
| `metadata_viewer` | none |
| `data_viewer` | `SELECT` |
| `data_writer`, `editor`, `owner` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |

User, Team and namespace database roles keep their structure. A new admin group role
holds the write privileges on every managed table; an admin's login roles are members
while the platform reports them as admin, refreshed at SQL admission like Team
membership. The API checks every other action. Schema changes keep going through the
migration connection, which `tables.migrate` admits.

### 5. Deploying a new application with nothing created yet

Ana is an ordinary person. She deploys `crm`, whose migration Job `migrate-crm` creates
tables and whose FastAPI `crm-api` reads and writes them. Nothing exists yet.

```text
 Ana (no admin role)                          MetaTables of the Environment
 ───────────────────                          ─────────────────────────────
 1. push the workflow file ──► the platform creates migrate-crm and crm-api
                               and their workload Users; Ana manages them

 2. deploy: migrate-crm  ───────────────────► namespace crm      migrate-crm: editor
            registers its tables in crm                          (creating workload)
                                              its tables (no binding of their own)

 3. grant on crm  ──────────────────────────► crm-api:     data_writer
    (manages migrate-crm)                     Ana or a Team she belongs to: owner

 4. crm-api  ───────────────────────────────► reads and writes their rows
```

1. **Workloads.** Applying the workflow file creates both workload Users before any of
   its Jobs run. The platform reports that Ana manages them.
2. **Namespace and tables.** The first deployment's migration Job registers its tables
   in `crm`. The namespace does not exist, so the registration creates it, grants the
   Job `editor` and records it as the creating workload.
3. **Access.** Because she manages `migrate-crm`, Ana manages `crm`'s access. She grants
   `data_writer` to the FastAPI's workload User, and `owner` to herself or to a Team she
   belongs to, so the namespace keeps an owner if the Job is recreated.
4. **Use.** The FastAPI reads and writes rows; its requests before step 3 were refused,
   and succeed on the next request after it, with no redeployment.

This completes without an administrator:

- Every step needs only the push, the registration in step 2, or managing the Job.
- No namespace is created by hand, and the first migration succeeds.
- A Team is optional. With direct bindings, a recreated workload's new User needs an
  owner, or a manager of the creating workload, to grant its role again. With a Team,
  it needs only Team membership.
- A taken name stops the migration with `namespace_access_required`, naming the Job's
  workload User, the namespace, the missing action and the owners when the Job may see
  them. An owner grants the Job `editor`, or the application uses another namespace.
- Least privilege holds from the start: the FastAPI writes rows but cannot migrate,
  delete or share, and the Job never decides access.
- Each Environment has its own MetaTables. The first deployment there creates the
  namespace; step 3 is repeated by someone who manages the Job in that Environment.

### 6. API and clients

- `GET /access/roles/` returns the catalog: object types, actions, roles and their
  texts. The role documentation is generated from it.
- `POST /namespaces/` creates a namespace (replaces `POST /security/namespaces/`).
- `GET /namespaces/{uid}/access/` and `GET /meta-tables/{uid}/access/` return the
  bindings with their source, who granted each and when. A namespace's document also
  names its creating workload.
- `POST .../access/changes/` grants and revokes roles in one request, checked against
  the access revision the caller read.
- `GET .../access/me/` returns the caller's allowed actions; the Admin shows only the
  buttons they allow.
- `GET .../access/explain/?user_uid=...&action=...` explains why someone can or cannot
  do something. The `manager` source is shown only for the caller: the platform tells
  only the caller which workloads they manage.
- Removed: `PUT /meta-tables/{uid}/permissions`, `PUT /namespaces/{uid}/permissions`,
  `POST /security/namespaces/` and the Reader/Writer assignment documents.
- The Python client gets `Namespace.create()`, `get_access()`, `grant_role()`,
  `revoke_role()`, `allowed_actions()` and `explain()`, replacing `set_access()` and
  `revoke_access()`.
- The Admin's Access panel lists each binding with its role and texts; granting shows
  the texts before it is confirmed.

### 7. Converting existing grants

One new system migration converts every grant, with no compatibility layer:

| Today | After |
| --- | --- |
| Table Reader | `data_viewer` |
| Table Writer | `owner` (a workload User keeps the binding but never uses access management) |
| Namespace Reader | `data_viewer` |
| Namespace Writer | `editor` |
| Namespace without an owner | none; admins hold it until they grant an owner |

Access history is kept. A second migration records each namespace's creating workload;
existing namespaces have none, and their owners and admins manage them.

## Consequences

- An ordinary user deploys a new application in any Environment without an admin.
- Every grant says what it allows, and a workload can write rows without owning the
  table.
- Admins read and write every table directly. Calls made for a person stay limited to
  that person's access.
- A workload can no longer create a table outside a namespace. Updater Jobs that do so
  today must set a namespace.
- Any person, or a workload by registering a table, may claim a free namespace name.
  Admins can rename a namespace or change its owners.
- The people who manage a namespace's creating workload manage its access for as long as
  the platform reports that they manage it. A namespace whose creating workload nobody
  manages any more keeps its owners, and admins.
- The catalog stores bindings instead of Reader/Writer flags, every route checks an
  action, and database reconciliation gains the admin role.
- This amends ADR 0002 (namespace access is no longer admin-only; Reader/Writer become
  roles) and ADR 0007 (roles map to its two privilege sets; the admin role). The
  security guides, the client migration skill and the refusal messages change with it.

## Verification

- Every role's actions, the granting rules and the constraints, covered by tests.
- The catalog, the generated role documentation and the API agree, checked by a test.
- The conversion migration on a catalog with every kind of existing grant.
- The deployment of section 5 end to end as a non-admin, with direct bindings and with a
  Team; a recreated workload; a namespace name already taken.
- A workload's registration creates the namespace with `editor`; a manager of the Job
  grants any role; anyone else is refused.
- In the database: `data_viewer` gets `SELECT` only; `data_writer` writes rows but its
  migration admission is refused; an admin reads a table without a binding.
