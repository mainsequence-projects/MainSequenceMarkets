# Permissions, namespaces, and labels

See the dedicated [Security model](../security/index.md) for the administration
and Reader/Writer matrices, [sharing APIs](../security/ownership-and-sharing.md),
audit history, platform-fact freshness, and schema-execution limits.

Tables use direct User/Team grants and live grants from their current namespace.
Writer includes Reader and gives full table ownership. The API filters lists,
counts, search, and lineage using the same grants; hidden resources generally
return 404. Organization admins manage Settings and global Security but still
need explicit table grants for ordinary data operations.

## Namespaces

A catalog namespace groups table access. Namespace reads require a namespace
grant or access to at least one current member table. Counts show visible tables
only. Namespace Reader/Writer grants are administered in global Security and
apply live to current and future member tables. Revocation or a namespace move
removes that contribution; independent direct or Team grants remain effective.
Moving a table requires its Writer and destination namespace Writer, or admin
authority for the destination. Table Writer alone cannot change global grants.

## Labels

Labels classify resources and never authorize an operation. The catalog owns
unique label names, normalized slugs, and table links. Supported table PATCH
operations replace the label set. Inherited SDK add/remove-label actions remain
unsupported; consult the [capability reference](../reference/capabilities.md).

## Destructive operations

Deletion requires Writer on every affected table and retains lifecycle,
protection, and dependency checks. External deletion only unregisters its catalog
entry. Managed storage is dropped restrictively: unselected database dependents
cause failure rather than an unrestricted physical cascade. System and permission
tables cannot be registered as ordinary user tables. Direct application migration
connections are disabled in both runtime modes.

## Permissions during data execution

Data admission holds a shared catalog guard through physical work and catalog finalization on hosted backends. Permission/schema publication takes an exclusive guard and waits for affected admissions to finish. Reconciliation releases and reacquires admission before execution; it never upgrades a shared guard in place. Writes and statistics refresh on the same table also retain a table row lock through finalization. SQLite retains its native writer guard even for reads because WAL readers alone do not fence revocation. Main Sequence identity and membership-cache ownership are unchanged. See [ADR 0012](../adr/api/0012-bounded-data-transfer-and-safe-retries.md) for the protocol and verification limits.
