# 0057. Asset Calendar Links In Bulk And At Registration

## Status

Accepted (2026-11-17). The owner asked for both parts on 2026-11-17. Implemented on
`development`; see "Implementation Notes".

- It adds to [ADR 0056](0056-asset-trading-calendar-link.md). ADR 0056 says an asset is linked
  with the normal write on `AssetCalendar`, one asset a call. That write stays. This ADR adds
  a write for many assets and lets a registration carry the calendar.
- It amends [ADR 0051](0051-account-registration-in-one-transaction.md): an asset of an
  account registration may name its trading calendar, and `written` gains `asset_calendars`.

## Context

Since 4.0.0 a price update is refused when one of its assets has no trading calendar
(ADR 0056). After the upgrade every asset is unlinked.

Linking was one call for each asset:

```python
AssetCalendar.upsert(asset_uid=asset.uid, calendar_uid=calendar.uid)
```

What that left open:

- **Many assets on one calendar.** The inherited `AssetCalendar.upsert_many` takes rows of
  `asset_uid` and `calendar_uid`. A caller that knows its assets by `unique_identifier` reads
  their uids first and repeats the calendar uid in every row. Nothing says which identifiers
  matched no asset.
- **Registration.** `Asset.upsert_many`, the currency spot, bond and future composites, and
  the account registration of ADR 0051 create assets and take no calendar. Linking is always
  a second step, so a registered asset can be left without a calendar.
- **Finding what is missing.** The only sign of an unlinked asset was the price update's
  error.
- **Unlinking under the remote backend.** `AssetCalendar` inherited the base `delete`, which
  the rows route does not offer.
- **Deleting a calendar in use.** The foreign key refuses it and the caller saw the database's
  own error.

## Decision

### 1. One call links many assets to a calendar

```python
result = AssetCalendar.link_many(
    ["asset_us_equity_acme", "asset_us_equity_beta"],
    calendar_identifier="NYSE",
)
```

- Assets are named by `unique_identifier`. The calendar is named by `calendar_uid` or by
  `calendar_identifier`, its `unique_identifier`. Exactly one of the two is given.
- All links are written in one transaction.
- `relink` is true by default: an asset on another calendar is moved. With `relink=False`
  such an asset keeps its calendar.
- The answer says what happened to each identifier:

| Field | Meaning |
|---|---|
| `linked` | the asset had no trading calendar and now has this one |
| `moved` | the asset was on another calendar and is now on this one |
| `unchanged` | the asset was already on this calendar; nothing was written for it |
| `kept` | the asset is on another calendar and `relink` was false |
| `unknown` | no asset has that identifier; nothing was written for it |

- An unknown identifier does not fail the call. The caller reads `unknown`.
- A calendar that does not exist raises `LookupError` and nothing is written.
- When nothing would change, nothing is written.
- One call links up to about 64,000 assets: 32 statements of 2,000 identifiers. A longer list
  is refused and is sent in several calls.

### 2. The unlinked assets can be read

```python
AssetCalendar.unlinked_assets(asset_type="equity", limit=500, offset=0)
```

It returns the assets that have no trading calendar, by `unique_identifier`. These are the
assets a price update would refuse.

### 3. A link can be removed under the remote backend

`AssetCalendar` defines its own `delete`. It takes the asset's uid and removes the link.
Nothing references a link, so there is no other check.

### 4. A registration may name the asset's calendar

Every payload that writes an asset takes an optional `calendar_uid` or `calendar_identifier`:
`Asset.create`, `Asset.upsert`, `Asset.upsert_many`, `CurrencySpot.upsert` and
`upsert_many`, `Bond.upsert`, `Future.upsert` and `upsert_many`.

```python
Asset.upsert_many(
    [
        {"unique_identifier": "asset_us_equity_acme", "asset_type": "equity", "calendar_identifier": "NYSE"},
        {"unique_identifier": "asset_crypto_btc", "asset_type": "crypto", "calendar_identifier": "CRYPTO_24_7"},
        {"unique_identifier": "USD", "asset_type": "currency"},
    ]
)
```

- A payload that names a calendar links its asset to it. An asset on another calendar is
  moved: an upsert states what the asset is.
- A payload that names none leaves its asset's link as it is.
- The assets are written first, as before. The links of the call are written after them, in
  one transaction of their own.
