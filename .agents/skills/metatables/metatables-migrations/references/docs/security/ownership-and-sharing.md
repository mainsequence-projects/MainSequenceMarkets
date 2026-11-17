# Ownership, roles, and inheritance

## Creating gives ownership

Any person can create a namespace whose name is free; they are granted `owner` on
it. A person who creates or registers a table outside any namespace is granted
`owner` on that table. A table created in a namespace gets no binding of its own:
the namespace's roles cover it, so it never depends on the identity that created it.

`owner` decides who has access. An owner can grant any role on their namespace or
table to people, workload Users and Teams, change it, or revoke it. Several
principals can be owners. `created_by_user_uid` records who created a table and
grants nothing. Organization admins hold every action on every object, so a
namespace or table never ends up without someone who can manage it.

Registering a table into a namespace that does not exist creates it. A person who does
so owns it. A workload User gets `editor` instead, and the namespace records it as its
**creating workload**: the people who manage that Job, release or Agent in the platform
manage the namespace's access. They can see the namespace and its bindings and grant
or revoke any role on it, `owner` included, but get no access to its tables until they
grant themselves a role.

Workload Users never create tables outside a namespace, never grant roles and are never
granted `owner`. An existing namespace needs `editor` from its owners, its creating
workload's managers or a Team. See [Namespaces and applications](#namespaces-and-applications).

## Roles and bindings

A **role** is a named set of actions on a namespace or table
([permission matrices](permissions.md)): `metadata_viewer`, `data_viewer`,
`data_writer`, `editor` and `owner`, each including the one before it. Every role
carries three texts, shown before it is granted: what it allows, what it can cause,
and what it does not include. `GET /access/roles/` returns them.

A **binding** grants one role to one principal on one object:

| Field | Meaning |
| --- | --- |
| `uid` | Binding identity |
| object | The namespace or table |
| `principal_kind` | `user` (a person or a workload User) or `team` |
| `principal_uid` | Platform User or Team UID |
| `role` | One of the five roles |
| `granted_by_user_uid` | Who granted it or last changed it |
| `created_at`, `updated_at` | When it was created or changed |

A principal holds at most one binding per object; granting another role replaces it.
There is no explicit deny. Bindings and their history live in the selected runtime
database. History records the actor, the principal, the previous and new role and the
time of every change, and survives the object's deletion. The API checks authority
when it commits a change, rather than trusting a previously enabled button.

## Effective access

MetaTables combines a caller's direct bindings, the bindings of the caller's current
platform Teams, and the bindings on every namespace the table is in. The strongest
applicable role wins. Without a matching binding there is no access.

| Bindings that apply to Bob on `prices` | Bob's role |
| --- | --- |
| None | No access |
| Direct `data_viewer` | `data_viewer` |
| Team Research `editor`, and Bob is a current member | `editor` |
| Direct `data_viewer` plus Team Research `data_writer` | `data_writer` |
| Namespace `metadata_viewer` plus direct `owner` | `owner` |

The platform supplies current Team membership through the SDK. MetaTables controls
the roles granted to a Team, not who belongs to it. Removing Bob from Research removes
the access that membership supplied. A direct binding to Bob can still provide access.

Organization admins hold every action, reading and writing data included. A call an
application makes for a person, such as the Analyst, carries only that person's
access, never admin status, and stays read-only.

## Granting

To grant a role on a namespace or table, the caller must:

1. hold `set_access` on it (`owner`, or an admin) and every action of the role; or
2. manage the target workload User and hold every action of the role on the object.

A non-admin grants roles only to Teams they belong to, checked with the platform when
they grant, and to people and workload Users they can find in their own platform
directory. Workloads never grant or revoke roles, whatever they hold; a Team holding
`owner` gives its workload members no access management.

Anyone can revoke their own binding, and a workload's manager can lower or revoke that
workload's binding. Revoking the last owner leaves the admins.

## Workload Users

A deployed Job, FastAPI release or Agent calls MetaTables as its own workload User,
not as the person who deployed it. Grant it a role like a person, directly or through
a Team:

- Search for it by its Job, release or Agent name, or pass its `workload_user_uid`.
  MetaTables labels a workload by its name when you can view that workload,
  otherwise by its kind and UID.
- **The person who manages a workload can grant it** any role whose actions they hold
  on the object, and lower or revoke that binding, without being an owner.
- A workload User whose workload was deleted is inactive and cannot be granted.

Workload Users change with each Environment and each recreated Job. A direct binding
to one needs granting again for its replacement; through a Team, the replacement
needs only membership.

