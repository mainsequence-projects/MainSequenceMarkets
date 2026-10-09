# Ownership, sharing, and inheritance

## Ownership is Writer access

The creator receives Writer access when a new table is registered, unless the
table's namespace already makes the creator a Writer, directly or through a Team.
Then the namespace's Writers control the table and no creator grant is added. A
Writer can grant Reader or Writer access to other platform Users and Teams, change
a direct grant, or revoke it. Readers cannot change grants.

Several principals can be Writers. The original creator has no permanent
permission separate from grants: `created_by_user_uid` records who created the
table, while effective access determines who controls it now. Organization admins
can restore access when no Writer remains.

Deployed Jobs, releases and Agents run as their own workload Users, which change
with each Environment and each recreated Job. Give an application's tables to a
Team instead: grant the Team Writer on the namespaces those tables are registered
in, and make the workload Users members. See
[Namespaces and applications](#namespaces-and-applications) and
[Migrate in the deployment workflow](../client/deploy-application-migrations.md#give-the-job-access-through-a-team).

## One central table-access model

`MetaTableGrant` is the foundation of the central access model. Each direct grant
connects one MetaTable to one User or Team; the collection describes direct access
across the catalog. This is the authoritative direct-grant model.

| Field | Meaning |
| --- | --- |
| `uid` | Grant identity |
| `meta_table_uid` | The controlled table |
| `principal_kind` | `user` or `team` |
| `principal_uid` | Platform User or Team UID |
| `access_level` | `reader` or `writer` |
| `granted_by_user_uid` | Who established or last changed the grant |
| `created_at`, `updated_at` | When the record was created or changed |

There is one direct grant per table/principal combination. Removing access deletes
that grant; there is no third access level or explicit deny rule. These fields are stored in the runtime database.

Grants and their audit history live in the selected runtime database. Audit records
retain the actor, target, previous/new access, and time of each grant change or
revocation. Removing a grant does not remove its history. The API checks authority
when it commits the change, rather than trusting a previously enabled UI button.

## Effective access

MetaTables combines direct User grants, grants to the caller's current platform
Teams, and grants inherited from the table's current namespace. The strongest
applicable level wins: Writer includes Reader. Without a matching grant, access
is denied.

| Grants applying to Bob on `prices` | Effective access |
| --- | --- |
| None | No access |
| Direct Reader | Reader |
| Team Research Writer, and Bob is a current member | Writer |
| Direct Reader plus Team Research Writer | Writer |
| Namespace Reader plus direct Writer | Writer |

The platform supplies current Team membership through the SDK. MetaTables controls
the permissions assigned to a Team, not who belongs to that Team. Removing Bob
from Research removes the access that membership supplied on the next request. A direct grant to Bob can still provide access.

## Workload Users

A deployed Job, FastAPI release or Agent calls MetaTables as its own workload User,
not as the person who deployed it. Grant it access like a person, directly or
through a Team an Organization admin adds it to:

- Search for it by its Job, release or Agent name. Alternatively, pass its UID,
  the `workload_user_uid` of the Job, release or Agent, to `set_access`, or add
  it to the users in `assignments`. MetaTables labels a workload by its Job,
  release or Agent name when you can view that workload, otherwise by its kind
  and UID.
- **The person who manages a workload can grant it.** They can give it Reader on
  any table they can read, and lower or remove that grant, without being the
  table's Writer. Everything else needs a Writer or an admin.
- A workload User whose workload was deleted is inactive and cannot be granted.

The MetaTables Analyst ([ADR 0019](../adr/agent/0019-metatables-analyst-agent.md))
is a workload that holds no grants: it reads as the person it is answering
([ADR 0020](../adr/agent/0020-analyst-reads-as-its-requester.md)), with that person's own
and Team grants, and never writes. An Organization admin reads through it only what they
are granted. Do not grant its workload User Reader: everyone who can use the Analyst
could then read those tables through it.

## Who you can find

Sharing candidates, search and principal checks show what you can see in the
platform directory. They don't show what the API's own identity can see:

- people and Teams under the platform's directory rules;
- the workloads you can view.

Previewing another User's access counts the Teams granted on the table, or on its
namespace, whose members you can see. Any granted Team you cannot see is listed in
`unreadable_team_uids`.

## Live namespace inheritance

A catalog namespace groups table access. It is not a SQL schema, a migration
namespace, or an updater hash namespace. Granting a Team Reader access to namespace
`research` supplies Reader access to its current tables, including later additions.

Removing that namespace grant removes its contribution from all current member
tables. Moving `prices` out of `research` stops inheritance from `research`; moving
it into another namespace applies that namespace's grants. Direct table grants
remain in place. Labels never confer access.

For example, Bob has Reader access through `research` and a direct Writer grant
on `prices`. Removing the namespace grant does not remove Bob's Writer access to
`prices`. To remove all access, every remaining contributing grant must be
addressed by someone authorized to manage that grant.

A table Writer
can manage direct grants on their table, but cannot revoke a global namespace
grant for all its tables through the table's Access panel.

## Namespaces and applications

MetaTables decides access by identity: the calling User and the Teams the
platform says it belongs to. It never asks which project, repository or
migration provider a request comes from. A namespace is an access group, and its
Writers decide what goes in it.

![Two applications in one Environment. The prices migration Job and API are members of Team prices-development, which is Writer on namespace prices. The trading migration Job and API are members of trading-development, which is Writer on namespace trading and Reader on namespace prices. Registering a table in a namespace and reading or writing a table are enforced; which project uses which namespace is not.](../assets/diagrams/namespace-access.svg)

[Open the full-size diagram](../assets/diagrams/namespace-access.svg).

The Admin draws this live for any namespace you can see, on its **Access map**
tab: users and workloads, their Teams, the Reader and Writer grants on the
namespace and its tables, and optionally the foreign keys and updater inputs that
link its tables to others. It reads `GET /namespaces/{uid}/access-map/`, which
returns only what you could already read through the namespace's and tables'
Access tabs.

What MetaTables enforces:

- **Registering a new table in a namespace** needs Writer on that namespace,
  directly or through a Team. An Organization admin may register in any
  namespace. Anyone else gets `403 namespace_not_writable`.
- **Reading or writing a table** needs a grant on the table or on its namespace.
  The API checks it, and the database enforces it through the caller's own role
  ([ADR 0007](../adr/api/0007-database-enforced-table-access.md)).
- **A Writer's new table gets no grant of its own.** The namespace's Writers own
  it, so it does not depend on the identity that registered it.

What it does not enforce: which project's tables go in which namespace. Any
Writer of a namespace may register tables in it from any project, and a person or
workload in two Teams can register in both Teams' namespaces. A project may use
several namespaces, share one with another project, or register tables without a
namespace.

### Recommended: one namespace per application

Give each application its own namespace in each Environment, and make a Team for
that Environment its Writer, as in the diagram:

- One grant covers all of the application's tables, including the ones its later
  migrations add.
- Workload Users change with each Environment and each recreated Job. A new one
  needs only Team membership; the tables keep their owner.
- Another application gets read access through a single Reader grant on the
  namespace, like `trading-development` on `prices`. Removing that grant removes
  the access from every table at once.
- A Team per Environment keeps one Environment's workloads from being Writers in
  another.

It is a recommendation, not a rule. The platform signs who the caller is and its
Teams, not which project it runs. A project or provider name sent by the client
is only a claim that any Writer could change, so a project-to-namespace check
would block legitimate layouts without stopping anyone. The boundary is the
grant: give Writer on a namespace only to principals that should own everything
in it, and keep each application's workload Users in its own Team.

## The table Access panel

The Access panel has two responsibilities:

1. Let Writers add, change, or revoke direct User/Team Reader and Writer grants.
2. Explain effective access and its sources, including inherited grants that
   require global Security administration to change.

Use the effective-access API to preview whether another grant retains access,
including grants through Teams and the current namespace. The Access panel lists
these inherited sources and offers **Preview access** with an optional excluded
grant. **Load access history** shows the actor, old/new level, time, and reason. A namespace move changes those contributions.

Grant changes are available to table Writers without opening global Security.
Organization admins use global Security for catalog-wide administration, namespace
grants, audit inspection, and recovery. Both surfaces use the same API evaluator
and audit history.

## Initial scope

This version has table-level Reader and Writer access only. It does not introduce
custom roles, explicit denies, or row-, column-, or time-coordinate permissions.
The [permission matrices](permissions.md) show which operations each level covers.

## Python client

```python
from metatables import MetaTable

prices = MetaTable.get(identifier="prices")
access = prices.get_access()
prices.set_access(user_uid, access_level="reader")
prices.set_access(team_uid, principal_kind="team", access_level="writer")
preview = prices.get_effective_access(user_uid=user_uid, without_grant_uid=grant_uid)
print(preview["remaining_access"], preview["remaining_contributions"])
prices.revoke_access(user_uid)
```

Supply platform UUIDs for `user_uid` and `team_uid`; `grant_uid` comes from
`get_access()["grants"]`. These methods also work on `TimeIndexMetaTable`.
An admin can recover a known table UID without first obtaining ordinary data
access by constructing `MetaTable(uid=table_uid)` and calling `set_access`.

The supported methods above replace unsupported inherited SDK sharing helpers.
A failed revision check is not retried silently: reload the access document and
review intervening changes.

## HTTP interface

| Endpoint | Authority |
| --- | --- |
| `GET /meta-tables/{uid}/permissions` | Table Reader or application admin |
| `PUT /meta-tables/{uid}/permissions` | Table Writer or application admin; a workload's manager for that workload's Reader grant |
| `GET /meta-tables/{uid}/effective-access/` | Reader for self; Writer/admin for another User |
| `GET /security/principals/?search=` | Any caller; searches the caller's own platform directory |
| `GET /meta-tables/{uid}/access-history/` | Table Writer or application admin |
| `GET /namespaces/{uid}/permissions` | Visible namespace or application admin |
| `PUT /namespaces/{uid}/permissions` | Application admin |
| `GET /security/resources/` | Application admin; includes orphaned resources |
| `POST /security/namespaces/` | Application admin |
| `GET /security/access-history/?kind=table&uid=...` | Application admin; works after deletion |

Sharing PUT uses the returned `revision` and complete `assignments`:
`{"view": {"users": [], "teams": []}, "edit": {"users": [], "teams": []}}`.
These wire names mean Reader and Writer; every Writer must also appear in `view`.
The response contains current grants, effective access, and contributing sources.
`without_grant_uid` previews removing one contribution; it does not modify access.
Namespace-wide grants are changed through global Security. Directory choices and
new grant recipients, workload Users included, are obtained or validated through
existing SDK User/Team operations. An unavailable directory cannot create an
unverified grant.
