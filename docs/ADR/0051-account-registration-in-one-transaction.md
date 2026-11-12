# 0051. Account Registration In One Transaction

## Status

Proposed (2026-11-12) for
[issue #63](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/63).
It amends the worked example "a provider account sidecar" in
[ADR 0047](0047-markets-api-application-boundary.md) (see "Amendment To ADR 0047"
below). It builds on two fixes:

- [#61](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/61): one read
  resolves every position's asset, and a holdings write is not read back;
- [#62](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/62): unchanged
  asset snapshots and upserts are not rewritten.

Statement lists run on PostgreSQL and SQLite, as in
[ADR 0050](0050-account-deletion.md) (MetaTables ADR 0026).

## Context

A venue connector registers a brokerage account through the Markets API. Issue #63 reports
that one connector makes 13 sequential Markets calls to do this, and makes most of them again
on every holdings sync: an account lookup, asset lookups, asset-type and asset upserts, asset
snapshots, the currency asset, the account upsert and the holdings publish. On a hosted
Markets API these 13 calls take 2.5 to 3 minutes. Each MetaTables operation costs about
3.4 s there (MetaTables#106, reported in #61). These timings come from a hosted deployment
and were not reproduced for this ADR.

None of these calls is atomic with the others. A connector that fails halfway leaves assets
without the account, or an account without its holdings.

ADR 0047's worked example already expects a combined route. Registration "runs
`Account.upsert`, an upsert on the sidecar and a holdings snapshot as three separate
MetaTables requests". Under that ADR, "atomicity is unchanged; a composite register route on
Markets could later make it better than today".

The pieces such a route needs already exist:

- `compile_markets_statements` and `execute_markets_write`
  (`src/msm/repositories/base.py`) send an ordered statement list that MetaTables runs in one
  transaction. Account deletion uses them (`src/msm/repositories/account_deletion.py`).
- `AccountHoldingsStorage` is a time-index storage (`MarketsTimeIndexMetaTableMixin`). It is
  already written with plain SQL inside a transaction by `replace_account_holdings_snapshot`
  (`src/msm/repositories/accounts.py`), not by an updater.
- `AssetSnapshotsStorage` is the same kind of storage. Today it is written only through the
  `AssetSnapshot` updater (`AssetSnapshots.publish`), which makes about a dozen backend calls
  per publish (#62).
- `asset_reference_details` (`src/msm/services/assets/reference_details.py`) returns each
  asset's uid, `asset_type` and latest snapshot in one select.
- `AccountTable.uid` defaults to `new_markets_uid` in Python, so a caller can choose the uid
  of a row before inserting it.
- `msm_migrations` does not seed `BUILT_IN_ASSET_TYPE_DEFINITIONS`. A `currency` asset needs
  `ASSET_TYPE_CURRENCY_DEFINITION` created first, as `CurrencySpot.upsert` already does for its
  own type.

## Decision

### 1. One route

`POST /api/v1/account/registration/` (`registerAccount`) registers an account and writes one
holdings snapshot. A connector calls it once to register, and once per holdings sync.
`msm.services.register_account` implements it; `MarketsClient.register_account` calls it.

The request:

```json
{
  "account": {"unique_identifier": "...", "account_name": "...",
              "is_paper": true, "account_is_active": true},
  "assets": [
    {"unique_identifier": "<venue>::<venue asset id>",
     "asset_type": {"asset_type": "us_equity", "display_name": "...", "description": "..."},
     "snapshot": {"name": "...", "ticker": "...", "exchange_code": "...",
                  "asset_ticker_group_id": "..."}}
  ],
  "cash_currency": "USD",
  "holdings_date": "2026-01-02T21:00:00Z",
  "overwrite": true,
  "positions": [{"asset_identifier": "<venue>::<venue asset id>", "quantity": "3",
                 "direction": 1, "target_trade_time": null, "extra_details": {}}]
}
```

- `assets` lists the assets the call may create. Each one names its asset type, and may carry
  a `snapshot`. The snapshot fields are the value columns of `AssetSnapshotsStorage`, so the
  exchange is `exchange_code`.
- `cash_currency` is optional. It names a currency asset, as in decision 9.
- A position may name any asset in `assets`, the cash currency, or an asset that already
  exists. Each asset appears at most once among the positions.
- `is_paper` and `account_is_active` are optional. When one is left out, a new account gets
  the `AccountCreate` default and an existing account keeps its value.
- A call names at most 1,000 distinct asset identifiers and 1,000 positions. That keeps each
  read to one MetaTables page and each statement well under the parameter limits of both
  dialects.

### 2. Two reads

The route makes exactly two reads, whatever the number of assets or positions:

1. `asset_reference_details` for every identifier the request names: those in `assets`, in
   `positions` and the cash currency. It answers each existing asset's uid, `asset_type` and
   latest snapshot.
2. The account by `unique_identifier`, with its holdings rows at `holdings_date`. This is one
   select: the account, left-joined to its holdings set at `holdings_date` and to that set's
   rows.

Asset types are not read; decision 4 creates only the missing ones without reading them.

The route then decides what to write from these two reads. Any of these refusals is answered
before a write is sent, so nothing is written:

- a position whose asset is not in `assets`, is not the cash currency and does not exist:
  `400`, naming every such identifier;
- an asset named twice among the positions: `400`;
- an existing asset whose type differs from the request (decision 7): `409`;
- an existing holdings snapshot that differs from the request while `overwrite` is false
  (decision 8): `409`.

### 3. One transaction

Everything the call writes goes in one statement list, which MetaTables runs in one
transaction. The route uses `compile_markets_statements` and `execute_markets_write`, as
account deletion does, on PostgreSQL and on SQLite. If any statement fails, nothing is
written. Each statement is included only when it has something to write:

1. **Asset types.** The types of the assets being created, the cash currency's included:
   `INSERT ... ON CONFLICT (asset_type) DO NOTHING`. An existing asset type is never changed.
2. **Assets.** The assets the first read did not find, each with a uid the route chose:
   `INSERT ... ON CONFLICT (unique_identifier) DO NOTHING`.
3. **Asset snapshots.** The rows decision 6 selects, inserted into `AssetSnapshotsStorage`
   at `holdings_date`: `INSERT ... ON CONFLICT (time_index, asset_identifier) DO NOTHING`.
4. **Account.** Only when the account is missing, or when `account_name` or a supplied flag
   differs from the second read: `INSERT ... ON CONFLICT (unique_identifier) DO UPDATE` with
   the request's fields. The account's other columns are not touched.
5. **Holdings.** The holdings set, the removal of its rows when `overwrite` is true, and the
   new rows. These are the statements `replace_account_holdings_snapshot` sends on SQLite,
   with the account uid looked up as in decision 5. They are left out when the stored
   holdings at `holdings_date` equal the request (decision 8).
6. **Answer.** A final select returns the account row, the uid of every asset the request
   names and the holdings set uid. It also counts the rows this transaction created, found by
   the uids the route chose. A statement list returns only its last statement's rows.

When the reads show that nothing differs, no transaction is sent. A re-registration of known
assets with a new `holdings_date` makes two reads and one transaction.

### 4. Only missing rows are created

Asset types and assets are inserted with `ON CONFLICT DO NOTHING`. If another call creates the
same row between the read and the transaction, its row stays and the final select reports it.
That select also returns that asset's uid, which is why the route does not answer with the
uids it chose. The `created` counts include only the rows whose uid the route chose.

### 5. The account uid in the holdings rows

The holdings set and its rows take the account uid from
`(SELECT uid FROM account WHERE unique_identifier = :account_identifier)` inside each
statement. They do not take a uid passed as a parameter. The route chooses a candidate uid
with `new_markets_uid` only for the account insert.

Two concurrent first registrations of one account both read "no account", and both choose a
uid. The first to commit inserts its own. The second hits the `unique_identifier` conflict
and updates that row instead, and its lookup returns the uid that won. The holdings rows of
both calls therefore reference the account that exists. With the candidate uid as a
parameter, the second call's rows would name an account that was never inserted, and its
foreign key would refuse them.

### 6. Snapshots are written with plain SQL

Snapshot rows are inserted with plain SQL inside the registration transaction, as
`AccountHoldingsStorage` rows already are. They do not go through the `AssetSnapshot` updater.

An asset in `assets` that carries a `snapshot` gets a row at `holdings_date` when:

- it has no snapshot; or
- its latest snapshot is earlier than `holdings_date` and differs in any of the four value
  columns: `name`, `ticker`, `exchange_code` or `asset_ticker_group_id`. A missing value and
  an empty string are equal.

Otherwise the call writes no snapshot for it. A re-registration or sync with unchanged values
therefore writes none.

This is #62's comparison, limited to what the first read returns. #62 compares each row with
the snapshot in effect at that row's time. For a `holdings_date` after the latest snapshot,
the snapshot in effect at that time is the latest one, so both comparisons agree. When an
asset's latest snapshot is at or after `holdings_date`, the snapshot in effect could be an
earlier one, and finding it would take another read. In that case the call writes nothing.
Registration does not rewrite or backfill snapshot history; `AssetSnapshots.publish` does.

Writing outside the updater skips the updater's bookkeeping. MetaTables merges an update
run's index progress into the table's catalog statistics, and rows the registration writes
are not counted there, as holdings rows are not counted today. `asset_reference_details`
reads the table with plain SQL, so readers through Markets see the rows.

### 7. An existing asset's type is never changed

An asset that already exists keeps its `asset_type`. The requested type is normalized with
`normalize_asset_type` before it is compared. If it differs from the stored type, the call
answers `409` and writes nothing. An existing asset with no type differs from any requested
type. The answer lists every such asset with its stored and its requested type. The cash
currency is compared with `currency`.

The route creates only what is missing; it never changes an asset's identity. `asset_type`
selects an asset's type-specific details (`Bond`, `CurrencySpot`) and how other applications
classify it, so changing it silently changes what they read. Keeping the stored type silently
would instead attach holdings to an instrument the caller describes differently. To resolve
the conflict, the caller either changes the asset's type through the asset routes or sends
the stored type.

### 8. Repeats and `overwrite`

The call is idempotent on `(account.unique_identifier, holdings_date)`. The second read
returns the holdings stored at `holdings_date`. They equal the request when both name the same
assets and, for each asset, the same `quantity` (as stored, a float), `direction`,
`target_trade_time` and `extra_details`. As in `add-holdings`, a position without
`target_trade_time` uses `holdings_date`.

| Stored holdings at `holdings_date` | `overwrite: false` | `overwrite: true` |
|---|---|---|
| none | written | written |
| equal to the request | not written; `200` | not written; `200` |
| different | `409`, and nothing in the call is written | rows replaced |

A repeat that sends the same positions with `overwrite: false` therefore succeeds. It answers
the existing `holdings_set_uid`, and the holdings counts are zero. The other writes in the
call still happen: new assets, changed snapshots and a changed account.

If another call creates the snapshot between the read and the transaction, the holdings-set
insert is refused by its guard (`overwrite: false`). The call then answers `409` and writes
nothing. A retry reads the stored snapshot and gets one of the answers in the table.

### 9. A currency asset get-or-create

`Asset.get_or_create_currency(code)`, backed by `msm.services.get_or_create_currency_asset`,
returns the currency asset whose `unique_identifier` is `code`. It creates the asset if it is
missing, and creates `ASSET_TYPE_CURRENCY_DEFINITION` first, in one transaction. An existing
asset of another type raises `AssetTypeConflictError` (`409`), following decision 7. It is a
row operation, so it also runs through the Markets API, and it is a registry write. The
registration treats `cash_currency` the same way, as an asset with the `currency` type
definition.

### 10. The answer

- `account`: the Account row.
- `asset_uids`: the uid of every asset the request names, by identifier.
- `holdings_set_uid` and `holdings_date`.
- `written`: per table (`asset_types`, `assets`, `asset_snapshots`, `accounts`,
  `holdings_sets`, `holdings`), the counts of rows `created` and `changed`. A holdings set
  whose rows were replaced counts as changed.

### 11. Audit

The service is wrapped in `registry_write("account", "register")`. It also calls
`record_registry_write(..., details=...)` once for each sub-write, so the audit log names
every row the call created or changed:

- each asset type and asset created;
- the account created or updated;
- the snapshot rows written;
- the holdings set created or replaced, with its row count.

Every record carries the registered account's `unique_identifier`, so the records of one call
can be grouped. A refused call records nothing.

### 12. Provider sidecars stay provider-owned

The route writes only Markets tables. A provider's account sidecar stays in the provider's
namespace (ADR 0047), with its encrypted columns. The provider writes the sidecar after the
registration returns the account uid, in its own request. Registration is idempotent, so a
provider whose sidecar write fails can run both again.

## Amendment To ADR 0047

In ADR 0047's worked example, the bullet "`Account.upsert` and the active-flag update go
through the Markets account create and update routes ... a composite register route on
Markets could later make it better than today" now reads:

> Registration and each holdings sync go through `POST /api/v1/account/registration/`. The
> call creates the missing asset types, assets and cash currency asset, writes changed asset
> snapshots, creates or updates the account, and writes the holdings snapshot, all in one
> MetaTables transaction. The provider then upserts its sidecar with the account uid the call
> returns. The active-flag update still uses `PATCH /api/v1/account/{uid}/`, or a
> registration that sends `account_is_active`. The Markets rows are written atomically; the
> sidecar is a separate write by the provider.

The rest of the worked example is unchanged.

## Rejected Alternatives

### Keep The Separate Calls

This is today's path: about 13 Markets calls and no atomicity. It is the problem #63
describes.

### Publish Snapshots Through The Updater

This is the approach #63 first proposed. The updater runs its own backend calls outside the
registration transaction, so a first registration would stay non-atomic, and it would use
the slow path #62 reports.

### Read Asset Types Or Snapshots Separately

A separate read of asset types, or of snapshots, adds one MetaTables operation per call. An
insert with `ON CONFLICT DO NOTHING` creates only the missing asset types without knowing
which exist. `asset_reference_details` already returns each asset's latest snapshot in the
same select as the asset.

### Pass The Account Uid As A Parameter

The uid read before the transaction, or the candidate uid, is wrong when a concurrent call
registers the same new account first (decision 5).

### Compare Holdings Inside The Transaction

A guarded statement could compare the stored rows with the request inside the transaction.
Comparing them on the second read instead means an identical repeat sends no transaction at
all. The guard on the holdings-set insert still covers a snapshot created in between.

### Change Or Ignore A Differing Asset Type

Both are covered by decision 7: changing the type silently changes what other applications
read, and ignoring it attaches holdings to an instrument the caller describes differently.

### Write Snapshots Before The Latest One

Writing them correctly needs the snapshot in effect at `holdings_date`, which is another read
for each such asset. `AssetSnapshots.publish` already does that.

### Write The Sidecar In The Same Transaction

The sidecar is in the provider's namespace, and only the provider's keyring can write its
encrypted columns (ADR 0047).

### A Read-Only Plan Call

A plan call would add a Markets call without saving a write. The route already works out
what is missing, and the caller makes any ownership check in its own sidecar.

## Consequences

- A connector registers, or syncs, with one Markets call. For known assets, the Markets API
  makes two reads and one transaction, or no transaction when nothing changed. Before, #63
  reports about 35 MetaTables operations.
- `msm.client` gains `MarketsClient.register_account`, so connectors no longer carry their
  own holdings-publish helpers.
- `AssetSnapshotsStorage` has two writers: the `AssetSnapshot` updater and the
  registration's plain SQL. MetaTables catalog statistics do not count the registration's
  rows.
- A registration dated at or before an asset's latest snapshot records no snapshot change
  for that asset.
- An asset whose stored type differs from the request blocks the registration until the
  caller resolves it.
- The Markets API gains `registerAccount` and the `asset` row operation
  `get_or_create_currency`. The release is a minor version. `MUTATION_OPERATION_IDS`, the
  exact set of registry writes in `tests/msm/fastapi/v1/test_acting_identity.py` and the
  account route documentation list them.