The MetaTables Analyst ([ADR 0019](../adr/agent/0019-metatables-analyst-agent.md)) is
a workload that holds no roles: it reads as the person it is answering
([ADR 0020](../adr/agent/0020-analyst-reads-as-its-requester.md)) and never writes.
Do not grant its workload User a role: everyone who can use the Analyst could then
read those tables through it.

## Who you can find

Grant candidates, search and principal checks show what you can see in the platform
directory, not what the API's own identity can see:

- people and Teams under the platform's directory rules, and only the Teams you
  belong to when you are not an admin;
- the workloads you can view.

`explain` for another User counts the Teams bound on the object, or on its namespaces,
whose members you can see. Any bound Team you cannot see is listed in
`unreadable_team_uids`.

## Live namespace inheritance

A namespace groups tables for access. It is not a SQL schema, a migration namespace
or an updater hash namespace. A role on a namespace gives the table role of the same
name on every table currently in it, including tables added later: Team Research with
`data_viewer` on `research` can read every table in `research`.

Revoking that binding removes its contribution from every table at once. Removing
`prices` from `research` stops inheritance from `research`; adding it to another
namespace applies that namespace's roles as well. Direct table bindings stay in place.
Labels never confer access.

For example, Bob has `data_viewer` through `research` and a direct `owner` binding on
`prices`. Revoking the namespace binding does not remove Bob's ownership of `prices`.
To remove all access, every contributing binding must be revoked by someone allowed
to manage it.

## Namespaces and applications

MetaTables decides access by identity: the calling User and the Teams the platform
says it belongs to. It never asks which project, repository or migration provider a
request comes from. A namespace is an access group, and its owners decide who works
in it.

![Two applications in one Environment. The prices migration Job and API are members of Team prices-development, which holds editor on namespace prices. The trading migration Job and API are members of trading-development, which holds editor on namespace trading and data_viewer on namespace prices. Creating a table in a namespace and reading or writing a table are enforced; which project uses which namespace is not.](../assets/diagrams/namespace-access.svg)

[Open the full-size diagram](../assets/diagrams/namespace-access.svg).

The Admin draws this live for any namespace you can see, on its **Access map** tab:
users and workloads, their Teams, the roles on the namespace and its tables, and
optionally the foreign keys and updater inputs that link its tables to others. It
reads `GET /namespaces/{uid}/access-map/`, which returns only what you could already
see.

What MetaTables enforces:

- **Creating a table in a namespace** needs `tables.create` on it (`editor` or
  `owner`). A missing namespace is created by the registration. An existing one
  without that action is refused with `namespace_access_required`, naming the caller,
  the action and, when visible, the namespace's owners.
- **Reading or writing a table** needs `tables.get_data` or `tables.update_data`
  through a role on the table or one of its namespaces. The API checks it, and the database
  enforces it through the caller's own role
  ([ADR 0007](../adr/api/0007-database-enforced-table-access.md)).
- **A table created in a namespace gets no binding of its own.**

What it does not enforce: which project's tables go in which namespace. A project may
use several namespaces, share one with another project, or, for a person, create
tables without a namespace.

### Recommended: one namespace per application

1. Pushing the workflow file creates the workload Users.
2. The first deployment's migration Job registers its tables in `crm`, which creates
   the namespace and gives the Job `editor`.
3. A person who manages the Job grants `data_writer` to the workload Users that only
   read and write rows, and `owner` to themselves or to a Team they belong to. They can
   instead grant these roles to a Team that contains the workloads.

