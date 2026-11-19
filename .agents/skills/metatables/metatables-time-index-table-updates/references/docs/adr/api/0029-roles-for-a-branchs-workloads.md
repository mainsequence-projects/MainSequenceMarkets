# ADR 0029: Roles for a branch's workloads

Status: Accepted.

Implementation status: implemented in the API, the Python client and the client skills. The
platform change it depends on (section 2) has shipped. The Admin does not yet show a binding's
source or name a branch (Open questions). Non-container tests pass; the container matrix has
not been run for this change.

Owner: MetaTables API, with client and Admin consumers.

Related decisions: [ADR 0024](0024-namespace-and-table-access-roles.md) (roles on
namespaces and tables, amended here), [ADR 0028](0028-tables-in-several-namespaces.md)
(declared namespace memberships), [ADR 0007](0007-database-enforced-table-access.md)
(database roles enforce table access) and [ADR 0002](0002-application-administration-and-table-ownership.md)
(workload Users as principals). Platform: ADR-0048 (workload principals) and ADR-0053
(declared workflow access).

## Context

Every Job, FastAPI release and Agent calls MetaTables as its own workload User. A role
binding names one principal UID. A recreated workload gets a new User, and nothing
carries its roles over. A workload never grants or revokes a role (ADR 0024), so after
each first deployment in an Environment, and after each recreation, a person must grant
the new workload Users their roles again. A Team helps only partly. A person still grants
the Team once per Environment, and a workload cannot add itself or another workload to a
Team.

This has already broken a Production application. A commit renamed two Job keys in the
workflow file. The platform deleted both Jobs and created new ones with new workload
Users. Those Users held no role on the application's namespace, so the Jobs could not see
its version table. They read the applied revision as "none" and skipped every run while
reporting success. A namespace owner restored the roles by hand.

Applications want a push to set up its own workloads' access, in every Environment and
after any rename, with no person involved.

## Decision

### 1. The model

A **branch** becomes a principal, next to a user and a Team. A binding to a branch
gives its role to every active workload User declared on that code repository branch.
It never matches a person.

```text
namespace orders
  user   Ana               owner        explicit
  team   finance           data_viewer  explicit
  branch orders-service    editor       declared   <- every workload of that branch
```

Branch membership is computed on each request, as Team membership is. Nothing is stored
per workload:

- A renamed or recreated Job is on the same branch, so its first request has the role.
- A deactivated workload is not admitted, so it has nothing.
- Nothing has to be revoked when a workload goes away.

The branch is only a principal. Namespaces stay access groups owned by people and Teams,
and they are not tied to repositories. Any branch can hold roles on any namespace, and
code still places tables in any namespace it has `tables.create` on.

An Environment is bound to one git branch, so a branch UID names one repository in one
Environment. A binding in one Environment's MetaTables never matches a workload of
another Environment.

### 2. The caller's branch

MetaTables reads the caller's branch from its platform User row, the same row it already
reads to tell a workload from a person, and keeps the answer for a day: a User's identity
type and branch never change. A person has no branch. A row without the field gives no
branch, so the caller matches no branch binding. A failed read fails the request; it is
never read as "no branch".

The row is read only when it can matter. Access checks ask for the branch only while some
binding in the catalog names a branch; the set of branches named is cached like the Teams
named, so another pod sees a new branch binding within a minute and the pod that wrote it
at once. A declaration (section 3) always reads the branch.

This needed one platform change, which names nothing about MetaTables. The platform added
`code_repository_branch_uid` and `code_repository_uid` to the workload fields of a User's
representation, next to `job_uid`, shown to every member of the Organization. The SDK's
`User` model does not declare them yet, so MetaTables reads User rows through a subclass
that does.

### 3. Declaring access in the application

The migration provider declares a role per namespace for its own branch:

```python
build_metatable_migration_provider(
    ...,
    branch_access={
        "orders": "editor",
        "orders-reporting": "editor",
    },
)
```

Every way of making a provider takes the same mapping and checks it the same way, before
anything is sent: `AlembicMetaTableMigration`, `build_metatable_migration_provider`, which
the scaffold writes, and `metatables migrations scaffold --branch-access NAMESPACE=ROLE`.
Names are read as the API reads them, trimmed and case-folded. A test fails when a
provider option is missing from the builder, and another when the client's declarable
roles differ from the API's (issue #119: 0.1.69 shipped a builder without the option).

Each `upgrade` and `downgrade` already finalizes the catalog (ADR 0028). After a successful
finalization the provider sends this declaration to `POST /namespaces/branch-access/`
(`Namespace.declare_branch_access`). For each named namespace, the API writes a `declared`
binding for the **caller's own branch**:

- The request never names a branch. The API uses the branch from the caller's admission.
- The declaring caller must be a workload with a branch, and must hold `tables.create`
  on the namespace.
