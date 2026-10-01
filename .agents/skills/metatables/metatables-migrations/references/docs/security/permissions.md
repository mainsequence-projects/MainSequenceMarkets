# Administration and table permissions

These matrices describe the implemented [security model](index.md).
Writer authorizes migration connection admission and catalog operations. Application
DDL runs in the client with the configured environment login's database privileges.

## Application administration

These operations affect the application instance or its storage configuration.
Organization admin status comes from the platform through the SDK.

| Application operation | Ordinary application user | Organization admin |
| --- | --- | --- |
| Enter the application and browse permitted resources | Yes | Yes |
| Create or register a table in an available DataSource | Yes | Yes |
| Configure, validate, disable, or remove DataSources | No | Yes |
| Select runtime mode or the runtime DataSource where supported | No | Yes |
| Initialize or upgrade MetaTables system tables | No | Yes |
| Destroy a local runtime database through Settings | No | Yes |
| Change application-wide Settings and security policies | No | Yes |
| Manage grants across the application and recover orphaned tables | No | Yes |

Creation checks the selected DataSource's storage access mode and the table's
lifecycle requirements. The table and its creator's Writer grant are recorded
together. Re-registering an existing table cannot give another caller ownership.

Initial runtime setup must check the platform admin fact before the application
grant tables exist. Configuring a pending database does not make the first caller
an admin. Once configured, the original DataSource creator has no exclusive
administrative entitlement.

## Table access

Writer means full control of the particular table. There are no separate curator,
schema-maintainer, or updater-operator roles.

| Table operation | Reader | Writer / Owner |
| --- | --- | --- |
| View metadata, schema, and permitted lineage | Yes | Yes |
| Read, query, preview, and export data | Yes | Yes |
| Insert, update, upsert, and delete rows | No | Yes |
| Roll back time-index data | No | Yes |
| Edit descriptions, labels, and table configuration | No | Yes |
| Finalize an existing managed contract | No | Yes |
| Request application migration connection and finalize catalog | No | Yes |
| Register, configure, and operate the table's updaters | No | Yes |
| Manage the table's dependencies | No | Yes |
| Grant, change, or revoke Reader/Writer access to the table | No | Yes |
| Delete managed storage or unregister an external table | No | Yes |

Users and Teams receive these access levels on individual tables or through
namespace grants. No applicable grant means no access. Writer includes Reader.
Sharing Writer access makes the recipient a co-owner who can also share or delete
the table; it is not a restricted ingestion permission.

## Operations involving several resources

Permissions follow the resources actually affected:

- A query needs Reader access to every table it reads and Writer access to every
  table it changes. Supplying an authorized table UID does not authorize arbitrary
  SQL against other tables.
- A cascade needs Writer access to every affected table. Migration connection
  admission checks all provider catalog tables, including their registry. The
  resulting direct connection is governed by database privileges, not table grants.
- An updater needs Writer access to its output and Reader access to its inputs.
  A read-only `TimeIndexTableRef` does not require control of the upstream producer.
  Running an upstream producer requires Writer access to that producer's output.
- Moving a table between namespaces requires Writer access to the table and
  authorization for the destination. It can change inherited access, so the UI
  must show that impact. Global namespace grants remain a Security operation.

Full control remains subject to lifecycle safeguards: a reserved table is not
ready for ordinary writes, active work can block destructive changes, and deletion
protections and dependency constraints still apply. Read-only or disabled sources
cannot be made writable by a table grant. Unsupported engine operations remain
unsupported.

For an external table, deletion removes its MetaTables registration; it does not
drop the externally owned physical relation. Application system tables and grant
records cannot be edited as ordinary API table data. Direct migration access uses
the environment login's privileges; its restrictions are the environment operator's responsibility.

## Choosing the right page

A Writer uses the table page for data, schema, updater, deletion, and sharing
actions. They do not need to visit global Security. An Organization admin uses
Settings for DataSources/runtime configuration and Security to administer access
across the catalog or restore access to an orphaned table.

See [ownership, grants, and inheritance](ownership-and-sharing.md) for examples
of shared ownership and revocation.


## Imported tables and views

Discovery and creation of external registrations require an administrator.
Reader/Writer and namespace inheritance govern imported output. Writer permits
metadata refresh, sharing and unregistration; it never makes an imported view
writable. External reads use the stored connection account through the bounded
relation reader. They create no database roles, grants, helper objects or tables
in the external database, even with a privileged account configured as read-only.
Only the runtime catalog stores registrations and application grants.

Runtime views use native permission checks and adapter dependency validation.
SQLite permits view-only output through the bounded reader; its arbitrary SQL
path still requires underlying table grants to prevent CTE origin spoofing.