This needs no Organization admin and no namespace created by hand. A Team is optional: it saves granting again when a
workload User changes. Teams are Organization-wide and a workload reaches only its
own Environment's MetaTables, so one Team can hold the application's roles in every
Environment's catalog. Another application gets read access through one `data_viewer`
binding on the namespace; revoking it removes access to every table at once. See
[Migrate in the deployment workflow](../client/deploy-application-migrations.md#give-the-job-access).

## A table in several namespaces

A table can be in any number of namespaces
([ADR 0028](../adr/api/0028-tables-in-several-namespaces.md)). All of them are equal:
a caller's role on the table is the strongest it gets from any of them. Use a second
namespace to share part of an application's tables without naming them one by one.

```text
namespace alpaca-connectors          namespace alpaca-market-data
  bars  quotes  orders  positions      bars  quotes

Team alpaca-development: editor       Team research: data_viewer
```

Team research reads `bars` and `quotes` and nothing else. A market-data table added
later is covered as soon as its migration runs.

**Declare the namespaces in code.** `__metatable_namespace__` is the application's
namespace: one name, which a subclass replaces. `__metatable_namespaces__` lists
further ones and only adds: a table is in every name that it or any of its base classes
lists there, so a table joins a subset by having the base that declares it.

```python
class AlpacaBase(PlatformManagedMetaTable):
    __abstract__ = True
    __metatable_namespace__ = "alpaca-connectors"

class MarketData:
    __metatable_namespaces__ = ("alpaca-market-data",)

class Bars(MarketData, AlpacaBase, Base): ...      # in both
class Orders(AlpacaBase, Base): ...                # only alpaca-connectors
```

The application's migration applies the declaration: `metatables migrations upgrade
--provider <provider> head` adds the namespaces the code declares, creating a missing
one, and removes the ones it no longer declares. No revision and no new migration
folder are needed. The Job needs `tables.create` on each namespace; one it creates
gives it `editor`.

**Add a table by hand.** A person with `tables.update` on the table and `tables.create`
on the namespace adds it from the Admin or the client; removing needs `tables.create`
on the namespace. No migration removes a membership added this way.

What to know:

- **A second namespace only adds access.** There is no deny. Someone with a role on
  `alpaca-connectors` reaches every table whatever `alpaca-market-data` says. A subset
  works for principals that hold no role on the larger namespace.
- **Its owners are owners of the table.** Adding a table to a namespace gives that
  namespace's roles on the table, `owner` included.
- **Removing a name from the code removes access** at the next migration, with no
  binding revoked.
- **The last namespace** can be removed only when the table has a direct `owner`.
- **A table with no migration**, such as an imported external table, gets its
  namespaces when it is created. Registering or importing it again changes none; the
  answer lists them in `namespaces_not_applied`. Add or remove them by hand.

## The Access panels

Every namespace and table has an **Access** panel. It lists each binding with its
role, its texts, its source (direct, Team, namespace, admin), who granted it and when.
A namespace's panel also names its creating workload; if you manage it, your access
shows the source `manager`.
Owners grant, change and revoke roles there; granting shows the role's texts before it
is confirmed. **Explain** shows why a chosen User can or cannot do an action, and
**access history** shows past changes. Buttons follow the caller's allowed actions
from `access/me/`.

## Python client

```python
from metatables import MetaTable, Namespace

crm = Namespace.create("crm")                       # you become its owner
crm.grant_role(migration_job_user_uid, "editor")
crm.grant_role(team_uid, "data_viewer", principal_kind="team")

prices = MetaTable.get(identifier="prices")
prices.namespace_names                              # every namespace it is in
prices.add_to_namespace("research")                 # it stays in the others
prices.remove_from_namespace("research")
prices.get_access()                                 # bindings, inherited ones, revision
prices.allowed_actions()                            # e.g. ["tables.get", "tables.get_data"]
prices.explain("tables.update_data", user_uid=bob_uid)
prices.revoke_role(bob_uid)
```

Supply platform UUIDs for Users and Teams. These methods also work on
`TimeIndexMetaTable`. A failed revision check is not retried silently: reload access
and review intervening changes.

## HTTP interface

| Endpoint | Authority |
| --- | --- |
| `GET /access/roles/` | Any caller |
| `POST /namespaces/` | Any person (`namespaces.create`); never a workload |
| `GET /meta-tables/{uid}/access/`, `GET /namespaces/{uid}/access/` | `get_access` on the object, or a manager of the namespace's creating workload |
| `POST /meta-tables/{uid}/access/changes/`, `POST /namespaces/{uid}/access/changes/` | `set_access`, a manager of the namespace's creating workload, or a workload's manager for that workload; never a workload |
| `GET .../access/me/` | Any caller who can see the object |
| `GET .../access/explain/?action=...&user_uid=...` | Yourself: anyone who can see the object; another User: `get_access` |
| `POST /meta-tables/{uid}/namespaces/changes/` | Add: `tables.update` on the table and `tables.create` on the namespace. Remove: `tables.create` on the namespace |
| `GET /meta-tables/{uid}/access-history/` | `tables.get_access` |
| `GET /security/principals/?search=` | Any caller; searches the caller's own platform directory |
| `GET /security/resources/`, `GET /security/access-history/?kind=...&uid=...` | Organization admin |

`namespaces/changes/` takes `add` and `remove`, two lists of namespace names applied
together, and returns the table's `namespaces`. The names must exist. The access history
records each change with the namespace as the principal (`principal_kind` `ns`).

`access/changes/` takes the `revision` from `access/` plus lists of `grant`
(`principal_kind`, `principal_uid`, `role`) and `revoke` (`principal_kind`,
`principal_uid`), applied together. It returns the new access document.
