# 0046. Preserve The Populated Legacy 0017 Schema

## Status

Accepted for 2.2.7. Amends the legacy upgrade policy in
[ADR 0045](0045-squashed-initial-schema-and-namespaced-packages.md).

## Context

Production's migration Job fails with `Can't locate revision identified by
'0017'`. Its tables contain production data; resetting them or stamping a newer
revision would respectively destroy data or skip schema verification.
Development already uses the `0018`/`0019` graph and must keep working.

Replaying the original revisions from commit
`29dc96b693baa321dd8a0254c885407428378597` into disposable PostgreSQL produces
62 application tables. They match the frozen `0018` column baseline except for
ten unbounded identifier strings in OrdersTS, TradesTS, PortfolioWeightsTS and
SignalWeightsTS. Production's physical column inventory confirms these differences.

## Decision

Keep applied `0018` and `0019` byte for byte. Add a no-op `0017` compatibility
anchor whose parent is `0018`, then merge `0017` and `0019` at `0020`:

```text
base -> 0018 -> 0019 ---------------------> 0020
          |                                  ^
          +----> 0017 compatibility anchor ---+
```

The anchor maps the legacy schema to its verified baseline; it does not replay
the original `0017` DDL. A database already at `0017` skips initial table creation
and receives `0019` plus `0020`. Fresh databases and development histories also
reach one head, using the unchanged standard MetaTables migration environment.
Only the legacy head `0017` is recognized, not earlier legacy revisions.

`0020` checks every expected table, column, type and nullability before changing
anything. Extra tables and columns are preserved. It accepts only the ten known
unbounded strings as differences. PostgreSQL locks the affected tables, refuses
any value exceeding 255 characters, alters the limits in place, and compares row
counts and two 64-bit sums of row MD5 hashes before and after. A mismatch fails
the transaction. Logs report counts and checksum equality without row values.
SQLite checks the baseline without physical string-limit alterations.
Already-bounded development tables require no alterations or locks.

Hosted execution remains the candidate image's migration Job, followed by API
rollout only after successful catalog finalization. No local session runs hosted
DDL. Both new revisions reject downgrade; future corrections use new revisions.


Legacy TimescaleDB finalization also requires the shared **MetaTables API
0.1.34** ownership-before-conversion repair. On TimescaleDB 2.10.2, converting
a populated ordinary table and then reassigning it fails when the API login
lacks `CREATE` on `_timescaledb_internal`. The API now transfers the ordinary
table first, then converts it with `migrate_data`, in one transaction. This
requires no new grant or application revision. If `0020` committed but
finalization failed, deploy the repaired shared API and rerun the hosted Job at
head; keep all existing application data and applied revisions. An already
current development hypertable keeps its owner and rows. This is a server
requirement; the Markets migration client remains 0.1.33.

## Validation

The PostgreSQL regression fixture is a schema-only dump of the original `0017`
history. Tests seed all 62 application tables, prove overlong values fail without
changing rows or the revision, and compare every table's row multiset before and
after upgrading twice. Fresh, `0018`, and `0019` paths are also exercised, and a
missing required column fails validation. The frozen baseline ships in the wheel.
Release verification must include development's migration and API health before
promoting to Production, then Production's migration and both sites' API access.

## Consequences

The graph explicitly carries a compatibility mapping for an already-squashed
history. It cannot validate a falsely stamped or otherwise drifted database by
its revision alone; the frozen column guards provide that check. Identifier
values over 255 characters require a separate forward repair, never truncation.
The ledger uniqueness correction in `0019` remains the only constraint removal;
no application tables, columns, or rows are removed by this bridge.
