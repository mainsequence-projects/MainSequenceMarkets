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
3. **Give a Team the tables.** Before the first hosted migration in each
   Environment, set up the Team that owns the application's tables
   ([below](#give-the-job-access-through-a-team)).
4. **Deploy.** The application's workflow runs its migration Job from the
   candidate image, then deploys the resources that read or write the tables.

Hosted runtimes are migrated only by step 4. Do not run `metatables migrations
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
api_version: "2.3.0"
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

## Give the Job access through a Team

The Job runs as its own workload User, and each Environment, and each recreated
Job, has a new one. A table owned by one workload User is lost to the next, so the
application's tables belong to a platform Team instead:

1. **Create one Team per Environment** for the application, for example
   `ledger-development` and `ledger-production`. A shared Team would make one
   Environment's workloads Writers in another.
2. **Add the workload Users.** Add the migration Job's workload User, and the
   workload User of every resource that reads or writes the tables (FastAPI
   release, Agent, other Jobs). Each resource's `workload_user_uid` names it.
3. **Grant the Team its namespaces.** For each namespace the tables are
   registered in, an Organization admin creates it in that Environment's
   MetaTables if it doesn't exist yet, under **Security** or with
   `POST /security/namespaces/`, and grants the Team Writer on it
   (`PUT /namespaces/{uid}/permissions`). Every table registered in the namespace
   inherits the grant. One namespace per application is the recommended layout,
   not a rule; see
   [Namespaces and applications](../security/ownership-and-sharing.md#namespaces-and-applications).

The Job also needs platform `view` on the Environment's `metatables` release and
its branch to discover the API; declare it on the Job:

```yaml
  - key: migrate-ledger
    kind: job
    spec:
      name: Ledger migrations
      execution_path: jobs/migrate_ledger.py
    access:
      branches:
        - repository: MetaTables
          level: view
```

`upgrade_application()` waits up to five minutes for the API to wake or finish
replacing its pods before it fails with `ApiResolutionError`; other client calls
wait 30 seconds.

Team membership takes effect on the workload's next request, in the catalog and in
the database. When a workload User changes, add the new one to the Team; nothing
in MetaTables changes. A table registered in a namespace the caller already
writes gets no grant of its own, so the Team stays its only owner.

### When registration is refused

- **`namespace_not_writable`**: the namespace does not exist in this Environment,
  or the caller is not its Writer. Do steps 1 to 3 for the `caller_user_uid` the
  error names.
- **`table_not_editable`**: the table is already registered and the caller is not
  its Writer. Add the `caller_user_uid` to the Team with Writer on the table's
  namespace. When the table was registered before the Team existed, its only
  Writer may be a workload User that no longer runs: an Organization admin
  grants the Team Writer on the namespace, and the table inherits it. The error
  lists the table's Writers when the caller can read the table.

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
  workload User needs Writer, through the Team above, on every namespace the
  provider registers tables in.

## Keep each release compatible with the previous one

The Job runs before the rollout, so the previous release serves against the new
schema while the rollout proceeds, and keeps doing so if it fails. Write
revisions that the deployed release can still use: add tables, and nullable or
defaulted columns, first; drop or rename in a later release, once no deployed
code uses the old shape.

Redeploying an older image does not roll back the schema. A hosted `downgrade` is
a separate, explicitly requested operation, never a deployment step.