- Each role is at most the caller's own role on the namespace, and never `owner`. So
  every role is `editor` or below.
- A namespace that the next finalization no longer declares loses its `declared` branch
  binding. A changed role replaces the binding.
- If the branch already holds an `explicit` binding on that namespace, finalization
  leaves it unchanged and its answer says so. One principal holds one binding per object.
- A caller that is not a workload with a branch, such as a developer migrating locally,
  changes nothing and gets `applied: false`. The migration continues.
- Each namespace answers on its own. If any is refused, the provider raises
  `BranchAccessRefused` after finalization, so the migration Job fails visibly instead of
  leaving the branch's other workloads refused.

The declaration is the branch's whole set. A repository with several migration providers
gives each the same `branch_access`, for example from one shared constant. The migration
Job runs every provider in one process, so the client enforces this: a provider whose
mapping differs from one another provider already sent from the process raises
`BranchAccessConflict` before sending, instead of removing that provider's namespaces.
Two Jobs of one branch that each run different providers are not checked; one migration
Job per repository is the documented layout.

Declarations are per namespace only. A narrower set of tables is a namespace of its own,
as ADR 0028 describes.

The migration Job gets `tables.create` in one of two ways:

- It creates the namespace by registering into a free name and is granted `editor`
  (ADR 0024).
- A person grants it `editor` on an existing namespace once. After that, the branch
  binding it declares covers its own replacements.

### 4. Why a workload may do this

Anyone who can push to a branch already runs any code they like as that branch's
migration Job, and the Job holds the role it declares from. Giving the same branch's
other workloads that role, or less, gives nobody access they lack today. This is the
platform's own rule for pushes with no resolved person: they grant only inside the
branch's own reach.

Giving access to anyone outside the branch is sharing, and sharing stays with people.

### 5. Granting a branch by hand

Owners and admins may grant a branch any role except `owner` through the ordinary access
routes, by its UID. The managers of a namespace's creating workload may as well (ADR 0024
rule 3). Such a binding is `explicit`, and no finalization changes it.

This covers a workload in another repository. For example, the owner of
`orders-reporting` grants the `billing-service` repository's branch `data_viewer` once in
each Environment. The billing workloads then keep that role through every rename and
redeploy, and the billing code declares nothing about orders.

### 6. Catalog and database

- `namespace_grant` and `meta_table_grant` accept `principal_kind = 'branch'`, and
  `principal_uid` holds the branch UID.
- Both tables gain the `source` column that ADR 0024 already describes: `explicit`,
  `creator`, `converted` or `declared`. Existing rows become `explicit`.
- The evaluator's principal match gains one case: a branch binding matches when its UID
  is the caller's branch. Checks, list filters, `access/me` and `explain` all use that
  one evaluator.
- In the database, a branch has a group role like a Team's. The caller's login role is a
  member of its branch's role. SQL admission stores the branch on the caller's
  `sql_principal` row once it is known and never clears it, since a workload's branch
  never changes; a pod that has not yet seen a branch binding therefore cannot take the
  membership away. The daily security check (ADR 0023) rebuilds memberships from those rows.
- Bindings created by registration (a namespace's or table's creator) are `creator`. A
  person's change through the access routes makes a binding `explicit`, including a
  `declared` one.

### 7. Skills and documentation

This decision is not done until the guides and skills that tell applications how to deploy
teach `branch_access` as the default. They also have to explain the failure it prevents,
with the example below.

**The example.** An `orders` repository deploys three workloads from one workflow file:
the migration Job `migrate-orders`, the FastAPI `orders-api` and the Job `nightly-settlement`.
The API and the settlement Job read and write the tables of namespace `orders`.

*Without branch access (ADR 0024 today):*

```text
first deploy in an Environment
  migrate-orders registers its tables -> creates namespace orders, gets editor
  orders-api, nightly-settlement      -> refused until a person grants them roles
  a person who manages migrate-orders -> grants both, in this Environment

later: nightly-settlement is renamed settlement in the workflow file
  the platform creates a new Job with a new workload User -> no role
  settlement cannot see its tables. A Job that reads "no table" as "nothing to do"
  reports success and does nothing, until someone notices and grants again
```

Every new Environment and every rename needs a person. The broken state looks like success.

*With branch access:*

```python
# orders/migrations/__init__.py, the provider the scaffold wrote
migration = build_metatable_migration_provider(..., branch_access={"orders": "editor"})
```

```text
first deploy in an Environment
  migrate-orders registers its tables -> creates namespace orders, gets editor
  finalization declares                -> branch orders-service: editor on orders
  orders-api, nightly-settlement       -> have editor on their first request

later: nightly-settlement is renamed settlement
  same branch -> settlement has editor on its first request, nobody acts
```

