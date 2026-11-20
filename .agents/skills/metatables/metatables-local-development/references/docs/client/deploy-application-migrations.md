# Migrate in the deployment workflow

An application's tables must match the code that serves them. Apply application
migrations to a hosted runtime the same way MetaTables applies its own system
migrations: a Job in the deployment workflow runs them from the candidate image
before anything that uses the tables rolls out. See
[catalog migrations](../operations/catalog-migrations.md) for the API's own
`migrate-system` Job.

## Recommended workflow

1. **Develop locally.** Author the revision and apply it to verified local SQLite
   with `metatables --local migrations upgrade`. See
   [Managed tables and migrations](define-and-migrate-tables.md) and
   [Local storage](local-storage.md).
2. **Commit the revision with the code that needs it.** Applied revisions are
   immutable; every later schema change is a new revision.
3. **Deploy.** The application's workflow runs its migration Job from the
   candidate image, then deploys the resources that read or write the tables. The
   first deployment to an Environment creates the application's namespace there and
   gives the Job `editor` on it.
4. **Grant the other workloads.** Someone who manages the migration Job grants the
   resources that read and write rows their roles on the namespace
   ([below](#give-the-job-access)). Nobody creates the namespace by hand, and no
   Organization admin is needed.

Hosted runtimes are migrated only by step 3. Do not run `metatables migrations
upgrade` or `downgrade` against a hosted API from a developer machine or agent
session. Do not migrate at application startup either: several pods would race,
and a failure would not stop the rollout.

## Migration timings

At INFO level, `metatables.migrations.runner` logs preparation, database setup,
table-presence checks before and after Alembic, Alembic execution, catalog
finalization and total duration. The API logs physical inspection and total time
for each finalization batch. Use these to distinguish database work from platform
scheduling and workflow coordination.

An already-current database still reconciles the provider's catalog contracts.
Checks use fresh table inventories and batched physical reflection; an unchanged
revision does not skip missing-table checks, permissions or metadata refresh.
Each finalization batch carries current authored descriptions, labels and column
descriptions/labels/logical names. Non-empty values refresh existing bindings
without a new revision; empty or absent values preserve catalog metadata, as in
registration. Physical shape always comes from fresh database inspection. The
next equal-valued upgrade skips catalog writes. This metadata payload requires
the corresponding API update as well as the updated client.
PostgreSQL batches metadata queries by schema; other dialects use SQLAlchemy's
bulk reflection and its supported fallbacks. Caches do not survive the request.
Client improvements require updating the application's installed MetaTables package
and rebuilding its image; API improvements require deploying the shared API.
Applications and libraries continue to use `from metatables import upgrade_application`;
batching is automatic in this shared path, with no new import or opt-in flag.
After updating the installed package, refresh its agent guidance with
`metatables copy-metatables-skills --path /path/to/application`. This copies the
matching migration skill and its guide snapshots; importing Python code does not
update a project's copied skills.

## Declare the migration Job

Add one Job script that applies every provider the application owns, in
dependency order:

```python
"""Main Sequence Job: apply the ledger migrations before the application rolls out."""

from metatables import upgrade_application

for provider in ("ledger.migrations:migration",):
    result = upgrade_application(provider)
    state = "migrated" if result["migrated"] else "already current"
    print(f"{provider}: {result['revision']} ({state}) on {result['data_source_uid']}", flush=True)
```

Gate the deployments on it in `.mainsequence/workflows/<application>.yaml`:

```yaml
api_version: "3.0.0"
name: ledger
resources:
  - key: ledger-api
    kind: fastapi
    spec:
      source_path: api/main.py
      automatic_deployment: true
      automatic_redeployment:
        enabled: true
  - key: migrate-ledger
    kind: job
    spec:
      name: Ledger migrations
      execution_path: jobs/migrate_ledger.py
      automatic_redeployment:
        enabled: true

execution:
  steps:
    image:
      prepare_image: ledger-api
    migrate:
      run_job: migrate-ledger
      image_from: image
      needs: [image]
    deploy_api:
      deploy: ledger-api
      image_from: image
      needs: [migrate]
```

Give every other deployed resource that reads or writes the tables, such as a
`harness_agent`, its own deploy step with `needs: [migrate]`. Validate the file
against the branch's workflow template before committing it.

## Give the Job access

The Job runs as its own workload User. A workload never grants roles through the access
routes and never creates a table outside a namespace
([ADR 0024](../adr/api/0024-namespace-and-table-access-roles.md)). It creates its namespace
by registering its first table there, and declares its branch's roles
([ADR 0029](../adr/api/0029-roles-for-a-branchs-workloads.md)):

1. **Push the workflow file.** Applying it creates the Job, the FastAPI release and
   their workload Users before any step runs.
2. **The first migration creates the namespace.** When a provider's tables name a
   namespace that does not exist in this Environment, the Job's registration creates
   it and grants the Job `editor`. The namespace records the Job as its creating
   workload. Later runs and new tables need nothing more. A provider whose tables
   declare several namespaces creates each missing one the same way.
3. **The migration gives the branch's workloads their roles.** The provider declares
   `branch_access`, and after each finalization the Job gives those roles to every
   workload of its own code repository branch. In the provider the scaffold wrote:

   ```python
   migration = build_metatable_migration_provider(
       ...,
       branch_access={"ledger": "editor"},
   )
   ```

   `metatables migrations scaffold --branch-access ledger=editor` writes it for a new
   provider, and `AlembicMetaTableMigration(..., branch_access=...)` takes the same
   mapping. The FastAPI release and the other Jobs of the workflow file have the role on
   their first request. Each role is at most the Job's own and never `owner`. The next
   migration's declaration replaces this one. A refused namespace fails the Job with
   `BranchAccessRefused` after finalization.

   Each declaration replaces the branch's whole set, so every provider the Job runs
   declares the same mapping. Keep it in one constant that each provider imports. A
   provider whose mapping differs from one an earlier provider sent in the same run
   fails with `BranchAccessConflict` before it sends anything.
4. **Grant an owner.** The people who manage the Job in the platform manage the
   namespace's access. In that Environment's Admin, open the namespace's **Access**
   panel and grant `owner` to yourself or to a Team you belong to, so the namespace
   keeps an owner if the Job is recreated.

Repeat step 4 in every Environment, done by someone who manages the Job there: each
Environment has its own MetaTables and its own workload Users. Steps 1 to 3 need nobody.

```python
from metatables import Namespace

ledger = next(n for n in Namespace.filter(search="ledger") if n.name == "ledger")
ledger.grant_role(your_user_uid, "owner")                       # step 4
ledger.grant_role(billing_branch_uid, "data_viewer", principal_kind="branch")  # another repository
```

Managing the Job lets you manage the namespace's access only: it gives you no access
to its tables until you grant yourself a role.

### Why the branch and not each workload

An `orders` repository deploys three workloads from one workflow file: the migration
Job `migrate-orders`, the FastAPI `orders-api` and the Job `nightly-settlement`. The API
and the settlement Job read and write the tables of namespace `orders`.

Without `branch_access`, each workload User is granted by hand:

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

Every new Environment and every rename needs a person, and the broken state looks like
success. With `branch_access={"orders": "editor"}`:

```text
first deploy in an Environment
  migrate-orders registers its tables -> creates namespace orders, gets editor
  finalization declares                -> branch orders-service: editor on orders
  orders-api, nightly-settlement       -> have editor on their first request

later: nightly-settlement is renamed settlement
  same branch -> settlement has editor on its first request, nobody acts
```

A billing repository that reads `orders` gets one grant from that namespace's owner, to
its branch, in each Environment. After that, its renames and redeployments need nothing.

**When not to rely on the branch.** Every workload of a branch gets the same role on a
namespace. When one resource of the branch must not hold another's role, leave that
namespace out of `branch_access` and grant each workload User by hand, as below.

**Granting workload Users by hand.** In the namespace's **Access** panel, find each
workload by its Job or release name and grant it a role; from Python, pass its
`workload_user_uid`, which the Main Sequence SDK returns on the Job and the
ResourceRelease. Such a grant names one workload User: a recreated Job or release needs
it again. A grant takes effect on the next request, with no redeployment.

**Optionally, a Team.** Grant the roles to a Team you belong to instead of to the
workload Users, and add the workload Users to that Team: any person can create a Team
and, as its owner, add workloads they can view. A recreated Job or release then needs
only Team membership, not a new grant. One Team can hold the roles in every Environment:
Teams are Organization-wide, and a workload reaches only its own Environment's
MetaTables. People in the Team receive the same roles, so leave it once the workloads
are in if you should not hold them yourself.

**A name that is already taken.** If the namespace already exists, created by another
application, by a person or before this change, the first migration stops with
`namespace_access_required`. An owner of that namespace grants the Job `editor`, or the
application uses another namespace. A person may still create a namespace in advance,
with **Create namespace** in the Admin or `Namespace.create("ledger")`, and grant the
Job `editor`; nothing requires it.

**Namespaces created before roles.** A namespace from before ADR 0024 has no owner: its
former Writers hold `editor`. An Organization admin grants someone `owner` on it once;
from then on that owner manages it.

One namespace per application is the recommended layout, not a rule; see
[Namespaces and applications](../security/ownership-and-sharing.md#namespaces-and-applications).
To share part of the application's tables, declare a further namespace on those tables
instead of scaffolding another provider; see
[Put tables in namespaces](define-and-migrate-tables.md#put-tables-in-namespaces).

The Job also needs the platform's `reader` policy on the MetaTables branch, which
gives it `viewer` on the branch's `metatables` release, to discover the API. Declare it
on the Job (workflow API `3.0.0`):

```yaml
  - key: migrate-ledger
    kind: job
    spec:
      name: Ledger migrations
      execution_path: jobs/migrate_ledger.py
    access:
      branches:
        - repository: MetaTables
          policy: reader
```

`upgrade_application()` waits up to five minutes for the API to wake or finish
replacing its pods before it fails with `ApiResolutionError`; other client calls
wait 30 seconds. That includes a rollout of a new API revision, which the platform
can report as unavailable until it completes; an API whose revision failed is not
waited for. Within the same budget, the runtime-context request is retried
while the API answers 502, 503 or 504, for example while it cannot yet verify
callers; the final error keeps the API's last detail.

Team membership takes effect on the workload's next request, in the catalog and in
the database.

### When registration is refused

- **`namespace_access_required`**: the namespace already exists, but the
  `caller_user_uid` the error names lacks `tables.create` on it. The error lists the
  namespace's owners when the caller can see the namespace. One of them, or a manager
  of the workload that created the namespace, grants it `editor`. A recreated Job gets
  this too: its new workload User has no role yet.
- **`namespace_required`**: a workload tried to create a table outside any namespace.
  Set the table's namespace.
- **`table_not_editable`**: the table already exists and the caller lacks
  `tables.update` on it. An owner of the table or of one of its namespaces grants
  `editor`.
- **`last_namespace`**: the code no longer declares the only namespace the table is
  in. Keep one namespace on the model, or grant a person or Team `owner` on the table.

A refused namespace on an existing table fails that table's finalization and leaves its
namespaces as they were; the other tables are finalized.

After the grant, or after adding the workload User to a Team that holds the role,
re-run the Job. A refusal is rechecked against current Team membership before it
stands, so the re-run needs no wait. Do not run the Job as an Organization admin
or change physical names to get around a refusal.

## What the Job guarantees

- It runs on every deployment. A database already at head is left unchanged and
  reports `already current`.
- An exception fails the Job and blocks the rollout; the previous release keeps
  serving. Fix the revision and deploy again. If DDL committed but finalization
  failed, follow [Evolve and recover](define-and-migrate-tables.md#evolve-and-recover)
  before retrying.
- The Job finds the Environment's MetaTables API the same way any client does
  ([installation and connection](installation-and-connection.md)). That API must
  be deployed with its system migrations applied; otherwise the Job fails. Its
  workload User needs `editor`, directly or through a Team, on every existing
  namespace the provider creates tables in; a namespace it creates gives it `editor`.

## Keep each release compatible with the previous one

The Job runs before the rollout, so the previous release serves against the new
schema while the rollout proceeds, and keeps doing so if it fails. Write
revisions that the deployed release can still use: add tables, and nullable or
defaulted columns, first; drop or rename in a later release, once no deployed
code uses the old shape.

Redeploying an older image does not roll back the schema. A hosted `downgrade` is
a separate, explicitly requested operation, never a deployment step.
