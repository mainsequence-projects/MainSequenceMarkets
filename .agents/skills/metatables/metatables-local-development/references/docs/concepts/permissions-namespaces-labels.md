# Permissions, namespaces, and labels

See the dedicated [Security model](../security/index.md) for administration, the
[actions and roles](../security/permissions.md), the [access APIs](../security/ownership-and-sharing.md),
audit history, platform-fact freshness, and schema-execution limits.

Access is a role granted on a namespace or a table: `metadata_viewer`, `data_viewer`,
`data_writer`, `editor` or `owner`, each including the one before it. Tables combine
their direct bindings, their Teams' bindings and the bindings on their current
namespace; the strongest role wins. The API filters lists, counts, search, and lineage
by the same roles; hidden resources generally return 404. Organization admins hold
every action, data included.

## Namespaces

A catalog namespace groups tables for access. Any person can create a namespace whose
name is free and becomes its owner. Registering a table into a missing namespace also
creates it: a person owns it; a workload gets `editor`, and the people who manage that
workload manage the namespace's access. A namespace is visible to whoever holds a role
on it, can see at least one of its tables, or manages its creating workload; counts
show visible tables only. A role on a
namespace gives the table role of the same name on its current and future tables.
Revoking it, or moving a table out, removes that contribution; independent direct or
Team bindings remain. Moving a table needs `tables.update` on the table and
`tables.create` on the destination namespace.

A namespace is not tied to a project. Creating a table in it needs `tables.create`
(`editor` or `owner`), whatever project the caller runs. One namespace per application
is the recommended layout; see
[Namespaces and applications](../security/ownership-and-sharing.md#namespaces-and-applications).

## Labels

Labels classify resources and never authorize an operation. The catalog owns
unique label names, normalized slugs, and table links. Supported table PATCH
operations replace the label set. Inherited SDK add/remove-label actions remain
unsupported; consult the [capability reference](../reference/capabilities.md).

## Destructive operations

Deletion requires `tables.delete` on every affected table and retains lifecycle,
protection, and dependency checks. External deletion only unregisters its catalog
entry. Managed storage is dropped restrictively: unselected database dependents
cause failure rather than an unrestricted physical cascade. System and permission
tables cannot be registered as ordinary user tables. Direct application migration
connections are disabled in both runtime modes.

## Permissions during data execution

Data admission holds a shared catalog guard through physical work and catalog finalization on hosted backends. Permission/schema publication takes an exclusive guard and waits for affected admissions to finish. Reconciliation releases and reacquires admission before execution; it never upgrades a shared guard in place. Writes and statistics refresh on the same table also retain a table row lock through finalization. SQLite retains its native writer guard even for reads because WAL readers alone do not fence revocation. Main Sequence identity and membership-cache ownership are unchanged. See [ADR 0012](../adr/api/0012-bounded-data-transfer-and-safe-retries.md) for the protocol and verification limits.