A billing repository that reads `orders-reporting` gets one hand grant from that
namespace's owner, to its branch, in each Environment (section 5). After that, its renames
and redeployments need nothing.

**What changes.** These sources are edited in this repository. The bundle that
`metatables copy-metatables-skills` ships to applications is built from them.

| Source | Change |
| --- | --- |
| `.agents/skills/client/metatables-migrations/SKILL.md` | Step 4 ("Grant the other workloads") declares `branch_access` in the provider. Keep hand grants for people, for other repositories and for an application that wants different roles per workload. Add the rename failure: the symptom, how to check it with `explain`, and the fix. |
| `.agents/skills/client/metatables-time-index-table-updates/SKILL.md` | A producer Job gets `editor` on its output namespace through its branch. It no longer waits for a grant. |
| `.agents/skills/client/metatables-meta-tables/SKILL.md` | The access section lists `branch` as a principal kind, and `grant_role` to another repository's branch by UID. |
| `docs/client/deploy-application-migrations.md` | The deployment steps use `branch_access`. Add the example above with both versions. |
| `docs/security/ownership-and-sharing.md` | Principals include branches. "Workload Users" explains branch bindings, `declared` against `explicit`, and why a rename keeps access. |
| `docs/security/permissions.md` | Principals: every role except `owner` can be granted to a branch. Workloads change only their own branch's `declared` bindings. |
| `docs/concepts/permissions-namespaces-labels.md` | A namespace's bindings can name a branch. This does not tie the namespace to that repository. |
| Generated role catalog (`GET /access/roles/`) and its documentation | `branch` appears in each role's principals, except `owner`. |

The guides say plainly when not to rely on branch access: when one workload of a branch
must not get another's role. Branch access gives every workload of the branch the same
role (see Consequences).

## Consequences

- A push gives its own workloads their roles in every Environment, with no person
  involved, once its migration Job holds `editor`. A rename or recreation needs nothing.
- Every workload of a branch gets the same role on a namespace. Least privilege inside
  one branch is gone: a FastAPI on the migration Job's branch can migrate the tables it
  writes. This is not a security boundary, because the branch's pushers control every one
  of those workloads. Applications that want it keep their workloads on separate
  branches, or use explicit grants and declare nothing.
- ADR 0024's constraint becomes: a workload never grants or revokes a role through the
  access routes. Its only binding change is its own branch's `declared` bindings, made
  through finalization.
- Teams, direct workload bindings and the creating-workload managers keep working
  unchanged.
- A cross-repository role still needs a person once per Environment.
- The Admin shows branch bindings with their source and lets an owner remove them. A
  removed `declared` binding comes back at the next finalization while the code still
  declares it.

## Rejected alternatives

- **A workload grants other workload Users directly.** The binding would name a UID, and
  a rename would break it again.
- **A branch plus a workload key as the principal.** This restores least privilege
  inside a branch. It needs a further platform fact, and renaming a key would break
  access again, which is the failure described in Context.
- **A `metatables:` key in the platform workflow file.** The platform stays
  project-agnostic.
- **A repository as the principal.** Inside one Environment it means the same as a
  branch, and a branch UID already keeps Environments apart.
- **Declared roles for other repositories' branches.** This would move a sharing
  decision from owners into code.
- **Letting a workload view its own Job to learn its branch.** This contradicts platform
  ADR-0048 [48.14], and it would also expose runs, logs and invocation.

## Open questions

- **Naming a branch in the Admin.** MetaTables reads the platform as the caller only for
  users and Teams. A hand grant therefore takes a branch UID, and the API cannot confirm
  that the branch exists or show its repository name. A platform read of branches as the
  caller would fix this.
- **Field visibility.** Whether the platform shows the two new fields to every member, as
  it shows `job_uid`, or only to callers who can view the workload.

## Verification

- A renamed workload of a branch with a `declared` binding has the role on its first
  request. A person, a workload of another branch and an inactive workload do not.
- Finalization writes, changes and removes only its own branch's `declared` bindings. It
  refuses `owner`, a role above the caller's own, and a namespace where the caller lacks
  `tables.create`. It leaves an `explicit` binding unchanged.
- A person's call never declares, and the access routes still refuse every workload.
- In the database, a branch binding gives `SELECT` or write privileges to the workload's
  login role and none to a login role of another branch.
- The example application in section 7 deploys to a new Environment and survives a Job
  rename with no person granting anything. Its cross-repository reader needs one hand
  grant per Environment.
- A provider made directly, by the builder or by the scaffold carries `branch_access`, and
  each refuses `owner` before anything is sent or written. The builder takes every
  provider option, and the client's declarable roles equal the API's.
- A second provider of one run with a different mapping raises `BranchAccessConflict`
  and sends nothing.
- The skills and guides listed in section 7 describe `branch_access` and the branch
  principal, and the docs check passes.
