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
   candidate image, then deploys the resources that read or write the tables.

Hosted runtimes are migrated only by step 3. Do not run `metatables migrations
upgrade` or `downgrade` against a hosted API from a developer machine or agent
session. Do not migrate at application startup either: several pods would race,
and a failure would not stop the rollout.

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
  SDK user needs the same API access a developer needs to run the provider.

## Keep each release compatible with the previous one

The Job runs before the rollout, so the previous release serves against the new
schema while the rollout proceeds, and keeps doing so if it fails. Write
revisions that the deployed release can still use: add tables, and nullable or
defaulted columns, first; drop or rename in a later release, once no deployed
code uses the old shape.

Redeploying an older image does not roll back the schema. A hosted `downgrade` is
a separate, explicitly requested operation, never a deployment step.
