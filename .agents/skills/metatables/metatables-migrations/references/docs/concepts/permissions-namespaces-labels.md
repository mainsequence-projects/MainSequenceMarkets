# Permissions, namespaces, and labels

See the dedicated [Security model](../security/index.md) for administration, the
[actions and roles](../security/permissions.md), the [access APIs](../security/ownership-and-sharing.md),
audit history, platform-fact freshness, and schema-execution limits.

Access is a role granted on a namespace or a table: `metadata_viewer`, `data_viewer`,
`data_writer`, `editor` or `owner`, each including the one before it. Tables combine
their direct bindings, their Teams' bindings and the bindings on every namespace they
are in; the strongest role wins. The API filters lists, counts, search, and lineage
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
Revoking it, or removing a table from the namespace, removes that contribution;
independent direct or Team bindings remain.

A namespace's bindings can name a code repository branch: every workload of that branch
holds the role ([ADR 0029](../adr/api/0029-roles-for-a-branchs-workloads.md)). An
application's migration declares its own branch's roles with `branch_access`; an owner
grants another repository's branch. This does not tie the namespace to that repository:
any branch can hold roles on any namespace.

A table can be in several namespaces
([ADR 0028](../adr/api/0028-tables-in-several-namespaces.md)). Its role for a caller is
the strongest across all of them. An application shares part of its tables by declaring
a second namespace on those tables and granting on it once; see
[A table in several namespaces](../security/ownership-and-sharing.md#a-table-in-several-namespaces).
Adding a table to a namespace needs `tables.update` on the table and `tables.create` on
the namespace; removing it needs `tables.create` on the namespace.

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
