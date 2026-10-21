# ADR 0023: A daily security check instead of a sweep in every deployment

Status: Accepted.

Implementation status: implemented on development. Non-container tests pass; the
deployment, the first scheduled run and the container suites are pending.

Owner: this repository.

Related decisions: [ADR 0007](0007-database-enforced-table-access.md) (database roles
enforce table access), [ADR 0014](0014-main-sequence-release-jobs-and-production-migrations.md)
(the migration Job of every deployment) and
[ADR 0013](0013-application-owned-migrations.md) (application migrations).

## Context

Every deployment's migration Job ran the full security check. It compared every role,
membership, grant, table policy and routine MetaTables secures with the catalog's plan,
opened a fresh connection for every login role, and repaired what differed. It held the
security-state lock throughout, so callers' SQL waited. In development it took 135 s of
a 147 s migration step; in one run
([MetaTables #66](https://github.com/mainsequence-projects/MetaTables/issues/66)) it
took 25 minutes, close to the Job's 30-minute limit.

Most of that work repairs grants changed outside MetaTables. A deployment neither causes
them nor repairs them in time: drift made just after a deployment stays until the next
one, which in production can be weeks away. Drift the check cannot repair blocked the
release, even a release meant to fix it.

## Decision

The full check runs once a day as its own Job, and administrators can run it at any
time. A deployment does only what the new release needs.

### What a deployment does

The migration Job's security step:

1. sets up the owner role `mt_owner`, which normally changes nothing;
2. runs the full check on the first setup, and when the system migration heads differ
   from the ones the last full check ran at. System migrations change catalog rows
   without the hooks that keep grants in step. The heads are recorded with the check,
   so nothing depends on a developer bumping a version number;
3. sets every login password again when the DataSource password was rotated;
4. applies pending changes.

Otherwise it sends nothing.

### The daily check

- The `check-security` Job of the API workflow (`jobs/check_security.py`, exactly
  `metatables runtime check-security`) runs daily at 03:00 UTC. It is not a workflow
  step; every push activates its image.
- It holds the bootstrap lock, so it waits for a running migration. It skips while the
  database still awaits its image's system migrations, so a run that lands mid-rollout
  never checks one release's catalog with another's rules. Any other state that is not
  ready fails the run.
- It repairs whatever differs from the plan: the owner role, routines, table policies,
  roles, memberships and grants, and the passwords of logins that fail a fresh login
  probe. The probe runs before the security-state lock is taken.
- It never pauses caller SQL. A failed check rolls back what it changed.
- System migration `0013_security_check` records the last check on the security state:
  what started it (`schedule` or `admin`), its outcome (`running`, `passed`, `repaired`
  or `failed`), its times, and the statements it sent or its error code.
  `GET /security/database-permissions/` returns it as `last_check`.

### Run it now

`POST /security/checks/` (administrators only) replaces `POST /security/reconcile/`,
which paused caller SQL during the repair and had to finish within the 300 s request
timeout. Hosted starts the Job with `--trigger admin` and answers 202; the API's
workload may run that Job (`level: edit`), one run at a time. Local runs the check in
the request. The Admin's Database permissions panel has **Run security check now** and
shows the last check.

### Access rule changes

A release that changes how MetaTables computes access reaches the database at the next
daily check, or right away when an administrator runs it after deploying. Access rules
are the plan (`plan()`), the table policy checks, the grant and revoke statements,
routine securing and the owner role. Pull requests that change them carry the
`access-rules` label, and release notes list them under "Access rule changes: run the
security check after deploying". A version constant in the code was rejected: when
someone forgets to bump it, the deployment skips the check silently.

## Consequences

- An unchanged deployment's security step reads the security state and the owner role
  and sends nothing. It no longer grows with tables or users.
- Grants changed outside MetaTables are repaired within a day, whatever the release
  cadence.
- Drift the check cannot repair fails the daily Job, not a release.
- The daily check still makes caller SQL wait while it holds the lock, once a day at
  03:00 UTC. If that wait matters, the check can compute the differences before taking
  the lock.
- Application migrations are unchanged: finalization checks only the tables it
  finalizes (ADR 0013). A finalization waits for the daily check only if both run at
  the same time.

## Verification

- `tests/permissions/test_deployment_security.py`: an unchanged deployment reads and
  writes nothing; first setup and new system migration heads run the full check once;
  a rotated password sets only passwords; pending changes apply; outside drift waits
  for the check; the check probes logins before the lock and counts its repairs.
- `tests/permissions/test_security_check.py`: the recorded outcome, the Job's lock and
  skip, and starting the Job or refusing to.
- `tests/auth/test_runtime_storage_binding.py`: Local runs the check in the request; a
  failure is recorded and never pauses SQL.
