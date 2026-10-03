# Recovery, deletion, and observability

The catalog and physical table database have separate transactions. The API records
physical create/drop work in a durable journal with states `planned`, `running`,
`applied`, `failed`, and `reconciliation_required`.

A definite pre-effect failure can be retried through the operation's supported
path. If the physical commit result is uncertain, inspect the actual database and
journal before deciding whether the effect happened. The internal journal
repository has explicit reconciliation operations; there is no general public
reset command. Do not mark an operation successful merely to unblock a request.

## Managed migration failures

A migration can apply DDL while final catalog finalization fails. Inspect every
per-table finalization result, physical schema, provider identity, and registry
state. Reuse only a compatible registry resolved by physical identity. Preserve
Alembic's applied history; write new revisions for further changes.

## Deletion

Ordinary delete requires edit access and respects table and inbound
reference protections. Alembic-managed tables reject ordinary deletion. External
unregistration leaves the physical relation intact; owned managed storage is
dropped restrictively before catalog removal.

The ordinary delete API accepts compatibility switches such as
`override_protection` and `full_delete_selected`, but they do not bypass these
checks or enable cascading. Use the separate confirmed cascade action when a
reviewed destructive teardown is intended.

Cascade requires `confirm_cascade_delete=True`, edit access to every affected
catalog table, and explicit permission to include referencing table kinds.
Alembic-managed teardown additionally needs
`override_schema_management_protection=True`. Ordinary table protection remains
enforced. Edit access is required for all affected catalog tables.

Physical `DROP ... CASCADE` can remove dependent database objects that are not in
the catalog. Review the physical dependency graph and role privileges. Separate
DataSource groups can commit independently, so inspect uncertain or partial
outcomes rather than assuming catalog rollback restores physical objects.

## Logs and diagnostics

[ADR 0005](../adr/api/0005-run-logs-and-local-file-capture.md) accepts a shared
run-log API with local JSONL file capture and hosted retrieval through the SDK.
The API serves run logs through the selected runtime reader. See
[Run logs](run-logs.md) for capture prerequisites, query limits and availability.
Log bodies remain outside the catalog database.

Use request/resource UIDs, provider keys, update hashes, run UIDs, operation UIDs,
and safe error codes to correlate work. Never log connection responses, caller
assertions, migration passwords, or TLS keys. SDK logging/tracing integration is
optional behavior; catalog membership and storage authorization are not derived
from logging context.

The `metatables.bootstrap` logger records unexpected runtime database failures
(inspection, migration, registration and the Local selection file) with their
traceback, redacting passwords, tokens and connection-string credentials as run
logs do. The matching API error names only the exception type and, when the database
server answered, its SQLSTATE and message. See the
[deployment gate](hosted-runtime.md#deployment-gate).

Distinguish HTTP availability, catalog readiness, caller admission, source grants,
physical capabilities, and actual database connectivity when diagnosing failures.
The [testing guide](../contributing/testing.md) distinguishes isolated tests from
real SQLite/PostgreSQL execution and hosted verification.

## Data upload receipts

Retain receipts and their reserved keys indefinitely; do not purge them on table deletion or age. A crashed request can leave `running` after a physical commit. Inspect data through Main Sequence, then use the administrator reconciliation action with evidence, never elapsed time alone. Resolve `applied` without another write, or `not_applied` before explicitly retrying a failed chunk. Reconciliation fences older pending attempts; uncertain writes are never automatically replayed. Refresh statistics after confirming an applied outcome. See the [recovery procedure](../client/bounded-transfers.md#upload-and-recover).

The `metatables.transfer` logger records action, elapsed/queue time, and received/sent byte counts without payloads, SQL, or credentials. Correlate receipts using operation and chunk UUIDs. Measure database lock/fetch time and process RSS separately when diagnosing slow transfers; HTTP duration alone cannot identify the database bottleneck. No throughput claim is implied by the local tests.