- When the links fail, for example because a calendar does not exist, the call fails with the
  assets already written. The same call again, with a stored calendar, finishes it.
- A call in which no payload names a calendar reads and writes nothing more than before.

These writes were already several operations in a row, so the link is one more step and not a
new guarantee.

### 5. An account registration links in its one transaction

An asset of `AccountRegistrationRequest.assets` may carry `calendar_identifier`:

```json
{
  "unique_identifier": "venue::AAPL",
  "asset_type": {"asset_type": "venue_equity"},
  "calendar_identifier": "NYSE"
}
```

- The link is written in the registration's transaction, after the asset insert. An asset the
  registration creates is linked in it.
- **Only an asset that has no trading calendar is linked.** An asset that has one keeps it,
  as an existing asset keeps its type. A connector that names `NYSE` on every sync does not
  undo a link someone moved to another calendar.
- A calendar that does not exist refuses the registration before anything is written.
- `written` gains `asset_calendars`, with the links the registration created.
- The registration makes one more read, of the calendars, only when an asset names one, and
  a second one, of the current links, only when such an asset already exists.
- An identical repeat still needs no transaction.

### 6. A calendar in use is not deleted

Deleting a calendar that is the trading calendar of an asset, or the calendar of a portfolio,
is refused before the delete is sent. The error says how many assets and portfolios hold it.
`DELETE /api/v1/calendar/{uid}/` answers `409`, and the remote row call raises
`MarketsConflictError`.

## Not Decided Here

- **Routes for `AssetCalendar`.** ADR 0056 left the link to the row API. `link_many`,
  `unlinked_assets` and `delete` are served as row operations under
  `/api/v1/rows/asset-calendar/`.
- **Linking by exchange code or asset type.** ADR 0056 refuses to guess a calendar from
  stored data. A caller that wants "every equity on NYSE" reads
  `AssetCalendar.unlinked_assets(asset_type="equity")` and passes the identifiers to
  `link_many`.
- **Unlinking many assets in one call.**

## Rejected Alternatives

### A Default Calendar For An Asset That Names None

ADR 0056 rejects it: a calendar nobody chose is wrong for some assets, and nothing would show
it.

### Link In The Same Transaction As `Asset.upsert_many`

The bulk upsert reports a status for each row and runs as one or several statements, and
since issue 84 as several transactions for a long list. Putting the links inside it would
change that machinery for every table. The links go in a transaction of their own, and the
call is safe to repeat.

### Move An Existing Asset In An Account Registration

A registration runs on every sync of a connector. Moving the asset each time would undo a
correction made by hand, with no error to show it.

## Consequences

- Linking the assets of a deployment after the 4.0.0 upgrade is one read and one call for each
  calendar.
- A connector that registers assets names their calendar in the same call, so a new asset is
  not left unlinked.
- A caller that sends a wrong calendar name to `Asset.upsert_many` gets its assets written
  and an error. The error names the calendar.
- `written` in the account registration answer has one more key.

## Implementation Notes

### 2026-11-17: `development`

- Statements: `msm.repositories.asset_calendars`. A link is an `INSERT … SELECT` over `Asset`
  by `unique_identifier`, with `ON CONFLICT (asset_uid)`: `DO UPDATE` where the calendar
  differs for a relink, `DO NOTHING` for a registration.
- Services: `msm.services.asset_calendars`. Row API: `AssetCalendar.link_many`,
  `AssetCalendar.unlinked_assets`, `AssetCalendar.delete`, `AssetCalendarLinkResult`,
  `TradingCalendarReference`.
- Account registration: `AccountRegistrationAsset.calendar_identifier`,
  `AccountRegistrationWrites.calendar_links`.
- Calendar delete: `CalendarInUseConflictError` in `msm.services.calendars`.
- Run on SQLite through the MetaTables backend code, and on PostgreSQL 16 in a local
  container: 2,500 assets linked in one transaction, a relink, a kept link, bulk
  registration with calendars, and an account registration that links one asset and keeps
  another's link.

## Not Verified

- The same writes through a deployed MetaTables API.
- `Future.upsert` and `Future.upsert_many` with a calendar were not run end to end. They call
  the same helper as the currency spot and bond composites, which were.
- Whether the Command Center reads `written` of the account registration with a fixed list of
  keys. Its code is not in this repository.
