# ADR 0016: Impact pre-flight for cascades and deletes

Date: 2026-10-03

Status: Accepted.

Implementation status: implemented. Tests cover the planner through the Python
client against an isolated catalog and the SQLite engine. PostgreSQL,
TimescaleDB, MySQL and SQL Server cascade-target queries have not yet been run
against their containers.

Owner: MetaTables API. The Python client exposes the result; consuming projects
own their UIs.

Related decisions: [ADR 0001](0001-unified-api-storage-and-local-sqlite.md) (the SDK
makes no access decisions of its own), [ADR 0002](0002-application-administration-and-table-ownership.md)
(cascades need access to every affected table) and [ADR 0007](0007-database-enforced-table-access.md)
(amended 2026-10-03: write requires write on every cascade target).

## Context

Cascading foreign keys are now allowed. A caller keeps write on a table only while
they can write every table its `CASCADE`, `SET NULL` and `SET DEFAULT` actions
modify. A project that builds its own UI needs to show, before acting, which
tables a delete or key update reaches, what happens to each, and why a write is
or is not available. Before this decision, a caller could only try the action
and read the error.

## Decision

The API answers one question: *what would this action do, and may I do it?* The
API computes the answer from the catalog and the recorded cascade targets. The
client returns it unchanged.

```
GET /meta-tables/{uid}/impact/?action=delete_rows|update_keys|drop_table
GET /time-index-meta-tables/{uid}/impact/?action=...
```

`drop_table` also accepts the `delete-with-cascade` options. The client method is
`MetaTable.get_impact(action=...) -> MetaTableImpact`, inherited by
`TimeIndexMetaTable`.

```python
impact = table.get_impact(action="delete_rows")
if not impact.allowed:
    for blocker in impact.blockers:
        print(blocker.code, blocker.node, blocker.message)
```

The response is a graph rooted at the table:

- **Nodes**:
  - `meta_table` nodes carry the uid, identifier, namespace and physical name.
  - `relation` nodes are unregistered physical tables, identified by physical
    name only.
  - `update` nodes are updates that read an affected table.
  - `hidden` nodes are tables the caller cannot view. They are opaque: an effect
    with no names.

  Each node lists its `effects` (`drop`, `delete`, `update`, `input_changed`) and
  the caller's `can_write`. For row actions, `can_write` is the database
  privilege after cascade narrowing, computed by the same function the
  reconciler uses. For `drop_table`, it is the edit grant the drop requires.
- **Edges**: each edge points from the dependent to what it depends on, as in
  the schema graph. Edges are classified by effect: `cascade_delete`,
  `cascade_update`, `set_null`, `set_default`, `restrict` (fails while
  referencing rows exist), `drop`, and `reads`.
- **Verdict**: `allowed` and every blocker, each with a code and the node it
  concerns:
  - `cascade_target_unregistered`
  - `cascade_target_not_writable`
  - `table_not_writable`
  - `writes_unsupported`
  - `data_source_read_only`
  - `retained_referencing_table`
  - `alembic_protection`
  - `deletion_protected`

`delete-with-cascade` runs the same planner (`persistence/impact.py`) and refuses
with its first blocker's status and message, so a preview and the confirmed
delete cannot disagree. Recorded cascade targets now carry each foreign key's
`on_delete` and `on_update` action and are recorded for every table, so read-only
callers see the same graph.

The pre-flight is advisory. The database and the confirmed actions still enforce
every rule at execution time.

## Remaining gaps

| Need | Today |
| --- | --- |
| `on_update` in the catalog | `MetaTableForeignKey` and contracts carry only `on_delete`; contracts reject `set default`. Row-action edges use the physical actions, which are complete. |
| Effective write in table responses | `permissions.write` reflects catalog grants and can say yes when cascade narrowing says no. Callers should use the pre-flight. |
| Plain delete | `DELETE /meta-tables/{uid}/` still answers 409 without listing references. |
| Contract changes | No `change_contract` action; a PATCH that would invalidate an incoming key fails with a text message. |
| Schema and update graphs | `get_schema_graph` returns an untyped dict; `update-graph` has no client method. |
| Views | No view-to-table dependency tracking; views stay read-only registrations. |
| Admin visibility | `GET /security/database-permissions/` does not show cascade targets. |

## Consequences

- Consuming projects can render cascade and impact views without reimplementing
  permission or foreign-key rules, and their UIs stay correct when those rules
  change.
- One planner serves both the preview and the confirmed delete.
- Opaque nodes reveal that hidden tables are affected, but not which ones.
- Reconciliation now inspects foreign keys for every registered table, not only
  writable ones.
